"""Tests for the lib check (check_open_libs.py). Run from the repo root: python -X utf8 -m pytest src/gen -q"""
import json
import os
import pathlib
import shutil
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIBS = ROOT / "src" / "xeto"
sys.path.insert(0, str(HERE))

import check_open_libs  # noqa: E402
import generate  # noqa: E402

# A lib name outside every allowed set, for planting. A synthetic name: the check refuses anything it does not list.
ACME = "acme.points"


def test_the_repo_has_no_lib_violation():
    # Wrong behavior caught: a generated lib that depends on a lib outside its allowed set (another ontology, an
    # engine's lib such as axon), or one that ships without the AFL notice beside its copyright, or without MBL's NOTICE.
    assert check_open_libs.violations(LIBS) == []


def test_the_g36_libs_depend_on_hx_comps_kw_cdl_and_the_ph_point_libs():
    # Wrong behavior caught: a dependency set other than the intended one, so a G36 lib that names a ph point spec or
    # an hx.comps comp fails to load, or kw.cdl reaches past hx.comps.
    assert generate.OPEN_DEPENDS["kw.cdl"] == ("sys", "sys.comp", "hx.comps")
    want = ("sys", "sys.comp", "hx.comps", "kw.cdl", "ph", "ph.points", "ph.points.x")
    assert generate.OPEN_DEPENDS["kw.cdl.g36.common"] == want
    for lib in ("kw.cdl.g36.ahu", "kw.cdl.g36.terminal"):
        assert generate.OPEN_DEPENDS[lib] == want + ("kw.cdl.g36.common",)


def test_the_generated_set_is_the_four_libs():
    # Wrong behavior caught: a lib dropped from, or added to, the generated set, or ahu and terminal depending on
    # each other.
    assert generate.OPEN_LIBS == ("kw.cdl", "kw.cdl.g36.common", "kw.cdl.g36.ahu", "kw.cdl.g36.terminal")
    assert "kw.cdl.g36.terminal" not in generate.OPEN_DEPENDS["kw.cdl.g36.ahu"]
    assert "kw.cdl.g36.ahu" not in generate.OPEN_DEPENDS["kw.cdl.g36.terminal"]


@pytest.fixture
def tree(tmp_path):
    """A copy of every lib under src/xeto, to plant a fault in."""
    for f in sorted(LIBS.glob("*/lib.xeto")):
        shutil.copytree(f.parent, tmp_path / f.parent.name)
    return tmp_path


def test_a_fixture_tree_is_clean(tree):
    # Wrong behavior caught: a planted-fault test passing on a violation the copy already had, not the planted one.
    assert check_open_libs.violations(tree) == []


def _add_dep(path, dep):
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('    { lib: "sys" }', '    { lib: "sys" }\n    { lib: "%s" }' % dep, 1),
                    encoding="utf-8")


@pytest.mark.parametrize("lib,dep", [
    ("kw.cdl", ACME),
    ("kw.cdl.g36.ahu", "acme.ontology"),
    ("kw.cdl", "kw.cdl.resolve"),
    ("kw.cdl.g36.common", "axon"),
    ("kw.cdl", "ph.points"),
    ("kw.cdl", "axon"),
    ("kw.cdl.g36.ahu", "kw.cdl.g36.terminal"),
])
def test_a_planted_dependency_is_refused_by_name(tree, lib, dep):
    # The check's own red condition: each planted dependency must be named, with the rule it broke.
    _add_dep(tree / lib / "lib.xeto", dep)
    bad = check_open_libs.violations(tree)
    assert any(lib in b and dep in b and "outside its allowed set" in b for b in bad), bad


def test_a_file_without_the_licensing_notice_is_refused(tree):
    f = tree / "kw.cdl.g36.terminal" / "g36.xeto"
    f.write_text(f.read_text(encoding="utf-8").replace(generate.AFL_NOTICE + "\n", "", 1), encoding="utf-8")
    assert any("g36.xeto" in b and "AFL" in b for b in check_open_libs.violations(tree))


