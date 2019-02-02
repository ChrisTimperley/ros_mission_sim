from typing import Iterator, Tuple, Set, List, Dict, Any, Optional, Type
from uuid import UUID, uuid4
import concurrent.futures
import argparse
import functools
import contextlib
import attr
import logging
import json
import sys
import os
import signal
import psutil

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import PreservedScalarString
import yaml
import bugzoo
import houston
from bugzoo import Client as BugZooClient
from bugzoo import BugZoo as BugZooDaemon
from houston import System
from houston.mission import Mission
from houston.trace import CommandTrace, MissionTrace
from houston.ardu.copter import ArduCopter

from compare_traces import load_file as load_traces_file
from compare_traces import matches_ground_truth
from build_traces import build_sandbox

logger = logging.getLogger('houston')  # type: logging.Logger
logger.setLevel(logging.DEBUG)

DESCRIPTION = "Builds a ground truth dataset."


class FailedToCreateMutantSnapshot(houston.exceptions.HoustonException):
    """
    Thrown when this script fails to create a BugZoo snapshot for a
    mutant.
    """


@attr.s
class DatabaseEntry(object):
    diff = attr.ib(type=str)
    fn_inconsistent_traces = attr.ib(type=Tuple[Tuple[str, str], ...])
    fn_consistent_traces = attr.ib(type=Tuple[Tuple[str, str], ...])

    def to_dict(self) -> Dict[str, Any]:
        return {'diff': PreservedScalarString(self.diff),
                'inconsistent':  [{'oracle': o,
                                   'trace': t} for o, t in self.fn_inconsistents],
                'consistent':  [{'oracle': o,
                                 'trace': t} for o, t in self.fn_consistents]
                }


