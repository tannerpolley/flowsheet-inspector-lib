---
title: Flowsheet Inspector Library Usage
---
# Flowsheet Inspector Library Usage

The Flowsheet Inspector (FI) library is primarily a way to "wrap" the functions
used to build, set up, and solve a flowsheet so that these steps can be
controlled from outside the program, and also arbitrary "actions" can run before
and after each step or each sequence of steps. Built-in actions include
gathering information on variable state, creating a diagram, and running the
diagnostics, but this is extensible.

This section starts from the assumption that you have a FI-wrapped flowsheet and
describes how to run it and get back the information it collects during the
actions. For information on how to wrap the flowsheet, see the [API](api)
section.

## VSCode extension

You can load and run FI flowsheets with our VSCode extension. Please see the
[FI VSCode extension](https://github.com/prommis/flowsheet-inspector) for
details.

## Command-line (shell)

You can run a flowsheet from the command-line with `fi-run`.
You can list the steps in a flowsheet (or all possible ones) with the command-line program `fi-steps`.

### fi-run usage

The `fi-run` command lets you run a flowsheet from the command-line.
The results of that run (the report) are stored in the default database,
unless the user provides an alternate database.
Additional options help to select which flowsheet to run and which
steps to run ("up to" a given step).

```{code} text
$ fi-run -h
usage: fi-run [-h] [--db DB] [--skip-db-test] [--attr ATTR] [--last LAST] [-q] [-v] name

Run a flowsheet from the command-line.

positional arguments:
  name            Flowsheet file name or module name

options:
  -h, --help      show this help message and exit
  --db, -D DB     Alternate SQLite database file for results (default=/home/dang/.idaes/reportdb.sqlite)
  --skip-db-test  Skip the check of the result database before running. This risks losing the results after the run completes.
  --attr ATTR     Name of attribute in file/module containing structured flowsheet (e.g., 'FS'). This is only needed if there is more than one.
  --last LAST     Name of last step to run. Steps (in order): build, set_solver, initialize, set_operating_conditions, set_scaling, solve_initial, set_autoscaling, add_costing, initialize_costing, setup_optimization, solve_optimization
  -q, --quiet     Don't print extra info
  -v              increase verbosity
                                        
```

### fi-run examples

To run the structured flowsheet in `excellent_flowsheet.py` in the current
directory:

```{code} shell
fi-run excellent_flowsheet.py
```

To run the structured flowsheet "fs1" in `multiple_flowsheets.py` in the current
directory, use the `--attr` flag to indicate the one you want.

```{code} shell
fi-run excellent_flowsheet.py --attr fs1
```

### fi-steps usage

The term "steps" refers to one distinct stage of building or solving a flowsheet.
See the full description in the [sample notebook for the API](api) for details.
The `fi-steps` command allows you to see which steps are defined for a given
flowsheet. This is useful for higher-level interfaces to show the users what steps
they can run, so the default output is machine-readable JSON. However, since it may also be
handy in some cases for interactive use, a simple text output is also available.
 
```{code} text
usage: fi-steps [-h] [--fs FLOWSHEET] [--attr ATTR] [-t {json,text}]

List (standard) structured flowsheet steps

options:
  -h, --help            show this help message and exit
  --fs FLOWSHEET        Show steps implemented in FLOWSHEET, which is a module or file, instead of all standard
                        steps
  --attr ATTR           Name of attribute in file/module containing structured flowsheet (e.g., 'FS'). This is
                        ignored without '--fs' option, and only needed if there is more than one
  -t, --format {json,text}
                        Output format
```

### fi-steps examples

To get steps for the test/demo flowsheet, using its module path:

```{code} shell
$ fi-steps --fs idaes_fi.structfs.tests.demo_flowsheet_structured
["build", "set_solver", "set_operating_conditions", "set_scaling", "solve_initial", "solve_optimization"]
```

To get steps for the "FS2" flowsheet in a test/demo with multiple structured
flowsheets defined, using the file path and with output as plain text (not JSON):

```{code} shell
$ fi-steps --fs idaes_fi.structfs.tests.demo_flowsheet_structured_multi --attr FS2 -t text
build
set_solver
set_operating_conditions
set_scaling
solve_initial
solve_optimization
```

To see all possible steps (in order), as plain text

```{code} shell
$ fi-steps --format text
build
set_solver
initialize
set_operating_conditions
set_scaling
solve_initial
set_autoscaling
add_costing
initialize_costing
setup_optimization
solve_optimization
```

## Python API in a script

There are two basic ways to run structure flowsheets in a script.

The simplest and most obvious way is to import the structured flowsheet object
that was created in the module, and call `run_steps()` on that object.

```{code} python
from excellent_flowsheet import FS  # import flowsheet object
# ...
def main():
    FS.run_steps()
```

The second way is to call `run_flowsheet()`, which can run any module or path
(and is what the program `fi-run` calls internally).

```{code} python
def run_flowsheet(
    module_or_path: str, fs_attr: str = "", step_kw: dict[str, str] = None, **kwargs
) -> BaseFlowsheetRunner:
    """Run structfs-wrapper flowsheet found in a file or module.

    Args:
        module_or_path (str): Filesystem path or Python module path
        fs_attr: Used to select among multiple flowsheet wrappers in the same module.
                 If not given use the first one found, otherwise require a match.
        step_kw: Keywords sent to the `run_steps()` function, if applicable
        kwargs: Additional keyword arguments passed to fi_main, if applicable

    Returns:
        The flowsheet object that was run.

    Raises:
        ValueError, if no flowsheet is found, or no match to fs_attr
    """
```

## Python API in a Jupyter Notebook

Usage in Jupyter is the same as in a Python program. In this environment the
`fi_main` decorator may be handy. For a full example, see this
[example Jupyter notebook](usage_nb).

## Annotating inputs and outputs

Declare variables with `FS.annotate_var` in the build or operating-conditions step:

```python
FS.annotate_var(m.fs.feed.flow_vol[0], key="feed_flow", title="Brine feed",
                units="L/h", is_input=True, is_output=False,
                input_category="Feed", bounds=(0.1, 10), rebuild=False)
FS.annotate_var(m.fs.costing.LCOP, key="lcop", title="Product cost",
                is_input=False, is_output=True, output_category="Economics")
```

The default `inputs` action emits `report()["actions"]["inputs"]["variables"]`.
Each row contains the key, title, description, units, current value, fixed status,
bounds, input/output flags and categories, rounding, and `rebuild`. `category`
uses the input category for inputs and the output category for output-only rows.
Values and native variable bounds are converted to declared units. Explicit
`bounds` are metadata in those units and do not change the model's bounds.
Existing custom display-unit labels and values without native physical units
retain their original values. Recognized incompatible physical units raise an
error. Output expressions are supported, with nullable bounds and their
expression's fixed status.
Uninitialized values are `null`. Indexed variables with multiple entries produce
one row per entry, with keys such as `composition[0.0,benzene]`; a single entry
keeps the declared key. A model without annotations emits an empty list.

`FlowsheetRunner(resolve_from="initialize")` records the first step to use for a
future in-process re-solve (default: `"solve_initial"`). `rebuild=True` marks
structural inputs. These declarations do not themselves edit inputs or run a
solve. A new build or `reset()` clears annotations from the previous model.

## Flowsheet graph action

The default `flowsheet_graph` action emits
`report()["actions"]["flowsheet_graph"]` with `units` and `arcs` lists. Units have
fully qualified `name`, Python `class_name`, `parent_block`, and `ports` (each with
a unit-relative `name` and inferred `direction`). Direction is `in`, `out`,
`bidirectional`, or `unknown`: directed Arcs determine direction first; otherwise
port names containing `inlet` or `outlet` provide a fallback.

Arcs have `name`, `source_unit`, `source_port`, `dest_unit`, `dest_port`, and
`directed`. Undirected Arcs retain their declared endpoint order without inferring
port direction. The action reads Pyomo Arc data directly, including IndexedArc
entries, expanded Arcs, and Arcs on nested blocks. It includes IDAES units without
connections, internal units with their parent relationship, and blocks that own
ports. Empty models produce empty lists. Icon lookup and block collapsing are
left to later consumers; no connectivity registry is required for this report.
