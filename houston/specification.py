__all__ = ['Specification', 'Expression', 'Idle']

from typing import List, Dict, Any, Tuple, Type, \
    Optional, Callable, Union
import logging
import random
import math

import attr
import sexpdata
import z3

from . import exceptions
from .configuration import Configuration
from .state import State
from .environment import Environment

logger = logging.getLogger(__name__)  # type: logging.Logger
logger.setLevel(logging.DEBUG)

Timeout = \
    Callable[['Command', State, Environment, Configuration], float]


class Expression(object):
    def __init__(self, s_expression: str) -> None:
        if not Expression.is_valid(s_expression):
            raise exceptions.InvalidExpression

        self.__expression = s_expression

    @property
    def expression(self) -> str:
        return self.__expression

    @staticmethod
    def is_valid(string: str) -> bool:
        """
        Determines whether a given specification, encoded as a string, is
        valid.
        """
        try:
            parsed = sexpdata.loads(string)
        except (sexpdata.ExpectClosingBracket, sexpdata.ExpectNothing) as e:
            return False
        return True

    def is_satisfied(self,
                     command: 'Command',
                     state_before: State,
                     state_after: State,
                     environment: Environment,
                     config: Configuration
                     ) -> bool:
        """
        Determines whether this specification is satisfied by a given
        before and after state in a particular context (i.e, command
        arguments, configuration and environment).
        """
        logger.debug("Checking for command: %s", command.name)  # FIXME
        ctx = z3.Context()
        solver = z3.SolverFor("QF_NRA", ctx=ctx)
        smt, decls = self._prepare_query(ctx,
                                         command,
                                         state_before,
                                         state_after)
        expr = self.get_expression(decls, state_before)
        smt.extend(expr)
        logger.info("SMT: {}".format(smt))
        solver.add(smt)
        logger.debug("Z3 result: {}".format(str(solver.check())))
        return solver.check() == z3.sat

    def _prepare_query(self,
                       ctx: z3.Context,
                       command: 'Command',
                       state_before: State,
                       state_after: State = None
                       ) -> Tuple[List[z3.ExprRef], Dict[str, Any]]:
        """
        Prepares the declarations and value assignment for a query
        given the command and states before and after.
        """
        decls = self.get_declarations(ctx, command, state_before)
        smt = Expression.values_to_smt('$', command, decls)
        smt.extend(Expression.values_to_smt('_',
                                            state_before,
                                            decls))
        if state_after:
            smt.extend(Expression.values_to_smt('__',
                                                state_after,
                                                decls))
        return smt, decls

    def get_declarations(self,
                         ctx: z3.Context,
                         command: 'Command',
                         state: State,
                         postfix: Optional[str] = None
                         ) -> Dict[str, z3.ArithRef]:
        """
        Creates a Z3 variable for all state variables and command
        parameters.
        Parameters:
            command: the command for which the declarations are
                being prepared.
            state: the state for which the declarations are being
                prepared.
            postfix: the optional string that could be used to
                properly rename the variables in the query.
        Returns:
            A dictionary with the name of variables as key and
            Z3 variable as value.
        """
        logger.debug("obtaining declarations for command [%s] and state [%s] using postfix [%s]",  # noqa: pycodestyle
                     command, state, postfix)
        declarations = {}
        var = lambda x, y: Expression.create_z3_var(ctx, x, y)

        if not postfix:
            postfix = ''

        for p in command.parameters:
            name = '${}{}'.format(p.name, postfix)
            ex = var(p.type, name)
            declarations['${}'.format(p.name)] = ex

        for n, v in state.variables.items():
            typ = v.typ
            name = '_{}'.format(n)
            declarations[name] = var(typ, '{}{}'.format(name, postfix))
            name = '__{}'.format(n)
            declarations[name] = var(typ, '{}{}'.format(name, postfix))

        logger.debug("obtained declarations: %s", declarations)
        return declarations

    @staticmethod
    def create_z3_var(ctx: z3.Context, type_py: Type, name: str):
        """
        Creates a named Z3 variable with a type corresponding to a given
        Python type.

        Parameters:
            type_py: the Python type of the variable.
            name: the name of the variable.

        Raises:
            UnsupportedVariableType: Houston and/or Z3 do not support the
                given Python type.
        """
        logger.debug("creating Z3 variable for [%s] with type [%s]",
                     name, type_py)
        py_to_z3 = {float: z3.Real,
                    bool: z3.Bool,
                    str: z3.String,
                    int: z3.Int}
        try:
            type_z3 = py_to_z3[type_py]
        except KeyError:
            raise exceptions.UnsupportedVariableType(type_py)
        var = type_z3(name, ctx=ctx)
        logger.debug("created Z3 variable for [%s]: %s", name, var)
        return var

    @staticmethod
    def values_to_smt(prefix: str,
                      state_or_command: Union[State, 'Command'],
                      declarations: Dict[str, Any]
                      ) -> List[z3.ExprRef]:
        """
        Creates a Z3 equality expression for all variables in values
        dictionary to assert their values and returns a list of Z3
        expressions.
        Parameters:
            prefix: the prefix that is added to this set of variables
                in the declarations.
            values: a state or command which contains the variables
                or parameters we want to add to query.
            declarations: a dictionary of all variables (e.g. command
                parameters and state variables) name as key and Z3
                variable as value.
        Returns:
            A list of Z3 expressions that assert equality of variables
                and their values.
        """
        smt = []
        logger.debug("converting values to SMT: %s", state_or_command)
        for param_or_variable in state_or_command:
            logger.debug("creating SMT assertion for var: %s",
                         param_or_variable.name)
            name = param_or_variable.name
            val = state_or_command[name]
            d = declarations['{}{}'.format(prefix, name)]
            if isinstance(val, str):
                smt.append(d == z3.StringVal(val, ctx=d.ctx))
            else:
                smt.append(d == val)
        logger.debug("converted values to SMT: %s", smt)
        return smt

    def is_satisfiable(self,
                       command: 'Command',
                       state: State,
                       environment: Environment
                       ) -> bool:
        """
        Determines whether this specification is satisifiable in a given
        context (i.e., command, state, environment, configuration).

        Parameters:
            command: the parameters supplied to the command.
            state: the state of the system immediately prior to executing the
                command.
            environment: the state of the environment immediately prior to
                executing the command.

        Returns:
            True if satisfiable, false if not.
        """
        ctx = z3.Context()
        s = z3.SolverFor("QF_NRA", ctx=ctx)
        decls = self.get_declarations(ctx, command, state)
        smt = Expression.values_to_smt('_', state, decls)
        smt.extend(self.get_expression(decls, state))
        s.add(smt)
        return s.check() == z3.sat

    def get_expression(self,
                       decls: Dict[str, Any],
                       state: State,
                       postfix: str = ""
                       ) -> List[z3.ExprRef]:
        """
        Constructs a Z3 expression from this expression for a particular
        state and set of declaration mappings.
        """
        ctx = None
        if decls:
            ctx = list(decls.values())[0].ctx
        s_expr = '(assert {})'.format(self.expression)
        expr = z3.parse_smt2_string(s_expr, decls=decls, ctx=ctx)
        logger.debug('generated (non-noisy) expression: %s', expr)
        variables = {}
        logger.debug('computing variable noise')
        for n, v in state.variables.items():
            variables['_{}{}'.format(n, postfix)] = float(v.noise) \
                if v.is_noisy else 0.0
            variables['__{}{}'.format(n, postfix)] = float(v.noise) \
                if v.is_noisy else 0.0
        logger.debug('computed variable noise: %s', variables)
        logger.debug('adding noise to expression')
        expr_with_noise = [Expression.recreate_with_noise(expr, variables)]
        logger.debug('added noise to expression')
        logger.debug('generated expression: %s', expr_with_noise)
        return expr_with_noise

    # FIXME needs docstring
    @staticmethod
    def recreate_with_noise(expr: z3.ExprRef,
                            variables: Dict[z3.ArithRef, float]
                            ) -> z3.ExprRef:
        recreate = Expression.recreate_with_noise
        logger.debug("recreating expression with noise: %s", expr)
        d = expr.decl()
        if str(d) != '==':
            children = [recreate(c, variables) for c in expr.children()]
            # TODO find a better solution
            if str(d) == 'And':
                return z3.And(*children, expr.ctx)
            elif str(d) == 'Or':
                return z3.Or(*children, expr.ctx)
            return d(*children)
        lhs, rhs = expr.children()[0], expr.children()[1]
        if not isinstance(lhs, z3.ArithRef) or \
                not isinstance(rhs, z3.ArithRef):
            return d(lhs, rhs)

        def absolute(x):
            return z3.If(x > 0, x, -x, ctx=expr.ctx)
        expr = absolute(lhs - rhs) <= Expression.get_noise(expr, variables)
        logger.debug('recreated expression with noise: %s', expr)
        return expr

    # FIXME needs docstring
    @staticmethod
    def get_noise(expr: z3.ExprRef,
                  variables: Dict[z3.ArithRef, float]
                  ) -> float:
        logger.debug("getting noise for expression: %s", expr)
        if len(expr.children()) == 0:
            if isinstance(expr, z3.ArithRef) and str(expr) in variables:
                return variables[str(expr)]
            else:
                return 0.0
        noises = [Expression.get_noise(c, variables) for c in expr.children()]
        if str(expr.decl()) == '*':
            f = 1.0
            for i in noises:
                f *= i
            return f
        elif str(expr.decl()) == '**':
            if isinstance(expr.children()[1], z3.IntNumRef):
                return math.pow(noises[0], int(expr.children()[1]))
            else:
                # TODO: FIX
                return noises[0]
        else:
            return math.fsum(noises)