def kill_child_processes(parent_pid, sig=signal.SIGTERM):
    try:
        parent = psutil.Process(parent_pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for process in children:
        if process.name() != "python":
            continue
        logger.debug("killing process %d", process.pid)
        process.send_signal(sig)


def setup_logging(verbose: bool = False) -> None:
    log_to_stdout = logging.StreamHandler()
    log_to_stdout.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter('%(processName)s - %(message)s')
    log_to_stdout.setFormatter(formatter)
    logging.getLogger('houston').addHandler(log_to_stdout)
    logging.getLogger('experiment').addHandler(log_to_stdout)


def parse_args():
    p = argparse.ArgumentParser(description=DESCRIPTION)
    p.add_argument('snapshot', help='the name of the BugZoo snapshot')
    p.add_argument('mutants', help='path to a JSON file of mutants.')
    p.add_argument('oracle', type=str, help='path to oracle trace directory.')
    p.add_argument('output', type=str,
                   help='the file to which the ground truth dataset should be written.')
    p.add_argument('--verbose', action='store_true',
                   help='increases logging verbosity')
    p.add_argument('--threads', type=int, default=1,
                   help='number of threads to use when building trace files.')
    return p.parse_args()


@contextlib.contextmanager
def build_mutant_snapshot(bz: BugZooClient,
                          snapshot: bugzoo.Bug,
                          diff: str
                          ) -> Iterator[bugzoo.Bug]:
    # generate a name for the snapshot and image
    uuid = uuid4().hex[:64]
    name_image = "houston-mutant:{}".format(uuid)

    # create a description of the mutant snapshot
    mutant = bugzoo.Bug(name=name_image,
                        image=name_image,
                        dataset='houston-mutants',
                        program=snapshot.program,
                        source=None,
                        source_dir=snapshot.source_dir,
                        languages=snapshot.languages,
                        tests=snapshot.tests,
                        compiler=snapshot.compiler,
                        instructions_coverage=snapshot.instructions_coverage)

    try:

        # create and store the Docker image
        patch = bugzoo.Patch.from_unidiff(diff)
        container = None
        try:
            container = bz.containers.provision(snapshot)
            if not bz.containers.patch(container, patch):
                m = "failed to patch using diff: {}".format(diff)
                raise FailedToCreateMutantSnapshot(m)

            logger.debug("patched using diff: %s", diff)
            build_attempt = bz.containers.build(container)
            if not build_attempt.successful:
                logger.error("build failure:\n%s",
                             build_attempt.response.output)
                m = "failed to build mutant: {}".format(diff)
                raise FailedToCreateMutantSnapshot(m)
            bz.containers.persist(container, name_image)
        finally:
            if container:
                del bz.containers[container.uid]

        # register the snapshot
        bz.bugs.register(mutant)

        yield mutant

    # ensure that all resources are freed
    finally:
        if mutant.name in bz.bugs:
            del bz.bugs[mutant.name]
        if bz.docker.has_image(name_image):
            bz.docker.delete_image(name_image)


def process_mutation(system: Type[System],
                     client_bugzoo: BugZooClient,
                     snapshot_orig: bugzoo.Bug,
                     trace_filenames: List[str],
                     dir_mutant_traces: str,
                     diff: str
                     ) -> Optional[DatabaseEntry]:
    bz = client_bugzoo
    sandbox_cls = system.sandbox

    inconsistent_results = []
    consistent_results = []

    # build an ephemeral image for the mutant
    try:
        with build_mutant_snapshot(client_bugzoo, snapshot_orig, diff) as snapshot:
            def obtain_trace(mission: houston.Mission) -> MissionTrace:
                jsn_mission = json.dumps(mission.to_dict())  # FIXME hack
                with build_sandbox(client_bugzoo, snapshot, jsn_mission) as sandbox:
                    return sandbox.run_and_trace(mission.commands)

            for fn_trace in trace_filenames:
                logger.debug("evaluating oracle trace: %s", fn_trace)
                mission, oracle_traces = load_traces_file(fn_trace)
                try:
                    trace_mutant = obtain_trace(mission)
                except:
                    logger.exception("failed to build trace %s for mutant: %s", fn_trace, diff)
                    continue

                # write mutant trace to file
                identifier = abs(hash((hash(diff), hash(mission))))
                fn_trace_mut_rel = "{}.json".format(identifier)
                fn_trace_mut = os.path.join(dir_mutant_traces, fn_trace_mut_rel)
                jsn = {'mission': mission.to_dict(),
                       'traces': [trace_mutant.to_dict()]}
                with open(fn_trace_mut, 'w') as f:
                    json.dump(jsn, f)

                try:
                    if not matches_ground_truth(trace_mutant, oracle_traces):
                        logger.info("found an acceptable mutant!")
                        inconsistent_results.append((fn_trace, fn_trace_mut))
                    else:
                        logger.debug("mutant is not sufficiently different for given mission.")
                        consistent_results.append((fn_trace, fn_trace_mut))
                except houston.exceptions.HoustonException as e:
                    logger.exception("failed to check matching of traces %s", e)
                    continue

    except FailedToCreateMutantSnapshot:
        logger.error("failed to build snapshot for mutant: %s", diff)
    except Exception:
        logger.exception("failed to obtain data for mutant: %s", diff)
    except (houston.exceptions.NoConnectionError, houston.exceptions.ConnectionLostError):
        logger.error("mutant resulted in crash")
    finally:
        if inconsistent_results or consistent_results:
            return DatabaseEntry(diff, tuple(inconsistent_results), tuple(consistent_results))
        else:
            return None



def main():
    args = parse_args()
    setup_logging(verbose=args.verbose)
    name_snapshot = args.snapshot
    fn_mutants = args.mutants
    dir_output = args.output
    dir_oracle = args.oracle
    fn_output_database = os.path.join(dir_output, 'database.yml')
    num_threads = args.threads
    system = ArduCopter

    assert num_threads >= 1

    # ensure that the output directory exists
    os.makedirs(args.output, exist_ok=True)

    if not os.path.exists(dir_oracle):
        logger.error("oracle directory not found: %s", dir_oracle)
        sys.exit(1)

    # load the mutant diffs
    try:
        with open(fn_mutants, 'r') as f:
            diffs = [e['diff'] for e in yaml.load(f)]
            logger.debug("loaded %d diffs from database", len(diffs))
    except Exception:
        logger.exception("failed to load mutation database: %s", fn_mutants)
        sys.exit(1)
    except FileNotFoundError:
        logger.error("mutation database file not found: %s", fn_mutants)
        sys.exit(1)

    # obtain a list of oracle traces
    trace_filenames = \
        [fn for fn in os.listdir(dir_oracle) if fn.endswith('.json')]
    trace_filenames = [os.path.join(dir_oracle, fn) for fn in trace_filenames]

    db_entries = []  # type: List[DatabaseEntry]
    futures = []
    with bugzoo.server.ephemeral() as client_bugzoo:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_threads) as executor:
            try:
                snapshot = client_bugzoo.bugs[name_snapshot]
                process = functools.partial(process_mutation,
                                            system,
                                            client_bugzoo,
                                            snapshot,
                                            trace_filenames,
                                            dir_output)
                for diff in diffs:
                    future = executor.submit(process, diff)
                    futures.append(future)

                for future in concurrent.futures.as_completed(futures):
                    entry = future.result()
                    if entry:
                        db_entries.append(entry)
            except (KeyboardInterrupt, SystemExit):
                logger.info("Received keyboard interrupt. Shutting down...")
                for fut in futures:
                    logger.debug("Cancelling: %s", fut)
                    fut.cancel()
                    logger.debug("Cancelled: %s", fut.cancelled())
                logger.info("Shutting down the process pool")
                executor.shutdown(wait=False)
                kill_child_processes(os.getpid())
                logger.info("Cancelled all jobs and shutdown executor.")
                client_bugzoo.containers.clear()
                logger.info("Killed all containers")
                logger.info("Removing all images")
                bug_names = [b for b in client_bugzoo.bugs if 'houston-mutant' in b]
                for b in bug_names:
                    logger.debug("Removing image %s", b)
                    del client_bugzoo.bugs[b]
                    if client_bugzoo.docker.has_image(b):
                        client_bugzoo.docker.delete_image(b)

                logger.debug("Removed all images")


    # save to disk
    logger.info("finished constructing evaluation dataset.")
    logger.debug("saving evaluation dataset to disk.")
    jsn = {
        'oracle-directory': dir_oracle,
        'snapshot': name_snapshot,
        'entries': [e.to_dict() for e in db_entries]
    }
    with open(fn_output_database, 'w') as f:
        YAML().dump(jsn, f)
    logger.info("saved evaluation dataset to disk")


if __name__ == '__main__':
    main()