def test_a_notice_moved_away_from_the_copyright_is_refused(tree):
    # "Adjacent" is the licence's word: a notice three lines below the copyright does not count.
    f = tree / "kw.cdl" / "lib.xeto"
    text = f.read_text(encoding="utf-8").replace(generate.AFL_NOTICE + "\n", "", 1)
    f.write_text(text.replace("pragma: Lib <", generate.AFL_NOTICE + "\npragma: Lib <"), encoding="utf-8")
    assert any("kw.cdl/lib.xeto" in b for b in check_open_libs.violations(tree))


# ---- the generated form ----
# A generated lib's lib.xeto pragma is read only in the exact form generate.render_pragma emits. Any other form is
# refused, so no Xeto lexical form (comment, string, heredoc, typed value, extra meta) can hide a dependency: a hand
# lexer chasing the grammar missed one form after another.

COMMON = '    { lib: "kw.cdl.g36.common" }'
PLANT = '\n    { lib: "%s" }' % ACME
NOT_GENERATED = "pragma is not in generated form"

# Pragmas the xeto compiler reads (the oracle below checks each one) in a form the generator never writes. Most name
# a dependency where an earlier reader could not see it.
OFF_FORM_PLANTS = {
    # A } in a comment. On its own line: the compiler refuses a // comment after a dict item on the same line.
    "line comment brace": [(COMMON, COMMON + "\n    // } closes depends early" + PLANT)],
    "block comment brace": [(COMMON, COMMON + " /* } } */" + PLANT)],
    "commented-out item": [(COMMON, COMMON + '\n    // { lib: "x" }' + PLANT)],
    # String forms and nesting.
    "heredoc doc": [("DOC", '  doc: ---\n    Its depends: { } names nothing else.\n    ---'), (COMMON, COMMON + PLANT)],
    "triple-quoted tag": [(COMMON, '    { lib: "kw.cdl.g36.common", note: """see " } """ }' + PLANT)],
    "heredoc tag": [(COMMON, '    { lib: "kw.cdl.g36.common", note: ---\n      } closes\n      ---\n    }' + PLANT)],
    "brace in a string": [(COMMON, '    { lib: "kw.cdl.g36.common", note: "} }" }' + PLANT)],
    "nested comment": [(COMMON, COMMON + " /* a /* b */ } */" + PLANT)],
    "escaped quote in triple quotes": [("DOC", '  doc: """a \\""" depends: { } """'),
                                       (COMMON, COMMON + '\n    { lib: "%s", note: """b \\""" c""" }' % ACME)],
    "four-dash heredoc": [("DOC", "  doc: ----\n    Its --- depends: { } --- names nothing.\n    ----"),
                          (COMMON, COMMON + PLANT)],
    "typed scalar lib name": [(COMMON, COMMON + '\n    { lib: Str "%s" }' % ACME)],
    "depends inside org": [("DOC", '  org: { dis: "kW", depends: { } }\n{DOC}'), (COMMON, COMMON + PLANT)],
    "typed list depends": [("  depends: {", "  depends: List {"), (COMMON, COMMON + PLANT)],
    "multi-line item": [(COMMON, '    {\n      lib: "kw.cdl.g36.common"\n    }' + PLANT)],
    # Around the pragma: the generated file is comment lines, the pragma, and nothing after it.
    "block comment header": [("pragma: Lib <", '/* { lib: "%s" } */\npragma: Lib <' % ACME)],
    "spec after the pragma": [('{"/NOTICE"}\n>', '{"/NOTICE"}\n>\n\nFoo: Dict { a: Str }')],
    # Inside the pragma's own shape: a doc escape the generator does not write (pins the re-render check).
    "unicode escape in doc": [("DOC", '  doc: "a \\u0022 b"')],
}
# Pragmas the compiler refuses: an unterminated comment or string, inside depends and ahead of it.
UNTERMINATED_PLANTS = {
    "block comment": [(COMMON, COMMON + "\n    /* never closed" + PLANT)],
    "block comment ahead of depends": [("DOC", "{DOC}\n  /* never closed"), (COMMON, COMMON + PLANT)],
    "triple-quoted string": [(COMMON, '    { lib: "kw.cdl.g36.common", note: """never closed }' + PLANT)],
    "heredoc": [(COMMON, '    { lib: "kw.cdl.g36.common", note: ---\n      never closed }' + PLANT)],
    "triple-quoted doc": [("DOC", '  doc: """never closed'), (COMMON, COMMON + PLANT)],
    "heredoc doc": [("DOC", "  doc: ---\n    never closed"), (COMMON, COMMON + PLANT)],
}
ALL_PLANTS = dict(OFF_FORM_PLANTS, **{"unterminated " + k: v for k, v in UNTERMINATED_PLANTS.items()})


