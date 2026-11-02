"""An independent reader for the subset of Modelica the CDL blocks use.

It shares no code with cxf.py or generate.py on purpose. The round trip checks the
generator against MBL's own source, so it must not share the parser it checks.
Returns {params, inputs, outputs, components, connects} for one class, plus, when MBL's tree is given,
ports: each instance connector's declared causality ("in" or "out"), read from the instance class's own .mo.
"""
import functools
import pathlib
import re

CONN = {"RealInput": "Real", "IntegerInput": "Integer", "BooleanInput": "Boolean",
        "RealOutput": "Real", "IntegerOutput": "Integer", "BooleanOutput": "Boolean"}


def _mask(s):
    strs = []

    def keep(m):
        strs.append(m.group(0))
        return '"\x00%d\x00"' % (len(strs) - 1)
    s = re.sub(r'"(?:[^"\\]|\\.)*"', keep, s)
    s = re.sub(r"//[^\n]*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s, strs


def _unmask(s, strs):
    return re.sub(r'"\x00(\d+)\x00"', lambda m: strs[int(m.group(1))], s)


def _drop(s, word):
    out, i = [], 0
    pat = re.compile(r"\b%s\s*\(" % word)
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:m.start()])
        j, depth = m.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(s[j], 0)
            j += 1
        i = j


def _split(s, sep):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _balanced(s, i):
    depth, j = 0, i
    while True:
        depth += {"(": 1, ")": -1}.get(s[j], 0)
        j += 1
        if depth == 0:
            return s[i + 1:j - 1], j


def _decl(stmt):
    m = re.match(r"((?:(?:final|parameter|constant|discrete|input|output|replaceable)\s+)*)([A-Za-z_][\w.]*)\s+"
                 r"([A-Za-z_]\w*)\s*", stmt)
    if not m:
        return None
    prefix, typ, name = m.group(1).split(), m.group(2), m.group(3)
    rest, mods = stmt[m.end():], ""
    array = rest.startswith("[")
    if array:
        # An array declaration, `parameter Real k[nin]=fill(1, nin)`: the subscript sits between the name
        # and the modifiers or default, and is the type's size, not part of either.
        depth, j = 0, 0
        while True:
            depth += {"[": 1, "]": -1}.get(rest[j], 0)
            j += 1
            if depth == 0:
                break
        rest = rest[j:].lstrip()
    if rest.startswith("("):
        mods, k = _balanced(rest, 0)
        rest = rest[k:].strip()
    default = cond = None
    # `= if c then a else b` is an if-expression default, not a conditional declaration (`... if c`): read it to
    # the description string (Reheat Controller's heaCoi, MBL 14.0.0).
    im = re.match(r"=\s*(if\b.*?)\s*(?=(\"\x00|$))", rest, re.S)
    dm = im or re.match(r"=\s*(.*?)\s*(?=(\bif\b|\"\x00|$))", rest, re.S)
    if dm:
        default = dm.group(1).strip() or None
        rest = rest[dm.end():].strip()
    cm = re.match(r"if\s+(.*?)\s*(?=(\"\x00|$))", rest, re.S)
    if cm:
        cond = cm.group(1).strip()
    return prefix, typ, name, mods, default, cond, array


UNIT_ATTRS = ("unit", "quantity", "displayUnit")


def _mods(mods, strs):
    """Modifier name -> value text, and the set of names written `final`. Split while strings are still masked, so
    a comma inside a message string does not split it. A nested modifier that sets only unit attributes on a
    sub-connector (`u1(final unit="Pa", displayUnit="Pa")`) is not a binding: its unit is returned in the third
    result, sub-connector name -> unit, so the round trip checks it."""
    out, finals, units = {}, set(), {}
    for part in _split(mods, ","):
        pre = re.match(r"^(?:(?:final|each)\s+)*", part).group(0)
        words, part = pre.split(), part[len(pre):]
        nm = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)$", part, re.S)
        if nm and all(re.match(r"^(?:final\s+)?(%s)\s*=" % "|".join(UNIT_ATTRS), x) for x in _split(nm.group(2), ",")):
            um = re.search(r"\bunit\s*=\s*(\S+?)\s*(?:,|$)", nm.group(2))
            if um:
                u = _unmask(um.group(1), strs).strip('"')
                units[nm.group(1)] = UNIT.get(u, u)
            continue
        if "=" in part and not part.startswith("("):
            k, v = part.split("=", 1)
            out[k.strip()] = _unmask(v.strip(), strs)
            if "final" in words:
                finals.add(k.strip())
    return out, finals, units


