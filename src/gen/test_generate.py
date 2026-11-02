#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Tests for the kw.cdl generator. Run from the repo root: python -X utf8 -m pytest src/gen -q"""
import copy
import json
import os
import re
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIBS = ROOT / "src" / "xeto"
sys.path.insert(0, str(HERE))

import cxf_source  # noqa: E402

SRC = cxf_source.source_root()

import cxf  # noqa: E402

MBL_DIR = pathlib.Path(os.environ.get("MBL_DIR", ""))   # an MBL clone at the pin; conftest.py checks it
OBC = "Buildings.Controls.OBC."


def test_relative_class_resolves_by_modelica_scope():
    # modelica-json writes MBL's own TDea constant as "CDL.Reals.Sources.Constant".
    known = {OBC + "CDL.Reals.Sources.Constant", OBC + "ASHRAE.G36.Generic.TrimAndRespond"}
    scope = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplyTemperature"
    assert cxf.resolve_class("CDL.Reals.Sources.Constant", scope, known) == OBC + "CDL.Reals.Sources.Constant"
    assert cxf.resolve_class(OBC + "CDL.Reals.Sources.Constant", scope, known) == OBC + "CDL.Reals.Sources.Constant"
    with pytest.raises(cxf.CxfError, match="does not resolve"):
        cxf.resolve_class("CDL.Reals.NoSuchBlock", scope, known)


@pytest.mark.inputs
def test_the_measured_relative_name_is_in_the_pinned_source():
    # The relative name the test above resolves is real, not invented: the pinned CXF carries it.
    doc = cxf.Cxf.load(SRC / "kw.cdl.g36.ahu/cxf/AHUs/MultiZone/VAV/SetPoints/SupplyTemperature.jsonld")
    types = {cxf.local(n.get("@type", "")) for n in doc.nodes.values()}
    assert "CDL.Reals.Sources.Constant" in types


@pytest.mark.parametrize("raw,val,expr", [
    (2, 2.0, None),                                                          # a JSON number
    (600.5, 600.5, None),
    (True, True, None),
    ({"@value": "-0.6", "@type": "http://www.w3.org/2001/XMLSchema#decimal"}, -0.6, None),   # measured
    ({"@value": "true", "@type": "http://www.w3.org/2001/XMLSchema#boolean"}, True, None),
    ("k", None, "k"),                                                        # a binding to a parent parameter
    ("273.15 + (55 - 32)/1.8", None, "273.15 + (55 - 32)/1.8"),              # preserved expression
])
def test_value_forms_agree(raw, val, expr):
    assert cxf.literal(raw) == (val, expr)


def test_one_or_many_reads_alike():
    one = cxf.Cxf({"@context": {"S231": cxf.S231, "ex": "http://example.org#"},
                   "@graph": [{"@id": "ex:A", "@type": "S231:Block", "S231:hasOutput": {"@id": "ex:A.y"}}]})
    many = cxf.Cxf({"@context": {"S231": cxf.S231, "ex": "http://example.org#"},
                    "@graph": [{"@id": "ex:A", "@type": "S231:Block", "S231:hasOutput": [{"@id": "ex:A.y"}]}]})
    a = one.nodes["http://example.org#A"]
    b = many.nodes["http://example.org#A"]
    assert one.ids(a, "hasOutput") == many.ids(b, "hasOutput") == ["http://example.org#A.y"]


# The grammar's cases live in one table, the resolver's test resource, which the resolver's evaluator also runs.
EXPRESSIONS = json.loads((ROOT / "src/fan/cdlResolve/test/res/expression-cases.json").read_text(encoding="utf-8"))


def _enum(lit):
    p = EXPRESSIONS["enumPrefix"]
    return lit.rsplit(".", 1)[1] if lit.startswith(p) else None


@pytest.mark.parametrize("case", EXPRESSIONS["accept"], ids=lambda c: c["src"][:60])
def test_expression_grammar(case):
    got = cxf.evaluate(case["src"], case["env"], _enum)
    assert got == case["want"] and type(got) is type(case["want"]), (got, case)


def test_typed_literal_is_parsed_exactly_from_its_text():
    # Non-integers arrive as {"@value": "0.05", "@type": "xsd:decimal"}
    assert cxf.literal({"@value": "0.05", "@type": cxf.XSD + "decimal"}) == (0.05, None)


def test_division_by_zero_refuses():
    with pytest.raises(cxf.CxfError, match="division by zero"):
        cxf.evaluate("a / (b - b)", {"a": 1.0, "b": 2.0}, lambda lit: None)


def test_old_continuous_names_refuse_naming_the_clause7_class():
    with pytest.raises(cxf.CxfError, match="CDL.Reals.PID"):
        cxf.resolve_class("CDL.Continuous.PID", OBC + "ASHRAE.G36.Generic.TrimAndRespond", {OBC + "CDL.Reals.PID"})


@pytest.mark.parametrize("case", EXPRESSIONS["refuse"], ids=lambda c: c["src"][:60])
def test_expression_outside_the_grammar_refuses_quoting_it(case):
    with pytest.raises(cxf.CxfError) as e:
        cxf.evaluate(case["src"], case["env"], _enum)
    assert case["src"] in str(e.value)


def test_every_if_expression_in_the_open_libs_evaluates_under_the_grammar():
    # Wrong behavior caught: an if-expression in a generated default or size that the grammar
    # refuses, so the resolver cannot instantiate the class. At MBL 14.0.0 there are three: Reheat Controller's heaCoi
    # default and kw.cdl's MatrixMax and MatrixMin output sizes.
    found = []
    for lib in ["kw.cdl"] + list(generate.G36_LIBS):
        for f in sorted((LIBS / lib).glob("*.xeto")):
            for m in re.finditer(r'(cdlDefault|cdlArraySize|cdlBind|cdlEnable|cdlCondition):("(?:[^"\\]|\\.)*"|\{[^}]*\})',
                                 f.read_text(encoding="utf-8")):
                if re.search(r"\bif\b", m.group(2)):
                    found.append((lib, m.group(1), m.group(2)))
    assert sorted((lib, k) for lib, k, _ in found) == [("kw.cdl", "cdlArraySize")] * 2 + [("kw.cdl.g36.terminal", "cdlDefault")], found
    cases = {c["src"].strip() for c in EXPRESSIONS["accept"]}
    for lib, k, v in found:
        src = json.loads(v)
        assert src.strip() in cases or src.replace("rowMin", "rowMax").strip() in cases, src


import generate  # noqa: E402
import mo_reader  # noqa: E402


def g36_text(root=ROOT):
    """Every generated G36 lib's text, concatenated (the G36 set splits into common, ahu and terminal)."""
    return "\n".join((root / generate.LIBS / lib / "g36.xeto").read_text(encoding="utf-8") for lib in generate.G36_LIBS)


def _regen(tmp_path):
    out = tmp_path / "out"
    generate.main(["--out", str(out), "--no-fetch"])
    return out


@pytest.mark.inputs
def test_byte_stable_regeneration(tmp_path, mbl_cdl):
    # Wrong behavior caught: a hand edit to a generated file, or a generator that is not deterministic. Each open
    # lib's lib.xeto pragma is generated too: check_open_libs.py accepts only that form.
    out = _regen(tmp_path)
    for rel in generate.generated_files() + generate.lib_xeto_files() + [generate.BOUNDS_REPORT, generate.UNITS_REPORT]:
        assert (out / rel).read_bytes() == (ROOT / rel).read_bytes(), rel + " differs from a fresh regeneration"


@pytest.mark.inputs
def test_two_regenerations_are_byte_identical(tmp_path, mbl_cdl):
    # Wrong behavior caught: output that depends on set or dict iteration order (propagate_bounds walks sets of
    # candidate paths), which a single comparison against the checked-in files could pass by luck.
    a, b = tmp_path / "a", tmp_path / "b"
    generate.main(["--out", str(a), "--no-fetch"])
    generate.main(["--out", str(b), "--no-fetch"])
    for rel in generate.generated_files() + [generate.BOUNDS_REPORT]:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_spec_names_flatten_as_the_spec_says():
    assert generate.spec_name(OBC + "CDL.Reals.Sources.Constant", generate.CDL_PREFIX) == "RealsSourcesConstant"
    assert generate.spec_name(OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplyTemperature",
                              generate.G36_PREFIX) == "AhusMultiZoneVavSetPointsSupplyTemperature"
    assert generate.spec_name(OBC + "ASHRAE.G36.TerminalUnits.Reheat.Subsequences.SystemRequests",
                              generate.G36_PREFIX) == "TerminalUnitsReheatSubsequencesSystemRequests"
    assert generate.spec_name(OBC + "CDL.Reals.PIDWithReset", generate.CDL_PREFIX) == "RealsPidWithReset"


def test_slot_names_lower_and_keep_the_cdl_name():
    text = g36_text()
    assert 'tSupCoo_min: Number? <cdlParam, cdlName:"TSupCoo_min"' in text    # MBL default 285.15: a maybe slot


@pytest.mark.inputs
def test_every_generated_link_path_resolves_inside_its_spec():
    # Xeto compile does not check that a link path resolves, so this does.
    text = g36_text()
    classes = generate.load_classes(SRC)
    del text
    for cls in [OBC + "ASHRAE.G36." + c for c in generate.G36]:
        got = generate.read_generated(ROOT, cls)
        ci = classes[cls]
        slots = {generate.lower(x.name) for x in ci.conns}
        inst_conns = {generate.lower(i.name): {generate.lower(c.name) for c in classes[i.cls].conns} for i in ci.insts}
        for pair in got["connects"]:
            for end in pair:
                parts = end.split(".")
                ok = (len(parts) == 1 and parts[0] in slots) or \
                     (len(parts) == 2 and parts[1] in inst_conns.get(parts[0], set()))
                assert ok, "%s: link end %s resolves to nothing" % (cls, end)


def test_defaulted_parameters_are_maybe_slots_and_no_default_ones_are_required():
    # On 4.0.6 a default does not make a slot optional.
    text = (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8")
    assert 'amplitude: Number? <cdlParam' in text      # Reals.Sources.Pulse, composed in kw.cdl: MBL default 1
    assert 'period: Number <cdlParam' in text          # no MBL default: required
    g36 = g36_text()
    assert 'floHys: Number <cdlParam' in g36          # no MBL default: required


def test_quantities_are_camel_case():
    g36 = g36_text()
    assert 'quantity:"volumetricFlow"' in g36 and "cdlDelta" in g36
    assert 'temperature differential' not in g36


def test_slot_lowering_collision_refuses():
    with pytest.raises(cxf.CxfError, match="collide"):
        generate.slot_names(["TOut", "tOut"], "X")


# The name differences between Clause 7 as printed and MBL 12.1.0, by clause number: seven renames, and
# two headings that print a stray 7 before the package name (7.5.65.1, 7.5.76.1). clause7.json keeps them as
# printed, and they are normalized here in code.
NORMALIZE = {"7.5.29.1": "CDL.Reals.MultiSum", "7.5.29.2": "CDL.Integers.MultiSum", "7.5.39.2": "CDL.Integers.Change",
             "7.5.66.2": "CDL.Integers.LessThreshold", "7.5.71.1": "CDL.Integers.Stage",
             "7.5.82.3": "CDL.Logical.Sources.Constant", "7.5.83.3": "CDL.Logical.Sources.Pulse",
             "7.5.65.1": "CDL.Integers.LessEqualThreshold", "7.5.76.1": "CDL.Logical.Timer"}


def test_kw_cdl_is_exactly_the_clause7_set():
    # A block added to or missing from MBL fails here instead of entering kw.cdl.
    c7 = json.loads((HERE / "clause7.json").read_text(encoding="utf-8"))["classes"]
    # As printed: 132 headings and 132 distinct names. 7.5.66.2 repeats LessEqualThreshold, and
    # 7.5.65.1's printed stray 7 keeps that repeat from collapsing two entries into one.
    assert len(c7) == 132 and len(set(c7.values())) == 132
    want = {OBC + NORMALIZE.get(num, name) for num, name in c7.items()}
    assert len(want) == 132
    # Each class is a CdlClass instance or a refusal by name in kw.cdl/classes.xeto, exactly once.
    text = (LIBS / "kw.cdl/classes.xeto").read_text(encoding="utf-8")
    found = re.findall(r'(?m)^  cdlClass: "(Buildings\.Controls\.OBC\.CDL\.[^"]+)"$', text) + \
        re.findall(r'CdlRefusal \{name:"\w+", cdlClass:"(Buildings\.Controls\.OBC\.CDL\.[^"]+)"', text)
    got = set(found)
    assert len(found) == len(got) == 132
    assert sorted(got - want) == [] and sorted(want - got) == []


def test_every_generated_block_carries_its_clause_and_231_spelling():
    # The array specs keep their clause meta; every class's CdlClass instance or refusal carries both.
    text = (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8")
    assert 'cdlClause:"7.5.29.1", cdl231Name:"CDL.Reals.Multisum"' in text
    classes = (LIBS / "kw.cdl/classes.xeto").read_text(encoding="utf-8")
    assert '@cdl-RealsMultiSum: CdlClass {\n  cdlClass: "Buildings.Controls.OBC.CDL.Reals.MultiSum"\n  grade: "array"\n' \
        '  clause: "7.5.29.1"\n  name231: "CDL.Reals.Multisum"\n' in classes
    assert classes.count('  clause: "') + classes.count(', clause:"') == 132


def test_no_conformance_wording():
    # No compliance or approval claim in anything the generator writes.
    for rel in generate.generated_files() + generate.lib_xeto_files():
        low = (ROOT / rel).read_text(encoding="utf-8").lower()
        for word in ("complian", "conform", "certif", "approved by ashrae", "231 reference"):
            assert word not in low, (rel, word)


def _g36_generated(kind):
    """Every G36 class the checked-in libs carry, by kind: "enum" or "composite"."""
    text = g36_text()
    heads = re.findall(r'(?m)^[A-Z]\w*: (\S+) <cdlClass:"(Buildings\.Controls\.OBC\.ASHRAE\.G36\.[^"]+)"', text)
    return sorted(c for base, c in heads if (base == "Enum") == (kind == "enum"))


def _kw_cdl_specs():
    """The CDL elementary classes kw.cdl still carries a spec for: the array classes and the composed classes."""
    text = (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'(?m)^[A-Z]\w*: CdlBlock <[^>]*?cdlClass:"(Buildings\.Controls\.OBC\.CDL\.[^"]+)"', text)))


def _generated_classes():
    # The round trip covers every generated class: each CDL elementary class kw.cdl carries a spec for
    # (the 28 array classes and the 4 composed ones) and every G36 composite the three G36 libs carry (116 on MBL
    # 14.0.0), read from the checked-in files. The other elementary classes have no spec since they run as hx.comps
    # comps; test_classmap.py covers them.
    return _kw_cdl_specs() + _g36_generated("composite")


# Round-trip differences between MBL's .mo source and the generated Xeto that are ACCEPTED, each with its
# reason. The test fails when a class shows a difference not listed here, and when a listed
# difference no longer occurs, so the list cannot rot.
ACCEPTED = {}


@pytest.mark.inputs
@pytest.mark.parametrize("cls", _generated_classes())
def test_round_trip_against_mbl_source(cls):
    # Wrong behavior caught: a dropped or renamed connector, parameter, default, unit, component, connection,
    # guard or final binding between MBL's .mo and the generated Xeto; a connector or parameter whose CDL type,
    # Xeto slot type or connector unit differs from MBL's; a final parameter or final binding lost.
    # Measured: 45 Real inputs flipped to Bool fail 33 classes, every class carrying one.
    mo = MBL_DIR / (cls.replace(".", "/") + ".mo")
    assert mo.exists(), "set MBL_DIR to an MBL checkout at the pin in src/gen/stamp.json; missing " + str(mo)
    want = mo_reader.read(mo.read_text(encoding="utf-8"), cls, MBL_DIR)
    got = generate.read_generated(ROOT, cls)
    problems = generate.compare(want, got, elementary=cls.startswith(generate.CDL_PREFIX))
    accepted = {line for line, _why in ACCEPTED.get(cls, [])}
    assert sorted(set(problems) - accepted) == [], "new differences"
    assert sorted(accepted - set(problems)) == [], "accepted differences that no longer occur"


