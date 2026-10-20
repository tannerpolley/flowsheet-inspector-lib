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
"""Declared inputs and outputs action."""

from pydantic import BaseModel, Field
from pyomo.environ import units as pyunits, value

from ..action_base import Action


class AnnotatedVariable(BaseModel):
    """One declared input or output, with display metadata and current state."""

    key: str
    title: str
    description: str
    units: str
    value: float | None
    fixed: bool
    bounds: tuple[float | None, float | None]
    category: str
    input_category: str
    output_category: str
    is_input: bool
    is_output: bool
    rebuild: bool
    rounding: int


class Inputs(Action):
    """Report annotated inputs and outputs from the current model."""

    class Report(BaseModel):
        variables: list[AnnotatedVariable] = Field(default_factory=list)

    def report(self) -> Report:
        variables = []
        for key, annotation in self._runner.annotated_vars.items():
            component = annotation["var"]
            items = component.items() if component.is_indexed() else [(None, component)]
            for index, variable in items:
                native_units = pyunits.get_units(variable)
                try:
                    declared_units = getattr(pyunits, annotation["units"])
                except AttributeError:
                    # Existing annotations may use arbitrary display labels.
                    declared_units = None

                def converted(number):
                    if (
                        number is None
                        or declared_units is None
                        or str(native_units) == "dimensionless"
                    ):
                        return number
                    return pyunits.convert_value(
                        number, from_units=native_units, to_units=declared_units
                    )

                bounds = annotation["bounds"]
                if bounds is None:
                    bounds = tuple(
                        converted(bound)
                        for bound in getattr(variable, "bounds", (None, None))
                    )
                row_key = key
                if component.is_indexed() and len(component) > 1:
                    suffix = (
                        ",".join(map(str, index))
                        if isinstance(index, tuple)
                        else str(index)
                    )
                    row_key = f"{key}[{suffix}]"
                metadata = {
                    name: annotation[name]
                    for name in (
                        "title",
                        "description",
                        "units",
                        "input_category",
                        "output_category",
                        "is_input",
                        "is_output",
                        "rebuild",
                        "rounding",
                    )
                }
                variables.append(
                    AnnotatedVariable(
                        key=row_key,
                        value=converted(value(variable, exception=False)),
                        fixed=variable.is_fixed(),
                        bounds=bounds,
                        category=annotation[
                            (
                                "input_category"
                                if annotation["is_input"]
                                else "output_category"
                            )
                        ],
                        **metadata,
                    )
                )
        return self.Report(variables=variables)