# Modelica unit strings -> the Haystack symbols the generator writes (one symbol per unit).
UNIT = {"m3/s": "m³/s", "degC": "°C", "1": "1"}


def is_extension_block(src):
    """231 5.9 names __cdl(extensionBlock=true); 6.7 misspells it extenstion. Recognize both."""
    return re.search(r"__cdl\s*\([^)]*\bexten(?:s|st)ion(?:Block)?\s*=\s*true", src) is not None


def _call_args(s, word):
    """The text inside the first top-level `word(...)` of s, or None."""
    m = re.search(r"\b%s\s*\(" % re.escape(word), s)
    if not m:
        return None
    inner, _ = _balanced(s, m.end() - 1)
    return inner


def _dialog(stmt, strs):
    """Dialog(enable, group, tab) and __cdl(ValueInReference) from one declaration's annotation, read from MBL's
    source text: {"enable": text, "group": str, "tab": str, "valueInReference": bool}, keys only where present."""
    ann = _call_args(stmt, "annotation")
    out = {}
    if ann is None:
        return out
    dia = _call_args(ann, "Dialog")
    for part in _split(dia or "", ","):
        k, _, v = part.partition("=")
        k, v = k.strip(), _unmask(v.strip(), strs)
        if k == "enable":
            out["enable"] = v
        elif k in ("group", "tab"):
            out[k] = v.strip('"')
    cdl = _call_args(ann, "__cdl")
    m = re.search(r"\bValueInReference\s*=\s*(true|false)\b", cdl or "")
    if m:
        out["valueInReference"] = m.group(1) == "true"
    return out


