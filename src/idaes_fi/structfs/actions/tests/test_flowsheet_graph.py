"""Graph reports retain real ports and nested, indexed connections."""

from types import SimpleNamespace

import idaes  # Load IDAES extensions before Pyomo.
import pytest
from idaes.core import FlowsheetBlock
from idaes.models.properties.examples.saponification_thermo import (
    SaponificationParameterBlock,
)
from idaes.models.unit_models import MSContactor
from pyomo.environ import Block, ConcreteModel, TransformationFactory
from pyomo.network import Arc

from ..flowsheet_graph import FlowsheetGraph
from ...tests import flash_flowsheet, hda_flowsheet


@pytest.mark.unit
@pytest.mark.parametrize("flowsheet", [flash_flowsheet, hda_flowsheet])
def test_flowsheet_graph_report(flowsheet, tmp_path):
    runner = flowsheet.FS
    runner.reset()
    runner.set_report_db(dbfile=tmp_path / "graph.db")
    runner.build()
    assert not runner.failed
    report = runner.report()["actions"]["flowsheet_graph"]
    units = {unit["name"]: unit for unit in report["units"]}
    if flowsheet is flash_flowsheet:
        assert not report["arcs"]
        flash = units["fs.flash"]
        assert flash["class_name"] == "_ScalarFlash"
        assert flash["parent_block"] == "fs"
        assert flash["ports"] == [
            {"name": "inlet", "direction": "in"},
            {"name": "vap_outlet", "direction": "out"},
            {"name": "liq_outlet", "direction": "out"},
        ]
    else:
        assert len(report["arcs"]) == 7
        arc = next(arc for arc in report["arcs"] if arc["name"] == "fs.s03")
        assert arc == {
            "name": "fs.s03",
            "source_unit": "fs.M101",
            "source_port": "outlet",
            "dest_unit": "fs.H101",
            "dest_port": "inlet",
            "directed": True,
        }
        assert {
            port["name"]: port["direction"] for port in units["fs.S101"]["ports"]
        } == {
            "inlet": "in",
            "purge": "unknown",
            "recycle": "out",
        }
    assert (
        runner.get_report_db().get_last_report()["actions"]["flowsheet_graph"] == report
    )


@pytest.fixture
def mscontactor_model():
    model = ConcreteModel()
    model.fs = FlowsheetBlock(dynamic=False)
    model.fs.properties = SaponificationParameterBlock()
    model.fs.section = Block()
    for name in ("first", "second"):
        model.fs.section.add_component(
            name,
            MSContactor(
                number_of_finite_elements=2,
                streams={
                    stream: {
                        "property_package": model.fs.properties,
                        "has_energy_balance": False,
                        "has_pressure_balance": False,
                    }
                    for stream in ("aqueous", "organic")
                },
            ),
        )
    section = model.fs.section
    section.aqueous = Arc(
        source=section.first.aqueous_outlet, destination=section.second.aqueous_inlet
    )
    section.organic = Arc(
        [1, 2],
        rule=lambda block, index: {
            "source": block.second.organic_outlet,
            "destination": block.first.organic_inlet,
        },
    )
    return model


@pytest.mark.unit
def test_mscontactor_subblock_and_indexed_arcs(mscontactor_model):
    action = FlowsheetGraph(SimpleNamespace(model=None))
    assert action.report().model_dump() == {"units": [], "arcs": []}
    action = FlowsheetGraph(SimpleNamespace(model=mscontactor_model))
    report = action.report()
    units = {unit.name: unit for unit in report.units}
    first = units["fs.section.first"]
    assert first.parent_block == "fs.section"
    assert first.class_name == "_ScalarMSContactor"
    assert {port.name: port.direction for port in first.ports} == {
        "aqueous_inlet": "in",
        "aqueous_outlet": "out",
        "organic_inlet": "in",
        "organic_outlet": "out",
    }
    assert [arc.name for arc in report.arcs] == [
        "fs.section.aqueous",
        "fs.section.organic[1]",
        "fs.section.organic[2]",
    ]
    assert report.arcs[0].source_unit == "fs.section.first"
    assert report.arcs[0].source_port == "aqueous_outlet"
    assert report.arcs[0].dest_unit == "fs.section.second"
    assert report.arcs[0].dest_port == "aqueous_inlet"
    assert report.arcs[1].source_unit == "fs.section.second"
    assert report.arcs[1].dest_port == "organic_inlet"
    TransformationFactory("network.expand_arcs").apply_to(mscontactor_model)
    assert action.report() == report
