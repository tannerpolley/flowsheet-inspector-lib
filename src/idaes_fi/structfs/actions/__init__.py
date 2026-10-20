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

"""Runner action implementations."""

from importlib import import_module

__all__ = [
    "CaptureSolverOutput",
    "Diagnostics",
    "GitHash",
    "GetSolverResults",
    "MermaidDiagram",
    "ModelVariables",
    "SolverActionBase",
    "SolverResult",
    "StreamTable",
    "Timer",
    "UnitDofChecker",
    "UnitDofType",
    "UnitModelReport",
    "Progress",
    "Inputs",
]

_EXPORT_MODULES = {
    "CaptureSolverOutput": "solver",
    "Diagnostics": "solver",
    "GitHash": "git_hash",
    "GetSolverResults": "solver",
    "MermaidDiagram": "mermaid_diagram",
    "ModelVariables": "model_variables",
    "SolverActionBase": "solver",
    "SolverResult": "solver",
    "StreamTable": "stream_table",
    "Timer": "timer",
    "UnitDofChecker": "unit_dof_checker",
    "UnitDofType": "unit_dof_checker",
    "UnitModelReport": "model_report",
    "Progress": "progress",
    "Inputs": "inputs",
}


# Lazy-load allows you to not install dependencies
# for actions that you never import and use
def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as err:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from err
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