def _planted(text, edits):
    for old, new in edits:
        if old == "DOC":
            old = next(l for l in text.splitlines() if l.startswith("  doc: "))
        assert old in text, old
        text = text.replace(old, new.replace("{DOC}", old), 1)
    return text


def _plant(tree, edits, lib="kw.cdl.g36.ahu"):
    f = tree / lib / "lib.xeto"
    f.write_text(_planted(f.read_text(encoding="utf-8"), edits), encoding="utf-8", newline="\n")


@pytest.mark.parametrize("name", sorted(ALL_PLANTS))
def test_a_pragma_not_in_generated_form_is_refused(tree, name):
    # Wrong behavior caught: a lib.xeto in any form the generator does not write passing the check, which is how a
    # comment, a string form, a heredoc, a typed value or a depends key inside other meta each hid a dependency from a
    # hand lexer.
    _plant(tree, ALL_PLANTS[name])
    bad = check_open_libs.violations(tree)
    assert any(b.startswith("kw.cdl.g36.ahu: " + NOT_GENERATED) for b in bad), bad
    assert check_open_libs.main([str(tree)]) == 1


def test_the_generated_form_still_reads_a_dependency_it_names(tree):
    # Wrong behavior caught: a reader that refuses or skips the generated form, so a forbidden dependency written
    # exactly as the generator writes one goes unread. The canonical pragma must be read, and the rule applied.
    _plant(tree, [(COMMON, COMMON + PLANT)])
    bad = check_open_libs.violations(tree)
    assert any("kw.cdl.g36.ahu depends on %s, outside its allowed set" % ACME in b for b in bad), bad
    assert not any(NOT_GENERATED in b for b in bad), bad


def test_a_second_copy_of_a_lib_is_refused_and_cannot_mask_the_real_one(tree):
    # Wrong behavior caught: lib_files keyed on the directory name, so a clean decoy at zzz/kw.cdl.g36.ahu replaced
    # the real kw.cdl.g36.ahu, whose planted dependency then passed with exit 0. The check reads the directories
    # directly under src/xeto and refuses any second copy of a name.
    shutil.copytree(tree / "kw.cdl.g36.ahu", tree / "zzz" / "kw.cdl.g36.ahu")
    _plant(tree, [(COMMON, COMMON + PLANT)])
    bad = check_open_libs.violations(tree)
    assert any("kw.cdl.g36.ahu depends on %s" % ACME in b for b in bad), bad
    assert any("kw.cdl.g36.ahu" in b and "duplicate" in b and "zzz" in b for b in bad), bad


def _toolchain():
    home = os.environ.get("FAN_HOME")
    if not home or not (pathlib.Path(home) / "lib/fan/xetoc.pod").exists():
        pytest.skip("no Haxall toolchain in FAN_HOME; the compiler oracle runs where one is installed")
    return home


def test_the_generated_form_reads_as_the_xeto_compiler_reads_it_and_every_other_form_is_refused(tmp_path):
    # Wrong behavior caught: the generated-form reader and the xeto compiler disagreeing on a repo lib's depends, or
    # a plant the compiler refuses (so not a real bypass) standing in for one it accepts. The compiler's reading
    # (XetoEnv.readAst) is the reference. It needs a JVM, so this runs where FAN_HOME holds a Haxall toolchain and
    # skips elsewhere; check_open_libs.py --compiler is the same reader as a CLI.
    home = _toolchain()
    libs = check_open_libs.lib_files(LIBS)[0]
    files = {"repo " + lib: libs[lib] for lib in generate.OPEN_LIBS}
    base = (LIBS / "kw.cdl.g36.ahu" / "lib.xeto").read_text(encoding="utf-8")
    canon = tmp_path / "canonical.xeto"
    canon.write_text(_planted(base, [(COMMON, COMMON + PLANT)]), encoding="utf-8", newline="\n")
    files["canonical with a plant"] = canon
    for name, edits in ALL_PLANTS.items():
        f = tmp_path / ("plant-%s.xeto" % name.replace(" ", "-"))
        f.write_text(_planted(base, edits), encoding="utf-8", newline="\n")
        files["plant " + name] = f
    read = check_open_libs.compiler_depends(list(files.values()), home)
    assert len(read) == len(files)
    for key, f in files.items():
        got = read[str(f)]
        text = f.read_text(encoding="utf-8")
        assert ("error" in got) == key.startswith("plant unterminated"), (key, got)
        if key.startswith(("repo", "canonical")):
            assert check_open_libs.pragma_depends(text) == got["depends"], key
        else:
            with pytest.raises(ValueError, match=NOT_GENERATED):
                check_open_libs.pragma_depends(text)
    assert ACME in read[str(canon)]["depends"]


