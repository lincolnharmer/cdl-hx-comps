"""Tests for the class-to-comp table (classmap.py, classmap_table.py). Run: python -X utf8 -m pytest src/gen -q"""
import copy
import json
import os
import pathlib
import re
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cxf_source  # noqa: E402

SRC = cxf_source.source_root()

import classmap  # noqa: E402
import classmap_table  # noqa: E402
import generate  # noqa: E402
import hx_comps_index  # noqa: E402


@pytest.fixture(scope="module")
def classes():
    return generate.load_classes(SRC)


@pytest.fixture(scope="module")
def built(classes):
    doc, errors = classmap.build(classes)
    assert errors == []
    return doc


def test_the_committed_class_map_is_what_the_table_builds(built):
    # Wrong behavior caught: an edit to classmap_table.py, the hx.comps index or the pinned CXF that is not carried
    # into class-map.json, so the committed map and the table the generator reads disagree.
    assert classmap.CLASS_MAP.read_text(encoding="utf-8") == classmap.render(built)


def test_the_table_grades_every_elementary_class_once(built):
    # Wrong behavior caught: a class dropped from the table, or one graded outside the known grades.
    assert len(built["classes"]) == 132 == len(generate.CLAUSE7)
    assert sum(built["counts"].values()) == 132


@pytest.mark.skipif(not os.environ.get("HX_COMPS_SRC"), reason="HX_COMPS_SRC names no hx.comps source directory")
def test_the_committed_hx_comps_index_is_what_the_source_gives():
    # Wrong behavior caught: an index edited by hand, or left behind when the pinned hx.comps source moves.
    got = hx_comps_index.render(hx_comps_index.index(os.environ["HX_COMPS_SRC"]))
    assert classmap.HX_INDEX.read_text(encoding="utf-8") == got


def _planted(classes, edit):
    """The build errors for a copy of the table with one planted error."""
    table = copy.deepcopy(classmap_table.T)
    edit(table)
    doc, errors = classmap.build(classes, table=table)
    assert doc is None
    return errors


def _set(row, path, value):
    def edit(table):
        d = table[row]
        for k in path[:-1]:
            d = d[k]
        if value is _DELETE:
            del d[path[-1]]
        else:
            d[path[-1]] = value
    return edit


_DELETE = object()


@pytest.mark.parametrize("edit, want", [
    # TrueDelay's offDelay defaults to 1sec, which would delay every fall by a second.
    (_set("LogicalTrueDelay", ["fixed", "offDelay"], _DELETE), "LogicalTrueDelay: config slots ['offDelay'] are left unset"),
    # A config slot hidden under unused instead of named in keep with its reason.
    (lambda t: (t["RealsPid"]["keep"].clear(), t["RealsPid"]["unused"].append("yReset")),
     "RealsPid: unused yReset is a config slot"),
    (lambda t: t["RealsPid"]["keep"].clear(), "RealsPid: config slots ['yReset'] are left unset"),
])
def test_a_config_slot_left_unset_is_refused(classes, edit, want):
    # Wrong behavior caught: a comp configuration slot that no CDL parameter or fixed value sets runs at the comp's
    # own default, which is not the CDL behaviour (BoolDelay offDelay is 1sec, CDL TrueDelay has no fall delay).
    assert any(e.startswith(want) for e in _planted(classes, edit))


def test_a_map_that_is_not_one_to_one_is_refused(classes):
    # Wrong behavior caught: two CDL connectors on one comp slot (PID u_s and u_m both on inSetpoint) merge the
    # setpoint and the measurement into one signal, and the old check accepted it.
    errors = _planted(classes, _set("RealsPid", ["connectors", "u_m"], "inSetpoint"))
    assert any("comp slot inSetpoint carries u_s, u_m; the map must be one to one" in e for e in errors)


@pytest.mark.parametrize("edit, want", [
    # PID k is a Float on the comp; without the conversion a Real lands on a Float slot unconverted.
    (_set("RealsPid", ["params", "k"], {"slot": "k", "feed": "set"}), "RealsPid: param k -> k: CDL Real does not fit slot type Float"),
    # A Real input mapped to the Boolean control input of the switch.
    (_set("RealsSwitch", ["connectors", "u1"], "inSwitch"), "RealsSwitch: connector u1 -> inSwitch: CDL Real does not fit slot type StatusBool"),
    # Seconds written onto a Duration slot as a plain Number.
    (_set("LogicalTrueDelay", ["params", "delayTime"], {"slot": "onDelay", "feed": "set"}),
     "LogicalTrueDelay: param delayTime -> onDelay: CDL Real does not fit slot type Duration"),
])
def test_a_slot_type_that_does_not_fit_the_cdl_type_is_refused(classes, edit, want):
    # Wrong behavior caught: a CDL value mapped onto a comp slot of another type, which the comp reads as null or
    # throws on at execute.
    assert any(e.startswith(want) for e in _planted(classes, edit))


