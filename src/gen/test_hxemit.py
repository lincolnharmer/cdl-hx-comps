#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Tests for the hx.comps form of the CDL libs (hxemit.py): the G36 composites wired from hx.comps comps, the CdlClass
instances, and the point meta. Run from the repo root: python -X utf8 -m pytest src/gen -q"""
import json
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

import connector_points  # noqa: E402
import cxf  # noqa: E402
import generate  # noqa: E402
import hxemit  # noqa: E402

CDL = generate.CDL_PREFIX
G36 = generate.G36_PREFIX


def g36_text():
    return "\n".join((LIBS / lib / "g36.xeto").read_text(encoding="utf-8") for lib in generate.G36_LIBS)


def classes_text():
    return (LIBS / "kw.cdl/classes.xeto").read_text(encoding="utf-8")


def spec_block(text, name):
    m = re.search(r"(?ms)^%s: \S+ <.*?^\}$" % re.escape(name), text)
    assert m is not None, name
    return m.group(0)


def instance(text, name):
    """The body of lib instance @<name> in a classes.xeto text."""
    m = re.search(r"(?ms)^@%s: \w+ \{\n.*?^\}$" % re.escape(name), text)
    assert m is not None, name
    return m.group(0)


def composites(text):
    """Each composite spec block of a G36 text."""
    return [m.group(0) for m in re.finditer(r"(?ms)^\w+: kw\.cdl::CdlBlock <.*?^\}$", text)]


@pytest.fixture(scope="module")
def mapped():
    return generate.mapped_classes(SRC)


# ---- the class map, applied ----

def test_every_constant_feed_carries_a_value_or_its_child_carries_the_expression():
    # Wrong behavior caught: a NumberConst feed with no value and no expression to resolve, which runs null. An
    # earlier draft would have left 19 unbound GreaterThreshold t, 131 BooleanToReal realFalse and 75 BooleanToInteger
    # integerTrue that way.
    empty, n = [], 0
    for block in composites(g36_text()):
        for name, inst, param, rest in re.findall(r'(?m)^  (\w+): hx\.comps::NumberConst\? <cdlFeed:"(\w+)\.(\w+)"(.*)$',
                                                  block):
            n += 1
            if rest.endswith("{"):
                continue                               # a body with its out value
            # the expression rides the child's cdlBind, keyed by the CDL parameter with its first letter lowered
            child = re.search(r'(?m)^  %s: \S+ <.*cdlBind:\{([^}]*)\}' % re.escape(generate.lower(inst)), block)
            if child is None or not re.search(r"(?<!\w)%s:" % re.escape(generate.lower(param)), child.group(1)):
                empty.append(name)
    assert n > 900 and empty == []


def test_every_defaulted_value_is_the_cdl_default(mapped):
    # Wrong behavior caught: a value the generator wrote for an unbound parameter that is not CDL's default (a wrong
    # row, a dropped substitution), which the round trip cannot see because it drops every defaulted value.
    allc, rows = mapped
    checked = 0
    for text in composites(g36_text()):
        checked += _defaulted(text, allc, rows)
    assert checked > 200, checked


def _defaulted(text, allc, rows):
    checked = 0
    for m in re.finditer(r'(?m)^  (\w+): (\S+)\? <cdlInstance, cdlName:"(\w+)", cdlOf:@kw\.cdl::cdl-(\w+).*?'
                         r'cdlDefaulted:"([^"]+)"(.*)$', text):
        row = next(r for r in rows.values() if r["name"] == m.group(4))
        sub = allc[row["cdlClass"]]
        body = text[m.end():text.index("\n  }", m.end())] if m.group(6).endswith("{") else ""
        for low in m.group(5).split(","):
            param = next(p for p in sub.params if generate.lower(p.name) == low)
            pm = row["params"][param.name]
            # a parameter written whenever its unit group carries one (a PID's r) takes the CDL default itself
            want = row["cdlDefaults"].get(param.name, generate.fmt_num(param.val) if param.val is not None else None)
            binds = dict(re.findall(r'(\w+):"([^"]*)"', (re.search(r"cdlBind:\{([^}]*)\}", m.group(0)) or [None, ""])[1]))
            if low in binds:
                # an expression default, substituted: a bare parameter name becomes that parameter's binding
                if re.fullmatch(r"[A-Za-z_]\w*", want):
                    assert binds[low] == "(%s)" % binds[generate.lower(want)], (m.group(1), param.name, binds)
                checked += 1
                continue
            if pm["feed"] == "set":
                got = re.search(r"(?m)^    %s: (.*)$" % pm["slot"], body)
                assert got is not None, (m.group(1), param.name)
                val = got.group(1).strip().strip('"')
                val = val[:-3] if val.endswith("sec") else hxemit.NUMBER_UNIT.match(val).group(1)
            else:
                feed = re.search(r'(?ms)^  %s_%s: \S+ <cdlFeed:[^\n]*\{\n    out: \S+ \{ val: (\S+) \}' %
                                 (re.escape(m.group(1)), re.escape(param.name)), text)
                assert feed is not None, (m.group(1), param.name)
                val = hxemit.NUMBER_UNIT.match(feed.group(1)).group(1)
            try:
                expect = float(cxf.evaluate(want, {}, lambda lit: None))
            except cxf.CxfError:
                # a default naming one parameter (falseHoldDuration = trueHoldDuration): the value written for it
                assert re.fullmatch(r"[A-Za-z_]\w*", want), (m.group(1), param.name, want)
                other = re.search(r"(?m)^    %s: (.*)$" % row["params"][want]["slot"], body)
                if other is None:                      # the named parameter is unbound too: its own CDL default
                    expect = float(row["params"][want]["cdlDefault"])
                else:
                    o = other.group(1).strip()
                    expect = float(o[:-3] if o.endswith("sec") else hxemit.NUMBER_UNIT.match(o).group(1))
            assert float(val) == expect, (m.group(1), param.name)
            checked += 1
    return checked


def _synthetic(mapped, insts, edges, conns):
    allc, rows = mapped
    ci = generate.ClassInfo(G36 + "Test.Requirements", "composite", "A test composite")
    ci.conns = [generate.Conn(n, d, t, None, None, None, "") for n, d, t in conns]
    ci.insts = [generate.Inst(n, CDL + c, b, None, None) for n, c, b in insts]
    ci.edges = list(edges)
    every = dict(allc, **{ci.path: ci})
    generate.orient(ci, every)
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    return "\n".join(hxemit.Mapper(ci, every, rows).emit(stamp, "TestRequirements", "kw.cdl::CdlBlock", False))


def test_the_requirements_of_the_class_map_are_applied(mapped):
    # Wrong behavior caught: requires.linkAlways, requires.loopCut or requires.whenNull read by nobody, so an
    # unconnected Counter reset leaves `out` null, a UnitDelay loop depends on creation order, and a null Derivative
    # gain reads the whenNull slot's missing default.
    text = _synthetic(mapped,
                      [("cou", "Integers.OnCounter", {}), ("del", "Discrete.UnitDelay", {"samplePeriod": (1.0, None)}),
                       ("der", "Reals.Derivative", {})],
                      [("b", "cou.trigger"), ("u", "del.u"), ("u", "der.u"), ("u", "der.k"), ("u", "der.T"),
                       ("cou.y", "y")],
                      [("u", "in", "Real"), ("b", "in", "Boolean"), ("y", "out", "Integer")])
    cou = spec_block(text.replace("TestRequirements:", "X:"), "X")
    assert '  cou_reset: hx.comps::BoolConst? <cdlFeed:"cou.reset"> {\n    out: hx.comps::StatusBool { val: "false" }' in cou
    assert '    reset: <link:"cou_reset.out">' in cou
    assert '    in: <link:"u", loopCut>' in cou                       # the UnitDelay's input
    assert '  der_k: hx.comps::StatusNumberToNumber? <cdlFeed:"der.k"> {\n    in: <link:"u">\n    whenNull: 1' in cou
    assert '  der_T: hx.comps::StatusNumberToNumber? <cdlFeed:"der.T"> {\n    in: <link:"u">\n    whenNull: 1' in cou
    assert '    timeConst: <link:"der_T.out">' in cou


def test_a_linked_reset_takes_no_constant(mapped):
    # Wrong behavior caught: linkAlways adding a constant on top of a real link, so `reset` has two drivers.
    text = _synthetic(mapped, [("cou", "Integers.OnCounter", {})],
                      [("b", "cou.trigger"), ("b", "cou.reset"), ("cou.y", "y")],
                      [("b", "in", "Boolean"), ("y", "out", "Integer")])
    assert "cou_reset" not in text and '    reset: <link:"b">' in text


def test_seconds_and_fixed_slots_are_written_with_their_unit_and_value():
    # Wrong behavior caught: a dropped `sec` or a dropped fixed slot passed the round trip, which read
    # both back unchanged, so `onDelay: 180` or a TrueDelay with no `offDelay` (a 1sec delay on every fall) shipped.
    text = g36_text()
    assert re.search(r'(?m)^    onDelay: 180sec$', text)
    delays = re.findall(r'(?ms)^  \w+: hx\.comps::BoolDelay\? <.*?^  \}$', text)
    assert delays and all("    offDelay: 0sec" in d for d in delays)
    with pytest.raises(cxf.CxfError, match="without its unit"):
        hxemit._unconvert("180", "sec", "Real")


def test_the_round_trip_refuses_a_dropped_fixed_slot(mapped):
    allc, rows = mapped
    cls = G36 + "Generic.TrimAndRespond"
    text = (LIBS / "kw.cdl.g36.common/g36.xeto").read_text(encoding="utf-8")
    hxemit.parse_mapped(text, cls, rows, allc)
    block = spec_block(text, "GenericTrimAndRespond")
    assert "    offDelay: 0sec\n" in block
    with pytest.raises(cxf.CxfError, match="fixed slot offDelay"):
        hxemit.parse_mapped(text.replace(block, block.replace("    offDelay: 0sec\n", "", 1)), cls, rows, allc)


def test_pre_becomes_a_loop_cut_link_through_a_wire_record():
    # Wrong behavior caught: Logical.Pre emitted as a comp, dropped with its link, or linked without loopCut, so
    # ReliefFanGroup's feedback loop reads this cycle's value or sorts by creation order.
    block = spec_block((LIBS / "kw.cdl.g36.ahu/g36.xeto").read_text(encoding="utf-8"),
                       "AhusMultiZoneVavSetPointsReliefFanGroup")
    assert 'pre: kw.cdl::CdlWire? <cdlInstance, cdlName:"pre", cdlOf:@kw.cdl::cdl-LogicalPre, cdlBind:{pre_u_start:"true"}, cdlFinalBind:"pre_u_start">' in block
    assert '    inB: <link:"not1.out", loopCut, cdlLinkVia:"pre">' in block


def test_integer_to_real_is_a_plain_link_through_a_wire_record():
    block = spec_block(g36_text(), "GenericTrimAndRespond")
    assert 'intToRea: kw.cdl::CdlWire? <cdlInstance, cdlName:"intToRea", cdlOf:@kw.cdl::cdl-ConversionsIntegerToReal>' in block
    assert '    in: <link:"numOfReq", cdlLinkVia:"intToRea">' in block


# The G36 composites that expand when instantiated: each holds an array connector, a vectorized instance or an
# instance of an array class, at MBL 14.0.0.
ARRAY_COMPOSITES = ("AHUs.MultiZone.VAV.SetPoints.OutdoorAirFlow.ASHRAE62_1.SumZone",
                    "AHUs.MultiZone.VAV.SetPoints.OutdoorAirFlow.Title24.SumZone",
                    "AHUs.MultiZone.VAV.SetPoints.ReliefFanGroup", "AHUs.SingleZone.VAV.SetPoints.ReliefFanGroup",
                    "ZoneGroups.GroupStatus", "ZoneGroups.ZoneGroupSystem", "ZoneGroups.ZoneStatusDuplicator")


def test_the_expanding_composites_are_the_seven_array_composites():
    # Wrong behavior caught: an array composite left unmarked (it would instantiate with abstract children), or a
    # scalar one marked (a resolver would refuse to run it).
    got = sorted(c[len(G36):] for c in re.findall(r'(?m)^\w+: kw\.cdl::CdlBlock <cdlClass:"([^"]+)", cdlExpand>', g36_text()))
    assert got == sorted(ARRAY_COMPOSITES)
    arrays = re.findall(r'(?m)^\w+: CdlBlock <cdlClass:"[^"]+", abstract, cdlExpand,', (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8"))
    assert len(arrays) == 28


def test_every_vectorized_instance_carries_its_size():
    # Wrong behavior caught: the size of a vectorized instance dropped (GroupStatus booToInt[nGroZon] written with no
    # size), so an expander cannot tell an array of instances from one instance.
    text = g36_text()
    sized = re.findall(r'(?m)^  \w+: \S+ <cdlInstance, [^\n]*cdlArraySize:"([^"]+)"', text)
    assert len(sized) == 113
    block = spec_block(text, "ZoneGroupsGroupStatus")
    assert re.search(r'(?m)^  booToInt: hx\.comps::NumberSwitch\? <cdlInstance, cdlName:"booToInt", [^\n]*cdlArraySize:"\(nGroZon\)"', block)


# ---- point meta ----

def test_the_point_meta_is_the_reviewed_table():
    # Wrong behavior caught: point meta dropped, added where the table has none, or moved to another connector.
    text = g36_text()
    rows = connector_points.load()["connectors"]
    assert text.count("cdlPointSpec:") == sum("cdlPointSpec" in r["meta"] for r in rows) == 511
    assert text.count("cdlPointSpecCases:") == sum("cdlPointSpecCases" in r["meta"] for r in rows) == 25
    for r in rows:
        line = re.search(r'(?m)^  %s: [^\n]*' % re.escape(r["slot"]),
                         spec_block(text, r["composite"])).group(0)
        if "cdlPointSpec" in r["meta"]:
            assert "cdlPointSpec:%s" % r["meta"]["cdlPointSpec"] in line, (r["composite"], r["slot"])
        elif "cdlPointSpecCases" not in r["meta"]:
            assert "cdlPointSpec" not in line, (r["composite"], r["slot"])


def test_every_point_connector_carries_its_scope():
    # Wrong behavior caught: scope written only where two connectors collide, so 9 upstreamAir
    # connectors (u1Fan on the terminal controllers, tSup on CoolingOnly Dampers) lost it, and a fan-powered box's
    # own fan could bind as the AHU supply fan.
    text = g36_text()
    rows = [r for r in connector_points.load()["connectors"] if r["meta"]]
    scopes = re.findall(r'cdlPointScope:"([^"]+)"', text)
    assert len(scopes) == len(rows) == 536 and set(scopes) <= set(connector_points.SCOPES)
    block = spec_block(text, "TerminalUnitsCoolingOnlyController")
    assert re.search(r'(?m)^  tDis: [^\n]*cdlPointSpec:ph\.points\.x::DischargeAirTempSensor, cdlPointScope:"self"', block)
    assert re.search(r'(?m)^  tSup: [^\n]*cdlPointSpec:ph\.points\.x::DischargeAirTempSensor, cdlPointScope:"upstreamAir"', block)
    assert re.search(r'(?m)^  tZon: [^\n]*cdlPointScope:"zone"', block)
    for spec in ("TerminalUnitsSeriesFanVVFController", "TerminalUnitsCoolingOnlySubsequencesDampers"):
        b = spec_block(text, spec)
        for slot in ("u1Fan", "tSup"):
            m = re.search(r"(?m)^  %s: [^\n]*" % slot, b)
            if m and "cdlPointSpec" in m.group(0):
                assert 'cdlPointScope:"upstreamAir"' in m.group(0), (spec, m.group(0))


def test_overrides_and_alarms_stay_unbound_and_fan_powered_primary_flow_is_inlet():
    text = g36_text()
    for spec in ("TerminalUnitsReheatController", "TerminalUnitsSeriesFanVVFController"):
        block = spec_block(text, spec)
        for line in re.findall(r"(?m)^  (?:ove\w+|y\w*Ala\w*): [^\n]*", block):
            assert "cdlPointSpec" not in line, line
    block = spec_block(text, "TerminalUnitsParallelFanCVFController")
    assert re.search(r'(?m)^  vPri_flow: [^\n]*cdlPointSpec:ph\.points\.x::InletAirFlowSensor', block)


# ---- kw.cdl ----

def test_the_refused_classes_are_the_five_with_no_comp_and_no_g36_use(mapped):
    # Wrong behavior caught: a class refused that G36 uses (its sequences would not generate), or a refusal item that
    # carries the reserved entity tag `spec`.
    text = classes_text()
    items = re.findall(r"(?m)^    CdlRefusal \{(.*)\}$", text)
    names = sorted(re.search(r'name:"(\w+)"', i).group(1) for i in items)
    assert names == ["RealsSourcesCalendarTime", "RealsSourcesCivilTime", "RealsSourcesRamp", "RealsSourcesSin",
                     "UtilitiesSunRiseSet"]
    assert not any(re.search(r"(?<![\w])spec:", i) for i in items)
    used = {generate.spec_name(i.cls, CDL) for p, c in mapped[0].items() if p.startswith(G36) for i in c.insts
            if i.cls.startswith(CDL)}
    assert not set(names) & used


def test_the_four_composed_classes_wire_comps_as_their_compositions_say():
    blocks = (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8")
    nand = spec_block(blocks, "LogicalNand")
    assert 'and1: hx.comps::And? <cdlInstance, cdlName:"and1", cdlOf:@kw.cdl::cdl-LogicalAnd> {\n    inA: <link:"u1">\n    inB: <link:"u2">' in nand
    assert 'not1: hx.comps::Not? <cdlInstance, cdlName:"not1", cdlOf:@kw.cdl::cdl-LogicalNot> {\n    in: <link:"and1.out">' in nand
    assert 'y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"not1.out">' in nand
    pulse = spec_block(blocks, "RealsSourcesPulse")
    assert 'booTo: hx.comps::NumberSwitch? <cdlInstance, cdlName:"booTo", cdlOf:@kw.cdl::cdl-ConversionsBooleanToReal, cdlBind:{realFalse:"offset", realTrue:"offset+amplitude"}>' in pulse
    assert 'pul: hx.comps::BoolPulse? <cdlInstance, cdlName:"pul", cdlOf:@kw.cdl::cdl-LogicalSourcesPulse, cdlBind:{period:"period", shift:"shift", width:"width"}>' in pulse
    assert '    inSwitch: <link:"pul.out">' in pulse
    g36 = g36_text()
    assert re.search(r'(?m)^  \w+: kw\.cdl::LogicalNor\? <cdlInstance, [^\n]*cdlOf:@kw\.cdl::cdl-LogicalNor', g36)


def test_the_timer_departure_and_the_requirements_reach_the_cdlclass_instances():
    text = classes_text()
    timer = instance(text, "cdl-LogicalTimer")
    assert "departures: {" in timer and "start-up" in timer
    assert 'linkAlways: {reset:"false"}' in instance(text, "cdl-IntegersOnCounter")
    assert 'loopCut: "u"' in instance(text, "cdl-DiscreteUnitDelay")
    assert "whenNull: {k:1, t:1}" in instance(text, "cdl-RealsDerivative")
    pre = instance(text, "cdl-LogicalPre")
    assert 'grade: "link"' in pre and 'loopCut: "u"' in pre and "first cycle" in pre


# Words a generated or published comment must not carry: process citations and the generator's own paths. MBL's
# descriptions and source files are public and may be cited.
INTERNAL = ("scripts/", "src/gen", "source/", "stamp.json", "ruling", "review", "slice ")


def test_no_published_comment_cites_an_internal_reference():
    files = generate.generated_files() + generate.lib_xeto_files() + [
        generate.LIBS + "/kw.cdl/" + f for f in ("meta.xeto", "block.xeto", "constants.xeto", "class.xeto")]
    bad = []
    for rel in files:
        for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if any(w.lower() in low for w in INTERNAL) and ("//" in line or "departures" in line or "reason:" in line):
                bad.append("%s:%d: %s" % (rel, n, line.strip()[:100]))
    assert bad == []


def test_a_binding_to_a_package_constant_is_a_literal_value():
    # Wrong behavior caught: Types.OperationModes.occupied kept as a cdlBind expression, so the constant comp has no
    # value until a resolver runs, though the value is fixed at design time (MBL 14: occupied is 1).
    block = spec_block(g36_text(), "TerminalUnitsCoolingOnlySubsequencesActiveAirFlow")
    assert re.search(r'(?m)^  occMod: hx\.comps::NumberConst\? <[^\n]*\{\n    out: hx\.comps::StatusNumber \{ val: 1 \}', block)
    # a binding that also names a parameter stays an expression: fill(...occupied, nGro) in the expanding SumZone
    left = re.findall(r'cdlBind:\{[^}]*Types\.OperationModes\.[^}]*\}', g36_text())
    assert left and all("nGro" in x for x in left), left


def test_point_spec_cases_key_their_spec_as_point_spec_not_the_reserved_spec_tag():
    # Wrong behavior caught: a case dict carrying `spec`, the reserved entity type tag, so a reader takes the dict
    # itself for an instance of the point spec.
    cases = re.findall(r"cdlPointSpecCases:List \{((?:\{[^{}]*\}(?:, )?)+)\}", g36_text())
    assert len(cases) == 25
    for c in cases:
        assert not re.search(r"(?<![\w])spec:", c), c
        assert re.search(r"pointSpec:ph\.points(\.x)?::\w+", c), c


def test_with_every_driver_guarded_the_primary_link_is_the_one_that_holds_at_the_defaults(mapped):
    # Wrong behavior caught: the primary link chosen alphabetically, which wired MZ FreezeProtection's
    # ySupFan to the `not have_frePro` branch while have_frePro defaults to true.
    block = spec_block(g36_text(), "AhusMultiZoneVavSetPointsFreezeProtection")
    line = re.search(r"(?m)^  ySupFan: [^\n]*", block).group(0)
    assert 'link:"supFan.out"' in line and 'cdlAltLink:"gai11.out,gai7.out"' in line, line


def test_with_no_guard_holding_at_the_defaults_no_driver_is_primary(mapped):
    # Wrong behavior caught: a primary link picked when the defaults do not decide, so an instance runs a branch the
    # parameters never chose.
    allc, rows = mapped
    ci = generate.ClassInfo(G36 + "Test.Guards", "composite", "")
    ci.params = [generate.Param("a", "Boolean", False, None, None, None, False, False, ""),
                 generate.Param("b", "Boolean", False, None, None, None, False, False, "")]
    ci.conns = [generate.Conn("y", "out", "Boolean", None, None, None, "")]
    ci.insts = [generate.Inst("x1", CDL + "Logical.Sources.Constant", {"k": (True, None)}, "a", None),
                generate.Inst("x2", CDL + "Logical.Sources.Constant", {"k": (False, None)}, "b", None)]
    ci.edges = [("x1.y", "y"), ("x2.y", "y")]
    every = dict(allc, **{ci.path: ci})
    generate.orient(ci, every)
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    text = "\n".join(hxemit.Mapper(ci, every, rows).emit(stamp, "TestGuards", "kw.cdl::CdlBlock", False))
    line = re.search(r"(?m)^  y: [^\n]*", text).group(0)
    assert "link:" not in line.replace("cdlAltLink:", "") and 'cdlAltLink:"x1.out,x2.out"' in line, line


DEPARTURES = {   # differences the class map's notes record, which the published departures must carry
    "RealsPid": "response depends on the cycle length",
    "LogicalTimer": "refreshes once a second",
    "RealsLine": "where MBL warns",
    "DiscreteFirstOrderHold": "off CDL by up to one cycle",
    "RealsMovingAverage": "first seconds differ slightly",
    "RealsAdd": "computes from the valid inputs",
}


@pytest.mark.parametrize("cls, phrase", sorted(DEPARTURES.items()))
def test_every_recorded_difference_reaches_the_published_departures(cls, phrase):
    # Wrong behavior caught: departures claimed complete while listing only Pre and Timer, so a reader of the
    # library missed the cycle-dependent PID, the stepping Timer, the faulting Line and the rest.
    block = instance(classes_text(), "cdl-" + cls)
    deps = re.search(r"(?m)^  departures: \{(.*)\}$", block)
    assert deps is not None and phrase in deps.group(1), cls


def test_no_published_departure_or_reason_cites_a_source_line():
    # Wrong behavior caught: published text citing source lines (`Timer.fan:106`) or pull request labels, which drift.
    text = classes_text()
    for line in text.splitlines():
        if line.startswith("  departures:") or "reason:" in line:
            assert not re.search(r"\.(?:xeto|fan|mo|md)\b|[A-Za-z]:\d", line), line[:160]


def test_every_array_size_has_one_format():
    # Wrong behavior caught: connectors wrote the CXF size with its parentheses and instances without,
    # so a reader of cdlArraySize had to know which slot it was on.
    sizes = re.findall(r'cdlArraySize:"([^"]*)"', g36_text() + (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8"))
    # CXF's own text throughout: a sized array in parentheses; an array CXF gives no size (MatrixGain's K) is "",
    # and MatrixMax's output keeps MBL's conditional size expression as written
    odd = [s for s in sizes if not (s.startswith("(") and s.endswith(")")) and s != "" and not s.startswith(" if ")]
    assert sizes and odd == [], odd[:5]


def test_a_gain_in_a_unit_the_database_lacks_runs_on_a_line_whose_output_carries_the_numerator():
    # Wrong behavior caught: TimeSuppression's chaRat (s/K) on Multiply gave the product the unit of its K input,
    # and the K value then met seconds in pasSup and faulted. On Line through (0, 0) and (1 K, chaRat s) the output
    # is in seconds. The 1 K point is a difference in the unit group of u, which the resolver converts (Line does
    # not convert a difference against an absolute value), and each point comes through a NumberConst feed, so a
    # save or a flatten keeps it.
    text = (LIBS / "kw.cdl.g36.common/g36.xeto").read_text(encoding="utf-8")
    block = re.search(r"(?ms)^GenericTimeSuppression: .*?^\}$", text).group(0)
    gai = re.search(r"(?ms)^  gai: (\S+)\? <([^\n]*)> \{\n(.*?)\n  \}", block)
    assert gai.group(1) == "hx.comps::Line", gai.group(0)
    assert 'cdlCompoundGain:{unit:"s/K", gain:"inF2", per:"inX2", perGroup:"u"}' in gai.group(2), gai.group(2)
    body = gai.group(3)
    for line in ('    inF2: <link:"gai_k.out">', '    in: <link:"abs2.out">', '    inX2: <link:"gai_inX2.out">',
                 '    inX1: <link:"gai_inX1.out">', '    inF1: <link:"gai_inF1.out">',
                 '    limitBelow: "false"', '    limitAbove: "false"'):
        assert line in body.split("\n"), (line, body)
    per = re.search(r"(?ms)^  gai_inX2: hx.comps::NumberConst\? <([^\n]*)> \{\n    out: (.*?)\n  \}", block)
    assert per.group(2) == "hx.comps::StatusNumber { val: 1K }"
    assert 'cdlLiteralUnits:{out:"K"}' in per.group(1) and 'cdlLiteralDelta:"out"' in per.group(1)
    assert 'cdlUnitGroup:"gai.u"' in per.group(1)
    for z in ("gai_inX1", "gai_inF1"):
        assert re.search(r"(?m)^  %s: hx.comps::NumberConst\? <[^\n]*> \{\n    out: hx.comps::StatusNumber \{ val: 0 \}" % z,
                         block), z
    # every other MultiplyByParameter keeps Multiply: a gain in a database unit, or none, needs no line
    assert text.count("cdlCompoundGain") == 1


def _point_case(unit, point_unit, spec):
    ci = generate.ClassInfo("X", "composite", "")
    c = generate.Conn("u", "in", "Real", unit, None, None, "")
    c.point_unit = point_unit
    ci.conns.append(c)
    return ci, {"u": "u"}, {("X", "u"): ({"cdlPointSpec": spec}, "zone")}


def test_a_dimensionless_connector_on_a_point_in_another_unit_refuses_unless_decided():
    # Wrong behavior caught: either point-unit refusal in point_meta lost. A unit "1" connector on a ppm point with
    # no pointUnits decision, or a decision that disagrees with the point's unit, would otherwise pass with no scale
    # and no unit, a factor-of-a-million miss nobody sees.
    ci, names, points = _point_case("1", None, "ph.points::ZoneCo2Sensor")
    with pytest.raises(cxf.CxfError, match="no pointUnits decision"):
        hxemit.point_meta("X", ci, names, points)
    ci, names, points = _point_case("1", "ppm", "ph.points::ZoneAirTempSensor")
    with pytest.raises(cxf.CxfError, match="counted in ppm, and its point specs carry"):
        hxemit.point_meta("X", ci, names, points)
    # the decided and the percent cases pass, the second with its scale
    ci, names, points = _point_case("1", "ppm", "ph.points::ZoneCo2Sensor")
    assert hxemit.point_meta("X", ci, names, points)["u"] == ["cdlPointSpec:ph.points::ZoneCo2Sensor", 'cdlPointScope:"zone"']
    ci, names, points = _point_case("1", None, "ph.points::CoolModulatingCmd")
    assert 'cdlPointScale:"0.01"' in hxemit.point_meta("X", ci, names, points)["u"]