# No two libs declare one meta tag. Two declarers coexist in a namespace, but an unqualified meta lookup there is
# ambiguous, and a lib depending on both fails to compile. The compiler sees only a lib's own depends, so a pair that
# never shares a dependent is caught only here.

def _add_meta(f, tag):
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    if "+Spec {" in text:
        text = text.replace("+Spec {", "+Spec {\n  %s: Str?" % tag, 1)
    else:
        text += "\n+Spec {\n  %s: Str?\n}\n" % tag
    f.write_text(text, encoding="utf-8", newline="\n")


@pytest.mark.parametrize("where,tag,others", [
    ("kw.cdl.g36.common/zz.xeto", "cdlClass", ["kw.cdl"]),    # a G36 lib redeclaring the CDL model's tag
    ("kw.cdl.resolve/zz.xeto", "cdlPointSpec", ["kw.cdl"]),   # a lib that is not generated, which shares no dependent
])
def test_a_meta_tag_declared_by_two_libs_is_refused_naming_both(tree, where, tag, others):
    _add_meta(tree / where, tag)
    bad = [b for b in check_open_libs.violations(tree) if "meta tag" in b]
    lib = where.split("/")[0]
    assert any(("'%s'" % tag) in b and lib in b and all(o in b for o in others) for b in bad), bad


def test_an_allowed_duplicate_goes_stale_once_the_pair_no_longer_declares_it(tree, monkeypatch):
    # Wrong behavior caught: an allowance outliving the pair it was made for, so the next duplicate between those
    # names passes unseen. None is allowed today.
    assert check_open_libs.DUPLICATE_META_ALLOWED == {}
    monkeypatch.setattr(check_open_libs, "DUPLICATE_META_ALLOWED", {"cdlAcmeTag": ("kw.cdl", "kw.cdl.resolve")})
    assert any("cdlAcmeTag" in b and "stale" in b for b in check_open_libs.violations(tree))


def test_an_unclosed_spec_mixin_is_refused(tree):
    # Wrong behavior caught: a +Spec block the reader cannot close being skipped, so its tags go uncounted (fail closed).
    f = tree / "kw.cdl" / "meta.xeto"
    f.write_text(f.read_text(encoding="utf-8") + "\n+Spec {\n  cdlNever: Str?\n", encoding="utf-8", newline="\n")
    assert any(b.startswith("kw.cdl") and "+Spec" in b and "not closed" in b for b in check_open_libs.violations(tree))


# The generated libs' vocabulary, frozen. The plants use a synthetic name: the freeze refuses any tag it does not list.

def test_the_generated_vocabulary_is_kw_cdls_63_tags_and_none_in_g36():
    # Wrong behavior caught: the freeze covering fewer libs than the generator writes, or pinned to other tags than
    # the ones kw.cdl/meta.xeto declares today.
    assert set(check_open_libs.OPEN_META) == set(generate.OPEN_LIBS)
    assert len(check_open_libs.OPEN_META["kw.cdl"]) == 63 == len(set(check_open_libs.OPEN_META["kw.cdl"]))
    assert check_open_libs.meta_tags(LIBS / "kw.cdl", "kw.cdl")[0] == set(check_open_libs.OPEN_META["kw.cdl"])
    for lib in generate.G36_LIBS:
        assert check_open_libs.OPEN_META[lib] == ()


