#!/usr/bin/env python3
#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""The lib check: read every lib.xeto under src/xeto and refuse when a generated lib depends on anything outside its
allowed set, names something its depends do not declare, or carries its licence notices out of place.

  python -X utf8 src/gen/check_open_libs.py              # exit 0 when clean, 1 with one line per violation
  python -X utf8 src/gen/check_open_libs.py --compiler   # depends read by the xeto compiler (FAN_HOME)
  python -X utf8 src/gen/check_open_libs.py --xeto-names <Project Haystack xeto src/xeto>   # print xeto_names.json

The generated libs are generate.OPEN_LIBS. A generated lib's depends are read only from the exact pragma
generate.render_pragma writes. Its lib.xeto must be comment lines, then that pragma byte for byte, then nothing.
Anything else is refused as "pragma is not in generated form", so no Xeto form (a comment, any of the three string
forms, a typed value, a depends key inside other meta) can hide a dependency. A hand lexer chasing the Xeto grammar
missed one such form after another, and these libs are generated, so the check reads the one form the generator
writes and refuses the rest.

--compiler reads depends with the xeto compiler instead (xeto_depends.fan, XetoEnv.readAst). It is not the default
because it needs a JVM and a Haxall toolchain. test_open_libs.py holds the generated-form reader to the compiler's
reading wherever FAN_HOME holds a Haxall toolchain.

Libs are found as `fan xeto build` finds them: each directory under src/xeto holding a lib.xeto. A second lib.xeto
anywhere else under the same name is refused as a duplicate, so a decoy cannot stand in for the real lib.

A generated lib's depends must sit inside generate.OPEN_DEPENDS[lib]: sys, sys.comp and hx.comps for kw.cdl (a CDL
elementary class is an hx.comps comp); for the G36 libs also kw.cdl and the Project Haystack point libs ph, ph.points
and ph.points.x, and kw.cdl.g36.common for ahu and terminal. Anything else, another building ontology included, is
refused because it is not on that list. Every .xeto file of a generated lib opens with kW's copyright notice and, on
the next line, the AFL-3.0 licensing notice. Every generated lib carries MBL's licence in NOTICE, and its pragma
publishes it. Each generated lib declares exactly the meta tags OPEN_META lists, so a new concept needs a deliberate
edit here.

No two libs declare one meta tag. Every `+Spec` mixin of every lib under src/xeto is read, and a tag two libs declare
is refused naming both, except the pairs in DUPLICATE_META_ALLOWED (none today), each refused as stale once it no
longer holds.

Every qualified name a generated lib uses (`hx.comps::Limiter`, `ph.points.x::OutsideAirTempSensor`,
`@kw.cdl::cdl-RealsAdd`) must name a lib in its depends, or itself, and a spec or instance that lib declares. The names
of kw.cdl and the G36 libs are read from this repo; of hx.comps from hx_comps_index.json; and of sys, sys.comp, ph,
ph.points and ph.points.x from xeto_names.json, pinned from Project Haystack's xeto repo at commit 23be968. A name
outside them is refused, so a typo or a reference into a lib the depends do not name cannot ship.

