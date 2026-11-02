#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Tests for the units on literals (units.py, the unitRule rows, and their use in hxemit.py).
Run from the repo root: python -X utf8 -m pytest src/gen -q"""
import copy
import pathlib
import re
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIBS = ROOT / "src" / "xeto"
sys.path.insert(0, str(HERE))

import cxf_source  # noqa: E402

SRC = cxf_source.source_root()

import classmap  # noqa: E402
import classmap_table  # noqa: E402
import generate  # noqa: E402
import units  # noqa: E402

K, DK, PA, ONE = ("K", False), ("K", True), ("Pa", False), units.DIMENSIONLESS


def g36_text():
    return "\n".join((LIBS / lib / "g36.xeto").read_text(encoding="utf-8") for lib in generate.G36_LIBS)


def spec_block(text, name):
    return re.search(r"(?ms)^%s: \S+ <.*?^\}$" % re.escape(name), text).group(0)


@pytest.mark.parametrize("op, a, b, want", [
    ("sub", K, K, DK),             # two temperatures differ by a temperature difference
    ("sub", K, DK, K),
    ("sub", DK, DK, DK),
    ("sub", DK, K, None),          # a difference less an absolute temperature is no unit
    ("add", K, DK, K),
    ("add", DK, DK, DK),
    ("add", K, K, None),           # two absolute temperatures do not add
    ("add", PA, PA, PA),
    ("add", PA, K, None),
    ("mul", K, ONE, None),         # scaling an absolute temperature is no unit
    ("mul", DK, ONE, DK),
    ("mul", PA, ONE, PA),
    ("div", PA, PA, ONE),
    ("div", PA, ONE, PA),
])
def test_each_arithmetic_cell(op, a, b, want):
    # Wrong behavior caught: a difference of temperatures typed as an absolute temperature (it would convert with
    # the offset, 2 K becoming 35.6 °F instead of 3.6 Δ°F), or a sum of absolute temperatures given a unit.
    assert units.cell(op, a, b)[0] == want


def test_the_comparator_hysteresis_is_a_difference():
    assert units.cell("delta", K)[0] == DK and units.cell("delta", PA)[0] == ("Pa", True)


@pytest.mark.parametrize("op, i, other, y, want", [
    ("add", 1, K, units.UNKNOWN, DK),    # a literal added to a temperature is a temperature difference
    ("add", 1, K, K, DK),
    ("sub", 1, K, DK, K),                # TZon - t = a difference: t is a temperature
    ("sub", 1, K, K, DK),                # TZon - dT = a temperature: dT is a difference
    ("mul", 1, PA, PA, ONE),             # a gain between two values of one unit is dimensionless
    ("div", 0, ONE, PA, PA),
])
def test_an_op_solves_backward_where_the_arithmetic_fixes_the_answer(op, i, other, y, want):
    assert units.backward(op, i, other, y) == want


def test_a_temperature_is_written_in_kelvin_absolute_or_difference():
    # Wrong behavior caught (the delta trap): a difference written ΔK, which hx.comps refuses beside K (haystack
    # Number.plusUnit has no K plus ΔK, and ComparisonHys faults a deadband whose unit is not Number.minusUnit of
    # inB's, which is K for K). Whether it is a difference is recorded in cdlLiteralDelta instead.
    assert units.written_symbol(DK) == "K" and units.written_symbol(K) == "K"
    assert units.written_symbol(ONE) is None and units.written_symbol(("1", True)) is None


def test_two_units_join_into_a_conflict_but_a_difference_without_offset_does_not():
    m = units.Model()
    m.seed("a", K, "x"); m.seed("b", DK, "x"); m.join("a", "b")
    m.seed("c", PA, "x"); m.seed("d", ("Pa", True), "x"); m.join("c", "d")
    val = m.solve()
    assert m.unit_of(val, "a")[0] is None and "two different units" in m.unit_of(val, "a")[1]
    assert m.unit_of(val, "c")[0] == ("Pa", True)


@pytest.mark.inputs
def test_every_class_that_runs_has_a_unit_rule_and_a_bad_rule_is_refused():
    # Wrong behavior caught: a class with no rule silently left unitless, or a rule naming a connector the class
    # does not have, so the propagation stops at it.
    classes = generate.load_classes(SRC)
    doc, errors = classmap.build(classes)
    assert errors == []
    missing = [n for n, e in doc["classes"].items() if e["grade"] != "none" and not e["unitRule"]]
    assert missing == []
    table = copy.deepcopy(classmap_table.T)
    table["RealsLimiter"]["unitRule"]["keep"] = [["u", "uMin", "uMaxx", "y"]]
    del table["RealsAdd"]["unitRule"]
    _, errors = classmap.build(classes, table=table)
    assert "RealsLimiter: unitRule names uMaxx, which the class does not have" in errors
    assert "RealsAdd: no unitRule; every class that runs needs one" in errors


def test_the_freeze_protection_thresholds_carry_kelvin_and_their_mbl_text():
    # Wrong behavior caught: 277.55 written unitless, which hx.comps reads in the unit of a °F point, so
    # 55 °F < 277.55 holds and stage 3 shuts the supply fan. With K the comparison against °F faults instead.
    block = spec_block(g36_text(), "AhusMultiZoneVavSetPointsFreezeProtection")
    feed = re.search(r'(?m)^  lesThr_t: hx\.comps::NumberConst\? <([^\n]*)> \{\n    out: hx\.comps::StatusNumber \{ val: (\S+) \}', block)
    assert feed.group(2) == "277.55K"
    assert 'cdlLiteralUnits:{out:"K"}' in feed.group(1) and 'cdlLiteralExprs:{out:"273.15 +4.4"}' in feed.group(1)
    assert "cdlLiteralDelta" not in feed.group(1)


def test_a_pressure_deadband_carries_pascal():
    assert "    deadband: 1Pa" in g36_text()


def test_a_unitless_literal_has_its_reason_in_the_units_report():
    # Wrong behavior caught: a literal left unitless with no account of why, so a gap in the rules hides.
    rep = (HERE / "units-report.txt").read_text(encoding="utf-8")
    m = re.search(r"literals (\d+): with a unit (\d+), dimensionless (\d+), no unit (\d+)", rep)
    total, unit, dimless, none = map(int, m.groups())
    assert total == unit + dimless + none and total > 700
    listed = re.findall(r"(?m)^  \S+ \S+\.\S+: (.+)$", rep.split("each literal with no unit:")[1])
    assert len(listed) == none and all(listed)


def test_each_comp_gets_the_unit_it_takes():
    # Wrong behavior caught: a deadband written as a difference unit (ΔK) that ComparisonHys refuses beside a K
    # threshold, a Hysteresis limit with no unit beside a K input, or a unit suffix on a CdlPid Float slot, which
    # does not parse as a Float.
    text = g36_text()
    for m in re.finditer(r"(?ms)^  (\w+): hx\.comps::(\w+)\? <([^\n]*)> \{\n(.*?)^  \}", text):
        comp, meta, body = m.group(2), m.group(3), m.group(4)
        units_ = dict(re.findall(r'(\w+):"([^"]*)"', (re.search(r"cdlLiteralUnits:\{([^}]*)\}", meta) or [None, ""])[1]))
        for slot, val in re.findall(r"(?m)^    (\w+): (-?\d[^\s<]*)$", body):
            if "ΔK" in val:
                raise AssertionError("%s.%s written in ΔK: %s" % (m.group(1), slot, val))
            if comp == "CdlPid":
                assert re.fullmatch(r"-?[\d.eE+-]+", val), (m.group(1), slot, val)
            elif units_.get(slot) not in (None, "1"):
                assert val.endswith(units_[slot]), (m.group(1), slot, val, units_[slot])


@pytest.mark.parametrize("i, other, want", [
    (0, K, K),       # y = a - b with b absolute: a difference less an absolute is no unit, so a is absolute
    (1, DK, DK),     # y = a - b with a a difference: b is a difference too
    (1, K, None),    # with a absolute, b may be either: not fixed
])
def test_subtract_solves_backward_from_one_operand_where_that_fixes_the_other(i, other, want):
    # Wrong behavior caught: backward subtraction gave nothing for a temperature unless the
    # output was known, which left ZoneGroups hys9/hys10 limits unitless.
    assert units.backward("sub", i, other, units.UNKNOWN) == want


def _literal_unit(cls, inst, name):
    import hxemit
    allc, rows = generate.mapped_classes(SRC)
    m = hxemit.Mapper(allc[generate.G36_PREFIX + cls], allc, rows)
    return m.literal_unit(m.ci.inst(inst), name)[0]


@pytest.mark.inputs
@pytest.mark.parametrize("cls, inst, name, want", [
    ("ZoneGroups.OperationMode", "hys9", "uLow", DK),
    ("ZoneGroups.OperationMode", "hys10", "uHigh", DK),
    ("AHUs.SingleZone.VAV.SetPoints.SupplyFan", "addPar", "p", DK),
    ("AHUs.SingleZone.VAV.SetPoints.SupplyTemperature", "addPar3", "p", DK),
])
def test_a_constant_with_a_known_unit_passes_it_forward(cls, inst, name, want):
    # Wrong behavior caught: a constant bound to a parameter of known unit never passed that unit to
    # what it feeds, so these temperature differences stayed unitless.
    assert _literal_unit(cls, inst, name) == want


@pytest.mark.inputs
def test_every_pid_whose_setpoint_carries_a_unit_records_its_error_scale():
    # Wrong behavior caught: 18 temperature and pressure loops left r at the comp default 1 with
    # no record of its unit, so a resolver converting the loop to °F gave 1.8 times the gain, silently.
    import hxemit
    allc, rows = generate.mapped_classes(SRC)
    text = g36_text()
    checked = 0
    for p, ci in sorted(allc.items()):
        if ci.kind != "composite" or not p.startswith(generate.G36_PREFIX):
            continue
        m = None
        for inst in ci.insts:
            r = rows.get(inst.cls)
            if not r or r["name"] not in ("RealsPid", "RealsPidWithReset"):
                continue
            m = m or hxemit.Mapper(ci, allc, rows)
            model, val = m.unit_model()
            us = model.unit_of(val, "i:%s.u_s" % inst.name)[0]
            if us is None or us[0] == "1":
                continue
            checked += 1
            block = spec_block(text, generate.spec_name(p, generate.G36_PREFIX))
            line = re.search(r"(?ms)^  %s: hx\.comps::CdlPid\? <([^\n]*)> \{\n(.*?)^  \}" % inst.name, block)
            assert line, (p, inst.name)
            assert 'r:"%s"' % us[0] in line.group(1), (p, inst.name, us)
            assert re.search(r'cdlLiteralDelta:"(?:[^"]*,)?r[,"]', line.group(1)), (p, inst.name)
            assert re.search(r"(?m)^    r: [\d.]+$", line.group(2)), (p, inst.name)
    assert checked == 23, checked


def test_the_economizer_low_cutoffs_carry_the_unit_of_the_high_cutoff():
    # Wrong behavior caught: TOutHigLimCutLow and hOutHigLimCutLow, which MBL computes as the
    # typed high cutoff less a hysteresis, had no unit meta at all, so a resolver could not convert them beside the
    # high cutoff they pair with in one Hysteresis. The high cutoff is a temperature DIFFERENCE (TOut - TOutCut).
    text = g36_text()
    t = re.findall(r"(?m)^  tOutHigLimCutLow: [^\n]*", text)
    h = re.findall(r"(?m)^  hOutHigLimCutLow: [^\n]*", text)
    assert len(t) == 2 and len(h) == 2
    for l in t:
        assert 'cdlUnitInferred:"K"' in l and re.search(r"[<, ]cdlDelta[,>]", l) and "quantity:" not in l, l
    for l in h:
        assert 'cdlUnitInferred:"J/kg"' in l and "cdlDelta" not in l and " unit:" not in l, l


def test_a_pulse_amplitude_is_a_difference_beside_its_absolute_offset():
    # Wrong behavior caught: amplitude kept in one group with offset and y, so a resolver
    # converts a 5 K amplitude with the offset (to 41 degrees F) where it should scale it (to 9 Fahrenheit degrees).
    rule = classmap_table.T["RealsSourcesPulse"]["unitRule"]
    assert not any("amplitude" in g for g in rule["keep"])
    assert (rule["op"], rule["ins"], rule["out"]) == ("add", ["offset", "amplitude"], "y")
    assert units.backward("add", 1, K, K) == DK


def test_a_dimensionless_connector_on_a_percent_point_records_the_scale_and_ppm_is_recorded_as_counted():
    # Wrong behavior caught: a unit "1" connector bound to a % point read 100 for a fully open damper
    # where the sequence expects 1, and ThermalZones.Alarms' ppmCO2, unit "1" in MBL, looked like a fraction. Nothing
    # told the two apart, so a miss was silent.
    import hxemit
    text = g36_text()
    scaled = [l for l in text.splitlines() if "cdlPointScale" in l]
    assert len(scaled) == 110
    for l in scaled:
        assert 'cdlUnit:"1"' in l and 'cdlPointUnit:"%"' in l and 'cdlPointScale:"0.01"' in l, l
        specs = re.findall(r"(?:cdlPointSpec|pointSpec):([\w.]+::\w+)", l)
        assert specs and all(hxemit.ph_point_unit(s) == "%" for s in specs), l
    # every unit "1" connector with a point spec carries the scale, a ppm count, or a spec with no unit (Bool)
    for l in text.splitlines():
        if 'cdlUnit:"1"' in l and "cdlPointSpec" in l and "cdlPointScale" not in l:
            specs = re.findall(r"(?:cdlPointSpec|pointSpec):([\w.]+::\w+)", l)
            assert 'cdlPointUnit:"ppm"' in l or all(hxemit.ph_point_unit(s) is None for s in specs), l
    ppm = [l for l in text.splitlines() if 'cdlPointUnit:"ppm"' in l]
    names = sorted(re.match(r"\s*(\w+):", l).group(1) for l in ppm)
    assert names == ["cO2Set"] + ["ppmCO2"] * 14 + ["ppmCO2Set"] * 13 + ["ppmHys"], names
    # every CO2 point connector reads a ppm point; the two parameters carry no point spec
    for l in ppm:
        specs = re.findall(r"cdlPointSpec:([\w.]+::\w+)", l)
        assert (not specs) == ("cdlParam" in l) and all(hxemit.ph_point_unit(s) == "ppm" for s in specs), l
    # a CO2 slot MBL leaves with no unit takes "1" as an inferred unit
    assert sum('cdlUnitInferred:"1"' in l for l in ppm) == 27


def test_a_point_unit_decision_on_a_slot_that_is_not_dimensionless_refuses():
    # Wrong behavior caught: a pointUnits decision that outlived an MBL fix (the slot now declares a unit) applied anyway.
    saved = generate.POINT_UNITS
    generate.POINT_UNITS = {"X.y": {"unit": "ppm"}}
    try:
        assert generate.point_unit("X", "z", "K") is None
        assert generate.point_unit("X", "y", "1") == "ppm"
        with pytest.raises(generate.CxfError):
            generate.point_unit("X", "y", "K")
    finally:
        generate.POINT_UNITS = saved


def test_every_pid_left_without_r_is_named_with_why():
    # Wrong behavior caught: a PID whose setpoint group lost its unit skipped writing r silently,
    # and only the pin of 23 written loops would notice. The units report now names each skipped loop and why.
    text = (HERE / "units-report.txt").read_text(encoding="utf-8")
    m = re.search(r"(?m)^PID error scales r left unwritten \(requires.writeWhenUnit\): (\d+)\n((?:  .*\n)*)", text)
    assert m and int(m.group(1)) == 23 == len(m.group(2).splitlines()), m and m.group(0)
    # all 23 are normalized loops; one whose group unit is unknown would name "no declared unit reaches it"
    assert all(l.endswith(": its group is dimensionless") for l in m.group(2).splitlines()), m.group(2)


def test_a_dimensionless_factor_beside_a_value_of_known_unit_is_recorded_as_dimensionless():
    # Wrong behavior caught: BooleanToReal factors and TrimAndRespond's sign gain k=-1 written with
    # no recorded unit, so a resolver could not tell a factor from a value it must convert, and refused a °F building.
    text = g36_text()
    gai_k = re.search(r'(?m)^  gai_k: hx.comps::NumberConst\? <cdlFeed:"gai.k"[^\n]*cdlLiteralUnits:\{out:"1"\}[^\n]*> \{\n'
                      r'    out: hx.comps::StatusNumber \{ val: -1 \}', spec_block(text, "GenericTrimAndRespond"))
    assert gai_k, "TrimAndRespond's gain -1 is not recorded dimensionless"
    tz = spec_block(text, "ThermalZonesSetpoints")
    for i in [""] + [str(n) for n in range(1, 8)]:
        for side in ("realTrue", "realFalse"):
            assert re.search(r'(?m)^  booToRea%s_%s: hx.comps::NumberConst\? <[^\n]*cdlLiteralUnits:\{out:"1"\}' % (i, side),
                             tz), (i, side)
    report = (HERE / "units-report.txt").read_text(encoding="utf-8")
    assert re.search(r"(?m)^literals 825: with a unit 260, dimensionless 440, no unit 125$", report)
    assert "ThermalZones.Setpoints booToRea" not in report and "TrimAndRespond gai.k" not in report


@pytest.mark.inputs
def test_a_literal_unit_decision_naming_no_literal_refuses(tmp_path, monkeypatch):
    # Wrong behavior caught: a literalUnits decision that outlived the literal it named (MBL renamed an instance)
    # applied to nothing and passed silently.
    real = generate.load_classes
    def load(root):
        classes = real(root)
        generate.LITERAL_UNITS["Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond.gaiX.k"] = {"unit": "1"}
        return classes
    monkeypatch.setattr(generate, "load_classes", load)
    with pytest.raises(generate.CxfError, match="literalUnits names no literal"):
        generate.main(["--out", str(tmp_path / "out"), "--no-fetch"])


def test_a_reviewed_unit_override_corrects_mbl_and_refuses_once_mbl_is_fixed():
    # Wrong behavior caught: SeriesFanCVF and SeriesFanVVF DamperValves.damPosHys, a damper-position hysteresis MBL
    # 14.0.0 declares m3/s, written as a flow, so a resolver converts the 0.05 threshold into cfm and compares it with a
    # 0 to 1 position. And an override that outlives the MBL fix it stood in for, applied a second time.
    text = g36_text()
    for spec in ("TerminalUnitsSeriesFanCVFSubsequencesDamperValves", "TerminalUnitsSeriesFanVVFSubsequencesDamperValves"):
        line = re.search(r"(?m)^  damPosHys: [^\n]*", spec_block(text, spec)).group(0)
        assert 'cdlUnit:"1"' in line and "unitless" in line and 'cdlUnitOverride:"m³/s"' in line, line
        assert "volumetricFlow" not in line, line
    assert sum('cdlUnitOverride:' in l for l in text.splitlines()) == 2
    saved = dict(generate.UNIT_OVERRIDES)
    try:
        generate.UNIT_OVERRIDES.clear()
        generate.UNIT_OVERRIDES["X.y"] = {"from": "m³/s", "unit": "1"}
        assert generate.unit_override("X", "y", "m³/s") == ("1", "m³/s")
        assert generate.unit_override("X", "z", "m³/s") == ("m³/s", None)
        with pytest.raises(generate.CxfError, match="MBL now declares 1; remove the override"):
            generate.unit_override("X", "y", "1")
    finally:
        generate.UNIT_OVERRIDES.clear()
        generate.UNIT_OVERRIDES.update(saved)
