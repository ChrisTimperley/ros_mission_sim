from typing import Set, Optional, Tuple, Dict, List, Any
import random

from ..system import System
from ..state import State
from ..environment import Environment
from ..mission import Mission, MissionOutcome
from ..valueRange import DiscreteValueRange
from ..command import Command, Parameter
from ..configuration import Configuration


class MissionDomain(object):
    """
    Specification of a range of missions.
    """
    def __init__(self, system: System, initial_domain=[]):
        self.__system = system
        self.__domain = initial_domain


    def __str__(self):
        return str(self.domain)


    @property
    def system(self):
        """
        The system under which this domain is defined.
        """
        return self.__system


    @property
    def domain(self) -> List[Tuple[int, Any, List[Parameter]]]:
        """
        The domain specified by sequence of Actions with
        specific parameter ranges.
        """
        return self.__domain


    @staticmethod
    def from_initial_mission(system: System, mission: Mission, discrete_params=False):
        """
        Create a mission domain by considering the initial sequence
        of actions in mission and all possible values for parameters.
        """
        i = 0
        domain = []
        for command in mission.commands:
            if discrete_params:
                parameters = [Parameter(p.name, DiscreteValueRange([command[p.name]])) for p in command.parameters]
            else:
                parameters = command.parameters
            domain.append((i, command.__class__, parameters))
            i += 1
        return MissionDomain(system, domain)


    @property
    def command_size(self):
        """
        Number of actions in this domain.
        """
        return len(self.__domain)


    def generate_mission(self, environment: Environment, initial_state: State, config: Configuration, rng) -> Mission:
        """
        Return a mission in this domain.
        """
        cmds = []
        for _, cmd_class, params in self.domain:
            parameters = {}
            for p in params:
                parameters[p.name] = p.generate(rng)
            cmds.append(cmd_class(**parameters))
        return Mission(config, environment, initial_state, cmds)


class RootCauseFinder(object):
    """
    RootCauseFinder is used to find minimum requirements that
    results in mission failure the same way that initial failing
    missions do. 
    """
    def __init__(self, system: System, initial_state: State, environment: Environment,
        config: Configuration, initial_failing_missions: List[Mission], random_seed=100):

        assert(len(initial_failing_missions) > 0)

        self.__system = system
        self.__initial_state = initial_state
        self.__environment = environment
        self.__rng = random.Random(random_seed)
        self.__initial_failing_missions = initial_failing_missions
        self.__configuration = config


    @property
    def system(self):
        """
        The system under test.
        """
        return self.__system


    @property
    def initial_state(self):
        """
        the initial state used for running all missions.
        """
        return self.__initial_state


    @property
    def environment(self):
        """
        the environment used for running all missions.
        """
        return self.__environment


    @property
    def initial_failing_missions(self):
        """
        the failing missions provided by the user.
        """
        return self.__initial_failing_missions

    @property
    def configuration(self):
        return self.__configuration

    @property
    def rng(self):
        return self.__rng


    def find_root_cause(self, time_limit=None) -> MissionDomain:
        """
        The main function that finds the root cause.
        """
        raise NotImplementedError

