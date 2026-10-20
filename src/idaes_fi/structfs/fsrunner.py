#################################################################################
# Process Optimization and Modeling for Minerals Sustainability (PrOMMiS) Copyright (c) 2023-2026
#
# “Process Optimization and Modeling for Minerals Sustainability (PrOMMiS)” was produced under the DOE
# Process Optimization and Modeling for Minerals Sustainability (“PrOMMiS”) initiative, and is
# copyrighted by the software owners: The Regents of the University of California, through Lawrence
# Berkeley National Laboratory, National Technology & Engineering Solutions of Sandia, LLC through
# Sandia National Laboratories, Carnegie Mellon University, University of Notre Dame, and West
# Virginia University Research Corporation.
#
# NOTICE. This Software was developed under funding from the U.S. Department of Energy and the
# U.S. Government consequently retains certain rights. As such, the U.S. Government has been granted
# for itself and others acting on its behalf a paid-up, nonexclusive, irrevocable, worldwide license
# in the Software to reproduce, distribute copies to the public, prepare derivative works, and perform
# publicly and display publicly, and to permit other to do so.
#
#################################################################################
"""
Specialize the generic `Runner` class to running a flowsheet,
in `FlowsheetRunner`.
"""

# stdlib
import argparse
from enum import Enum
import inspect
import logging
from pathlib import Path
import sys
from types import FunctionType
from typing import Sequence

# third-party
from pyomo.environ import ConcreteModel, SolverFactory, UnknownSolver
from pyomo.environ import units as pyunits
from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver

from idaes_fi.structfs.actions.progress import Progress

try:
    from idaes_connectivity.base import Connectivity
    from idaes_connectivity.jupyter import display_connectivity
except ImportError:
    Connectivity = None

# package
from .runner import Runner
from .common import (
    ActionNames,
    DEFAULT_SOLVER_NAME,
    RESULT_FLOWSHEET_KEY,
    load_module,
    find_flowsheet_objects,
    Steps,
)
from .reportdb import DBError
from .. import gitutil

_log = logging.getLogger(__name__)


class Context(dict):
    """Syntactic sugar for the dictionary for the 'context' passed into each
    step of the `FlowsheetRunner` class.
    """

    @property
    def model(self):
        """The model being run."""
        return self["model"]

    @model.setter
    def model(self, value):
        """The model being run."""
        self["model"] = value

    @property
    def solver(self):
        """The solver used to solve the model."""
        return self["solver"]

    @solver.setter
    def solver(self, value):
        """The solver used to solve the model."""
        if isinstance(value, str):
            value = SolverFactory(value)
            if isinstance(value, UnknownSolver):
                raise ValueError(f"Unknown solver: {value}")
        self["solver"] = value

    def solve(self):
        """Perform solve, store result"""
        if self.solver is None:
            self.solver = SolverFactory(DEFAULT_SOLVER_NAME)
        self.results = self.solver.solve(self.model, tee=self["tee"])

    @property
    def tee(self):
        """Return whether solver output should be streamed.

        Returns:
            True if solver output should be echoed, otherwise False.
        """
        return self["tee"]

    @property
    def results(self) -> dict:
        """Return the stored solver results, if any.

        Returns:
            The stored solver results object, or an empty dict if no solve has run.
        """
        return self.get("results", {})

    @results.setter
    def results(self, value: dict):
        """Store solver results in the context.

        Args:
            value: Solver results object to store.
        """
        self["results"] = value