class Specification(object):
    def __init__(self,
                 name: str,
                 precondition: str,
                 postcondition: str,
                 timeout: Timeout = lambda c, s, e, o: 1.0) -> None:
        self.__name = name
        self.__precondition = Expression(precondition)
        self.__postcondition = Expression(postcondition)
        self.__timeout = timeout

    @property
    def precondition(self) -> Expression:
        return self.__precondition

    @property
    def postcondition(self) -> Expression:
        return self.__postcondition

    @property
    def name(self) -> str:
        return self.__name

    def timeout(self,
                command: 'Command',
                state: State,
                environment: Environment,
                config: Configuration
                ) -> float:
        """
        Returns an upper bound on the length of time that it should take for
        a given command to satisfy this specification.
        """
        return self.__timeout(command, state, environment, config)

    def get_constraint(self,
                       ctx: z3.Context,
                       command: 'Command',
                       state: State,
                       postfix: str = ''
                       ) -> Tuple[List[z3.ExprRef], Dict[str, Any]]:
        decls = self.precondition.get_declarations(ctx,
                                                   command,
                                                   state,
                                                   postfix)
        smt = self.precondition.get_expression(decls, state, postfix)
        smt.extend(self.postcondition.get_expression(decls, state, postfix))

        return smt, decls


# FIXME generate an Idle for a given system
Idle = Specification(
    "idle",
    "true",
    """
    (and (= _latitude __latitude)
         (= _longitude __longitude)
         (= _altitude __altitude)
         (= _armed __armed)
         (= _armable __armable)
         (= _mode __mode))
    """)
