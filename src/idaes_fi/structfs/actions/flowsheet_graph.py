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
"""Units, ports, and Pyomo Arc graph action."""

from typing import Literal

from idaes.core import UnitModelBlockData
from pydantic import BaseModel, Field
from pyomo.environ import Block
from pyomo.network import Arc, Port

from ..action_base import Action


class GraphPort(BaseModel):
    name: str
    direction: Literal["in", "out", "bidirectional", "unknown"]


class GraphUnit(BaseModel):
    name: str
    class_name: str
    parent_block: str
    ports: list[GraphPort] = Field(default_factory=list)


class GraphArc(BaseModel):
    name: str
    source_unit: str
    source_port: str
    dest_unit: str
    dest_port: str
    directed: bool


class FlowsheetGraph(Action):
    """Extract units, ports and individual Arc data, including nested blocks."""

    class Report(BaseModel):
        units: list[GraphUnit] = Field(default_factory=list)
        arcs: list[GraphArc] = Field(default_factory=list)

    def report(self) -> Report:
        model = self._runner.model
        if model is None:
            return self.Report()
        units = {
            block.name: block
            for block in model.component_data_objects(Block, descend_into=True)
            if isinstance(block, UnitModelBlockData)
        }
        ports = list(model.component_data_objects(Port, descend_into=True))
        owners = {}
        directions = {port.name: set() for port in ports}
        for port in ports:
            parent = port.parent_block()
            owner = parent
            while owner is not None and not isinstance(owner, UnitModelBlockData):
                owner = owner.parent_block()
            owner = parent if owner is None else owner
            units[owner.name] = owner
            owners[port.name] = owner

        arcs = []
        # Expanded Arcs are inactive, but still own the endpoint information.
        for arc in model.component_data_objects(Arc, descend_into=True, active=None):
            source, dest = arc.ports
            if arc.directed:
                directions[source.name].add("out")
                directions[dest.name].add("in")
            source_unit, dest_unit = owners[source.name], owners[dest.name]
            arcs.append(
                GraphArc(
                    name=arc.name,
                    source_unit=source_unit.name,
                    source_port=source.getname(
                        fully_qualified=True, relative_to=source_unit
                    ),
                    dest_unit=dest_unit.name,
                    dest_port=dest.getname(fully_qualified=True, relative_to=dest_unit),
                    directed=arc.directed,
                )
            )

        graph_units = {}
        for name, unit in units.items():
            graph_units[name] = GraphUnit(
                name=name,
                class_name=type(unit).__name__,
                parent_block=(
                    unit.parent_block().name if unit.parent_block() is not None else ""
                ),
            )
        for port in ports:
            direction = directions[port.name]
            if len(direction) == 2:
                inferred = "bidirectional"
            elif direction:
                inferred = next(iter(direction))
            else:
                name = port.local_name.lower()
                if "inlet" in name:
                    inferred = "in"
                elif "outlet" in name:
                    inferred = "out"
                else:
                    inferred = "unknown"
            owner = owners[port.name]
            graph_units[owner.name].ports.append(
                GraphPort(
                    name=port.getname(fully_qualified=True, relative_to=owner),
                    direction=inferred,
                )
            )
        return self.Report(units=list(graph_units.values()), arcs=arcs)