class BaseFlowsheetRunner(Runner):
    """Specialize the base `Runner` to handle IDAES flowsheets.

    This class pre-determine the name and order of steps to run

    Attributes:
        STEPS: List of defined step names.
    """

    _SET_SOLVER_STEP = "set_solver"

    STEPS = (
        Steps.build,
        Steps.set_solver,
        Steps.set_operating_conditions,
        Steps.initialize,
        Steps.set_scaling,
        Steps.solve_initial,
        Steps.set_autoscaling,
        Steps.add_costing,
        Steps.initialize_costing,
        Steps.setup_optimization,
        Steps.solve_optimization,
    )

    def __init__(
        self,
        solver=None,
        tee=True,
        solver_options: dict | None = None,
        steps: Sequence[str] | None = None,
        allow_user_steps: bool = False,
        resolve_from: str = "solve_initial",
        **target_kw,
    ):
        """Constructor

        Args:
            solver: Pyomo solver to use, or string name of solver
            tee: If True, echo solver output to stdout
            solver_options: Options to pass to the solver
            steps: List of step names to run. If None (the default), use `STEPS`. If empty,
                   then dynamically set the list of steps as they are added.
            resolve_from: First step for a later in-process re-solve; stored only.
            target_kw: Keyword arguments to set the report target (e.g., module, filename, filedir, hash)
        """
        if steps is None:
            steps = self.STEPS
        self.build_step = steps[0] if steps else None
        self._solver, self._tee = solver, tee
        self._solver_options = solver_options or {}
        self._ann = {}
        self.resolve_from = self.normalize_name(resolve_from)
        super().__init__(steps)  # needs to be here
        # This allows things like 'name', 'module', and even 'tags', to be
        # passed directly as keywords to the constructor
        if target_kw:
            try:
                self.set_report_target(**target_kw)
            except KeyError as err:
                raise KeyError(
                    f"Keyword argument to BaseFlowsheetRunner instance was not "
                    f"a valid keyword for the report target: {err}"
                )

    def set_solve_steps(self, solve_steps: Sequence[str]):
        """Set `solve_steps` for all contained actions which have this attribute."""
        for _, action in self._actions.items():
            if hasattr(action, "solve_steps"):
                action.solve_steps = solve_steps

    def run_steps(
        self,
        first: str = Runner.STEP_ANY,
        last: str = Runner.STEP_ANY,
        before=None,
        after=None,
        **kwargs,
    ):
        """Run the steps.

        Before it calls the superclass to run the steps, checks
        if the step name matches the `build_step` attribute and,
        if so, creates an empty Pyomo ConcreteModel to use as
        the base model for the flowsheet.
        """
        if self.build_step is None:
            if self._step_names:
                self.build_step = self._step_names[0]
            else:
                raise ValueError(
                    "Cannot run steps when no steps are defined and no build_step is set."
                )
        self._set_solver()
        from_step_name = self.normalize_name(first)
        if (
            from_step_name == "-"
            or from_step_name == self.build_step
            or self._context.model is None
        ):
            self._context.model = self._create_model()
            self._ann.clear()

        # replace first/last with before/after, if present
        if before is not None:
            kwargs["before"] = before
            last = ""
        if after is not None:
            kwargs["after"] = after
            first = ""

        super().run_steps(first, last, **kwargs)

    def _set_solver(self):
        """Set the solver, if no 'set_solver' step exists."""
        if self._SET_SOLVER_STEP not in self._steps:
            if self._solver is None:
                # use default solver, if none given
                self._context.solver = get_solver()
            elif isinstance(self._solver, str):
                # create solver from string
                self._context.solver = SolverFactory(self._solver)
            else:
                self._context.solver = self._solver
            if self._solver_options:
                self._context.solver.options = self._solver_options

    def reset(self):
        """Reset the runner context to its initial state."""
        self._context = Context(solver=self._solver, tee=self._tee, model=None)
        self._ann.clear()

    def _create_model(self):
        m = ConcreteModel()
        m.fs = FlowsheetBlock(dynamic=False)
        return m

    @property
    def model(self):
        """Syntactic sugar to return the model."""
        return self._context.model

    @property
    def results(self):
        """Syntactic sugar to return the `result` in the context.
        Returns:
            results from Pyomo, or None if not set
        """
        return self._context.results

    def annotate_var(
        self,
        variable: object,
        key: str = None,
        title: str = None,
        desc: str = None,
        units: str = None,
        rounding: int = 3,
        is_input: bool = True,
        is_output: bool = True,
        input_category: str = "main",
        output_category: str = "main",
        bounds: tuple[float | None, float | None] | None = None,
        rebuild: bool = False,
    ) -> object:
        """Annotate a Pyomo variable.

        Args:
            variable: Pyomo variable being annotated
            key: Key for this block in dict. Defaults to object name.
            title: Name / title of the block. Defaults to object name.
            desc: Description of the block. Defaults to object name.
            units: Units. Defaults to string value of native units.
            rounding: Significant digits
            is_input: Is this variable an input
            is_output: Is this variable an output
            input_category: Name of input grouping to display under
            output_category: Name of output grouping to display under
            bounds: Optional input limits in the declared units. Defaults to variable bounds.
            rebuild: Whether changing this input requires rebuilding the model.

        Returns:
             Input block (for chaining)

        Raises:
            ValueError: if `is_input` and `is_output` are both False
        """
        if not is_input and not is_output:
            raise ValueError("One of 'is_input', 'is_output' must be True")

        qual_name = variable.name
        key = key or variable.name
        unit_variable = (
            next(iter(variable.values()), variable)
            if variable.is_indexed()
            else variable
        )

        self._ann[key] = {
            "var": variable,
            "fullname": qual_name,
            "title": title or qual_name,
            "description": desc or qual_name,
            "units": units or str(pyunits.get_units(unit_variable)),
            "rounding": rounding,
            "is_input": is_input,
            "is_output": is_output,
            "input_category": input_category,
            "output_category": output_category,
            "bounds": bounds,
            "rebuild": rebuild,
        }

        return variable

    @property
    def annotated_vars(self) -> dict[str,]:
        """Get (a copy of) the annotated variables."""
        return {key: annotation.copy() for key, annotation in self._ann.items()}