The hx.comps depend carries no version range. No released Haxall carries the comps these libs need (haxall pull
requests #138 to #152 are not in a release yet), so there is no released version to range from. Range it to that
release when it ships.
"""
import functools
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
XETO_NAMES = HERE / "xeto_names.json"
HX_INDEX = HERE / "hx_comps_index.json"
# The libs whose names xeto_names.json pins, all from Project Haystack's xeto repo.
PINNED_LIBS = ("sys", "sys.comp", "ph", "ph.points", "ph.points.x")
QUALIFIED = re.compile(r"(?<![\w.@])@?([a-z][\w]*(?:\.[a-z][\w]*)*)::([A-Za-z_][\w-]*)")
sys.path.insert(0, str(HERE))
import generate  # noqa: E402

COPYRIGHT_RE = re.compile(r"^// Copyright \(c\) \d{4}, kW Engineering$")
AFL_LINE = generate.AFL_NOTICE

# The meta tags each generated lib declares, frozen. A generated lib names only its own vocabulary here, so a new tag
# is a deliberate edit. kw.cdl declares the 63 tags of its meta.xeto, in that file's order; the G36 libs declare none.
OPEN_META = {
    "kw.cdl": ("cdlClass", "cdlElementary", "cdlParam", "cdlInput", "cdlOutput", "cdlInstance", "cdlName", "cdlType",
               "cdlUnit", "cdlQuantityKind", "cdlDefault", "cdlProtected", "cdlFinal", "cdlBind", "cdlFinalBind",
               "cdlCondition", "cdlArraySize", "cdlMin", "cdlMax", "cdlMinConst", "cdlMaxConst", "cdlMinVia",
               "cdlMaxVia", "cdlMinOwn", "cdlMaxOwn", "cdlMinWhen", "cdlMaxWhen", "cdlMinExpr", "cdlMaxExpr",
               "cdlClause", "cdl231Name", "cdlAltLink", "cdlEnable", "cdlGroup", "cdlTab", "cdlValueInReference",
               "cdlQuantityInferred", "cdlUnitInferred", "cdlUnitVia", "cdlCompoundGain", "cdlUnitGroup", "cdlUnitOverride", "cdlSiMin", "cdlSiMax", "cdlPointUnit", "cdlPointScale", "cdlConnUnits", "cdlState", "cdlStateInit",
               "cdlStateInitBasis", "cdlStateBasis", "cdlOf", "cdlDefaulted", "cdlFeed", "cdlLinkVia", "cdlExpand",
               "cdlDelta", "cdlLiteralUnits", "cdlLiteralDelta", "cdlLiteralExprs", "cdlPointSpec", "cdlPointSpecCases",
               "cdlPointScope"),
    "kw.cdl.g36.common": (),
    "kw.cdl.g36.ahu": (),
    "kw.cdl.g36.terminal": (),
}
ALL_OPEN = generate.OPEN_LIBS

# Meta tags two libs may both declare, with the exact pair. Each entry is refused as stale once the pair no longer
# declares the tag.
DUPLICATE_META_ALLOWED = {}


def lib_files(root):
    """(libs, others): each directory directly under `root` holding a lib.xeto, which is what `fan xeto build` builds,
    by lib name; and every other lib.xeto below `root`, as paths."""
    libs = {f.parent.name: f for f in sorted(root.glob("*/lib.xeto"))}
    others = [f for f in sorted(root.rglob("lib.xeto")) if f.parent.parent != root]
    return libs, others


NOT_GENERATED = "pragma is not in generated form"
# The shape render_pragma writes, read only to pull out its three values. The re-render below is the authority.
PRAGMA_SHAPE = re.compile(r'pragma: Lib <\n  doc: ("(?:[^"\\\n]|\\.)*")\n  version: "([^"\n]*)"\n  depends: \{\n'
                          r'((?:    \{ lib: "[^"\n]*" \}\n)*)  \}\n(?:  publish: \{([^}\n]*)\}\n)?>\n')
PUBLISH_ITEM = re.compile(r'"([^"\n]*)"')
DEPEND_LINE = re.compile(r'    \{ lib: "([^"\n]*)" \}\n')


def pragma_depends(text):
    """The depends of a lib.xeto in generated form: comment lines, then exactly what generate.render_pragma writes
    for the doc, version and depends it declares, then nothing. Raises ValueError naming NOT_GENERATED otherwise."""
    try:
        header, pragma = generate.split_lib_xeto(text)
    except ValueError as e:
        raise ValueError("%s: %s" % (NOT_GENERATED, e))
    for line in header.splitlines():
        if line and not line.startswith("//"):
            raise ValueError("%s: a line before the pragma is not a // comment: %r" % (NOT_GENERATED, line[:60]))
    m = PRAGMA_SHAPE.fullmatch(pragma)
    if m is None:
        raise ValueError("%s: it is not the shape generate.render_pragma writes" % NOT_GENERATED)
    try:
        doc = json.loads(m.group(1))
    except ValueError as e:
        raise ValueError("%s: its doc is not a plain string (%s)" % (NOT_GENERATED, e))
    deps = DEPEND_LINE.findall(m.group(3))
    publish = PUBLISH_ITEM.findall(m.group(4) or "")
    if generate.render_pragma(doc, m.group(2), deps, publish) != pragma:
        raise ValueError("%s: generate.render_pragma does not write it byte for byte" % NOT_GENERATED)
    return deps


def vocabulary_violations(name, d):
    """A generated lib declares exactly its frozen meta tags, OPEN_META[name]: no tag more, no tag less."""
    tags, _ = meta_tags(d, name)
    vocab = OPEN_META[name]
    want = set(vocab)
    shown = list(vocab) if len(vocab) <= 8 else "of %d tags (check_open_libs.OPEN_META)" % len(vocab)
    out = ["%s declares meta tag '%s', outside its vocabulary %s" % (name, tag, shown) for tag in sorted(tags - want)]
    out += ["%s does not declare meta tag '%s' of its vocabulary" % (name, tag) for tag in sorted(want - tags)]
    return out


def _code(text):
    """`text` with comments and string contents blanked to spaces, newlines kept, so braces and names read as code."""
    out, i, n = [], 0, len(text)

    def blank(j):
        out.append("".join(c if c == "\n" else " " for c in text[i:j]))
        return j
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = blank(n if j < 0 else j)
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = blank(n if j < 0 else j + 2)
        elif text.startswith('"""', i):
            j = text.find('"""', i + 3)
            i = blank(n if j < 0 else j + 3)
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            i = blank(min(j + 1, n))
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


SPEC_MIXIN_RE = re.compile(r"^\+(?:sys::)?Spec\s*\{", re.M)


def meta_tags(d, label):
    """(tags, errors): the meta tag names the `+Spec` mixins of a lib directory declare, and one error per mixin whose
    braces do not close (fail closed: its tags would otherwise go uncounted)."""
    tags, errors = set(), []
    for x in sorted(d.glob("*.xeto")):
        code = _code(x.read_text(encoding="utf-8"))
        for m in SPEC_MIXIN_RE.finditer(code):
            depth, j = 1, m.end()
            while j < len(code) and depth:
                depth += {"{": 1, "}": -1}.get(code[j], 0)
                j += 1
            if depth:
                errors.append("%s/%s: a +Spec block opened at line %d is not closed"
                              % (label, x.name, code.count("\n", 0, m.start()) + 1))
                continue
            level = 0
            for line in code[m.end():j - 1].split("\n"):
                t = re.match(r"\s*([a-z][A-Za-z0-9_]*)\s*:", line) if level == 0 else None
                if t:
                    tags.add(t.group(1))
                level += sum({"{": 1, "}": -1, "<": 1, ">": -1}.get(c, 0) for c in line)
    return tags, errors


def meta_violations(libs):
    """One declarer per meta tag across the libs. Two declarers coexist in a namespace, but an unqualified meta lookup
    there is ambiguous, and a lib depending on both fails to compile."""
    out, by_tag = [], {}
    for name, f in libs.items():
        tags, errors = meta_tags(f.parent, name)
        out += errors
        for tag in tags:
            by_tag.setdefault(tag, set()).add(name)
    for tag, names in sorted(by_tag.items()):
        if len(names) < 2 or tuple(sorted(names)) == DUPLICATE_META_ALLOWED.get(tag):
            continue
        out.append("meta tag '%s' is declared by %s; no two libs may declare one meta tag"
                   % (tag, ", ".join(sorted(names))))
    for tag, pair in sorted(DUPLICATE_META_ALLOWED.items()):
        now = sorted(by_tag.get(tag, ()))
        if now != sorted(pair):
            out.append("the allowed duplicate meta tag '%s' of %s is stale: it is declared by %s now; remove it from "
                       "DUPLICATE_META_ALLOWED" % (tag, ", ".join(pair), ", ".join(now) or "no lib"))
    return out


def compiler_depends(files, fan_home):
    """The xeto compiler's own reading of each file's depends, by xeto_depends.fan (XetoEnv.readAst):
    {str(file): {"depends": [...], "versions": [...]} or {"error": msg}}, versions null where a depend has none. The
    reference the generated-form reader is tested against, and the reader `--compiler` uses where a toolchain is
    installed."""
    fan = pathlib.Path(fan_home) / "bin" / ("fan.bat" if os.name == "nt" else "fan")
    env = dict(os.environ, FAN_HOME=str(fan_home))
    res = subprocess.run([str(fan), str(HERE / "xeto_depends.fan")] + [str(f) for f in files],
                         capture_output=True, text=True, encoding="utf-8", env=env)
    rows = [json.loads(line) for line in res.stdout.splitlines() if line.startswith("{")]
    if res.returncode != 0 or len(rows) != len(files):
        raise RuntimeError("xeto_depends.fan failed (exit %d): %s" % (res.returncode, res.stderr[-2000:]))
    return {r.pop("file"): r for r in rows}


def notice_pair_ok(text):
    """True when a line is kW's copyright notice and the next line is the AFL-3.0 licensing notice."""
    lines = text.splitlines()
    return any(COPYRIGHT_RE.match(lines[i]) and lines[i + 1] == AFL_LINE for i in range(len(lines) - 1))


def violations(root, reader=None):
    """Every violation under `root` (src/xeto). `reader` maps a generated lib's lib.xeto path to its depends; by
    default pragma_depends. A reader's ValueError is reported here as a violation (fail closed)."""
    out = []
    libs, others = lib_files(root)
    for lib in ALL_OPEN:
        if lib not in libs:
            out.append("%s: no lib.xeto directly under %s (a generated lib is missing)" % (lib, root.name))
    seen = set(libs)
    for f in others:
        name = f.parent.name
        if name in seen:
            out.append("%s: duplicate lib.xeto at %s; a lib is found once, directly under %s"
                       % (name, f.relative_to(root).as_posix(), root.name))
        seen.add(name)
    for name in [l for l in generate.OPEN_LIBS if l in libs]:
        f = libs[name]
        allowed = set(generate.OPEN_DEPENDS[name])
        try:
            deps = reader(f) if reader else pragma_depends(f.read_text(encoding="utf-8"))
        except ValueError as e:
            out.append("%s: %s" % (name, e))
            deps = []
        for dep in deps:
            if dep not in allowed:
                out.append("%s depends on %s, outside its allowed set %s" % (name, dep, sorted(allowed)))
        out += notice_violations(name, f.parent)
        out += vocabulary_violations(name, f.parent)
        out += name_violations(root, name, f.parent)
    return out + meta_violations(libs)


@functools.lru_cache(maxsize=128)
def code_of(text):
    """_code, remembered by text: the name check reads the same generated files once per tree, not once per call."""
    return _code(text)


def lib_names(texts):
    """The spec names (top-level, upper case first) and instance names (`@name`) some .xeto texts declare."""
    out = set()
    for text in texts:
        code = code_of(text)
        out |= set(re.findall(r"(?m)^([A-Z]\w*)\s*:", code))
        out |= set(re.findall(r"(?m)^@([\w-]+)\s*:", code))
    return out


def xeto_names(src):
    """{lib: sorted names} for the PINNED_LIBS under a Project Haystack xeto src/xeto directory."""
    src = pathlib.Path(src)
    return {lib: sorted(lib_names(x.read_text(encoding="utf-8") for x in sorted((src / lib).glob("*.xeto"))))
            for lib in PINNED_LIBS}


def known_names(root, lib):
    """The names lib `lib` declares, from the source this check trusts for it; None when it has none."""
    if lib in generate.OPEN_LIBS:
        return lib_names(x.read_text(encoding="utf-8") for x in sorted((root / lib).glob("*.xeto")))
    if lib == "hx.comps":
        return set(json.loads(HX_INDEX.read_text(encoding="utf-8")))
    if lib in PINNED_LIBS:
        return set(json.loads(XETO_NAMES.read_text(encoding="utf-8"))[lib])
    return None


def name_violations(root, name, d):
    """Every qualified name in generated lib `name` (directory `d`) that names a lib outside its depends, or a name
    its lib does not declare, by file and line. Comments and strings are not read."""
    allowed = set(generate.OPEN_DEPENDS[name]) | {name}
    cache, out = {}, []
    for x in sorted(d.glob("*.xeto")):
        code = code_of(x.read_text(encoding="utf-8"))
        for m in QUALIFIED.finditer(code):
            lib, nm = m.group(1), m.group(2)
            if lib not in cache and lib in allowed:
                cache[lib] = known_names(root, lib)
            if lib not in allowed:
                why = "and %s is outside its depends" % lib
            elif cache[lib] is None or nm not in cache[lib]:
                why = "which %s does not declare" % lib
            else:
                continue
            line = code.count("\n", 0, m.start()) + 1      # counted only for a violation: the files are large
            out.append("%s/%s:%d names %s::%s, %s" % (name, x.name, line, lib, nm, why))
    return out


def notice_violations(name, d):
    """A generated lib's notices: AFL-3.0 beside kW's copyright in every .xeto, and MBL's licence in NOTICE."""
    out = []
    for x in sorted(d.glob("*.xeto")):
        if not notice_pair_ok(x.read_text(encoding="utf-8")):
            out.append("%s/%s: no AFL-3.0 licensing notice adjacent to kW's copyright notice" % (name, x.name))
    notice = d / "NOTICE"
    if not notice.exists() or "Modelica Buildings Library" not in notice.read_text(encoding="utf-8"):
        out.append("%s: NOTICE missing or without MBL's licence" % name)
    # The packer ships a lib's .xeto files and chapters only; NOTICE reaches the xetolib only when the pragma
    # publishes it, so a NOTICE the pragma does not name is missing from every build.
    lib_xeto = d / "lib.xeto"
    if notice.exists() and lib_xeto.exists():
        m = re.search(r'(?m)^  publish: \{([^}\n]*)\}$', lib_xeto.read_text(encoding="utf-8"))
        if m is None or "/NOTICE" not in PUBLISH_ITEM.findall(m.group(1)):
            out.append('%s: its pragma does not publish "/NOTICE", so the xetolib ships without MBL\'s licence' % name)
    return out


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--xeto-names"] and len(args) == 2:
        # The names xeto_names.json pins, from a Project Haystack xeto checkout's src/xeto.
        print(json.dumps(xeto_names(args[1]), indent=1))
        return 0
    use_compiler = "--compiler" in args
    args = [a for a in args if a != "--compiler"]
    root = pathlib.Path((args or [str(generate.REPO / generate.LIBS)])[0])
    reader = None
    if use_compiler:
        # The compiler's reading in place of the hand reader, where FAN_HOME holds a Haxall toolchain.
        libs = lib_files(root)[0]
        read = compiler_depends([libs[l] for l in ALL_OPEN if l in libs], os.environ["FAN_HOME"])

        def row_of(f):
            row = read[str(f)]
            if "error" in row:
                raise ValueError("the xeto compiler refuses it: " + row["error"])
            return row

        def reader(f):
            return row_of(f)["depends"]
    bad = violations(root, reader)
    for line in bad:
        print(line)
    print("generated libs: %s; violations: %d" % (", ".join(generate.OPEN_LIBS), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