def read(src, cls, root=None):
    """`root` is the directory holding MBL's Buildings/ tree; with it, a relative class name resolves by Modelica's
    lookup through the enclosing packages (Types.EnergyStandard from G36.AHUs...); without it, by the class path."""
    s, strs = _mask(src)
    res0 = {"extensionBlock": is_extension_block(src)}
    res = {"params": {}, "inputs": {}, "outputs": {}, "components": {}, "connects": set()}
    section = "public"
    leaf = cls.rsplit(".", 1)[1]
    s = re.sub(r"\bwithin\b[^;]*;", "", s)
    s = re.sub(r"^\s*(?:partial\s+)?(?:block|model)\s+%s\s*(\"\x00\d+\x00\")?" % leaf, "", s.strip())
    nested = None
    for stmt in _split(s, ";"):
        dialog = _dialog(stmt, strs)
        stmt = _drop(stmt, "annotation").strip()
        if nested is not None:
            # Inside a class defined within this one (VariablePulse.mo's `block Cycle`): its members are its
            # own, not this class's, so skip to its `end`.
            body = re.sub(r"^(?:(?:protected|public|initial\s+equation|equation|initial\s+algorithm|algorithm)\b\s*)*",
                          "", stmt)
            if re.match(r"end\s+%s$" % re.escape(nested), body):
                nested = None
            continue
        while True:
            m = re.match(r"(protected|public|initial\s+equation|equation)\b\s*", stmt)
            if not m:
                break
            section = {"protected": "protected", "public": "public"}.get(m.group(1), "equation")
            stmt = stmt[m.end():]
        if not stmt or stmt.startswith("end ") or stmt.startswith("extends "):
            continue
        nm = re.match(r"(?:(?:encapsulated|partial)\s+)*(?:block|model|function|record|package)\s+([A-Za-z_]\w*)\b(?!\s*=)",
                      stmt)
        if nm:
            nested = nm.group(1)
            continue
        if section == "equation":
            # MBL sometimes writes a space after the dot (`connect(TDis,addPar. u)`, SystemRequests.mo:406)
            for a, b in re.findall(r"connect\s*\(\s*([\w.\[\]\s]+?)\s*,\s*([\w.\[\]\s]+?)\s*\)", stmt):
                res["connects"].add(frozenset((re.sub(r"\s+", "", a), re.sub(r"\s+", "", b))))
            continue
        d = _decl(stmt)
        if d is None:
            continue
        prefix, typ, name, mods, default, cond, array = d
        m, finals, cunits = _mods(mods, strs)
        leaf_type = typ.rsplit(".", 1)[-1]
        u = (m.get("unit") or "").strip('"') or None
        fm = re.match(r'^fill\(\s*"([^"]*)"\s*,.*\)$', m.get("unit") or "", re.S)
        if fm:
            u = fm.group(1)          # an array's unit, `unit=fill("K", nZon)`: one unit for every element
        if "parameter" in prefix:
            if default is not None and re.match(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$", default) \
                    and not default.startswith("Buildings."):
                # A relative enumeration literal (`CDL.Types.Smoothness.LinearSegments`, TimeTable.mo) is
                # qualified by the same lookup as a relative component class.
                default = _scope(default, cls, root)
            if typ not in ("Real", "Integer", "Boolean", "String") and not typ.startswith("Buildings."):
                typ = _scope(typ, cls, root)
            res["params"][name] = {"default": default, "unit": UNIT.get(u, u),
                                   "protected": section == "protected", "type": typ,
                                   "final": "final" in prefix, "array": array, "dialog": dialog}
        elif leaf_type in CONN and ".Interfaces." in "." + typ:
            res["inputs" if "Input" in leaf_type else "outputs"][name] = {
                "type": CONN[leaf_type], "unit": UNIT.get(u, u), "array": array}
        elif typ in ("Real", "Integer", "Boolean"):
            continue
        else:
            full = typ if typ.startswith("Buildings.") else _scope(typ, cls, root)
            keep = {k: v for k, v in m.items() if k not in ("unit", "quantity", "displayUnit")}
            res["components"][name] = {"class": full, "binds": keep, "cond": cond,
                                       "finals": {k for k in finals if k in keep}, "units": cunits}
    res.update(res0)
    if root is not None:
        # The causality of every instance connector, read from the instance class's own source (the
        # round trip checks each generated link runs from a source-side endpoint into a sink-side one). MBL's CDL
        # and G36 blocks declare their connectors directly (no `extends`, measured at 14.0.0), so the class file is
        # the whole answer. A class with no file of its own gives no ports, and compare() refuses its links.
        res["ports"] = {}
        for name, comp in res["components"].items():
            for port, way in _causality(str(root), comp["class"]).items():
                res["ports"][name + "." + port] = way
    return res


@functools.lru_cache(maxsize=None)
def _causality(root, cls):
    f = pathlib.Path(root).joinpath(*cls.split(".")).with_suffix(".mo")
    if not f.is_file():
        return {}
    r = read(f.read_text(encoding="utf-8"), cls)
    return dict({n: "in" for n in r["inputs"]}, **{n: "out" for n in r["outputs"]})


def _scope(typ, cls, root=None):
    """Modelica lookup for a relative component class, written independently of cxf.resolve_class: the innermost
    enclosing package that holds an element named like the name's first part, by the files of MBL's tree."""
    pkgs = cls.split(".")[:-1]
    first = typ.split(".")[0]
    if root is not None:
        import pathlib
        for i in range(len(pkgs), 0, -1):
            base = pathlib.Path(root).joinpath(*pkgs[:i])
            if (base / first).is_dir() or (base / (first + ".mo")).is_file():
                return ".".join(pkgs[:i] + [typ])
    for i in range(len(pkgs), 0, -1):
        if pkgs[i - 1] == first:
            return ".".join(pkgs[:i - 1] + [typ])
    return ".".join(pkgs[:3] + [typ]) if first == "CDL" else typ