@pytest.mark.inputs
def test_generator_loads_every_clause7_class_with_no_load_error():
    # The generator must load and emit all 132 Clause 7 classes from the real CXF. Measured on modelica-json
    # 5460add3's CXF-Core.jsonld: 132 classes, 4 CDL.Types enumerations, and one class left out by rule
    # (CDL.Constants).
    classes = generate.load_classes(SRC)
    cdl_report = [r for r in generate.load_classes.report if r.startswith(generate.CDL_PREFIX)]
    assert [r for r in cdl_report if "CDL.Constants" not in r] == []
    c7 = generate.clause7()
    elem = [p for p in classes if p in c7]
    assert len(elem) == 132
    assert all(classes[p].kind == "elementary" for p in elem)          # Clause 7 decides, not containsBlock
    assert classes[OBC + "CDL.Reals.PID"].insts == [] and classes[OBC + "CDL.Reals.Greater"].edges == []
    enums = [p for p in classes if p.startswith(OBC + "CDL.Types.") and classes[p].kind == "enum"]
    assert len(enums) == 4
    zt = classes[OBC + "CDL.Reals.Sources.CalendarTime"].param("zerTim")
    assert zt.dtype == OBC + "CDL.Types.ZeroTime"                       # the recorded hand rule


def test_no_slot_is_named_writeLevel():
    # Wrong behavior caught: a record that Folio will not persist, because SkySpark reserves the writeLevel tag.
    for rel in generate.generated_files() + [generate.LIBS + "/kw.cdl/meta.xeto", generate.LIBS + "/kw.cdl/block.xeto"]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s+writeLevel\s*:", text), rel


def test_instance_slots_carry_their_modelica_name():
    # Wrong behavior caught: an importer that falls back to the lowered slot name, so MBL's TDea reads as tDea.
    text = g36_text()
    assert 'tDea: hx.comps::NumberConst? <cdlInstance, cdlName:"TDea",' in text
    inst = re.findall(r"(?m)^  \w+: \S+ <cdlInstance(.*)$", text)
    assert len(inst) == 3990 and all(line.startswith(', cdlName:"') for line in inst)   # the 116 G36 composites


def test_a_qudt_unit_with_no_haystack_symbol_refuses():
    # Wrong behavior caught: a raw qudt key (HZ, RAD and J-PER-KiloGM each shipped this way once) written
    # as cdlUnit instead of refusing.
    node = {"@id": "http://example.org#X.u", "http://qudt.org/schema/qudt/hasUnit": {"@id": "http://qudt.org/vocab/unit/FURLONG"}}
    with pytest.raises(cxf.CxfError, match="FURLONG"):
        generate._unit(node, None)


@pytest.mark.inputs
def test_a_hand_connector_that_cxf_already_lists_refuses():
    # Wrong behavior caught: a modelica-json that types CalendarTime.year, and the hand rule adding it a second time.
    doc = cxf.Cxf(json.loads((SRC / "kw.cdl/cdl-elementary.jsonld").read_text(encoding="utf-8")))
    cls = OBC + "CDL.Reals.Sources.CalendarTime"
    cid = next(k for k in doc.nodes if cxf.local(k) == cls)
    yid = next(k for k in doc.nodes if cxf.local(k) == cls + ".year")
    doc.nodes[yid]["@type"] = cxf.S231 + "IntegerOutput"
    doc.nodes[cid][cxf.S231 + "hasOutput"] = cxf.as_list(doc.nodes[cid][cxf.S231 + "hasOutput"]) + [{"@id": yid}]
    generate.load_classes(SRC)
    with pytest.raises(cxf.CxfError, match="already lists"):
        generate.read_class(doc, cid, set(), set())


def test_conditional_alternative_drivers_become_one_link_and_an_alt_link():
    # MBL's TrimAndRespond drives notHol.u from fal.y or truHol.y, by have_hol; both survive in the type.
    text = g36_text()
    assert 'in: <link:"fal.out", cdlAltLink:"truHol.out">' in text


