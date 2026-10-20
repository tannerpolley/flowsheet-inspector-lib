"""Declared metadata stays tied to the current flowsheet variables."""

import idaes  # Load IDAES extensions before Pyomo.
import pytest
from pyomo.environ import Expression, Var, value
from pyomo.core.base.units_container import UnitsError

from ...fsrunner import FlowsheetRunner
from ...tests import flash_flowsheet, hda_flowsheet


@pytest.mark.unit
@pytest.mark.parametrize(
    "flowsheet,unit_name", [(flash_flowsheet, "flash"), (hda_flowsheet, "H101")]
)
def test_inputs_report(flowsheet, unit_name, tmp_path, monkeypatch):
    runner = flowsheet.FS
    monkeypatch.setattr(runner, "_ann", {})
    runner.reset()
    runner.set_report_db(dbfile=tmp_path / "inputs.db")
    runner.build()
    assert not runner.failed
    assert runner.report()["actions"]["inputs"] == {"variables": []}
    assert runner.resolve_from == "solve_initial"
    assert FlowsheetRunner(resolve_from="initialize").resolve_from == "initialize"

    unit = getattr(runner.model.fs, unit_name)
    pressure = unit.inlet.pressure[0]
    pressure.setlb(10000)
    pressure.setub(200000)
    runner.annotate_var(
        pressure,
        key="pressure",
        title="Feed pressure",
        units="kPa",
        is_output=False,
        input_category="Feed",
        bounds=(20, 190),
        rebuild=True,
    )
    runner.annotate_var(
        unit.heat_duty[0], key="duty", is_input=False, output_category="Results"
    )
    runner.annotate_var(unit.inlet.temperature, key="temperature", units="K")
    runner.run_steps("set_operating_conditions", "set_operating_conditions")
    assert not runner.failed
    rows = {
        row["key"]: row for row in runner.report()["actions"]["inputs"]["variables"]
    }
    assert rows["pressure"] == {
        "key": "pressure",
        "title": "Feed pressure",
        "description": pressure.name,
        "units": "kPa",
        "value": value(pressure) / 1000,
        "fixed": pressure.fixed,
        "bounds": (20, 190),
        "category": "Feed",
        "input_category": "Feed",
        "output_category": "main",
        "is_input": True,
        "is_output": False,
        "rebuild": True,
        "rounding": 3,
    }
    assert rows["duty"]["category"] == "Results"
    assert rows["duty"]["is_output"] and not rows["duty"]["is_input"]
    assert rows["temperature"]["bounds"] == unit.inlet.temperature[0].bounds
    stored = runner.get_report_db().get_last_report()
    assert stored["actions"]["inputs"]["variables"][0]["bounds"] == [20, 190]

    pressure.fix(180000)
    assert runner.get_action("inputs").report().variables[0].value == 180
    runner.annotate_var(pressure, key="pressure", units="kPa")
    assert runner.get_action("inputs").report().variables[0].bounds == (10, 200)
    unit.heat_duty[0].set_value(None)
    assert runner.get_action("inputs").report().variables[1].value is None
    composition = unit.inlet.vars.get("mole_frac_comp")
    if composition is None:
        composition = unit.inlet.flow_mol_phase_comp
    runner.annotate_var(composition, key="composition")
    keys = [row.key for row in runner.get_action("inputs").report().variables]
    assert any(
        key.startswith("composition[0.0,") and key.endswith("benzene]") for key in keys
    )
    runner.model.fs.metric = Expression(expr=2 * pressure)
    runner.annotate_var(
        runner.model.fs.metric, key="metric", units="kPa", is_input=False
    )
    runner.model.fs.untyped = Var(initialize=300)
    runner.annotate_var(runner.model.fs.untyped, key="untyped", units="K")
    runner.annotate_var(pressure, key="label", units="Centipedes")
    rows = {
        row["key"]: row for row in runner.report()["actions"]["inputs"]["variables"]
    }
    assert rows["metric"]["value"] == 360
    assert rows["metric"]["bounds"] == (None, None)
    assert rows["metric"]["fixed"]
    assert rows["untyped"]["value"] == 300
    assert rows["untyped"]["units"] == "K"
    assert rows["label"]["value"] == 180000
    assert rows["label"]["units"] == "Centipedes"
    runner.annotate_var(pressure, key="invalid", units="K")
    with pytest.raises(UnitsError):
        runner.report()
    runner.build(save_report=False)
    assert runner.get_action("inputs").report().variables == []
