from typing import Set, Optional, Tuple, Dict, List

from houston.root_cause import MissionDomain
from houston.system import System
from houston.state import State, Environment
from houston.mission import Mission, MissionOutcome


class SymbolicExecution(object):

    def __init__(self, system: System, initial_state: State, environment: Environment):
        self.__system = system
        self.__initial_state = initial_state
        self.__environment = environment


    @property
    def system(self):
        return self.__system


    @property
    def initial_state(self):
        return self.__initial_state


    @property
    def environment(self):
        return self.__environment


    def execute_symbolically(self, mission: Mission) -> List[Tuple[Mission, MissionOutcome]]:
        """
        Having the sequense of actions in `mission` this function
        will generate parameters for those actions in order to
        explore all possible action branches.
        """

        actions = mission.actions
        all_paths = []
        self_dfs(actions, 0, BranchPath([]), all_paths)
        raise NotImplementedError


    def _dfs(self, actions, start_index, path: BranchPath, all_paths: List[BranchPath] = []):
        if start_index == len(actions)-1:
            all_paths.append(path)
            return
        for b in self.system.schemas[actions[start_index].schema_name].branches:
            self._dfs(actions, start_index + 1, path.extended(b), allPaths)