class DiagnosticReportType(Enum):
    """Different types of diagnostic reports"""

    STRUCTURAL = "structural"
    NUMERICAL = "numerical"


class FlowsheetRunner(BaseFlowsheetRunner):
    """Interface for running and inspecting IDAES flowsheets."""

    def __init__(self, solve_steps: list[str] = None, **kwargs):
        """Initialize a flowsheet runner with default inspection actions.

        Args:
            solve_step: Optional list of steps considered solves.
            **kwargs: Additional keyword arguments passed to
                `BaseFlowsheetRunner`.
        """
        from .actions import (  # pylint: disable=C0415
            Timer,
            GitHash,
            CaptureSolverOutput,
            GetSolverResults,
            ModelVariables,
            MermaidDiagram,
            Diagnostics,
            StreamTable,
            UnitDofChecker,
            UnitModelReport,
            Progress,
            Inputs,
        )

        super().__init__(**kwargs)

        caller = inspect.currentframe().f_back
        caller_file = caller.f_globals.get("__file__") if caller else None

        dof_steps = [Steps.build, Steps.solve_initial, Steps.solve_optimization]
        # note: put solver_output first to re-enable stdout
        self.add_action(ActionNames.SOLVER_OUTPUT.value, CaptureSolverOutput)
        self.add_action(ActionNames.DIAGNOSTICS.value, Diagnostics)
        self.add_action(ActionNames.DOF.value, UnitDofChecker, "fs", dof_steps)
        self.add_action(ActionNames.MERMAID_DIAGRAM.value, MermaidDiagram)
        self.add_action(ActionNames.MODEL_REPORTS.value, UnitModelReport)
        self.add_action(ActionNames.MODEL_VARIABLES.value, ModelVariables)
        self.add_action(ActionNames.SOLVER_RESULTS.value, GetSolverResults)
        self.add_action(ActionNames.STREAM_TABLE.value, StreamTable)
        self.add_action(ActionNames.TIMINGS.value, Timer)
        self.add_action(ActionNames.GIT_HASH.value, GitHash, caller_file)
        self.add_action(ActionNames.PROGRESS.value, Progress)
        self.add_action(ActionNames.INPUTS.value, Inputs)

    def build(self, **kwargs):
        """Run just the build step"""
        self.run_step("build", **kwargs)

    def solve_initial(self, **kwargs):
        """Perform all steps up to 'solve_initial'"""
        self.run_steps(last="solve_initial", **kwargs)

    def show_diagram(self):
        """Return the diagram."""
        if Connectivity is not None:
            return display_connectivity(input_model=self.model)
        else:
            return ""

    @property
    def solver_status(self) -> str:
        """Solver status, from Pyomo

        Returns:
            str: Pyomo value (e.g., "ok") or "unknown" if it cannot be found
        """
        rpt = self.get_action("solver_results").report()
        if len(rpt.results) > 0:
            value = rpt.results[0].solver["Status"]
        else:
            value = "unknown"
        return value


# Load and run modules (or files)


def run_flowsheet(
    module_or_path: str,
    fs_attr: str = "",
    step_kw: dict[str, str] = None,
    report_db_file: str = None,
    test_db: bool = True,
    **kwargs,
) -> BaseFlowsheetRunner:
    """Run structfs-wrapper flowsheet found in a file or module.

    Args:
        module_or_path (str): Filesystem path or Python module path
        fs_attr: Used to select among multiple flowsheet wrappers in the same module.
                 If not given use the first one found, otherwise require a match.
        step_kw: Keywords sent to the `run_steps()` function, if applicable
        report_db_file: If given, set the report DB to this file
        test_db: If True, test the DB connection before running the flowsheet
        kwargs: Additional keyword arguments passed to fi_main, if applicable

    Returns:
        The flowsheet object that was run.

    Raises:
        ValueError, if no flowsheet is found, or no match to fs_attr
    """
    mod = load_module(module_or_path=module_or_path)
    target_kw = _module_target(mod)
    obj_map = find_flowsheet_objects(mod)
    if obj_map:
        if fs_attr:
            if fs_attr not in obj_map:
                raise ValueError(
                    f"Flowsheet object found, but specified name '{fs_attr}' "
                    f"not found in: {list(obj_map.keys())}"
                )
            fs = obj_map[fs_attr]
        else:
            if len(obj_map) > 1:
                _log.warning(
                    "Multiple flowsheet objects found, but no attribute "
                    "specified; using first."
                )
            fs = list(obj_map.values())[0]
        fs.set_report_target(**target_kw)
        if step_kw is None:
            step_kw = {}
        if report_db_file is not None:
            fs.set_report_db(dbfile=report_db_file)
        # pre-flight check for database
        if test_db:
            fs.test_db_connection()
        # now run
        fs.run_steps(**step_kw)
    else:
        func = _find_wrapped_main(mod)
        if func is None:
            raise ValueError(
                f"Could not find either a BaseFlowsheetRunner instance "
                f"or a @fi_main wrapped function in: {module_or_path}"
            )
        # run the wrapped function, with user arguments
        # pick flowsheet out of return value, to return to caller
        model, results = func(**kwargs)
        fs = results[RESULT_FLOWSHEET_KEY]
    return fs