@pytest.mark.inputs
def test_round_trip_catches_a_dropped_connection(tmp_path):
    # RED evidence for the round trip itself: drop one connection from TrimAndRespond's CXF in memory.
    src = json.loads((SRC / "kw.cdl.g36.common/cxf/Generic/TrimAndRespond.jsonld").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(src)
    for n in mutated["@graph"]:
        if n["@id"].endswith("TrimAndRespond.tim.y"):
            n["S231:isConnectedTo"] = cxf.as_list(n["S231:isConnectedTo"])[:1]
            break
    cls = OBC + "ASHRAE.G36.Generic.TrimAndRespond"
    got = generate.read_generated_from_sources(SRC, cls, override={cls: mutated})
    want = mo_reader.read((MBL_DIR / (cls.replace(".", "/") + ".mo")).read_text(encoding="utf-8"), cls, MBL_DIR)
    problems = generate.compare(want, got)
    assert any("connect" in p and "tim.y" in p for p in problems), problems


def test_every_slot_name_that_is_a_ph_tag_has_a_recorded_decision():
    decided = json.loads((HERE / "collisions.json").read_text(encoding="utf-8"))
    found = generate.tag_collisions(ROOT)
    assert sorted(found) == sorted(decided), "decide each colliding slot name in src/gen/collisions.json"




@pytest.mark.inputs
def test_an_output_to_output_connect_refuses():
    classes = generate.load_classes(SRC)
    ci = classes[OBC + "ASHRAE.G36.Generic.TrimAndRespond"]
    ci.edges = ci.edges + [("tim.y", "uniDel.y")]          # two outputs joined: output to output
    with pytest.raises(cxf.CxfError, match="joins"):
        generate.orient(ci, classes)


@pytest.mark.inputs
def test_an_untyped_enum_parameter_takes_its_type_from_its_default():
    # SystemRequests.heaCoi has no @type and no isOfDataType
    classes = generate.load_classes(SRC)
    p = classes[OBC + "ASHRAE.G36.TerminalUnits.Reheat.Subsequences.SystemRequests"].param("heaCoi")
    assert p.dtype == OBC + "ASHRAE.G36.Types.HeatingCoil"
    assert classes[p.dtype].items == ["Electric", "None", "WaterBased"]




# The open model. kw.cdl and the three G36 libs carry the CDL model only: plain connector types, no engine's
# `output` flag, no runtime slot, no runtime spec, no runtime provenance and no building ontology. A runtime that
# binds these libs keeps its own half in its own libs. These tests hold the open model to what it declares, an
# allow-list, so they name nothing a runtime might add: the meta tags are frozen in check_open_libs.OPEN_META, and
# the specs below. A clash between an open slot and a runtime's own slot is that runtime's check, which reads both.
# The dependency rule itself is test_open_libs.py.


def _spec_lines(text, name):
    """The body lines of one top-level spec in a .xeto file."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith(name + ":"):
            inside = True
            continue
        if inside and line.startswith("}"):
            break
        if inside:
            out.append(line)
    assert out, "spec %s not found" % name
    return out


def _open_xeto_files():
    return [f for lib in generate.OPEN_LIBS for f in sorted((LIBS / lib).glob("*.xeto"))]


def test_connectors_ride_hx_comps_status_types_and_parameters_stay_plain():
    """Red when a scalar connector keeps a plain type, so a link from it into a comp's status slot carries a bare
    number the comp cannot read (a composite input Number into Limiter.in read as null), or when a parameter is
    retyped. A CDL Integer connector rides StatusNumber, as hx.comps carries every number."""
    want = {"Real": "hx.comps::StatusNumber?", "Integer": "hx.comps::StatusNumber?", "Boolean": "hx.comps::StatusBool?",
            "String": "hx.comps::StatusStr?"}
    n = 0
    for rel in generate.generated_files():
        for l in (ROOT / rel).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^  \w+: (\S+) <(cdlInput|cdlOutput|cdlParam)[,>]", l)
            if not m:
                continue
            ctype = _meta(l, "cdlType")
            if m.group(2) == "cdlParam":
                assert "Status" not in m.group(1), l.strip()
            elif "cdlArraySize" not in l:
                assert m.group(1) == want[ctype], l.strip()
                n += 1
    assert n > 1500, n
    tr = _spec_lines((LIBS / "kw.cdl.g36.common/g36.xeto").read_text(encoding="utf-8"), "GenericTrimAndRespond")
    assert any(l.startswith("  numOfReq: hx.comps::StatusNumber? <cdlInput") for l in tr), "an Integer input"
    assert any(l.startswith("  delTim: Number <cdlParam") for l in tr)


def test_every_output_is_transient_and_readonly_and_carries_no_engine_flag():
    """Red when an output lacks transient or readonly (an output is computed, never stored), or carries the axon lib's
    `output` flag, which an open lib cannot resolve: it depends on sys and sys.comp only."""
    outs = [l for f in generate.generated_files() for l in (ROOT / f).read_text(encoding="utf-8").splitlines()
            if "<cdlOutput" in l]
    assert len(outs) > 100
    bad = [l.strip() for l in outs if not all(re.search(r"[<, ]%s[,>]" % m, l) for m in ("transient", "readonly"))
           or re.search(r"[<, ]output[,>]", l)]
    assert bad == [], bad[:5]


# The files each open lib holds, and the specs its hand-written files declare: the whole of what is not generated.
OPEN_FILES = {"kw.cdl": {"lib.xeto", "blocks.xeto", "block.xeto", "constants.xeto", "meta.xeto", "class.xeto",
                          "classes.xeto"},
              "kw.cdl.g36.common": {"lib.xeto", "g36.xeto"}, "kw.cdl.g36.ahu": {"lib.xeto", "g36.xeto"},
              "kw.cdl.g36.terminal": {"lib.xeto", "g36.xeto"}}
HAND_SPECS = {"kw.cdl/block.xeto": ["CdlBlock"], "kw.cdl/constants.xeto": ["CdlConstants"],
              "kw.cdl/meta.xeto": ["CdlBoundWhen"],
              "kw.cdl/class.xeto": ["CdlGrade", "CdlClass", "CdlRefusal", "CdlRefused", "CdlWire"]}
# CdlBlock's own slots, on every class: the open block marker, its instance path, its layer and its citations.
CDLBLOCK_SLOTS = ["cdlBlock", "cdlPath", "cdlLayer", "cdlCites"]
TOP_DECL = re.compile(r"^(@?[A-Za-z_][A-Za-z0-9_]*)\s*:([^\n]*)$", re.M)


def _top_decls(f):
    """(name, rest of line) of each top-level declaration in a .xeto file, comments and strings blanked."""
    import check_open_libs
    text = f.read_text(encoding="utf-8")
    code = check_open_libs._code(text).split("\n")
    return [(m.group(1), text.split("\n")[text.count("\n", 0, m.start())]) for m in TOP_DECL.finditer("\n".join(code))]


def test_the_open_model_declares_only_its_own_specs():
    """Red when an open lib declares anything beyond the CDL model: a file beyond its pinned set (a runtime file), a
    spec in a hand-written file beyond its pinned set, a slot on CdlBlock beyond its four, or a top-level spec in a
    generated file that is not an MBL class or constants package. An allow-list, so it names nothing a runtime
    might add; the meta tags are frozen in check_open_libs.OPEN_META."""
    for lib, files in OPEN_FILES.items():
        assert {f.name for f in (LIBS / lib).glob("*.xeto")} == files, lib
    for rel, specs in HAND_SPECS.items():
        assert [n for n, _ in _top_decls(LIBS / rel)] == specs, rel
    assert [l.split(":")[0].strip() for l in _spec_lines((LIBS / "kw.cdl/block.xeto").read_text(encoding="utf-8"),
                                                          "CdlBlock") if l.strip() and not l.strip().startswith("//")] \
        == CDLBLOCK_SLOTS
    for rel in generate.generated_files():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for name, line in _top_decls(ROOT / rel):
            if name == "@cdl-refused":
                assert line == name + ": CdlRefused {", (rel, line)
            elif name.startswith("@cdl-"):
                assert line == name + ": CdlClass {", (rel, line)
                body = text[text.index(line):].split("\n}", 1)[0]
                assert re.search(r'^  cdlClass: "Buildings\.', body, re.M), (rel, name)
            elif name.startswith("@"):
                assert line.startswith(name + ": kw.cdl::CdlConstants {"), (rel, line)
                body = text[text.index(line):].split("\n}", 1)[0]
                assert re.search(r'^  cdlClass: "Buildings\.', body, re.M), (rel, name)
            else:
                assert re.match(r'%s: \S+ <cdlClass:"Buildings\.' % re.escape(name), line), (rel, line)


@pytest.mark.parametrize("rel,plant", [
    ("kw.cdl/block.xeto", "\nCdlAcmeRuntime: Dict {\n  acmeTick: Str\n}\n"),
    ("kw.cdl/meta.xeto", "\nCdlAcmeHeartbeat: Dict\n"),
    ("kw.cdl.g36.ahu/g36.xeto", "\nAcmeSequence: Dict <abstract>\n"),
    ("kw.cdl/block.xeto", None),
])
def test_a_spec_or_file_beyond_the_open_model_is_refused(tmp_path, monkeypatch, rel, plant):
    # The check's own red conditions, on a copy of the open libs: a spec planted in a hand-written file or a generated
    # one, a slot planted on CdlBlock, and a new file. Synthetic names: the allow-list refuses anything it does not list.
    for lib in OPEN_FILES:
        shutil.copytree(LIBS / lib, tmp_path / generate.LIBS / lib)
    f = tmp_path / generate.LIBS / rel
    if plant is None:
        (tmp_path / generate.LIBS / "kw.cdl" / "acme.xeto").write_text("// a runtime file\n", encoding="utf-8")
    else:
        f.write_text(f.read_text(encoding="utf-8") + plant, encoding="utf-8", newline="\n")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "LIBS", tmp_path / generate.LIBS)
    with pytest.raises(AssertionError):
        test_the_open_model_declares_only_its_own_specs()


def test_a_slot_beyond_cdlblocks_four_is_refused(tmp_path, monkeypatch):
    for lib in OPEN_FILES:
        shutil.copytree(LIBS / lib, tmp_path / generate.LIBS / lib)
    f = tmp_path / generate.LIBS / "kw.cdl" / "block.xeto"
    t = f.read_text(encoding="utf-8")
    assert "  cdlBlock\n" in t
    f.write_text(t.replace("  cdlBlock\n", "  cdlBlock\n  acmeStamp: Str?\n", 1), encoding="utf-8", newline="\n")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "LIBS", tmp_path / generate.LIBS)
    with pytest.raises(AssertionError):
        test_the_open_model_declares_only_its_own_specs()
    assert not (LIBS / "kw.cdl.g36").exists(), "kw.cdl.g36 split into common, ahu and terminal"


def test_cdlblock_is_an_abstract_sys_comp_comp():
    """Red when CdlBlock goes back on an engine's base (hx.comps::HxComp ties the published model to one runtime)
    or regains a runtime or provenance slot."""
    text = (LIBS / "kw.cdl" / "block.xeto").read_text(encoding="utf-8")
    assert re.search(r"(?m)^CdlBlock: sys\.comp::Comp <abstract> \{", text)
    assert _slot_decls(text, "CdlBlock") == {"cdlBlock": "", "cdlPath": "Str?", "cdlLayer": "Str?", "cdlCites": "Dict?"}


def test_g36_composites_extend_the_cdl_block_base():
    """Red when a generated G36 composite names a base other than kw.cdl::CdlBlock (an engine's base, or the retired
    kw.cdl.g36 lib)."""
    heads = re.findall(r"(?m)^([A-Z]\w*): (\S+) <cdlClass:", g36_text())
    assert heads and all(base in ("kw.cdl::CdlBlock", "Enum") for _, base in heads), heads


def _slot_decls(text, name):
    """Slot name -> its declaration with the trailing comment removed, for one top-level spec. A bare marker slot
    maps to the empty string."""
    out = {}
    for line in _spec_lines(text, name):
        m = re.match(r"^  (\w+)(?:: (.*?))?\s*(//.*)?$", line)
        if m:
            out[m.group(1)] = m.group(2) or ""
    return out


def test_no_spec_has_a_compound_base():
    """Red when any spec in an open lib names a compound base (A & B): a compound base carries no component binding,
    so an engine that binds its subtypes gets sys::Obj."""
    bad = []
    for f in _open_xeto_files():
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Z]\w*): ([^<{/]*)", line)
            if m and "&" in m.group(2):
                bad.append("%s: %s" % (f, line.strip()))
    assert bad == [], bad


def test_no_open_lib_names_a_lib_outside_its_depends():
    """Red when an open lib names a spec of a lib outside its declared depends (a private ontology, say): a
    ph-modeled building would then fail fits, and the published lib would carry a dependency nobody can resolve."""
    for lib in generate.OPEN_LIBS:
        allowed = set(generate.OPEN_DEPENDS[lib]) | {lib}
        for f in sorted((LIBS / lib).glob("*.xeto")):
            named = set(re.findall(r"\b([a-z][\w]*(?:\.[a-z][\w]*)*)::", f.read_text(encoding="utf-8")))
            assert sorted(named - allowed) == [], (f, sorted(named - allowed))


# ---- package constants ----

OPM = OBC + "ASHRAE.G36.Types.OperationModes"


@pytest.mark.inputs
def test_operation_modes_read_from_the_pinned_json_equal_mbl_source():
    # Wrong behavior caught: a constant read from the json output with the wrong value, or one dropped, so a mode
    # comparison in SupplyFan tests the wrong integer. The reference is MBL's own package.mo, read by a regex that
    # shares nothing with the json reader.
    src = (MBL_DIR / "Buildings/Controls/OBC/ASHRAE/G36/Types/OperationModes/package.mo").read_text(encoding="utf-8")
    want = {n: float(v) for n, v in re.findall(r"constant\s+Integer\s+(\w+)\s*=\s*(\d+)", src)}
    assert len(want) == 7
    got = generate.load_constants(SRC)[OPM]
    assert got["type"] == "Integer"
    assert {n: v for n, (v, _) in got["items"].items()} == want


def test_g36_lib_carries_one_constants_instance_with_every_mode():
    # Wrong behavior caught: the constants table missing from the published lib, so the importer has nothing to
    # resolve conInt.k against on a project.
    text = (LIBS / "kw.cdl.g36.common/g36.xeto").read_text(encoding="utf-8")
    block = text[text.index("@typesOperationModes: kw.cdl::CdlConstants {"):]
    block = block[:block.index("\n}\n")]
    assert 'cdlClass: "%s"' % OPM in block
    for n, v in [("occupied", 1), ("coolDown", 2), ("setUp", 3), ("warmUp", 4), ("setBack", 5),
                 ("freezeProtection", 6), ("unoccupied", 7)]:
        assert re.search(r"\n    %s: Number \"%d\"" % (n, v), block), n


@pytest.mark.inputs
def test_a_dotted_name_no_package_defines_refuses_at_generation():
    # Wrong behavior caught: a generated binding naming a constant of a package nobody generated, which would ship
    # and refuse only at expansion on a project.
    classes = generate.load_classes(SRC)
    cls = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplyFan"
    consts = generate.load_constants(SRC)
    assert generate.unresolved_names(classes, [cls], consts) == []
    bad = generate.unresolved_names(classes, [cls], {})
    assert len(bad) == 5 and all("OperationModes" in b for b in bad), bad
    ci = copy.deepcopy(classes[cls])
    ci.insts[0].binds["k"] = (None, OPM + ".bogus")
    assert any(".bogus" in b for b in generate.unresolved_names(dict(classes, **{cls: ci}), [cls], consts))


# CDL units. kw.cdl 0.4.0 writes canonical Xeto `unit` meta beside `cdlUnit` (kept as CXF provenance), so
# `xeto fits` and the validator check a record's unit. The table is fixed: K by quantity, s to sec, 1 to the
# unitless marker, 1/s to /s, and Pa, Hz, rad, J/kg, m³/s unchanged. These tests read a fresh regeneration, not the
# checked-in files, so they test the generator; test_byte_stable_regeneration ties the two together.
# Since 0.8.0 a unit a resolver shows in the bound point's unit (K, Pa, m³/s, J/kg, /s) carries no Xeto unit, so
# fits does not refuse the converted value; cdlUnit keeps the SI unit, and cdlDelta marks a temperature difference.
CANONICAL = {("K", "temperature"): None, ("K", None): None,
             ("s", "time"): 'unit:"sec"', ("1", None): "unitless", ("1/s", None): None,
             ("Pa", "pressure"): None, ("Hz", None): 'unit:"Hz"', ("rad", None): 'unit:"rad"',
             ("J/kg", "specificEnthalpy"): None, ("m³/s", "volumetricFlow"): None,
             # m³/s where CXF carries no quantity kind (the full G36 set), and the two CDL units Haystack has no
             # symbol for, which carry neither unit nor unitless (generate.NO_HAYSTACK_UNIT).
             ("1/K", None): None, ("s/K", None): None}
SLOT_LINE = re.compile(r"^  \w+: \S+ <(cdlParam|cdlInput|cdlOutput)[,>]")


def _meta(line, key):
    m = re.search(r'[<, ]%s:"([^"]*)"' % key, line)
    return m.group(1) if m else None


def _has_unitless(line):
    return re.search(r"[<, ]unitless[,>]", line) is not None


@pytest.fixture(scope="module")
def regen(tmp_path_factory, mbl_cdl):
    out = tmp_path_factory.mktemp("units") / "out"
    generate.main(["--out", str(out), "--no-fetch"])
    return {"kw.cdl": [l for l in (out / generate.LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8").splitlines() if SLOT_LINE.match(l)],
            "kw.cdl.g36": [l for l in g36_text(out).splitlines() if SLOT_LINE.match(l)]}


def allines_all(regen):
    return regen["kw.cdl"] + regen["kw.cdl.g36"]


@pytest.mark.inputs
def test_every_cdl_unit_maps_to_canonical_unit_meta(regen):
    """Red when a differential slot gets K (fits would then accept an absolute temperature on a difference),
    a seconds slot gets s (the Xeto Unit enum keys a second as sec, so nothing fits it), a cdlUnit slot ships
    with no unit meta, or a bare-s slot stays without quantity:"time"."""
    counts = {}
    for lib, lines in regen.items():
        units = [l for l in lines if _meta(l, "cdlUnit") is not None]
        counts[lib] = len(units)
        for l in units:
            cu, q = _meta(l, "cdlUnit"), _meta(l, "quantity")
            assert (cu, q) in CANONICAL, "%s: no canonical row for cdlUnit %s with quantity %s: %s" % (lib, cu, q, l.strip())
            want = CANONICAL[(cu, q)]
            if want is None:
                assert _meta(l, "unit") is None and not _has_unitless(l), l.strip()
            elif want == "unitless":
                assert _has_unitless(l) and _meta(l, "unit") is None, l.strip()
            else:
                assert want in l and not _has_unitless(l), "%s: want %s: %s" % (lib, want, l.strip())
    # Measured on the 126 G36 classes of MBL 14.0.0. kw.cdl carried 73 until its elementary specs retired (0.8.0):
    # the 11 left are on the array classes and the composed classes, the only CDL classes kw.cdl still models.
    assert counts == {"kw.cdl": 11, "kw.cdl.g36": 2173}, counts
    allines = regen["kw.cdl"] + regen["kw.cdl.g36"]
    diff = [l for l in regen["kw.cdl.g36"] if re.search(r"[<, ]cdlDelta[,>]", l)]
    assert len(diff) == 165 + 14 + 10 and all(_meta(l, "unit") is None and re.search(r"[<, ]cdlDelta[,>]", l)
                                         for l in diff), [l.strip() for l in diff][:5]
    assert not any("ΔK" in l for l in allines_all(regen))
    assert not any(re.search(r"[<, ]cdlDelta[,>]", l) for l in regen["kw.cdl"])
    # a difference carries cdlDelta and no Xeto quantity: no one quantity fits both K and a Fahrenheit difference
    assert not any(_meta(l, "quantity") == "temperatureDifferential" for l in allines_all(regen))
    secs = [l for l in allines if _meta(l, "cdlUnit") == "s"]
    assert len(secs) == 6 + 406 and all(_meta(l, "unit") == "sec" for l in secs)
    assert not any(_meta(l, "unit") == "s" for l in allines)
    bare = [l for l in secs if _meta(l, "cdlQuantityKind") is None]
    assert len(bare) == 0 + 235 and all(_meta(l, "quantity") == "time" for l in bare), [l.strip() for l in bare][:5]
    # Only s implies a quantity alone, and only K slots get an inferred one (cdlQuantityInferred, 133: 38 by displayUnit
    # degC, 6 by displayUnit K, 89 by src/gen/quantities.json). No other unit gains a quantity. Since 0.7.1,
    # slots MBL declares with no unit at all take unit and quantity from a recorded decision (cdlUnitInferred, which
    # holds the unit) and carry no cdlUnit, since CXF states none: 14 K slots, plus 2 J/kg cutoffs with no quantity.
    # Since 0.8.0 a parameter bound by bare name into one that declares a unit takes it too (infer_bound_units), and
    # names the declaring parameter in cdlUnitVia: 68 at MBL 14.0.0, 10 of them K and all 10 differences (24 through
    # an elementary block's unitRule, PlantRequests' THys among them).
    inferred = [l for l in allines if re.search(r"[<, ]cdlQuantityInferred[,>]", l)]
    uinferred = [l for l in inferred if _meta(l, "cdlUnitInferred") == "K"]
    assert len(inferred) == 133 + 14 + 10 and len(uinferred) == 14 + 10
    ujkg = [l for l in allines if _meta(l, "cdlUnitInferred") == "J/kg"]
    assert len(ujkg) == 2 and all(_meta(l, "quantity") == "specificEnthalpy" and not _meta(l, "unit") for l in ujkg), ujkg
    vias = [l for l in allines if _meta(l, "cdlUnitVia") is not None]
    by_unit = {}
    for l in vias:
        by_unit[_meta(l, "cdlUnitInferred")] = by_unit.get(_meta(l, "cdlUnitInferred"), 0) + 1
    assert by_unit == {"1": 47, "1/K": 6, "K": 10, "Pa": 2, "m³/s": 3}, by_unit
    assert all(re.search(r"[<, ]cdlParam[,>]", l) for l in vias)
    assert not any(re.search(r"[<, ]cdlUnitInferred[,>]", l) for l in allines)   # never the bare marker
    assert all(_meta(l, "cdlUnit") == "K" for l in inferred if l not in uinferred)
    assert all(_meta(l, "cdlUnit") is None and _meta(l, "unit") is None and re.search(r"[<, ]cdlDelta[,>]", l)
               for l in uinferred)
    assert not any(re.search(r"[<, ]cdlUnitInferred[:,>]", l) for l in regen["kw.cdl"])
    # Since 0.8.0 Pa, J/kg and m³/s imply pressure, specificEnthalpy and volumetricFlow too, so fits refuses a value
    # in another quantity after a resolver converts it
    implied = [l for l in allines if _meta(l, "quantity") is not None and _meta(l, "cdlQuantityKind") is None
               and l not in inferred]
    implied_si = [l for l in implied if l not in bare]
    assert all((_meta(l, "cdlUnit") or _meta(l, "cdlUnitInferred"), _meta(l, "quantity")) in
               (("Pa", "pressure"), ("J/kg", "specificEnthalpy"), ("m³/s", "volumetricFlow")) for l in implied_si)
    assert [l for l in implied if l in bare] == bare
    assert not any(_meta(l, "cdlUnit") in ("Pa", "J/kg", "m³/s") and _meta(l, "quantity") is None for l in allines)


@pytest.mark.inputs
def test_a_connector_or_parameter_with_no_cdl_unit_carries_no_unit_meta(regen):
    """Red when a polymorphic connector is typed in the lib, so every instance inherits a wrong unit. Absence of
    unit meta means "polymorphic, typed per instance", and this is what enforces it."""
    for lib, lines in regen.items():
        nounit = [l for l in lines if _meta(l, "cdlUnit") is None]
        # The one exception (0.7.1): a slot whose unit a recorded decision supplied carries cdlUnitInferred and unit
        # meta with no cdlUnit; 16 in the G36 libs at MBL 14.0.0 by recorded decision, 68 by binding and 27 CO2 slots counted in ppm, none in kw.cdl.
        inferred = [l for l in nounit if _meta(l, "cdlUnitInferred") is not None]
        assert len(inferred) == {"kw.cdl": 0, "kw.cdl.g36": 16 + 68 + 27}[lib], (lib, len(inferred))
        free = [l for l in nounit if l not in inferred]
        # measured on MBL 14.0.0; kw.cdl's was 432 until its elementary specs retired (0.8.0), and the G36
        # libs' 1101 until the four economizer cutoff decisions 1097 until units inferred by binding, and 1029 until the CO2 ppm decisions (0.8.0)
        assert len(free) == {"kw.cdl": 122, "kw.cdl.g36": 1002}[lib], (lib, len(free))
        bad = [l.strip() for l in free if _meta(l, "unit") is not None or _has_unitless(l)]
        assert bad == [], "%s: %s" % (lib, bad[:5])


@pytest.mark.inputs
def test_reals_add_connectors_stay_unit_free():
    """The named case of the test above. Red when RealsAdd's u1, u2 or y (one block for every quantity) carries
    unit or unitless. The class runs as hx.comps::Add and has no kw.cdl spec, so this renders the CDL model of it
    on its own."""
    out = generate.render(generate.load_classes(SRC), [OBC + "CDL.Reals.Add"],
                          json.loads((HERE / "stamp.json").read_text(encoding="utf-8")), "t")
    body = _spec_lines(out, "RealsAdd")
    for slot in ("u1", "u2", "y"):
        line = next(l for l in body if l.startswith("  %s: " % slot))
        assert _meta(line, "unit") is None and not _has_unitless(line), line.strip()


def _stamp():
    return json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))


@pytest.mark.inputs
@pytest.mark.parametrize("kind", ["param", "conn"])
def test_an_unmapped_cdl_unit_fails_generation_by_name(kind):
    """Red when a new MBL unit (here %, which generate.UNITS maps from qudt PERCENT) ships with no unit meta and
    nobody notices. The refusal names the class, the slot and the unit."""
    classes = generate.load_classes(SRC)
    cls = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplyTemperature"
    ci = copy.deepcopy(classes[cls])
    if kind == "param":
        target = next(p for p in ci.params if p.unit == "K")
    else:
        target = next(c for c in ci.conns if c.unit == "K")
    target.unit, target.qkind = "%", None
    with pytest.raises(cxf.CxfError) as e:
        generate.emit_class(ci, dict(classes, **{cls: ci}), _stamp())
    msg = str(e.value)
    assert cls in msg and target.name in msg and "%" in msg, msg


@pytest.mark.inputs
def test_a_kelvin_slot_with_no_quantity_kind_fails_generation_by_name():
    """The K row of the test above. Red when a K slot with no quantity kind is guessed as an absolute temperature
    (or a difference) instead of refusing: K alone cannot say which, and the wrong guess converts 0.3 ΔK to
    -459.13 °F."""
    classes = generate.load_classes(SRC)
    cls = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplyTemperature"
    ci = copy.deepcopy(classes[cls])
    target = next(p for p in ci.params if p.unit == "K")
    target.qkind = None
    with pytest.raises(cxf.CxfError) as e:
        generate.emit_class(ci, dict(classes, **{cls: ci}), _stamp())
    msg = str(e.value)
    assert cls in msg and target.name in msg and "K" in msg, msg


# ---- the MBL 14.0.0 pin ----

def test_every_generated_header_names_the_pinned_mbl():
    # Wrong behavior caught: a generated file, or one class inside it, that still says MBL 12.1.0 after the pins
    # moved, so a reader trusts the wrong reference implementation; or a stamp that moved without its regeneration.
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    assert stamp == {"mbl": "14.0.0", "mblCommit": "ad48324b74e9751e2e49dac5fe3c4dcb546755a2",
                     "modelicaJson": "5460add3b273286157412d8f5992493bd48ab061"}
    want = "MBL 14.0.0 (ad48324b)"
    for rel in generate.generated_files():
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        heads = [l for l in lines if l.startswith("// GENERATED")]
        assert heads and all(want in l for l in heads), (rel, [l for l in heads if want not in l][:3])
    for lib in generate.OPEN_LIBS:
        for f in (LIBS / lib).glob("*"):
            if f.is_file():
                assert "12.1.0" not in f.read_text(encoding="utf-8"), f


def _legal_lines(commit):
    html = subprocess.run(["git", "-C", str(MBL_DIR), "show", commit + ":Buildings/legal.html"],
                          capture_output=True, check=True).stdout.decode("utf-8")
    text = re.sub(r"<[^>]+>", "", html).replace("\r", "")
    return [" ".join(l.split()) for l in text.splitlines() if l.strip()]


@pytest.mark.inputs
def test_every_open_lib_notice_reproduces_mbl_license_at_the_pin():
    # Wrong behavior caught: a NOTICE that keeps 12.1.0's copyright years (1998-2024) or drops a clause of MBL's
    # license, which its first condition requires every redistribution to retain.
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    legal = _legal_lines(stamp["mblCommit"])
    assert "Modelica Buildings Library. Copyright (c) 1998-2026" in legal
    for lib in generate.OPEN_LIBS:
        notice = " ".join((LIBS / lib / "NOTICE").read_text(encoding="utf-8").split())
        missing = [l for l in legal if l not in notice]
        assert missing == [], (lib, missing[:3])
        assert "Modelica Buildings Library %s" % stamp["mbl"] in notice, lib


# ---- modelica-json's json output ----
# CXF drops the type of an enumeration-typed parameter, every Dialog annotation and every __cdl annotation. The
# generator reads them from the json output (mjson.py) and writes cdlEnable, cdlGroup, cdlTab and
# cdlValueInReference. mo_reader.py reads the same annotations from MBL's .mo source with its own parser, so the
# round trip checks the json path against MBL itself.

import mjson  # noqa: E402

AHU_CTRL = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.Controller"


@pytest.mark.inputs
def test_an_untyped_enum_parameter_with_no_default_takes_its_type_from_the_json_output():
    # Wrong behavior caught: venStd, eneStd or ecoHigLimCon (no @type, no isOfDataType, no default in CXF) left out of
    # the generated set, or typed as anything but MBL's enumeration.
    classes = generate.load_classes(SRC)
    assert not [r for r in generate.load_classes.report if "has no data type" in r]
    for cls, par, enum in [
            ("AHUs.MultiZone.VAV.Economizers.Subsequences.Limits.SeparateWithDP", "venStd", "VentilationStandard"),
            ("Generic.AirEconomizerHighLimits", "ecoHigLimCon", "ControlEconomizer")]:
        p = classes[OBC + "ASHRAE.G36." + cls].param(par)
        assert p.dtype == OBC + "ASHRAE.G36.Types." + enum, (cls, par, p.dtype)
        assert classes[p.dtype].kind == "enum"


def test_a_dialog_enable_renders_to_the_text_both_evaluators_parse():
    # Wrong behavior caught: an enable gate rendered with a dropped `not`, a lost parenthesis or a swapped operand,
    # which would show a configurator question that does not apply (or hide one that does).
    tree = {"logical_expression": {"logical_or": [
        {"logical_and": [{"arithmetic_expressions": ["eneStd", OBC + "ASHRAE.G36.Types.EnergyStandard.ASHRAE90_1"],
                          "relation_operator": "=="},
                         {"not": True, "arithmetic_expressions": [{"terms": [{"factors": [{"primary1": [
                             {"simple_expression": {"logical_expression": {"logical_or": [
                                 {"logical_and": [{"arithmetic_expressions": ["a"]}]},
                                 {"logical_and": [{"arithmetic_expressions": ["b"]}]}]}}}]}]}]}]}]},
        {"logical_and": [{"arithmetic_expressions": ["have_frePro"]}]}]}}
    text = mjson.render(tree, "t")
    assert text == "eneStd == %sASHRAE.G36.Types.EnergyStandard.ASHRAE90_1 and not (a or b) or have_frePro" % OBC
    env = {"eneStd": "ASHRAE90_1", "a": False, "b": False, "have_frePro": False}
    item = lambda lit: lit.rsplit(".", 1)[1] if lit.startswith(OBC + "ASHRAE.G36.Types.") else None
    assert cxf.evaluate(text, env, item) is True
    assert cxf.evaluate(text, dict(env, a=True), item) is False


@pytest.mark.parametrize("bad", [
    {"logical_expression": {"logical_or": [{"logical_and": [{"arithmetic_expressions": ["f(x)"]}]}]}},
    {"if_expression": {}},
    {"logical_expression": {"logical_or": [{"logical_and": [{"arithmetic_expressions": ["a", "b"],
                                                             "relation_operator": "+"}]}]}},
])
def test_an_enable_shape_the_reader_does_not_know_refuses_by_name(bad):
    # Wrong behavior caught: a function call, an if-expression or an arithmetic operator rendered as if it were a
    # logical gate, instead of refusing with where it sits.
    with pytest.raises(cxf.CxfError) as e:
        mjson.render(bad, "Some.Class.par")
    assert "Some.Class.par" in str(e.value)


def _loaded_g36_composites():
    classes = generate.load_classes(SRC)
    return classes, sorted(p for p, ci in classes.items() if p.startswith(generate.G36_PREFIX) and ci.kind == "composite")


@pytest.mark.inputs
def test_every_loadable_g36_composite_round_trips_with_its_dialog_annotations():
    # Wrong behavior caught: a Dialog(enable), group, tab or __cdl(ValueInReference) read from the json output that
    # differs from MBL's own .mo (mo_reader reads the annotation text independently), or a G36 composite whose
    # parameters, connectors, instances or connections drift from its source. Emitted in memory, so it covers every
    # class the generator can read, not only the ones the libs carry at this step.
    classes, paths = _loaded_g36_composites()
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    assert len(paths) >= 80, len(paths)
    bad, gated, source_gates = {}, 0, 0
    for cls in paths:
        got = generate.parse_generated("\n".join(generate.emit_class(classes[cls], classes, stamp)), cls)
        want = mo_reader.read((MBL_DIR / (cls.replace(".", "/") + ".mo")).read_text(encoding="utf-8"), cls, MBL_DIR)
        problems = generate.compare(want, got)
        gated += sum(1 for v in got["params"].values() if "enable" in v["dialog"])
        source_gates += sum(1 for v in want["params"].values() if "enable" in v["dialog"])
        if problems:
            bad[cls] = problems[:3]
    assert bad == {}, bad
    # Red when the reader reads no gate at all (a compare that skipped Dialog would pass on an empty both sides).
    assert gated == source_gates and gated > 0, (gated, source_gates)


# ---- units the full G36 set brings ----

def _emit_slot(cls, slot):
    classes = generate.load_classes(SRC)
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    text = "\n".join(generate.emit_class(classes[OBC + "ASHRAE.G36." + cls], classes, stamp))
    return next(l for l in text.splitlines() if l.startswith("  %s: " % slot))


@pytest.mark.inputs
@pytest.mark.parametrize("cls,slot,unit", [
    ("AHUs.MultiZone.VAV.SetPoints.SupplySignals", "kTSup", "1/K"),
    ("TerminalUnits.Reheat.Subsequences.DamperValves", "kVal", "1/K"),
    ("Generic.TimeSuppression", "chaRat", "s/K"),
])
def test_a_unit_with_no_haystack_symbol_keeps_cdl_unit_and_claims_no_canonical_unit(cls, slot, unit):
    # Wrong behavior caught: 1/K or s/K refusing its class, or written as a canonical unit
    # Haystack does not define (fits would then reject every record), or as unitless (a gain on kelvin is not 1).
    line = _emit_slot(cls, slot)
    assert 'cdlUnit:"%s"' % unit in line, line
    assert _meta(line, "unit") is None and not _has_unitless(line), line


@pytest.mark.inputs
@pytest.mark.parametrize("cls,slot,quantity,unit", [
    ("AHUs.SingleZone.VAV.SetPoints.ModeAndSetPoints", "tActCoo_max", "temperature", False),           # displayUnit degC
    ("AHUs.MultiZone.VAV.Economizers.Controller", "delTOutHis", "temperatureDifferential", True),    # displayUnit K
    ("AHUs.MultiZone.VAV.SetPoints.FreezeProtection", "tHys", "temperatureDifferential", True),      # recorded decision
])
def test_a_kelvin_slot_without_a_quantity_takes_mbls_display_unit_or_a_recorded_decision(cls, slot, quantity, unit):
    # Wrong behavior caught: an absolute setpoint written as a difference (300.15 K would convert as a 27 degree
    # rise) or a hysteresis written as an absolute temperature, or an inferred quantity not marked as inferred.
    line = _emit_slot(cls, slot)
    assert _meta(line, "quantity") == (None if unit else quantity) and _meta(line, "unit") is None, line
    assert bool(re.search(r"[<, ]cdlDelta[,>]", line)) == unit, line
    assert re.search(r"[<, ]cdlQuantityInferred[,>]", line), line
    assert _meta(line, "cdlQuantityKind") is None, line           # cdlQuantityKind stays what CXF wrote: nothing


@pytest.mark.inputs
def test_every_kelvin_slot_without_a_quantity_or_display_unit_is_decided():
    # Wrong behavior caught: a new MBL slot of unit K with no quantity and no displayUnit generated by a guess, or a
    # recorded decision for a slot that no longer needs one (the list cannot rot).
    import mjson
    decls = {}
    for f in generate.g36_sources(SRC, "json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        decls[mjson.class_path(d)] = mjson.read(d)
    need = set()
    for f in generate.g36_sources(SRC, "cxf"):
        doc = cxf.Cxf.load(f)
        for nid, n in doc.nodes.items():
            if n.get("@type") not in (cxf.S231 + "Parameter", cxf.S231 + "RealInput", cxf.S231 + "RealOutput"):
                continue
            u = generate._qudt(n, "hasUnit")
            key = None if u is None else (cxf.local(u["@id"]) if "#" in u["@id"] else u["@id"].rsplit("/", 1)[-1])
            if key == "K" and generate._qkind(n) is None:
                cls, name = cxf.local(nid).rsplit(".", 1)
                if decls[cls][name].displayUnit is None:
                    need.add(cxf.local(nid))
    bare = set()   # slots CXF gives neither a unit nor a quantity kind: the only ones a decision may give a unit
    for f in generate.g36_sources(SRC, "cxf"):
        doc = cxf.Cxf.load(f)
        for nid, n in doc.nodes.items():
            if n.get("@type") in (cxf.S231 + "Parameter", cxf.S231 + "RealInput", cxf.S231 + "RealOutput") \
                    and generate._qudt(n, "hasUnit") is None and generate._qkind(n) is None:
                bare.add(cxf.local(nid))
    decided = json.loads((HERE / "quantities.json").read_text(encoding="utf-8"))["decisions"]
    quantity_only = {k for k, v in decided.items() if "unit" not in v}
    with_unit = {k for k, v in decided.items() if "unit" in v}
    assert sorted(need - quantity_only) == [] and sorted(quantity_only - need) == []
    assert len(need) == 89
    # A unit decision (0.7.1) names a slot CXF leaves with no unit and no quantity: 12 at MBL 14.0.0, the single-zone
    # AHU sequences' occupant setpoint adjustments and demand-limit offsets. One on a typed slot has rotted.
    # The economizer enable sequences add four (0.8.0): the protected low cutoffs MBL computes from typed parameters.
    assert sorted(with_unit - bare) == [] and len(with_unit) == 16, sorted(with_unit - bare)
    assert sorted(decided[k]["unit"] for k in with_unit) == ["J/kg"] * 2 + ["K"] * 14
    assert all(v["why"] for v in decided.values())
    assert all(v["quantity"] in generate.XETO_KELVIN for v in decided.values() if v.get("unit", "K") == "K")
    assert not any("quantity" in v for v in decided.values() if v.get("unit", "K") != "K")


@pytest.mark.inputs
def test_an_undecided_kelvin_slot_refuses_its_class_by_name():
    # Wrong behavior caught: a K slot with no quantity, no displayUnit and no recorded decision generated anyway.
    cls = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.FreezeProtection"
    classes = generate.load_classes(SRC)
    decl = type("D", (), {"displayUnit": None})()
    saved = generate.QUANTITY_DECISIONS
    generate.QUANTITY_DECISIONS = {k: v for k, v in saved.items() if k != cls + ".THys"}
    try:
        assert generate.infer_quantity(cls, "THys", "K", None, decl) is None
    finally:
        generate.QUANTITY_DECISIONS = saved
    ci = copy.deepcopy(classes[cls])
    ci.param("THys").qinferred = None
    with pytest.raises(cxf.CxfError) as e:
        generate.emit_class(ci, dict(classes, **{cls: ci}), _stamp())
    assert cls + ".THys" in str(e.value) and "unit K" in str(e.value)


@pytest.mark.inputs
@pytest.mark.parametrize("cls,slot", [
    ("AHUs.SingleZone.VAV.Controller", "cooSetAdj"),                       # RealInput, no unit, no quantity in MBL
    ("AHUs.SingleZone.VAV.SetPoints.ModeAndSetPoints", "incTSetDem_1"),   # parameter, no unit in MBL
])
def test_a_slot_mbl_declares_with_no_unit_takes_a_recorded_unit_and_says_so(cls, slot):
    # Wrong behavior caught: a Δ offset port with no unit at all, which a binder can neither guard nor convert (a
    # side with no quantity converts to nothing), or an inferred unit written as cdlUnit as if CXF had declared it,
    # which the round trip against MBL would then have to accept.
    line = _emit_slot(cls, slot)
    assert _meta(line, "unit") is None and re.search(r"[<, ]cdlDelta[,>]", line), line
    assert _meta(line, "quantity") is None, line
    assert _meta(line, "cdlUnitInferred") == "K" and re.search(r"[<, ]cdlQuantityInferred[,>]", line), line
    assert _meta(line, "cdlUnit") is None and _meta(line, "cdlQuantityKind") is None, line


def test_a_recorded_unit_on_a_slot_cxf_already_types_refuses():
    # Wrong behavior caught: a unit decision outliving an MBL fix and silently overriding the declared unit, or a slot
    # with no decision gaining a unit from nowhere.
    cls = OBC + "ASHRAE.G36.ThermalZones.Setpoints"
    saved = generate.QUANTITY_DECISIONS
    generate.QUANTITY_DECISIONS = dict(saved, **{cls + ".cooSetAdj": {"unit": "K", "quantity": "temperatureDifferential",
                                                                     "why": "planted"}})
    try:
        with pytest.raises(cxf.CxfError) as e:
            generate.infer_unit(cls, "cooSetAdj", "K", "TemperatureDifference")
        assert cls + ".cooSetAdj" in str(e.value) and "already types" in str(e.value)
        assert generate.infer_unit(cls, "heaSetAdj", None, None) is None
    finally:
        generate.QUANTITY_DECISIONS = saved


# ---- input-to-input connects ----

MODULATION = OBC + "ASHRAE.G36.AHUs.SingleZone.VAV.Economizers.Subsequences.Modulation"


@pytest.mark.inputs
def test_an_input_to_input_connect_gives_both_inputs_the_sets_driver():
    # Wrong behavior caught: connect(HeaCoi.u, retDamPos.u) refusing the single-zone Modulation (and the single-zone
    # controllers above it), or HeaCoi.u left undriven, or driven by anything but uTSup.y, the one driver of the set.
    classes = generate.load_classes(SRC)
    ci = classes[MODULATION]
    drivers = {b: a for a, b in ci.edges}
    assert drivers["HeaCoi.u"] == "uTSup.y" and drivers["retDamPos.u"] == "uTSup.y"
    assert not any(a.endswith(".u") and b.endswith(".u") for a, b in ci.edges)


@pytest.mark.inputs
def test_connected_inputs_with_no_driver_refuse_by_name():
    # Wrong behavior caught: two inputs joined to each other and to nothing else emitted with no link, so both read
    # null on every record instead of the generator refusing the class.
    classes = generate.load_classes(SRC)
    ci = copy.deepcopy(classes[MODULATION])
    ci.edges = [(a, b) for a, b in ci.edges if b not in ("HeaCoi.u", "retDamPos.u")] + [("HeaCoi.u", "retDamPos.u")]
    with pytest.raises(cxf.CxfError) as e:
        generate.orient(ci, classes)
    assert "HeaCoi.u" in str(e.value) and "no driver" in str(e.value)


def _got(links):
    return {"params": {}, "inputs": {}, "outputs": {}, "components": {},
            "connects": {frozenset(l) for l in links}, "links": set(links)}


def test_the_round_trip_accepts_an_input_to_input_expansion_and_nothing_else():
    # Wrong behavior caught: a set-only comparison that passes a link moved to another source
    # inside the same set, or an output driven from an input. Pairs compare exactly; only MBL's input-to-input connect
    # may become a link from the common driver to each input. "Nothing else" includes direction: a link that runs
    # against MBL's causality is refused too, pinned by test_the_round_trip_refuses_a_link_that_runs_against_causality.
    ports = {"a.y": "out", "b.u": "in", "c.u": "in", "c.v": "in"}
    want = {"params": {}, "inputs": {}, "outputs": {}, "components": {}, "ports": ports,
            "connects": {frozenset(("a.y", "b.u")), frozenset(("b.u", "c.u"))}}
    assert generate.compare(want, _got({("a.y", "b.u"), ("a.y", "c.u")})) == []
    moved = generate.compare(want, _got({("a.y", "b.u"), ("a.y", "c.v")}))
    assert any("dropped" in x for x in moved) and any("invented" in x for x in moved)
    fan = {"params": {}, "inputs": {}, "outputs": {}, "components": {}, "ports": ports,
           "connects": {frozenset(("a.y", "b.u")), frozenset(("a.y", "c.u"))}}
    chained = generate.compare(fan, _got({("a.y", "b.u"), ("b.u", "c.u")}))       # a chain through b.u
    assert any("both driven and a driver" in x for x in chained) and any("dropped" in x for x in chained)
    # The composite output y driven from the instance input b.u, with every endpoint's causality declared, so the
    # refusal is the direction and the shared endpoint, never "no declared causality".
    want_b, got_b = _class_pair({("a.y", "b.u"), ("b.u", "y")}, outputs=["y"], ports=ports,
                                connects=[("a.y", "b.u"), ("b.u", "y")])
    backwards = generate.compare(want_b, got_b)
    assert any("from b.u" in x for x in backwards) and any("both driven and a driver" in x for x in backwards), backwards
    assert not any("no declared causality" in x for x in backwards), backwards


def _conn(cdl_type="Real"):
    return {"type": cdl_type, "unit": None, "array": False}


def _class_pair(links, inputs=(), outputs=(), ports=None, connects=()):
    """A synthetic (want, got) for compare(): MBL's view with declared causality, and the generated links."""
    want = {"params": {}, "inputs": {n: _conn() for n in inputs}, "outputs": {n: _conn() for n in outputs},
            "components": {}, "connects": {frozenset(c) for c in connects}, "ports": dict(ports or {})}
    got = _got(links)
    for kind, names in (("inputs", inputs), ("outputs", outputs)):
        got[kind] = {n: {"type": "Real", "unit": None, "xeto": generate.CONN_TYPE["Real"]} for n in names}
    return want, got


def test_the_round_trip_refuses_a_link_that_runs_against_causality():
    # Wrong behavior caught: compare() read links as unordered pairs, so a reversed link
    # (b.u -> a.y, an instance input driving an instance output) and an output driving a composite input
    # (y -> u) both returned no problem whenever the endpoint had no other link. A link must run from a composite
    # input or an instance output into a composite output or an instance input, by MBL's declared causality.
    ports = {"a.y": "out", "b.u": "in"}
    want, got = _class_pair({("a.y", "b.u")}, ports=ports, connects=[("a.y", "b.u")])
    assert generate.compare(want, got) == []
    want, got = _class_pair({("b.u", "a.y")}, ports=ports, connects=[("a.y", "b.u")])
    rev = generate.compare(want, got)
    assert any("from b.u" in x for x in rev) and any("into a.y" in x for x in rev), rev
    want, got = _class_pair({("u", "y")}, inputs=["u"], outputs=["y"], connects=[("u", "y")])
    assert generate.compare(want, got) == []
    want, got = _class_pair({("y", "u")}, inputs=["u"], outputs=["y"], connects=[("u", "y")])
    out_in = generate.compare(want, got)
    assert any("from y" in x for x in out_in) and any("into u" in x for x in out_in), out_in


def test_a_link_endpoint_with_no_declared_causality_refuses():
    # Wrong behavior caught: an instance whose class mo_reader could not read (so no port causality) letting every
    # link to it pass unchecked, so a backwards link to that instance passes. The check fails closed instead.
    want, got = _class_pair({("a.y", "c.u")}, ports={"a.y": "out"}, connects=[("a.y", "c.u")])
    assert any("no declared causality for c.u" in x for x in generate.compare(want, got))


@pytest.mark.inputs
def test_per_instance_connector_units_reach_the_spec_and_the_round_trip_checks_them():
    # Wrong behavior caught: MBL's conErr(u1(final unit="Pa"), ...) dropped, which leaves a
    # polymorphic block untyped where MBL typed it, while the round trip agreed because mo_reader skipped it too.
    text = (LIBS / "kw.cdl.g36.ahu/g36.xeto").read_text(encoding="utf-8")
    body = _spec_lines(text, "AhusMultiZoneVavSetPointsReliefDamper")
    line = next(l for l in body if l.startswith("  conErr: "))
    assert 'cdlConnUnits:{u1:"Pa", u2:"Pa", y:"Pa"}' in line, line
    cls = OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.ReliefDamper"
    want = mo_reader.read((MBL_DIR / (cls.replace(".", "/") + ".mo")).read_text(encoding="utf-8"), cls, MBL_DIR)
    assert want["components"]["conErr"]["units"] == {"u1": "Pa", "u2": "Pa", "y": "Pa"}
    got = generate.read_generated(ROOT, cls)
    got["components"]["conErr"]["units"] = {}
    assert any("connector units" in x for x in generate.compare(want, got))


@pytest.mark.parametrize("text", ['"a b"', "f(x)", "a + b", "a[1]"])
def test_a_plain_enable_text_outside_the_grammar_refuses(text):
    # Wrong behavior caught: an enable that modelica-json writes as a plain string passed
    # through unchecked, however it reads.
    with pytest.raises(cxf.CxfError):
        mjson.render(text, "X.p")
    assert mjson.render("not have_hol and a == B.C.D", "X.p") == "not have_hol and a == B.C.D"


# ---- the G36 packages of constants ----

G36_TYPES = MBL_DIR / "Buildings/Controls/OBC/ASHRAE/G36/Types"


@pytest.mark.inputs
def test_every_g36_constants_package_is_generated_and_equals_mbl_source():
    # Wrong behavior caught: a G36 package of constants left ungenerated (a binding naming
    # Types.DemandLimitLevels.cooling1 would then refuse at expansion on a project), or a constant generated with the
    # wrong value. The reference is each package.mo, read by a regex that shares nothing with the json reader.
    pkgs = sorted(d.name for d in G36_TYPES.iterdir() if (d / "package.mo").exists())
    assert pkgs == ["DemandLimitLevels", "FreezeProtectionStages", "OperationModes", "ZoneStates"]
    consts = generate.load_constants(SRC)
    text = (LIBS / "kw.cdl.g36.common/g36.xeto").read_text(encoding="utf-8")
    for name in pkgs:
        src = (G36_TYPES / name / "package.mo").read_text(encoding="utf-8")
        want = {n: float(v) for n, v in re.findall(r"constant\s+Integer\s+(\w+)\s*=\s*(-?\d+)", src)}
        assert want, name
        got = consts[OBC + "ASHRAE.G36.Types." + name]
        assert got["type"] == "Integer" and {n: v for n, (v, _) in got["items"].items()} == want, name
        block = text[text.index("@types%s: kw.cdl::CdlConstants {" % name):]
        block = block[:block.index("\n}\n")]
        for n, v in want.items():
            assert re.search(r"\n    %s: Number \"%d\"" % (n, v), block), (name, n)


# ---- full generation, MBL 14.0.0 ----

@pytest.mark.inputs
def test_every_g36_class_outside_plants_is_generated_into_its_lib_with_zero_refusals():
    # Wrong behavior caught: a G36 class left out of the libs (zero refusals: the report holds only the
    # CDL.Constants rule), a class in the wrong lib, or a lib whose size drifts from the measured split (common 24,
    # ahu 38 + 4 FanCoilUnits, terminal 60).
    generate.load_classes(SRC)
    assert [r for r in generate.load_classes.report if "CDL.Constants" not in r] == []
    g36 = MBL_DIR / "Buildings/Controls/OBC/ASHRAE/G36"
    want = sorted(OBC + "ASHRAE.G36." + f.relative_to(g36).with_suffix("").as_posix().replace("/", ".")
                  for f in g36.rglob("*.mo") if f.name != "package.mo"
                  and not {"Validation", "Plants"} & set(f.relative_to(g36).parts))
    assert len(want) == 126
    got = _g36_generated("enum") + _g36_generated("composite")
    assert sorted(got) == want
    sizes = {lib: len(re.findall(r'(?m)^[A-Z]\w*: \S+ <cdlClass:', (LIBS / lib / "g36.xeto").read_text(encoding="utf-8")))
             for lib in generate.G36_LIBS}
    assert sizes == {"kw.cdl.g36.common": 24, "kw.cdl.g36.ahu": 42, "kw.cdl.g36.terminal": 60}, sizes
    for cls in got:
        rel = generate.g36_lib(cls)
        assert ('cdlClass:"%s"' % cls) in (LIBS / rel / "g36.xeto").read_text(encoding="utf-8"), cls
    assert any(c.startswith(OBC + "ASHRAE.G36.FanCoilUnits.") for c in got if generate.g36_lib(c) == "kw.cdl.g36.ahu")


def test_thys_is_thys_in_the_generated_ahu_specs():
    # Wrong behavior caught: the AHU hysteresis parameter still spelled Thys (MBL 12.1.0) after the move to 14.0.0
    # (MBL issue 4374), so a 14.0.0 design's THys modifier would bind to nothing.
    text = (LIBS / "kw.cdl.g36.ahu/g36.xeto").read_text(encoding="utf-8")
    assert 'cdlName:"Thys"' not in text and not re.search(r"\bThys\b", text)
    for spec in ("AhusMultiZoneVavController", "AhusMultiZoneVavSetPointsFreezeProtection",
                 "AhusMultiZoneVavSetPointsPlantRequests"):
        assert any('cdlName:"THys"' in l for l in _spec_lines(text, spec)), spec


@pytest.mark.inputs
@pytest.mark.parametrize("cls", _g36_generated("enum"))
def test_every_g36_enumeration_equals_mbl_source(cls):
    # Wrong behavior caught: an enumeration item dropped, renamed or invented between MBL's .mo and the generated Enum,
    # read by a regex that shares nothing with the CXF reader.
    src = (MBL_DIR / (cls.replace(".", "/") + ".mo")).read_text(encoding="utf-8")
    src = re.sub(r'"(?:[^"\\]|\\.)*"', "", src)                 # descriptions, which may hold parentheses
    start = re.search(r"enumeration\s*\(", src).end()
    depth, i = 1, start
    while depth:
        depth += {"(": 1, ")": -1}.get(src[i], 0)
        i += 1
    body = src[start:i - 1]
    want = sorted(re.findall(r"([A-Za-z_]\w*)\s*(?=,|$)", re.sub(r"\s+", " ", body).strip()))
    text = g36_text()
    head = re.search(r'(?m)^(\w+): Enum <cdlClass:"%s">' % re.escape(cls), text).group(1)
    got = sorted(re.findall(r'<key:"([^"]+)">', "\n".join(_spec_lines(text, head))))
    assert got == want, (cls, got, want)


# Parameter bounds (kw.cdl 0.6.0). The configurator validates a design's answers with `xeto fits`, which enforces
# minVal and maxVal, so a bound the generator drops is a value
# nobody checks. These tests read a fresh regeneration; test_byte_stable_regeneration ties it to the checked-in files.
@pytest.fixture(scope="module")
def bounds_regen(tmp_path_factory, mbl_cdl):
    out = tmp_path_factory.mktemp("bounds") / "out"
    generate.main(["--out", str(out), "--no-fetch"])
    return out


def _class_bounds(text, spec):
    """{slot: {meta key: value}} from the `bounds` field of @cdl-<spec> in a classes.xeto text."""
    m = re.search(r"^@cdl-%s: CdlClass \{\n(.*?)^\}" % re.escape(spec), text, re.M | re.S)
    assert m is not None, "no CdlClass instance " + spec
    b = re.search(r"^  bounds: \{(.*)\}$", m.group(1), re.M)
    if b is None:
        return {}
    return {k: dict(re.findall(r'(\w+):"([^"]*)"', v)) for k, v in re.findall(r"(\w+):\{([^{}]*)\}", b.group(1))}


def _slot_meta(root, rel, spec, slot):
    """The meta dict of one slot of one top-level spec, read with the round trip's own meta parser. For
    kw.cdl/classes.xeto, the bounds of one parameter or connector of a class's CdlClass instance."""
    if rel == "kw.cdl/classes.xeto":
        return _class_bounds((root / generate.LIBS / rel).read_text(encoding="utf-8"), spec).get(slot, {})
    line = next((l for l in _spec_lines((root / generate.LIBS / rel).read_text(encoding="utf-8"), spec) if l.startswith("  %s: " % slot)),
                None)
    assert line is not None, "%s.%s not found in %s" % (spec, slot, rel)
    return generate._meta(line[line.index("<"):])[0]


def _mbl_cdl_constants():
    """eps and small from MBL's own CDL/Constants.mo, read by regex: nothing here shares the CXF reader."""
    src = (MBL_DIR / "Buildings/Controls/OBC/CDL/Constants.mo").read_text(encoding="utf-8")
    return {n: float(re.search(r"constant\s+Real\s+%s\s*=\s*([-+0-9.eE]+)" % n, src).group(1)) for n in ("eps", "small")}


@pytest.mark.inputs
@pytest.mark.parametrize("rel,spec,slot,key,num,src_key,src", [
    ("kw.cdl/classes.xeto", "RealsPidWithReset", "k", "minVal", "1e-13", "cdlMinConst", "100*Constants.eps"),
    ("kw.cdl/classes.xeto", "RealsPid", "ti", "minVal", "1e-13", "cdlMinConst", "100*Constants.eps"),
    ("kw.cdl/classes.xeto", "RealsLimitSlewRate", "td", "minVal", "1e-15", "cdlMinConst", "Constants.eps"),
    ("kw.cdl/blocks.xeto", "RealsSourcesPulse", "period", "minVal", "1e-37", "cdlMinConst", "Constants.small"),
    ("kw.cdl/classes.xeto", "RealsLimitSlewRate", "fallingSlewRate", "maxVal", "-1e-37", "cdlMaxConst", "-Constants.small"),
    # A connector bound takes the same resolution and keeps the connector's own meta names.
    ("kw.cdl/classes.xeto", "RealsDerivative", "t", "cdlMin", "1e-13", "cdlMinConst",
     "100*Buildings.Controls.OBC.CDL.Constants.eps"),
    # CalendarTime's yearRef bounds (firstYear, lastYear) left with the class, which is refused by name.
])
def test_a_bound_written_with_a_cdl_constant_emits_its_number(bounds_regen, rel, spec, slot, key, num, src_key, src):
    # Wrong behavior caught: a bound MBL writes with Constants.eps, Constants.small or a class constant (firstYear)
    # dropped because the generator evaluated it with an empty environment (_num_or_none before 0.6.0), so fits
    # accepts k = -1 on a PID. Also caught: the number emitted without the expression it came from. An elementary
    # class that runs as a comp keeps its bounds on its CdlClass instance.
    meta = _slot_meta(bounds_regen, rel, spec, slot)
    assert meta.get(key) == num, (spec, slot, meta)
    assert meta.get(src_key) == src, (spec, slot, meta)


@pytest.mark.inputs
def test_every_constant_bound_equals_the_value_mbl_source_gives():
    # Wrong behavior caught: a constant resolved to the wrong number (a stale eps, small taken as 1E-60, lastYear
    # without its +21), or a constant-written bound that still reaches no minVal/maxVal. The values come from MBL's
    # .mo text by regex, and the expression from the emitted provenance meta, so the check does not share the
    # generator's constant table.
    consts = _mbl_cdl_constants()
    cal = (MBL_DIR / "Buildings/Controls/OBC/CDL/Reals/Sources/CalendarTime.mo").read_text(encoding="utf-8")
    first = int(re.search(r"constant\s+Integer\s+firstYear\s*=\s*(\d+)", cal).group(1))
    last = first + int(re.search(r"constant\s+Integer\s+lastYear\s*=\s*firstYear\s*\+\s*(\d+)", cal).group(1))
    env = {"Constants.eps": consts["eps"], "Buildings.Controls.OBC.CDL.Constants.eps": consts["eps"],
           "Constants.small": consts["small"], "firstYear": first, "lastYear": last}
    text = (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8")
    classes_text = (LIBS / "kw.cdl/classes.xeto").read_text(encoding="utf-8")
    metas = [generate._meta(l[l.index("<"):])[0] for l in text.splitlines() if SLOT_LINE.match(l)]
    for spec in re.findall(r"(?m)^@cdl-(\w+): CdlClass \{", classes_text):
        for b in _class_bounds(classes_text, spec).values():
            metas.append(dict(b, **({"cdlParam": True} if "minVal" in b or "maxVal" in b else {})))
    seen = {"param": 0, "conn": 0}
    for meta in metas:
        for src_key, keys in (("cdlMinConst", ("minVal", "cdlMin")), ("cdlMaxConst", ("maxVal", "cdlMax"))):
            if src_key not in meta:
                continue
            expr = meta[src_key]
            for name in sorted(env, key=len, reverse=True):
                expr = expr.replace(name, repr(float(env[name])))
            assert re.fullmatch(r"[-+*/0-9.eE() ]+", expr), meta[src_key]
            want = float(eval(expr, {"__builtins__": {}}))   # digits and operators only (fullmatch above)
            key = keys[0] if "cdlParam" in meta else keys[1]
            assert float(meta[key]) == want, (meta, want)
            seen["param" if "cdlParam" in meta else "conn"] += 1
    # 29 parameter bounds in kw.cdl are written with a constant; one connector
    # bound (Derivative.T) is too. Since 0.8.0 they ride the kw.cdl specs and the CdlClass instances, and the three
    # on refused classes left with them (CalendarTime's yearRef min and max, Sources.Ramp's duration).
    assert seen == {"param": 26, "conn": 1}, seen


@pytest.mark.inputs
def test_a_bound_naming_nothing_the_class_or_cdl_defines_refuses():
    # Wrong behavior caught: a bound expression that resolves to nothing (a constant MBL renamed, a typo in a pinned
    # CXF) dropped silently, which is how 29 bounds went missing before 0.6.0.
    doc = cxf.Cxf(json.loads((SRC / "kw.cdl/cdl-elementary.jsonld").read_text(encoding="utf-8")))
    cls = OBC + "CDL.Reals.LimitSlewRate"
    cid = next(k for k in doc.nodes if cxf.local(k) == cls)
    kid = next(k for k in doc.nodes if cxf.local(k) == cls + ".raisingSlewRate")
    doc.nodes[kid][cxf.S231 + "min"] = "100*Constants.nope"
    generate.load_classes(SRC)
    with pytest.raises(cxf.CxfError, match="Constants.nope"):
        generate.read_class(doc, cid, set(), set())


def _toy(path, kind, params=(), insts=()):
    """A hand-built ClassInfo for the propagation tests: params as (name, min, max, unit), insts as (name, class,
    {param: CDL expression}, guard)."""
    ci = generate.ClassInfo(path, kind, "")
    for name, lo, hi, unit in params:
        p = generate.Param(name, "Real", 0.0, None, unit, None, False, False, "", lo, hi)
        p.size, p.constant = None, False
        ci.params.append(p)
    for name, cls, binds, cond in insts:
        ci.insts.append(generate.Inst(name, cls, {k: (None, v) for k, v in binds.items()}, cond, ""))
    return ci


def _toys(own_x=None):
    # A.x binds into B1.h (min 0) and B2.k (min 0.1); A.y into B2.u (max 5); A.z binds into B2.k through 2*z.
    return {"B1": _toy("B1", "elementary", [("h", 0.0, None, None)]),
            "B2": _toy("B2", "elementary", [("k", 0.1, None, None), ("u", None, 5.0, None)]),
            "A": _toy("A", "composite", [("x", own_x, None, None), ("y", None, None, None), ("z", None, None, None)],
                      [("b1", "B1", {"h": "x"}, None), ("b2", "B2", {"k": "x", "u": "y"}, None),
                       ("b3", "B2", {"k": "2*z"}, None)])}


def test_two_paths_that_disagree_take_the_tighter_bound_and_say_so():
    # Wrong behavior caught: the looser of two downstream bounds kept (x = 0.05 would fit though B2.k refuses it),
    # the choice made silently, or a bound invented for a parameter that reaches its block through an expression.
    classes = _toys()
    report = generate.propagate_bounds(classes)
    x, y, z = (classes["A"].param(n) for n in "xyz")
    assert (x.vmin, x.min_via) == (0.1, "b2.k")
    assert (y.vmax, y.max_via) == (5.0, "b2.u") and y.vmin is None
    assert z.vmin is None and z.min_via is None
    assert any(l.startswith("A.x min") and "b1.h" in l and "b2.k" in l for l in report["disagree"]), report
    assert any("b3.k" in l and "2*z" in l for l in report["expression"]), report


def test_an_own_bound_tighter_than_every_path_is_kept_and_the_disagreement_recorded():
    # Wrong behavior caught: a parameter's own, tighter bound loosened by a block it feeds, or replaced silently.
    classes = _toys(own_x=0.5)
    report = generate.propagate_bounds(classes)
    x = classes["A"].param("x")
    assert (x.vmin, x.min_via) == (0.5, None)
    assert any(l.startswith("A.x min") for l in report["disagree"]), report


def test_a_bound_reaches_through_nested_composites_with_its_full_path():
    # Wrong behavior caught: propagation that stops one level down, so a root parameter feeding a PID inside a child
    # composite stays unbounded (the multizone AHU's kVal), or a path that names only the last hop.
    classes = _toys()
    classes["R"] = _toy("R", "composite", [("kVal", None, None, None)], [("sub", "A", {"x": "kVal"}, None)])
    generate.propagate_bounds(classes)
    p = classes["R"].param("kVal")
    assert (p.vmin, p.min_via) == (0.1, "sub.b2.k")


def test_an_own_bound_looser_than_a_path_is_intersected_and_both_sources_kept():
    # Wrong behavior caught: an own MBL bound that lets through a value the block it feeds refuses (SupplyFan.Td
    # declares min=0 and feeds a PID whose Td has min=100*Constants.eps, so Td = 0 is no valid answer), or the
    # tightened number emitted with no trace of MBL's own value.
    classes = _toys(own_x=0.05)
    report = generate.propagate_bounds(classes)
    x = classes["A"].param("x")
    assert (x.vmin, x.min_via, x.min_own) == (0.1, "b2.k", 0.05)
    assert any(l.startswith("A.x min: own 0.05 tightened to 0.1") and "b2.k" in l for l in report["tightened"]), report


@pytest.mark.inputs
def test_supply_fan_td_takes_the_pid_min_and_records_mbls_own(bounds_regen):
    # Wrong behavior caught: the real case of the test above, SupplyFan.Td emitted as MBL's 0 so fits accepts Td = 0.
    meta = _slot_meta(bounds_regen, "kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavSetPointsSupplyFan", "td")
    assert (meta.get("minVal"), meta.get("cdlMinVia"), meta.get("cdlMinOwn")) == ("1e-13", "conSpe.td", "0"), meta


def _guarded_toys(default=None):
    # A.w reaches B2.k (min 0.1) only through b4, which exists when have_x; A.have_x is a parameter of A.
    classes = _toys()
    a = classes["A"]
    w = generate.Param("w", "Real", default, None, None, None, False, False, "")
    w.size, w.constant = None, False
    hx = generate.Param("have_x", "Boolean", False, None, None, None, False, False, "")
    hx.size, hx.constant = None, False
    a.params += [w, hx]
    a.insts.append(generate.Inst("b4", "B2", {"k": (None, "w")}, "have_x", ""))
    return classes


def test_a_bound_only_a_guarded_instance_imposes_is_conditional_meta_not_min_val():
    # Wrong behavior caught: a guarded instance's bound emitted as a hard minVal, which refuses a value the design
    # never uses when the guard removes the instance.
    classes = _guarded_toys()
    report = generate.propagate_bounds(classes)
    w = classes["A"].param("w")
    assert w.vmin is None and w.min_via is None
    assert w.min_when == [{"val": 0.1, "cond": "have_x", "via": "b4.k"}]
    line = "\n".join(generate.emit_param(w, "w", classes, "A"))
    assert "minVal" not in line, line
    assert 'cdlMinWhen:List {CdlBoundWhen {val:Number "0.1", cond:"have_x", via:"b4.k"}}' in line, line
    assert any(l.startswith("A.w min") for l in report["conditional"]), report


def test_a_guard_inside_a_child_is_lifted_to_the_root_through_its_bindings():
    # Wrong behavior caught: a condition emitted in a child's names (have_x), which the root's answers cannot
    # evaluate, instead of the root parameter the child's have_x is bound to.
    classes = _guarded_toys()
    classes["R"] = _toy("R", "composite", [("wRoot", None, None, None), ("useX", None, None, None)],
                        [("sub", "A", {"w": "wRoot", "have_x": "useX"}, None)])
    generate.propagate_bounds(classes)
    p = classes["R"].param("wRoot")
    assert p.vmin is None and p.min_when == [{"val": 0.1, "cond": "useX", "via": "sub.b4.k"}]


def test_a_default_that_breaks_a_guarded_bound_still_fits_when_the_instance_is_absent():
    # Wrong behavior caught: a G36 default (here 0) that violates a bound only a guarded instance imposes made a hard
    # minVal, so the unmodified design fails fits. The slot carries the default and no minVal; the guarded bound
    # rides cdlMinWhen. (MBL 14.0.0 has no such default among the 104 guarded bounds with a literal default.)
    classes = _guarded_toys(default=0.0)
    generate.propagate_bounds(classes)
    line = "\n".join(generate.emit_param(classes["A"].param("w"), "w", classes, "A"))
    assert line.endswith('> "0"') and "minVal" not in line and "cdlMinWhen" in line, line


@pytest.mark.inputs
def test_the_multizone_root_carries_tddp_as_a_conditional_bound(bounds_regen):
    # Wrong behavior caught: TdDp, used only by the separate-damper-with-DP economizer section, made a hard minVal.
    meta = _slot_meta(bounds_regen, "kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavController", "tdDp")
    assert "minVal" not in meta, meta
    when = meta["cdlMinWhen"]
    assert len(when) == 1 and when[0]["val"] == "1e-13" and "minOADes" in when[0]["cond"], meta


def test_a_unit_mismatch_across_a_binding_is_carried_and_named():
    # Wrong behavior caught: MBL's own unit mismatch across a binding (the multizone AHU's kVal is declared "1" and
    # feeds kTSup, declared "1/K") either blocking the bound, which leaves kVal = -1 fitting, or passing unnamed.
    # Modelica passes the number through a binding unconverted, so the bound holds on the number.
    classes = _toys()
    classes["A"].param("x").unit = "1"
    classes["B2"].param("k").unit = "1/K"
    report = generate.propagate_bounds(classes)
    x = classes["A"].param("x")
    assert (x.vmin, x.min_via) == (0.1, "b2.k")
    assert any("A.x" in l and "b2.k" in l for l in report["unit"]), report


@pytest.mark.inputs
@pytest.mark.parametrize("slot,key,num,via_key,via", [
    ("kVal", "minVal", "1e-13", "cdlMinVia", "supSig.conTSup.k"),
    # frePro exists only with have_frePro, so not hard. THys is a K difference (inferred through the bindings), so
    # its bound is the SI one a resolver checks, not a minVal fits would compare with a converted value
    ("tHys", "cdlSiMin", "0K", "cdlMinVia", "plaReq.greThr.h"),
])
def test_the_multizone_ahu_root_takes_the_bounds_of_the_blocks_it_feeds(bounds_regen, slot, key, num, via_key, via):
    # Wrong behavior caught: the multizone AHU controller's kVal unbounded at the root, so fits accepts kVal = -1
    # although MBL's PIDWithReset.k declares min=100*Constants.eps.
    meta = _slot_meta(bounds_regen, "kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavController", slot)
    assert meta.get(key) == num, meta
    assert meta.get(via_key) == via, meta


@pytest.mark.inputs
@pytest.mark.parametrize("rel,spec,slot,lo,hi", [
    ("kw.cdl.g36.ahu/g36.xeto", "AhusSingleZoneVavEconomizersController", "outDamMinFloMinSpe", "outDamPhy_min",
     "outDamPhy_max"),
    ("kw.cdl.g36.ahu/g36.xeto", "AhusSingleZoneVavEconomizersSubsequencesLimits", "outDamDesFloMaxSpe",
     "outDamMinFloMaxSpe", "outDamPhy_max"),
    ("kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavEconomizersSubsequencesLimitsCommon", "uRetDam_min", "yMin", "yMax"),
    ("kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavSetPointsSupplyFan", "iniSpe", "minSpe", None),
    ("kw.cdl/classes.xeto", "IntegersStage", "h", "0.001/n", "0.5/n"),
])
def test_a_parameter_referencing_bound_emits_its_expression(bounds_regen, rel, spec, slot, lo, hi):
    # Wrong behavior caught: a bound MBL writes as another parameter (min=outDamPhy_min) dropped with no trace, as the
    # generator did before 0.6.0, or turned into a number it cannot have. The configurator evaluates the expression.
    meta = _slot_meta(bounds_regen, rel, spec, slot)
    assert meta.get("cdlMinExpr") == lo, meta
    assert meta.get("cdlMaxExpr") == hi, meta
    for key, expr in (("minVal", lo), ("maxVal", hi)):
        if expr is not None and key in meta:
            # A number may sit beside the expression only when it came from elsewhere (a propagated bound).
            assert ("cdlMinVia" if key == "minVal" else "cdlMaxVia") in meta, meta


@pytest.mark.inputs
def test_every_parameter_bound_in_the_cxf_reaches_the_spec_as_a_number_or_an_expression(bounds_regen):
    # Wrong behavior caught: any parameter bound MBL declares and CXF carries that reaches neither minVal/maxVal nor
    # cdlMinExpr/cdlMaxExpr: the silent drop before 0.6.0, in any form a later generator change might reintroduce.
    classes = generate.load_classes(SRC)
    texts = {rel[len(generate.LIBS) + 1:]: (bounds_regen / rel).read_text(encoding="utf-8") for rel in generate.generated_files()}
    missing, exprs = [], 0
    for path, ci in sorted(classes.items()):
        if ci.kind == "enum":
            continue
        rel = "kw.cdl/blocks.xeto" if path.startswith(generate.CDL_PREFIX) else generate.g36_lib(path) + "/g36.xeto"
        names = generate.slot_names([p.name for p in ci.params] + [c.name for c in ci.conns] +
                                    [i.name for i in ci.insts], path)
        on_class = 'cdlClass:"%s"' % path not in texts[rel]
        if on_class and ('  cdlClass: "%s"\n' % path) in texts["kw.cdl/classes.xeto"]:
            # an elementary class that runs as a comp: its bounds ride its CdlClass instance
            bounds = _class_bounds(texts["kw.cdl/classes.xeto"], generate.spec_name(path, generate.CDL_PREFIX))
        elif on_class:
            continue                                  # not emitted (CDL Types, Validation, refused): no spec anyone fits
        else:
            lines = _spec_lines(texts[rel], re.search(r'(?m)^(\w+): \S+ <cdlClass:"%s"' % re.escape(path),
                                                      texts[rel]).group(1))
        for p in ci.params:
            raw = getattr(p, "raw_bounds", (None, None))
            if on_class:
                meta = bounds.get(generate.lower(p.name), {})
            else:
                line = next(l for l in lines if l.startswith("  %s: " % names[p.name]))
                meta = generate._meta(line[line.index("<"):])[0]
            for side, r in zip(("min", "max"), raw):
                if r is None:
                    continue
                num, expr = side + "Val", "cdl%sExpr" % side.capitalize()
                if expr in meta:
                    exprs += 1
                elif num not in meta and "cdlSi" + side.capitalize() not in meta:
                    missing.append("%s.%s %s" % (path, p.name, side))
    assert missing == [], missing
    # 19 G36 bounds on 10 parameters name a parameter; kw.cdl adds Stage.h's 0.001/n and 0.5/n.
    assert exprs == 21, exprs


@pytest.mark.inputs
def test_the_report_names_every_expression_bound_and_every_connector_bound_not_emitted(bounds_regen):
    # Wrong behavior caught: an expression bound emitted as meta but absent from the report a reviewer reads, or a
    # connector bound that names a parameter (Stage.y max=n) dropped with no line anywhere.
    rep = (bounds_regen / generate.BOUNDS_REPORT).read_text(encoding="utf-8")
    sec = lambda title: re.search(r"(?ms)^## %s: (\d+)\n(.*?)(?=^## |\Z)" % re.escape(title), rep)
    params = sec(dict(generate.REPORT_SECTIONS)["param-expr"])
    assert params and int(params.group(1)) == 21, rep
    assert "Buildings.Controls.OBC.CDL.Integers.Stage.h min = 0.001/n" in params.group(2)
    assert "Buildings.Controls.OBC.ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplyFan.iniSpe min = minSpe" in params.group(2)
    conns = sec(dict(generate.REPORT_SECTIONS)["conn-expr"])
    assert conns and int(conns.group(1)) == 39, rep
    assert "Buildings.Controls.OBC.CDL.Integers.Stage.y max = n" in conns.group(2)


def _flag(name):
    p = generate.Param(name, "Boolean", False, None, None, None, False, False, "")
    p.size, p.constant = None, False
    return p


def test_guards_that_cover_every_configuration_give_a_hard_bound():
    # Wrong behavior caught: q feeds a PID through b5 when flag and through b6 when not flag, so the
    # bound holds in every configuration, yet it went out as cdlMinWhen and fits never checked it (DualDuctSnapActing's
    # kDam = -1 fit for both values of have_duaSen).
    classes = _toys()
    a = classes["A"]
    q = generate.Param("q", "Real", 1.0, None, None, None, False, False, "")
    q.size, q.constant = None, False
    a.params += [q, _flag("flag")]
    a.insts += [generate.Inst("b5", "B2", {"k": (None, "q")}, "flag", ""),
                generate.Inst("b6", "B2", {"k": (None, "q")}, "not flag", "")]
    report = generate.propagate_bounds(classes)
    assert (q.vmin, q.min_via, q.min_when) == (0.1, "b5.k", None)
    assert any(l.startswith("A.q min 0.1") for l in report["tautology"]), report


def test_a_weaker_guarded_bound_under_another_condition_is_kept():
    # Wrong behavior caught: only the tightest guarded bound emitted, so r's min 0 under f2 is lost
    # whenever f1 is false.
    classes = _toys()
    a = classes["A"]
    r = generate.Param("r", "Real", 1.0, None, None, None, False, False, "")
    r.size, r.constant = None, False
    a.params += [r, _flag("f1"), _flag("f2")]
    a.insts += [generate.Inst("b7", "B2", {"k": (None, "r")}, "f1", ""),
                generate.Inst("b8", "B1", {"h": (None, "r")}, "f2", "")]
    generate.propagate_bounds(classes)
    assert r.vmin is None
    assert r.min_when == [{"val": 0.1, "cond": "f1", "via": "b7.k"}, {"val": 0.0, "cond": "f2", "via": "b8.h"}]


@pytest.mark.inputs
@pytest.mark.parametrize("rel,spec,slot,key,num", [
    ("kw.cdl.g36.terminal/g36.xeto", "TerminalUnitsDualDuctSnapActingController", "kDam", "minVal", "1e-13"),
    ("kw.cdl.g36.terminal/g36.xeto", "TerminalUnitsDualDuctSnapActingController", "tiDam", "minVal", "1e-13"),
    ("kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavController", "uCooMin", "minVal", "0"),
    ("kw.cdl.g36.ahu/g36.xeto", "AhusMultiZoneVavController", "uHeaMax", "maxVal", "0"),
])
def test_the_seven_always_holding_guarded_bounds_are_hard(bounds_regen, rel, spec, slot, key, num):
    # Wrong behavior caught: the real cases of test_guards_that_cover_every_configuration_give_a_hard_bound
    # emitted as cdlMinWhen/cdlMaxWhen only.
    meta = _slot_meta(bounds_regen, rel, spec, slot)
    assert meta.get(key) == num, meta
    assert ("cdlMinWhen" if key == "minVal" else "cdlMaxWhen") not in meta, meta


# ---- CDL arrays and MultiSum ----

def _no_enum(lit):
    return None


@pytest.mark.parametrize("src,env,want", [
    ("fill(1, nin)", {"nin": 3.0}, [1.0, 1.0, 1.0]),
    ("fill(2,nZon)", {"nZon": 2.0}, [2.0, 2.0]),
    ("fill(true, 2)", {}, [True, True]),
    ("fill(1.5, 0)", {}, []),
    ("fill(a + 1, n * 2)", {"a": 1.0, "n": 1.0}, [2.0, 2.0]),
    ("size(k, 1)", {"k": [1.0, 2.0, 3.0]}, 3.0),
    ("size(k,1) + 1", {"k": [1.0]}, 2.0),
    ("gai", {"gai": [1.0, 2.0]}, [1.0, 2.0]),
])
def test_fill_and_size_evaluate(src, env, want):
    """Red when fill or size is still refused as a function call, when fill returns a scalar or the wrong count,
    or when size returns anything but the list's length as a float."""
    got = cxf.evaluate(src, env, _no_enum)
    assert got == want and type(got) is type(want)


@pytest.mark.parametrize("src,env", [
    ("fill(1, 2.5)", {}),                 # n not whole
    ("fill(1, -1)", {}),                  # n negative
    ("fill(k, 2)", {"k": [1.0]}),         # v a list
    ("fill(1)", {}),                      # one argument
    ("fill(1, true)", {}),                # n a Boolean
    ("size(k)", {"k": [1.0]}),            # one argument
    ("size(k, 2)", {"k": [1.0]}),         # dimension other than 1
    ("size(n, 1)", {"n": 2.0}),           # not a list
    ("size(fill(1, 2), 1)", {}),          # not a name
    ("max(a, b)", {"a": 1.0, "b": 2.0}),  # any other function
    ("k + 1", {"k": [1.0]}),              # a list in arithmetic
    ("-k", {"k": [1.0]}),
    ("k > 1", {"k": [1.0]}),              # a list in a comparison
    ("k == k", {"k": [1.0]}),
    ("not k", {"k": [True]}),             # a list in logic
    ("k and true", {"k": [True]}),
    ("k[1]", {"k": [1.0]}),               # subscripts refuse
    ("{{{1}}}", {}),                      # an array literal nested past two dimensions
])
def test_fill_and_size_refuse_what_they_must(src, env):
    """Red when the evaluator accepts a malformed fill or size, another function, a list where a number or a
    Boolean is needed, a subscript or a literal nested past two dimensions, or refuses without quoting the
    expression."""
    with pytest.raises(cxf.CxfError) as e:
        cxf.evaluate(src, env, _no_enum)
    assert repr(src) in str(e.value) or src in str(e.value)


def test_local_decodes_percent_encoded_brackets():
    """Red when an element endpoint keeps %5B and %5D, so u[3] never matches the connector u."""
    assert cxf.local("http://example.org#Example.ArrSum.intSum.u%5B1%5D") == "Example.ArrSum.intSum.u[1]"
    assert cxf.local("http://example.org#A.b") == "A.b"


_ALL_CLASSES = []


def _all_classes():
    if not _ALL_CLASSES:
        _ALL_CLASSES.append(generate.load_classes(SRC))
    return dict(_ALL_CLASSES[0])


# ---- reading array CXF, on a fixture ----
# testdata/arrays holds the CXF modelica-json 5460add3 wrote for two small Modelica models kW Engineering wrote to
# exercise CDL arrays; the models themselves are not kept. ArrSum declares an array parameter, an array input, two
# vectorized instances and two MultiSums, one fed by indexed connects; ArrWrap instantiates it and drives
# seq.TZon[k] element by element. They name CDL classes only, and carry no MBL model or value.
ARRAYS = HERE / "testdata" / "arrays"


def _probe_docs():
    return {f.name: json.loads(f.read_text(encoding="utf-8")) for f in sorted(ARRAYS.glob("*.jsonld"))}


def _node(docs, file, suffix):
    return next(n for n in docs[file]["@graph"] if n["@id"].endswith(suffix))


def _load_probe(tmp_path, docs=None):
    """(the class that instantiates the other, every class): the fixture's classes read by generate.read_class, as
    a design is read, and oriented, beside every pinned class."""
    docs = docs or _probe_docs()
    for name, d in docs.items():
        (tmp_path / name).write_text(json.dumps(d), encoding="utf-8")
    loaded = [cxf.Cxf.load(tmp_path / name) for name in sorted(docs)]
    defined = {cxf.local(nid): (d, nid) for d in loaded for nid, n in d.nodes.items()
               if n.get("@type") == cxf.S231 + "Block"}
    classes = _all_classes()
    known = set(classes) | set(defined)
    enums = {c for c in classes if classes[c].kind == "enum"}
    for c, (d, nid) in defined.items():
        classes[c] = generate.read_class(d, nid, known, enums, design=True)
    for c in defined:
        generate.orient(classes[c], classes)
    wrapper = next(c for c in defined if any(i.cls in defined for i in classes[c].insts))
    return wrapper, classes


@pytest.mark.inputs
def test_a_design_cxf_with_arrays_is_read(tmp_path):
    """Red when the reader refuses or drops the array forms modelica-json writes: a size kept with its parentheses
    or lost, an element endpoint left encoded, an element listed under hasInstance read as a modifier, or an indexed
    connect not oriented."""
    template, allc = _load_probe(tmp_path)
    assert template == "Probe.ArrWrap"
    s = allc["Probe.ArrSum"]
    assert s.param("gai").size == "nZon" and s.param("gai").expr == "fill(2,nZon)"
    assert s.param("nZon").size is None
    assert s.conn("TZon").size == "nZon" and s.conn("req1").size is None
    assert s.inst("gaiBlo").size == "nZon" and s.inst("addPar").size == "nZon"
    assert s.inst("mulSum").size is None and s.inst("intSum").size is None
    assert s.inst("intSum").binds == {"nin": (2.0, None)}            # u[1], u[2] are endpoints, not modifiers
    assert s.inst("gaiBlo").binds == {"k": (None, "gai")}
    assert ("req1", "intSum.u[1]") in s.edges and ("req2", "intSum.u[2]") in s.edges
    assert ("TZon", "gaiBlo.u") in s.edges and ("addPar.y", "mulSum.u") in s.edges
    w = allc["Probe.ArrWrap"]
    assert w.inst("seq").binds == {"nZon": (3.0, None)}
    assert ("T2", "seq.TZon[2]") in w.edges


@pytest.mark.inputs
def test_the_size_strips_one_outer_pair_and_keeps_whitespace(tmp_path):
    """Red when the size keeps its parentheses, strips more than one pair, or normalizes whitespace."""
    docs = _probe_docs()
    _node(docs, "ArrSum.jsonld", "ArrSum.gai")["S231:sizeOfDimensions"] = "((nZon + 0))"
    _, allc = _load_probe(tmp_path, docs)
    assert allc["Probe.ArrSum"].param("gai").size == "(nZon + 0)"


@pytest.mark.inputs
def test_three_dimensions_refuse_by_name(tmp_path):
    """Red when a three-dimensional array is read as fewer dimensions."""
    docs = _probe_docs()
    _node(docs, "ArrSum.jsonld", "ArrSum.gai")["S231:numberDimensions"] = 3
    with pytest.raises(cxf.CxfError, match=r"Probe.ArrSum: gai has 3 dimensions; one or two are supported"):
        _load_probe(tmp_path, docs)


@pytest.mark.inputs
def test_an_array_with_no_size_refuses_by_name(tmp_path):
    """Red when an array with no sizeOfDimensions is read as a scalar or with an empty size."""
    docs = _probe_docs()
    del _node(docs, "ArrSum.jsonld", "ArrSum.gaiBlo")["S231:sizeOfDimensions"]
    with pytest.raises(cxf.CxfError, match="Probe.ArrSum: gaiBlo is an array with no size"):
        _load_probe(tmp_path, docs)


@pytest.mark.inputs
def test_an_element_node_carrying_a_value_refuses_by_name(tmp_path):
    """Red when an element node carrying anything but a connection (here a value, an element modifier) is
    silently skipped or read as a modifier of the whole instance."""
    docs = _probe_docs()
    docs["ArrSum.jsonld"]["@graph"].append({"@id": "http://example.org#Probe.ArrSum.intSum.u%5B1%5D",
                                            "S231:value": 4})
    with pytest.raises(cxf.CxfError, match=r"ArrSum.jsonld: Probe.ArrSum.intSum.u\[1\] is an array element "
                                           r"carrying value; only connections may name an element"):
        _load_probe(tmp_path, docs)


@pytest.mark.inputs
def test_a_two_dimensional_instance_array_refuses_by_name(tmp_path):
    """Red when gaiBlo[nZon,2] is read as a one-dimensional vectorized instance."""
    docs = _probe_docs()
    _node(docs, "ArrSum.jsonld", "ArrSum.gaiBlo").update({"S231:numberDimensions": 2,
                                                          "S231:sizeOfDimensions": "(nZon,2)"})
    with pytest.raises(cxf.CxfError,
                       match=r"Probe.ArrSum: instance gaiBlo has 2 dimensions; a vectorized instance has one"):
        _load_probe(tmp_path, docs)


@pytest.mark.inputs
def test_the_multisum_classes_carry_their_array_sizes():
    """Red when load_classes leaves MultiSum's u and k without a size, so an expander could not count their
    elements, or when the size it reads differs from the cdlArraySize the generated spec carries."""
    classes = _all_classes()
    for c in ("Reals.MultiSum", "Integers.MultiSum"):
        ci = classes[generate.CDL_PREFIX + c]
        assert ci.conn("u").size == "nin" and ci.param("k").size == "nin" and ci.param("nin").size is None
        assert ci.conn("y").size is None
    text = (LIBS / "kw.cdl/blocks.xeto").read_text(encoding="utf-8")
    assert text.count('cdlArraySize:"(nin)"') >= 4


# ---- two-dimensional arrays ----

@pytest.mark.parametrize("src,env,want", [
    ("{2,3,1,4}", {}, [2.0, 3.0, 1.0, 4.0]),
    ("{{1,0},{1,0},{0,1},{0,1}}", {}, [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]),
    ("{ true, false }", {}, [True, False]),
    ("{}", {}, []),
    ("{n, n + 1}", {"n": 2.0}, [2.0, 3.0]),
    ("[1,0;0,1]", {}, [[1.0, 0.0], [0.0, 1.0]]),
    ("[1, 2]", {}, [[1.0, 2.0]]),
    ("1:nout", {"nout": 3.0}, [1.0, 2.0, 3.0]),
    ("2:n+1", {"n": 3.0}, [2.0, 3.0, 4.0]),
    ("3:2", {}, []),
    ("fill(0.5, 2, 3)", {}, [[0.5, 0.5, 0.5], [0.5, 0.5, 0.5]]),
    ("fill(true, 1, 2)", {}, [[True, True]]),
    ("size(K, 2)", {"K": [[1.0, 0.0, 1.0], [0.0, 1.0, 0.0]]}, 3.0),
    ("size(K, 1)", {"K": [[1.0, 0.0, 1.0], [0.0, 1.0, 0.0]]}, 2.0),
    ("size(K, 1) * size(K, 2)", {"K": [[1.0], [2.0]]}, 2.0),
])
def test_two_dimensional_forms_evaluate(src, env, want):
    """Red when a brace literal, a matrix literal, a range, a three-argument fill or size(a, 2) is refused, gives
    the wrong shape, or gives the wrong order: relFanMat, staVec, MatrixGain.K and
    ExtractSignal.extract are exactly these forms."""
    got = cxf.evaluate(src, env, lambda n: None)
    assert got == want and type(got) is type(want)


@pytest.mark.parametrize("src,env", [
    ("{{1},{2,3}}", {}),                  # ragged rows
    ("{1,{2}}", {}),                      # a row beside a scalar
    ("{{{1}}}", {}),                      # three dimensions
    ("[1,2;3]", {}),                      # ragged matrix
    ("[]", {}),                           # an empty matrix
    ("[k]", {"k": [1.0]}),                # a list inside a matrix row
    ("1:2:3", {}),                        # a step
    ("1.5:3", {}),                        # a bound that is not whole
    ("size(k, 2)", {"k": [1.0]}),         # one dimension asked for its second
    ("size(m, 3)", {"m": [[1.0]]}),       # a third dimension
    ("k[1]", {"k": [1.0]}),               # subscripts still refuse
    ("m[1,2]", {"m": [[1.0, 2.0]]}),
    ("{1,2} + 1", {}),                    # a list in arithmetic
    ("m == m", {"m": [[1.0]]}),           # a list in a comparison
])
def test_two_dimensional_forms_refuse_what_they_must(src, env):
    """Red when a ragged, over-deep or mixed literal, a stepped or fractional range, a size past the second
    dimension, a subscript or a list in arithmetic is accepted, or the refusal does not quote the expression."""
    with pytest.raises(cxf.CxfError) as e:
        cxf.evaluate(src, env, lambda n: None)
    assert repr(src) in str(e.value) or src in str(e.value)


@pytest.mark.inputs
def test_mbl_two_dimensional_declarations_are_read_with_paired_sizes():
    """Red when a two-dimensional MBL connector or parameter is read with one size, a joined string, or the
    wrong dimension count, or when the unsized MatrixGain.K gets a size."""
    classes = _all_classes()
    dup = classes[OBC + "ASHRAE.G36.ZoneGroups.ZoneStatusDuplicator"]
    assert dup.conn("y1Occ").dims == 2 and dup.conn("y1Occ").size == ("nZonGro", "nZon")
    assert dup.conn("y1Occ").raw_size == "(nZonGro,nZon)"
    assert dup.conn("u1Occ").dims == 1 and dup.conn("u1Occ").size == "nZon"
    sz = classes[OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.OutdoorAirFlow.ASHRAE62_1.SumZone"]
    assert sz.param("zonGroMat").dims == 2 and sz.param("zonGroMat").size == ("nGro", "nZon")
    assert sz.param("zonGroMatTra").size == ("nZon", "nGro")
    rep = classes[generate.CDL_PREFIX + "Routing.BooleanVectorReplicator"]
    assert rep.conn("y").dims == 2 and rep.conn("y").size == ("nout", "nin")
    mg = classes[generate.CDL_PREFIX + "Reals.MatrixGain"]
    assert mg.param("K").dims == 2 and mg.param("K").size is None and mg.param("K").raw_size == ""
    assert mg.param("nin") is None and mg.param("nout") is None            # the CXF gap DERIVED_PARAMS closes
    assert classes[OBC + "ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.ReliefFanGroup"].param("relFanMat").expr == \
        "{{1,0},{1,0},{0,1},{0,1}}"


def test_split_size_takes_the_top_level_comma_only():
    """Red when a two-dimensional size whose expression holds a parenthesized comma is split at the wrong comma,
    or a size with one or three parts is accepted."""
    assert generate.split_size("(nZonGro,nZon)", "C", "y") == ("nZonGro", "nZon")
    assert generate.split_size("( nZonGro , nZon )", "C", "y") == ("nZonGro", "nZon")
    assert generate.split_size("(max(a,b), n)", "C", "y") == ("max(a,b)", "n")
    for bad in ("(n)", "(a,b,c)", "(a,)"):
        with pytest.raises(cxf.CxfError, match=r"C: y has two dimensions but its size .* is not two expressions"):
            generate.split_size(bad, "C", "y")


def _mbl_bounds(cls):
    """{CDL name: {"min": text, "max": text}} from the class's own .mo declarations, read by regex here so the check
    shares nothing with the CXF reader: each `name(...)` modifier group, its min= and max= at the top level."""
    text = (MBL_DIR / (cls.replace(".", "/") + ".mo")).read_text(encoding="utf-8")
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    text = re.split(r"(?m)^protected\s*$", text)[0]    # a protected variable is the implementation, not the type
    out = {}
    # the class's own declarations sit at two spaces; a nested local class's sit deeper
    for m in re.finditer(r"(?m)^  (?:(?:final|parameter|constant|discrete)\s+)*(?:Real|Integer|Boolean|"
                         r"Buildings\.Controls\.OBC\.CDL\.Interfaces\.\w+|CDL\.Interfaces\.\w+|Interfaces\.\w+)\s+"
                         r"(\w+)\s*\(", text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body, top, d = text[m.end():i - 1], [], 0
        for ch in body:
            d += {"(": 1, ")": -1}.get(ch, 0)
            top.append(ch if d == 0 or ch in "()" else " ")
        flat = "".join(top)
        for side in ("min", "max"):
            k = re.search(r"(?:^|[,\s])(?:final\s+)?%s\s*=\s*" % side, flat)
            if k:
                rest = body[k.end():]
                dd, j = 0, 0
                while j < len(rest) and not (dd == 0 and rest[j] == ","):
                    dd += {"(": 1, ")": -1}.get(rest[j], 0)
                    j += 1
                out.setdefault(m.group(1), {})[side] = rest[:j].strip()
    return out


@pytest.mark.inputs
def test_the_cdlclass_bounds_are_the_bounds_mbl_declares(bounds_regen):
    # Wrong behavior caught: the bounds that moved from the retired elementary specs onto the CdlClass
    # instances no longer checked against MBL, so a wrong or lost bound (a PID k that may be 0) ships unseen.
    text = (LIBS / "kw.cdl/classes.xeto").read_text(encoding="utf-8")
    consts = _mbl_cdl_constants()
    checked, problems = 0, []
    for name, cls, grade in re.findall(r'(?m)^@cdl-(\w+): CdlClass \{\n  cdlClass: "([^"]+)"\n  grade: "(\w+)"', text):
        if grade in ("array", "composite"):
            continue                                   # their bounds stay on their own kw.cdl specs
        got = _class_bounds(text, name)
        want = _mbl_bounds(cls)
        for low, b in got.items():
            cdl = next((n for n in want if generate.lower(n) == low), None)
            for side, key in (("min", "minVal"), ("max", "maxVal"), ("min", "cdlMin"), ("max", "cdlMax")):
                if key not in b:
                    continue
                checked += 1
                if cdl is None or side not in want[cdl]:
                    problems.append("%s.%s %s: MBL declares no %s" % (name, low, key, side))
                    continue
                expr = want[cdl][side]
                for n, v in (("Buildings.Controls.OBC.CDL.Constants.eps", consts["eps"]),
                             ("Constants.eps", consts["eps"]), ("Constants.small", consts["small"])):
                    expr = expr.replace(n, repr(v))
                if not re.fullmatch(r"[-+*/0-9.eE() ]+", expr):
                    continue                           # a bound naming a parameter: checked as cdlMinExpr elsewhere
                # digits and operators only (the fullmatch above), so eval reads arithmetic and nothing else
                if float(eval(expr, {"__builtins__": {}})) != float(b[key]):
                    problems.append("%s.%s %s %s, MBL %s" % (name, low, key, b[key], want[cdl][side]))
        for cdl, sides in want.items():
            for side, expr in sides.items():
                if re.fullmatch(r"[-+*/0-9.eE() ]+", expr) or "Constants" in expr:
                    entry = got.get(generate.lower(cdl), {})
                    if not any(k in entry for k in (side + "Val", "cdl" + side.capitalize())):
                        problems.append("%s.%s: MBL's %s=%s did not reach the CdlClass bounds" % (name, cdl, side, expr))
    assert problems == [] and checked > 40, (checked, problems[:10])


@pytest.mark.inputs
@pytest.mark.parametrize("cls,slot,unit,via", [
    # MBL declares dpAbsMinOutDam=5 with no unit on the controllers; Limits.SeparateWithDP declares it Pa
    ("AHUs.MultiZone.VAV.Controller", "dpAbsMinOutDam", "Pa", "ecoCon.sepDp.dpAbsMinOutDam"),
    ("AHUs.MultiZone.VAV.Economizers.Controller", "dpAbsMinOutDam", "Pa", "sepDp.dpAbsMinOutDam"),
    # an elementary target answers through its unitRule; GreaterThreshold's h is a difference of u
    ("AHUs.MultiZone.VAV.SetPoints.PlantRequests", "tHys", "K", "greThr.h"),
    ("AHUs.SingleZone.VAV.SetPoints.PlantRequests", "tHys", "K", "greThr.h"),
])
def test_a_parameter_takes_the_unit_declared_where_it_is_bound_by_bare_name(cls, slot, unit, via):
    # Wrong behavior caught: a top-level parameter MBL leaves without a unit, bound by bare name into a
    # subsequence parameter that declares one, emitted with no unit at all, so nobody converts 5 Pa for an inH2O point.
    line = _emit_slot(cls, slot)
    assert _meta(line, "cdlUnitInferred") == unit and _meta(line, "cdlUnit") is None, line
    assert _meta(line, "cdlUnitVia") == via, line
    assert bool(re.search(r"[<, ]cdlDelta[,>]", line)) == (unit == "K"), line


def _bound_unit_classes(unit_b):
    """A top class whose parameter x feeds, by bare name, a Pa parameter of A and a parameter of B in unit_b."""
    def leaf(path, unit):
        ci = generate.ClassInfo(path, "composite", "")
        ci.params.append(generate.Param("p", "Real", None, None, unit, None, False, False, ""))
        return ci
    top = generate.ClassInfo("Top", "composite", "")
    top.params.append(generate.Param("x", "Real", None, None, None, None, False, False, ""))
    top.insts += [generate.Inst("a", "A", {"p": (None, "x")}, None, ""),
                  generate.Inst("b", "B", {"p": (None, "x")}, None, "")]
    return {"Top": top, "A": leaf("A", "Pa"), "B": leaf("B", unit_b)}


def test_a_parameter_bound_into_two_declared_units_that_disagree_refuses_its_class():
    # Wrong behavior caught: two binding targets declaring different units, with one silently picked.
    classes = _bound_unit_classes("m³/s")
    refused = generate.infer_bound_units(classes)
    assert list(refused) == ["Top"] and "Pa" in str(refused["Top"]) and "m³/s" in str(refused["Top"])
    assert classes["Top"].param("x").unit is None
    agree = _bound_unit_classes("Pa")
    assert generate.infer_bound_units(agree) == {}
    assert (agree["Top"].param("x").unit, agree["Top"].param("x").uvia) == ("Pa", "a.p")
    # a quantity one target names and the other leaves out is no disagreement when the units agree
    quant = _bound_unit_classes("Hz")
    quant["A"].param("p").unit = "Hz"
    quant["B"].param("p").qinferred = "frequency"
    assert generate.infer_bound_units(quant) == {}
    assert (quant["Top"].param("x").unit, quant["Top"].param("x").qinferred) == ("Hz", "frequency")
    # a K absolute beside a K difference is a disagreement, though the symbols agree
    kk = _bound_unit_classes("K")
    kk["A"].param("p").unit, kk["A"].param("p").qkind = "K", "ThermodynamicTemperature"
    kk["B"].param("p").qkind = "TemperatureDifference"
    assert list(generate.infer_bound_units(kk)) == ["Top"]


@pytest.mark.inputs
def test_a_converted_parameter_carries_its_bounds_with_their_si_unit_not_as_minval(regen):
    # Wrong behavior caught: minVal and maxVal on a slot a resolver converts, which fits compares as
    # bare numbers, so dpBuiSet's maxVal 30 (Pa) passed 30 inH2O and bouLim's minVal 0.5 (K) passed 0.6 degrees F.
    converted = {"K", "Pa", "m³/s", "J/kg", "1/s"}
    params = [l for l in regen["kw.cdl.g36"] if re.search(r"[<, ]cdlParam[,>]", l)
              and (_meta(l, "cdlUnit") or _meta(l, "cdlUnitInferred")) in converted]
    assert params and not any(_meta(l, "minVal") is not None or _meta(l, "maxVal") is not None for l in params)
    si = [l for l in params if _meta(l, "cdlSiMin") is not None or _meta(l, "cdlSiMax") is not None]
    assert len(si) == 79, len(si)
    sym = {"K": "K", "Pa": "Pa", "m³/s": "m³/s", "J/kg": "J/kg", "1/s": "/s"}
    for l in si:
        unit = sym[_meta(l, "cdlUnit") or _meta(l, "cdlUnitInferred")]
        for k in ("cdlSiMin", "cdlSiMax"):
            v = _meta(l, k)
            assert v is None or re.fullmatch(r"-?[0-9.e+-]+" + re.escape(unit), v), (k, v, l.strip())
    assert any('cdlName:"dpBuiSet"' in l and _meta(l, "cdlSiMax") == "30Pa" for l in si)


def test_a_parameter_whose_unit_rule_joins_two_units_refuses_its_class(monkeypatch):
    # Wrong behavior caught: infer_bound_units's docstring promised a refusal when an elementary
    # block's rule joins the parameter to two units, but a conflicting group came back as "no unit" and passed.
    classes = _bound_unit_classes("Pa")
    leaf = generate.ClassInfo("E", "block", "")
    leaf.params.append(generate.Param("h", "Real", None, None, None, None, False, False, ""))
    classes["E"] = leaf
    classes["Top"].insts = [generate.Inst("e", "E", {"h": (None, "x")}, None, "")]

    class FakeModel:
        def unit_of(self, val, port):
            return None, "its group joins two different units"

    class FakeMapper:
        def __init__(self, *a, **k):
            pass

        def unit_model(self):
            return FakeModel(), {}
    import hxemit
    monkeypatch.setattr(hxemit, "Mapper", FakeMapper)
    monkeypatch.setattr(hxemit, "composed", lambda c, m: {})
    monkeypatch.setattr(generate, "hx_rows", lambda c: ({}, {}))
    refused = generate.infer_bound_units(classes)
    assert list(refused) == ["Top"] and "joins two different units" in str(refused["Top"])