def test_an_unknown_conversion_is_refused(classes):
    # Wrong behavior caught: a renamed conversion label dropped silently from the generated library (18 of 19 `sec`
    # conversions vanished when the label was edited).
    edit = _set("LogicalTrueDelay", ["params", "delayTime", "convert"], "Real minutes to Duration")
    assert any("LogicalTrueDelay: param delayTime: unknown conversion 'Real minutes to Duration'" in e
               for e in _planted(classes, edit))


@pytest.mark.parametrize("edit, want", [
    (_set("ConversionsRealToInteger", ["fixed", "n"], "0"), "ConversionsRealToInteger: fixed n: '0' is not a Int"),
    (_set("LogicalTrueDelay", ["fixed", "offDelay"], "0"), "LogicalTrueDelay: fixed offDelay: '0' is not a Duration"),
    (_set("LogicalFallingEdge", ["fixed", "edge"], "fall"), "LogicalFallingEdge: fixed edge: 'fall' is not an item of BoolEdgeType"),
])
def test_a_fixed_value_of_the_wrong_type_is_refused(classes, edit, want):
    # Wrong behavior caught: a fixed value the comp slot cannot hold (a Str on an Int, a Duration with no unit, an
    # enum key the comp does not define), written into the library and rejected or misread at load.
    assert any(e.startswith(want) for e in _planted(classes, edit))


def _compose(row, f):
    def edit(table):
        f(table[row]["compose"])
    return edit


@pytest.mark.parametrize("edit, want", [
    (_compose("RealsSourcesPulse", lambda c: c["insts"][1][2].update(realTrue="ofset+amplitude")),
     "RealsSourcesPulse: instance booTo binds realTrue to 'ofset+amplitude', which names ofset"),
    (_compose("LogicalNor", lambda c: c["edges"].remove(("not1.y", "y"))), "LogicalNor: y is driven 0 times"),
    (_compose("LogicalNand", lambda c: c["edges"].__setitem__(2, ("not1.u", "and1.y"))),
     "LogicalNand: connection not1.u -> and1.y runs from not1.u, a sink"),
])
def test_a_composite_row_that_misbinds_or_miswires_is_refused(classes, edit, want):
    # Wrong behavior caught: a misspelt binding, an undriven output or a reversed connection in a
    # composite row was emitted silently, and the round trip compares a composed class by its interface only.
    assert any(e.startswith(want) for e in _planted(classes, edit))


def test_the_timer_start_up_departure_is_recorded(built):
    # Wrong behavior caught: LogicalTimer's row was silent that MBL starts `passed` true at t <= 0 while u is false
    # (Logical/Timer.mo:28) and the comp starts it false (Timer.fan:106), so a reader took the two to agree.
    deps = built["classes"]["LogicalTimer"]["departures"]
    assert any("start-up" in d and "`passed`" in d and "t` <= 0" in d for d in deps)


def test_the_generator_requirements_are_fields(built):
    # Wrong behavior caught: three requirements lived only in prose (always link `reset` on Counter and AccumTimer,
    # `loopCut` into UnitDelay, `whenNull` on the Derivative feeds), so a generator reading the map met none of them.
    rows = built["classes"]
    assert rows["IntegersOnCounter"]["requires"] == {"linkAlways": {"reset": False}}
    assert rows["LogicalTimerAccumulating"]["requires"] == {"linkAlways": {"reset": False}}
    assert rows["DiscreteUnitDelay"]["requires"] == {"loopCut": ["u"]}
    assert rows["RealsDerivative"]["requires"] == {"whenNull": {"k": 1, "T": 1}}


