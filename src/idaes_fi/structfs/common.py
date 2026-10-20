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
Common constants and functions
"""

import argparse
from collections import OrderedDict
from enum import Enum
import importlib
import importlib.util
import inspect
import json
from pathlib import Path
import os
import sys
import traceback

DEFAULT_SOLVER_NAME = "ipopt"

#: Special key used to embed a flowsheet runner instance in a result dict
RESULT_FLOWSHEET_KEY = "__fi"


class ActionNames(Enum):
    DIAGNOSTICS = "diagnostics"
    DOF = "degrees_of_freedom"
    MERMAID_DIAGRAM = "mermaid_diagram"
    MODEL_REPORTS = "model_reports"
    MODEL_VARIABLES = "model_variables"
    SOLVER_OUTPUT = "solver_output"
    SOLVER_RESULTS = "solver_results"
    STREAM_TABLE = "stream_table"
    TIMINGS = "timings"
    GIT_HASH = "git_hash"
    PROGRESS = "progress"
    INPUTS = "inputs"


class Steps:
    """Names of steps so that editor autocomplete, etc., will help
    to avoid typos.
    """

    build = "build"
    set_solver = "set_solver"
    initialize = "initialize"
    set_operating_conditions = "set_operating_conditions"
    set_scaling = "set_scaling"
    solve_initial = "solve_initial"
    set_autoscaling = "set_autoscaling"
    add_costing = "add_costing"
    initialize_costing = "initialize_costing"
    setup_optimization = "setup_optimization"
    solve_optimization = "solve_optimization"

    index = (
        build,
        set_solver,
        initialize,
        set_operating_conditions,
        set_scaling,
        solve_initial,
        set_autoscaling,
        add_costing,
        initialize_costing,
        setup_optimization,
        solve_optimization,
    )

    @classmethod
    def __len__(cls):
        return len(cls.index)


def load_module(module_or_path: str | Path):
    """
    Load a module - supports both module names and file paths.

    Args:
        module_or_path: Can be either:
            - Module name: "idaes.models.flash_flowsheet"
            - File path: "/Users/user/Downloads/my_flowsheet.py"
    Returns:
        module: The loaded Python module object.

    Raises:
        TypeError: not a string or Path
        ValueError: Relative module name
        FileNotFoundError: Could not find module file

    Note:
        For file paths, this function sets up a pseudo-package structure to
        support relative imports (e.g., 'from ..sibling import something').
    """
    # Check if input is a file path
    file_path, module_name = None, None
    if isinstance(module_or_path, Path):
        file_path = module_or_path
    elif isinstance(module_or_path, str):
        if module_or_path.endswith(".py") or os.path.isfile(module_or_path):
            file_path = Path(module_or_path)
        elif module_or_path.startswith("."):
            raise ValueError("Relative module names not allowed!")
        else:
            module_name = module_or_path
    else:
        raise TypeError("Input must be a string or Path")

    if file_path is not None:
        file_path = file_path.absolute()
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Get directory structure for package simulation
        dir_path = str(file_path.parent)  # e.g., /Users/user/workspace/subdir
        parent_dir = str(file_path.parent.parent)  # e.g., /Users/user/workspace
        package_name = str(file_path.parent.stem)  # e.g., "subdir"
        module_basename = file_path.stem
        full_module_name = f"{package_name}.{module_basename}"  # e.g., "subdir.test"

        # Add both current directory and parent directory to sys.path
        # Current dir is needed for same-directory imports (import hda_ideal_VLE)
        # Parent dir is needed for sibling package imports
        if dir_path not in sys.path:
            sys.path.insert(0, dir_path)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)

        # Create module spec with submodule_search_locations for package support
        spec = importlib.util.spec_from_file_location(
            full_module_name, file_path, submodule_search_locations=[dir_path]
        )

        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {file_path}")

        # Create the module object from spec
        module = importlib.util.module_from_spec(spec)

        # KEY: Set __package__ so relative imports know the package context
        module.__package__ = package_name

        # Register in sys.modules so other imports can find it
        sys.modules[full_module_name] = module

        # Execute the module code (this actually loads the content)
        spec.loader.exec_module(module)
        return module
    elif module_name is not None:
        return importlib.import_module(module_name)
    else:
        raise RuntimeError("Logic error")  # should not get here


def find_flowsheet_objects(a_module) -> dict[str, object]:
    """Find flowsheet objects in the module.

    Args:
      a_module: Module in which to look

    Returns:
        Dict mapping attribute name(s) to flowsheet object(s), or an
        empty dict if none found
    """
    obj_map = {}
    for key in dir(a_module):
        obj = getattr(a_module, key)
        # identify it with duck-typing
        if (
            not inspect.isclass(obj)
            and hasattr(obj, "run_steps")
            and hasattr(obj, "model")
        ):
            obj_map[key] = obj
    return obj_map


class FlowsheetLoadError(Exception):
    """Raised if a flowsheet is not found."""


def _get_steps_for_flowsheet(fs: str, fs_attr: str | None) -> list[str]:
    # Load the module with the flowsheet
    try:
        module = load_module(fs)
    except (ValueError, FileNotFoundError, ModuleNotFoundError) as err:
        raise FlowsheetLoadError(f"Could not load flowsheet: {err}")
    except Exception as err:
        div = "-" * 40
        raise FlowsheetLoadError(
            f"Error while loading module: {err}\n{div}\n{traceback.format_exc()}{div}"
        )

    # Get mapping of all flowsheet objects in module
    objs = find_flowsheet_objects(module)
    if not objs:
        raise FlowsheetLoadError(f"No structured flowsheets found in module '{fs}'")

    # Get one flowsheet object in the module
    fs_obj = None
    if len(objs) == 1:
        fs_obj = list(objs.values())[0]
    elif fs_attr is None:
        names = ", ".join(list(objs.keys()))
        raise FlowsheetLoadError(
            f"Multiple flowsheets found, use --attr option "
            f"to select which one to show: {names}"
        )
    else:
        if fs_attr not in objs:
            raise FlowsheetLoadError(
                f"Flowsheet object '{fs_attr}' not found in flowsheet module '{fs}'"
            )
        fs_obj = objs[fs_attr]

    return fs_obj.get_defined_steps()


def main(*cmdline):
    parser = argparse.ArgumentParser(
        description="List (standard) structured flowsheet steps", add_help=True
    )
    parser.add_argument(
        "--fs",
        metavar="FLOWSHEET",
        help="Show steps implemented in FLOWSHEET, which is a "
        "module or file, instead of all standard steps",
        default=None,
    )
    parser.add_argument(
        "--attr",
        default=None,
        help="Name of attribute in file/module "
        "containing structured flowsheet (e.g., 'FS'). "
        "This is ignored without '--fs' option, "
        "and only needed if there is more than one",
    )
    parser.add_argument(
        "-t", "--format", help="Output format", choices=["json", "text"], default="json"
    )
    if cmdline:
        args = parser.parse_args(cmdline)
    else:
        args = parser.parse_args()

    steps_list = None
    if args.fs is None:
        steps_list = Steps.index
    else:
        flowsheet = args.fs.strip()
        try:
            steps_list = _get_steps_for_flowsheet(args.fs, args.attr)
        except FlowsheetLoadError as err:
            print(f"Error loading flowsheet '{flowsheet}':\n  {err}")

    if steps_list is None:
        retcode = 1  # Not OK
    else:
        retcode = 0  # OK
        if args.format == "json":
            json.dump(steps_list, sys.stdout)
        else:
            for name in steps_list:
                print(name)

    return retcode


if __name__ == "__main__":
    print(sys.argv)
    sys.exit(main())