@pytest.mark.parametrize("where", ["kw.cdl/meta.xeto", "kw.cdl.g36.common/g36.xeto", "kw.cdl.g36.ahu/g36.xeto",
                                   "kw.cdl.g36.terminal/g36.xeto"])
def test_a_meta_tag_outside_the_generated_vocabulary_is_refused(tree, where):
    _add_meta(tree / where, "cdlAcmeFlag")
    lib = where.split("/")[0]
    bad = check_open_libs.violations(tree)
    assert any(b.startswith("%s declares meta tag 'cdlAcmeFlag', outside its vocabulary" % lib) for b in bad), bad


def test_a_dropped_generated_tag_is_refused(tree):
    f = tree / "kw.cdl" / "meta.xeto"
    text = f.read_text(encoding="utf-8")
    tab = "  cdlTab: Str?\n"
    assert tab in text
    f.write_text(text.replace(tab, "", 1), encoding="utf-8", newline="\n")
    assert "kw.cdl does not declare meta tag 'cdlTab' of its vocabulary" in check_open_libs.violations(tree)


@pytest.mark.parametrize("plant, want", [
    ("hx.comps::NoSuchComp", "names hx.comps::NoSuchComp, which hx.comps does not declare"),
    ("ph.points.x::OutsideAirTempSensr", "names ph.points.x::OutsideAirTempSensr, which ph.points.x does not declare"),
    ("sys.comp::NoSuchSpec", "names sys.comp::NoSuchSpec, which sys.comp does not declare"),
    ("acme.ontology::Ahu", "names acme.ontology::Ahu, and acme.ontology is outside its depends"),
    ("axon::Fn", "names axon::Fn, and axon is outside its depends"),
])
def test_a_qualified_name_its_depends_do_not_declare_is_refused(tree, plant, want):
    # Wrong behavior caught: a misspelt comp or point spec, or a reference into a lib the depends do not name,
    # compiled into a lib nothing checked.
    f = tree / "kw.cdl.g36.common" / "g36.xeto"
    f.write_text(f.read_text(encoding="utf-8") + "\nAcmeProbe: kw.cdl::CdlBlock <cdlClass:\"Buildings.X\"> {\n  p: %s?\n}\n"
                 % plant, encoding="utf-8", newline="\n")
    assert any(want in b for b in check_open_libs.violations(tree))


@pytest.mark.skipif(not os.environ.get("HAYSTACK_XETO_SRC"),
                    reason="HAYSTACK_XETO_SRC names no Project Haystack xeto src/xeto directory")
def test_the_pinned_xeto_names_are_what_the_source_declares():
    # Wrong behavior caught: a names table edited by hand, or left behind when the pinned commit moves.
    want = check_open_libs.xeto_names(os.environ["HAYSTACK_XETO_SRC"])
    assert json.loads(check_open_libs.XETO_NAMES.read_text(encoding="utf-8")) == want


@pytest.mark.parametrize("name", generate.OPEN_LIBS)
def test_a_lib_whose_pragma_does_not_publish_its_notice_is_refused(tree, name):
    # Wrong behavior caught: a NOTICE in the source but not in the xetolib. The packer (xetoc's Scanner) ships a
    # lib's .xeto files and chapters, and any other file only when a publish or include pattern names it, so a
    # pragma without publish: {"/NOTICE"} builds every xetolib without MBL's licence, silently.
    f = tree / name / "lib.xeto"
    text = f.read_text(encoding="utf-8")
    assert '  publish: {"/NOTICE"}\n' in text
    f.write_text(text.replace('  publish: {"/NOTICE"}\n', ""), encoding="utf-8", newline="\n")
    got = check_open_libs.violations(tree)
    assert any(v.startswith(name + ': its pragma does not publish "/NOTICE"') for v in got), got
    # and a publish list that names something else instead is refused the same way
    f.write_text(text.replace('{"/NOTICE"}', '{"/LICENSE"}'), encoding="utf-8", newline="\n")
    got = check_open_libs.violations(tree)
    assert any(v.startswith(name + ': its pragma does not publish "/NOTICE"') for v in got), got