@pytest.mark.parametrize("edit, want", [
    (_set("IntegersOnCounter", ["requires", "linkAlways"], {"trigger": 1}), "IntegersOnCounter: requires.linkAlways.trigger: 1 is not a value"),
    (_set("DiscreteUnitDelay", ["requires", "loopCut"], ["y"]), "DiscreteUnitDelay: requires.loopCut names y, which is no CDL input"),
    (_set("RealsDerivative", ["requires", "whenNull"], {"u": 1}), "RealsDerivative: requires.whenNull.u names no CDL input reached through a feed"),
    (_set("RealsDerivative", ["requires", "cut"], ["u"]), "RealsDerivative: requires.cut is not a requirement"),
])
def test_a_requirement_the_generator_cannot_act_on_is_refused(classes, edit, want):
    # Wrong behavior caught: a requirement naming an output, an input with no feed, or an unknown key would be skipped
    # by the generator, and the requirement would be lost as silently as the prose was.
    assert any(e.startswith(want) for e in _planted(classes, edit))


def test_every_fed_parameter_carries_its_cdl_default(built):
    # Wrong behavior caught: an earlier draft carried only three hand-listed defaults, so a threshold `t`, a
    # BooleanToReal `realFalse` or a BooleanToInteger `integerTrue` left unbound in G36 (19, 131 and 75 instances)
    # reached a NumberConst whose `out` has no default, and the feed was null.
    missing = [(n, k) for n, e in built["classes"].items() for k, p in e["params"].items()
               if p["feed"] != "set" and p["cdlDefault"] is not None and k not in e["cdlDefaults"]]
    assert missing == []
    rows = built["classes"]
    assert rows["RealsGreaterThreshold"]["cdlDefaults"]["t"] == "0"
    assert rows["ConversionsBooleanToReal"]["cdlDefaults"] == {"realFalse": "0", "realTrue": "1"}
    assert rows["ConversionsBooleanToInteger"]["cdlDefaults"] == {"integerFalse": "0", "integerTrue": "1"}
    # the three expression defaults stay
    assert rows["LogicalTrueFalseHold"]["cdlDefaults"] == {"falseHoldDuration": "trueHoldDuration"}
    assert rows["RealsPidWithReset"]["cdlDefaults"] == {"y_reset": "xi_start"}
    assert rows["RealsRamp"]["cdlDefaults"] == {"Td": "raisingSlewRate*0.001"}


def _semantics(tmp_path, doc):
    """Run comp_semantics.fan on a class map document; (exit code, output). Needs CDL_FAN_WORK, a work dir whose
    fan.props reaches an hx.comps with the comps the table names, and FAN_HOME. CDL_BASH names the shell that runs the
    command (Git Bash on Windows)."""
    import subprocess
    f = tmp_path / "class-map.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    fan = os.environ["FAN_HOME"].replace("\\", "/").rstrip("/") + "/bin/fan"
    cmd = [fan, str(HERE / "comp_semantics.fan"), str(f)]
    # fan is a shell script; a login shell puts cygpath on the PATH the fan launcher needs
    cmd = [os.environ.get("CDL_BASH", "bash"), "-lc", 'cd "$0" && exec "$@"', os.environ["CDL_FAN_WORK"]] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


@pytest.mark.skipif(not (os.environ.get("CDL_FAN_WORK") and os.environ.get("FAN_HOME")),
                    reason="CDL_FAN_WORK and FAN_HOME name no Haxall with the hx.comps comps the table names")
def test_one_comp_per_family_computes_its_cdl_equation_through_the_table(tmp_path):
    # Wrong behavior caught: a table that maps a connector onto the wrong comp slot (Subtract's u1 on
    # inB) passes every other check, since the round trip un-maps with the same table. This runs the comps.
    doc = json.loads(classmap.CLASS_MAP.read_text(encoding="utf-8"))
    code, out = _semantics(tmp_path, doc)
    assert code == 0 and "SEMANTICS PASS" in out, out[-3000:]
    swapped = copy.deepcopy(doc)
    swapped["classes"]["RealsSubtract"]["connectors"].update(u1="inB", u2="inA")
    code, out = _semantics(tmp_path, swapped)
    assert code != 0 and "FAIL RealsSubtract" in out, out[-3000:]
    # A parameter written onto a slot the comp does not read for it would pass with r 1 and h 0. Each
    # mutant moves one parameter onto another slot the comp has, so the run raises nothing and only a value differs.
    for cls, param, slot in [("RealsGreater", "h", "inB"), ("RealsPid", "r", "ydStart"),
                             ("LogicalTrueDelay", "delayTime", "offDelay"),
                             ("LogicalTrueFalseHold", "trueHoldDuration", "falseHold")]:
        mutant = copy.deepcopy(doc)
        mutant["classes"][cls]["params"][param]["slot"] = slot
        code, out = _semantics(tmp_path, mutant)
        assert code != 0 and re.search(r"(?m)^FAIL %s \[" % cls, out), (cls, out[-3000:])