def _module_target(mod):
    p = Path(mod.__file__)

    target_kw = {
        "module": mod.__name__,
        "filename": p.name,
        "filedir": str(p.parent.absolute()),
    }
    repo_hash = gitutil.git_head_hash(p)
    if repo_hash is not None:
        target_kw["hash"] = repo_hash

    return target_kw


def _find_wrapped_main(a_module) -> FunctionType | None:
    """Find a wrapped flowsheet main function.

    Returns:
       The wrapped function, or None if not found
    """
    if not hasattr(a_module, "fi_main"):
        return None
    all_found = []
    for k in dir(a_module):
        fn = getattr(a_module, k)
        if isinstance(fn, FunctionType):
            name = fn.__name__
            if name == "fi_wrapper":
                all_found.append(k)
    if len(all_found) > 1:
        raise ValueError(
            f"Multiple main() functions found in module {a_module.__name__}"
        )
    elif len(all_found) == 1:
        return getattr(a_module, all_found[0])
    return None


def main(args=None):
    """Run a flowsheet from the command-line."""
    try:
        default_report_file = Runner.get_default_report_db().filename
    except ValueError:
        default_report_file = "?unknown?"
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("name", help="Flowsheet file name or module name")
    ap.add_argument(
        "--db",
        "-D",
        help=f"Alternate SQLite database file for results (default={default_report_file})",
        default=None,
    )
    ap.add_argument(
        "--skip-db-test",
        action="store_true",
        help="Skip the check of the result database before running. "
        "This risks losing the results after the run completes.",
        default=False,
    )
    ap.add_argument(
        "--attr",
        default=None,
        help="Name of attribute in file/module "
        "containing structured flowsheet (e.g., 'FS'). "
        "This is only needed if there is more than one.",
    )
    steppenlist = ", ".join(Steps.index)
    ap.add_argument(
        "--last",
        default=None,
        help=f"Name of last step to run. Steps (in order): {steppenlist}",
    )
    ap.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Don't print extra info",
    )
    ap.add_argument(
        "-v", action="count", default=0, help="increase verbosity", dest="vb"
    )
    args = ap.parse_args(args=args)

    log = logging.getLogger("idaes_fi")
    h = logging.StreamHandler()
    h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] fi-run: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(h)
    if args.vb > 1:
        log.setLevel(logging.DEBUG)
    elif args.vb == 1:
        log.setLevel(logging.INFO)
    else:
        if args.quiet:
            log.setLevel(logging.ERROR)
        else:
            log.setLevel(logging.WARNING)
    log.propagate = False

    kwargs = {}
    if args.attr is not None:
        kwargs["fs_attr"] = args.attr
    if args.last is not None:
        kwargs["step_kw"] = {"last": args.last, "closest_step": True}

    if args.db is not None:
        log.info(f"Writing report to user-specified file: {args.db}")
    else:
        log.debug(f"Writing report to default file: {default_report_file}")

    try:
        fs = run_flowsheet(
            args.name, report_db_file=args.db, test_db=(not args.skip_db_test), **kwargs
        )
    except ValueError as err:
        print(f"ERROR: {err}")
        return 1
    except ModuleNotFoundError as err:
        print(f"ERROR loading flowsheet module: {err}")
        return 2
    except DBError as err:
        print(f"ERROR opening/loading database: {err}")
        return 3

    # unless the user requests, print solver output
    # (that we captured to the DB)
    if not args.quiet:
        try:
            rpt = fs.get_report_db().get_last_report()
        except DBError as err:
            print(f"ERROR: {err}")
            return 4
        if rpt:
            solver_out_steps = rpt["actions"][ActionNames.SOLVER_OUTPUT.value]["output"]
            for step_name, output in solver_out_steps.items():
                o = output.strip()
                if not o:
                    continue
                s = f"Solve, step={step_name}"
                n = len(s) + 2
                div = "+" + "=" * n + "+"
                print(f"\n{div}\n| {s} |\n{div}\n")
                print(o)

    return 0


if __name__ == "__main__":
    sys.exit(main())
