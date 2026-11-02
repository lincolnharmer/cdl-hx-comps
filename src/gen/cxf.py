#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Read modelica-json CXF (JSON-LD) into a normalized form.

Shared by generate.py, classmap.py, hxemit.py and mjson.py. mo_reader.py shares nothing with it on purpose:
the round trip in test_generate.py checks this code against MBL's own source.
"""
import json
import pathlib
import re
import sys

S231 = "http://data.ashrae.org/S231#"
QUDT = "http://qudt.org/schema/qudt#"
XSD = "http://www.w3.org/2001/XMLSchema#"


class CxfError(Exception):
    pass


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def local(iri):
    """'http://example.org#A.B' -> 'A.B'. CXF class and instance ids live after the '#'.

    modelica-json writes an array element endpoint as an absolute IRI with the brackets percent-encoded
    (`...intSum.u%5B1%5D`); the local name decodes them to `u[1]`. Nothing else is decoded."""
    if not (isinstance(iri, str) and "#" in iri):
        return iri
    return iri.split("#", 1)[1].replace("%5B", "[").replace("%5D", "]")


class Cxf:
    """One CXF document with every key, @id and @type expanded against @context."""

    def __init__(self, doc, name="CXF"):
        self.name = name                # the file name, for refusals that name the file
        self.ctx = {k: v for k, v in doc.get("@context", {}).items() if isinstance(v, str)}
        self.nodes = {}
        for raw in doc.get("@graph", []):
            node = {}
            for k, v in raw.items():
                key = k if k.startswith("@") else self.expand(k)
                node[key] = self._val(v)
            node["@id"] = self.expand(raw["@id"])
            if "@type" in raw:
                node["@type"] = self.expand(raw["@type"])
            if node["@id"] in self.nodes:
                raise CxfError("duplicate node " + node["@id"])
            self.nodes[node["@id"]] = node

    @staticmethod
    def load(path):
        with open(path, encoding="utf-8") as f:
            return Cxf(json.load(f), pathlib.Path(path).name)

    def expand(self, s):
        if not isinstance(s, str) or s.startswith("http://") or s.startswith("https://"):
            return s
        if ":" in s:
            prefix, rest = s.split(":", 1)
            if prefix in self.ctx:
                return self.ctx[prefix] + rest
        return s

    def _val(self, v):
        if isinstance(v, list):
            return [self._val(x) for x in v]
        if isinstance(v, dict) and set(v) == {"@id"}:
            return {"@id": self.expand(v["@id"])}
        return v

    def get(self, node, prop):
        return node.get(prop if prop.startswith("http") else S231 + prop)

    def ids(self, node, prop):
        return [x["@id"] for x in as_list(self.get(node, prop))]

    def node(self, nid):
        n = self.nodes.get(nid)
        if n is None:
            raise CxfError("no node " + nid)
        return n


def literal(v):
    """(value, expr): a JSON number or boolean is a value; an xsd typed literal is a value;
    a string is an expression (a parent parameter name, an enum literal or arithmetic)."""
    if isinstance(v, bool):
        return v, None
    if isinstance(v, (int, float)):
        return float(v), None
    if isinstance(v, dict) and "@value" in v:
        t = v.get("@type", "")
        if t.endswith("boolean"):
            return str(v["@value"]).lower() == "true", None
        return float(v["@value"]), None
    if isinstance(v, str):
        return None, v
    raise CxfError("unreadable value %r" % (v,))


CONNECT = ("isConnectedTo", "connectedTo")   # modelica-json's spelling, and 231 Table 6-2's


def continuous_refusal(cls):
    """231's informative examples use the old CDL.Continuous.* names; Clause 7 says CDL.Reals.*.
    Refuse with the Clause 7 name, never alias silently."""
    i = cls.find("CDL.Continuous.")
    if i < 0:
        return None
    return "class %s uses the old package name CDL.Continuous; 231 Clause 7 names it %s" % (
        cls, cls[:i] + "CDL.Reals." + cls[i + len("CDL.Continuous."):])


def resolve_class(raw, scope, known):
    """Modelica name lookup up the within chain. A class name may be relative to the
    packages that enclose `scope`: try the name as written, then under each enclosing prefix."""
    why = continuous_refusal(raw)
    if why:
        raise CxfError(why)
    if raw in known:
        return raw
    parts = scope.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i]) + "." + raw
        if cand in known:
            return cand
    raise CxfError("class %s does not resolve from %s" % (raw, scope))


# ---- expression grammar: numbers, booleans, names, + - * /, not, and, or, comparisons, parentheses, unary minus,
# ---- enum literals, the two array functions fill(v, n) and size(a, 1), the array literal {..}, the matrix literal
# ---- [..;..], the range a:b, fill(v, n1, n2) and size(a, 2). Anything else refuses, quoting the expression. An
# ---- environment value is a float, a Boolean, an enum item name, a list of floats or Booleans (a one-dimensional
# ---- array parameter) or a list of such lists of one length (a two-dimensional one).

_TOKEN = re.compile(r"(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)"
                    r"|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
                    r"|(<=|>=|==|<>|[-+*/()<>,{}\[\];:])")


def _tokens(src):
    out, pos = [], 0
    while pos < len(src):
        if src[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(src, pos)
        if not m:
            raise CxfError("expression outside the grammar: %r" % src)
        num, name, op = m.groups()
        out.append(("num", float(num)) if num else ("name", name) if name else ("op", op))
        pos = m.end()
    return out


KEYWORDS = ("true", "false", "not", "and", "or", "if", "then", "else", "elseif")
# The grammar's accepted and refused expressions live in src/fan/cdlResolve/test/res/expression-cases.json, the one
# table both evaluators (this one and the resolver's) are tested against.


class _Parser:
    def __init__(self, src, env, enum_item):
        self.src, self.env, self.enum_item = src, env, enum_item
        self.toks, self.i = _tokens(src), 0

    def fail(self, why):
        raise CxfError("%s in expression %r" % (why, self.src))

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def at(self, kind, *vals):
        k, v = self.peek()
        return k == kind and v in vals

    def boolean(self, v):
        if not isinstance(v, bool):
            self.fail("expected a Boolean")
        return v

    def number(self, v):
        if isinstance(v, bool) or not isinstance(v, float):
            self.fail("expected a number")
        return v

    def scalar(self, v):
        """== and <> compare scalars only: a list in a comparison refuses."""
        if isinstance(v, list):
            self.fail("expected a number")
        return v

    def parse(self):
        v = self.expr()
        if self.i != len(self.toks):
            self.fail("unexpected token %r" % (self.peek()[1],))
        return v

    def expr(self):
        """Modelica's if-expression, `if c then a else b`, binding looser than everything else: a branch extends as
        far as it can, so `if c then 1 else 2 + 3` takes 2 + 3 on else, and an if inside an operator needs
        parentheses, as in Modelica. Both branches are evaluated, and the condition must be a Boolean. `elseif`
        refuses: no expression in the G36 libraries at MBL 14.0.0 uses it."""
        if not self.at("name", "if"):
            return self.or_()
        self.take()
        c = self.boolean(self.expr())
        if not self.at("name", "then"):
            self.fail("if without then")
        self.take()
        a = self.expr()
        if self.at("name", "elseif"):
            self.fail("elseif, which no G36 expression uses")
        if not self.at("name", "else"):
            self.fail("if without else")
        self.take()
        b = self.expr()
        return a if c else b

    def or_(self):
        v = self.and_()
        while self.at("name", "or"):
            self.take()
            r = self.and_()
            v = self.boolean(v) or self.boolean(r)
        return v

    def and_(self):
        v = self.not_()
        while self.at("name", "and"):
            self.take()
            r = self.not_()
            v = self.boolean(v) and self.boolean(r)
        return v

    def not_(self):
        if self.at("name", "not"):
            self.take()
            return not self.boolean(self.not_())
        return self.cmp()

    def cmp(self):
        v = self.range_()
        if self.at("op", "<", "<=", ">", ">=", "==", "<>"):
            op = self.take()[1]
            r = self.range_()
            if op == "==":
                return self.scalar(v) == self.scalar(r)
            if op == "<>":
                return self.scalar(v) != self.scalar(r)
            a, b = self.number(v), self.number(r)
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        return v

    def range_(self):
        """a:b, a and b whole numbers: the list a, a+1, ..., b, empty when b < a. It binds looser
        than + - * / and tighter than a comparison, as in Modelica. A step (a:s:b) refuses."""
        v = self.add()
        if self.at("op", ":"):
            self.take()
            r = self.add()
            if self.at("op", ":"):
                self.fail("range with a step")
            a, b = self.number(v), self.number(r)
            if a != int(a) or b != int(b):
                self.fail("range bounds %r:%r are not whole numbers" % (a, b))
            return [float(x) for x in range(int(a), int(b) + 1)]
        return v

    def add(self):
        v = self.mul()
        while self.at("op", "+", "-"):
            op = self.take()[1]
            r = self.mul()
            v = self.number(v) + self.number(r) if op == "+" else self.number(v) - self.number(r)
        return v

    def mul(self):
        v = self.unary()
        while self.at("op", "*", "/"):
            op = self.take()[1]
            r = self.unary()
            if op == "*":
                v = self.number(v) * self.number(r)
            else:
                if self.number(r) == 0.0:
                    self.fail("division by zero")
                v = self.number(v) / r
        return v

    def unary(self):
        if self.at("op", "-"):
            self.take()
            return -self.number(self.unary())
        if self.at("op", "+"):
            self.take()
            return self.number(self.unary())
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            return v
        if k == "op" and v == "(":
            r = self.expr()
            if not self.at("op", ")"):
                self.fail("missing )")
            self.take()
            return r
        if k == "op" and v == "{":
            return self.brace()
        if k == "op" and v == "[":
            return self.matrix()
        if k == "name":
            if v in ("true", "false"):
                return v == "true"
            if v in ("not", "and", "or", "if", "then", "else", "elseif"):
                self.fail("misplaced " + v)
            if self.at("op", "("):
                if v == "fill":
                    return self.fill()
                if v == "size":
                    return self.size()
                self.fail("function call")
            if "." in v:
                item = self.enum_item(v)
                if item is None:
                    self.fail("dotted name %s is not an enum literal or a package constant" % v)
                return item
            if v not in self.env:
                self.fail("unknown name " + v)
            return self.env[v]
        self.fail("unexpected token %r" % (v,))


    def args(self):
        """The comma-separated arguments of a call, the opening ( still to take."""
        self.take()
        out = [self.expr()]
        while self.at("op", ","):
            self.take()
            out.append(self.expr())
        if not self.at("op", ")"):
            self.fail("missing )")
        self.take()
        return out

    def brace(self):
        """{e1, e2, ...}: a list, nested once for two dimensions; the opening { is taken."""
        out = []
        if self.at("op", "}"):
            self.take()
            return out
        out.append(self.expr())
        while self.at("op", ","):
            self.take()
            out.append(self.expr())
        if not self.at("op", "}"):
            self.fail("missing }")
        self.take()
        if any(isinstance(x, list) for x in out):
            if not all(isinstance(x, list) for x in out):
                self.fail("array literal mixing rows and scalars")
            if any(isinstance(y, list) for x in out for y in x):
                self.fail("array literal nested past two dimensions")
            if len({len(x) for x in out}) > 1:
                self.fail("array literal with rows of unequal length")
        return out

    def matrix(self):
        """[e11, e12; e21, e22]: a list of rows, ; between rows and , between columns; the
        opening [ is taken. A single row is still two-dimensional."""
        rows, row = [], []
        if self.at("op", "]"):
            self.fail("empty matrix literal")
        while True:
            x = self.expr()
            if isinstance(x, list):
                self.fail("matrix literal element that is a list")
            row.append(x)
            if self.at("op", ","):
                self.take()
                continue
            if self.at("op", ";"):
                self.take()
                rows.append(row)
                row = []
                continue
            if self.at("op", "]"):
                self.take()
                rows.append(row)
                break
            self.fail("missing ]")
        if len({len(r) for r in rows}) > 1:
            self.fail("matrix literal with rows of unequal length")
        return rows

    def fill(self):
        """fill(v, n): n copies of v, v a number or a Boolean, n a whole number >= 0; fill(v, n1, n2): n1 rows of n2
        copies."""
        a = self.args()
        if len(a) not in (2, 3):
            self.fail("fill takes two or three arguments")
        v, ns = a[0], a[1:]
        if not isinstance(v, (bool, float)):
            self.fail("fill of something other than a number or a Boolean")
        for n in ns:
            n = self.number(n)
            if n < 0 or n != int(n):
                self.fail("fill count %r is not a whole number >= 0" % n)
        if len(ns) == 2:
            return [[v] * int(ns[1]) for _ in range(int(ns[0]))]
        return [v] * int(ns[0])

    def size(self):
        """size(a, 1): the length of the list a NAME is bound to, as a float; size(a, 2): its row length, when it
        is a list of rows."""
        self.take()
        k, name = self.take()
        if k != "name" or "." in name or name in KEYWORDS or self.at("op", "("):
            self.fail("size of something other than a name")
        if not self.at("op", ","):
            self.fail("size takes two arguments, the second 1 or 2")
        self.take()
        d = self.expr()
        if not self.at("op", ")"):
            self.fail("size takes two arguments, the second 1 or 2")
        self.take()
        if isinstance(d, bool) or d not in (1.0, 2.0):
            self.fail("size of a dimension other than 1 or 2")
        if name not in self.env:
            self.fail("unknown name " + name)
        a = self.env[name]
        if not isinstance(a, list):
            self.fail("size of %s, which is not an array" % name)
        if d == 1.0:
            return float(len(a))
        if not a or not all(isinstance(r, list) for r in a):
            self.fail("size of %s in dimension 2, which has one dimension" % name)
        return float(len(a[0]))

def names(src):
    """Every name an expression mentions, dotted or not, in order of first appearance (keywords and literals
    excluded). Refuses an expression outside the grammar, as evaluate does."""
    out = []
    for kind, v in _tokens(src):
        if kind == "name" and v not in KEYWORDS and v not in out:
            out.append(v)
    return out


def evaluate(src, env, enum_item):
    """Evaluate a CDL expression. env maps CDL names to a float, a bool, an enum item name or a list."""
    if re.search(r"[A-Za-z0-9_)\]}]\s*\[", src):
        raise CxfError("array subscript in expression %r" % src)      # a [ after a value; a matrix literal's [ opens
    return _Parser(src, env, enum_item).parse()


# ---- merge: several CXF files into one, deterministic (sorted by @id, union of contexts)

def _lf(v):
    """CRLF to LF in every string. modelica-json copies MBL's documentation text from the working tree, so a
    Windows checkout with autocrlf writes CRLF where MBL's repository holds LF. The pinned source must not
    depend on the platform that regenerated it."""
    if isinstance(v, str):
        return v.replace("\r\n", "\n")
    if isinstance(v, list):
        return [_lf(x) for x in v]
    if isinstance(v, dict):
        return {k: _lf(x) for k, x in v.items()}
    return v


def merge(out_path, in_paths):
    ctx, nodes = {}, {}
    for p in in_paths:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        for k, v in doc.get("@context", {}).items():
            if k in ctx and ctx[k] != v:
                raise CxfError("context prefix %s differs between files" % k)
            ctx[k] = v
        for n in doc.get("@graph", []):
            n = _lf(n)
            if n["@id"] in nodes and nodes[n["@id"]] != n:
                raise CxfError("node %s differs between files" % n["@id"])
            nodes[n["@id"]] = n
    doc = {"@context": dict(sorted(ctx.items())), "@graph": [nodes[k] for k in sorted(nodes)]}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


# Keys of modelica-json's json output that depend on the machine that ran it, never on the class: the absolute
# path, and the checksum of the .mo file as it sits on disk (a Windows autocrlf checkout gives MBL's LF source CRLF,
# so the same class checksums differently on two machines).
MACHINE_KEYS = ("fullMoFilePath", "checksum")
# The annotations of modelica-json's json output that the generator reads: Dialog (enable, group, tab) and __cdl
# (ValueInReference). Every other annotation is graphics or documentation (Placement, Line, Icon, Diagram,
# Documentation, defaultComponentName, Evaluate) and is dropped when pinned, with
# the equation sections, whose connects the generator reads from CXF. What is kept is otherwise byte for byte the
# tool's output: keys, nesting and expression trees unchanged.
JSON_ANNOTATIONS = ("Dialog", "__cdl")


def _ann_name(a):
    """The name of one annotation entry: Dialog(...) carries `name`, graphics such as Placement(...) a single key."""
    em = (a.get("element_modification_or_replaceable") or {}).get("element_modification") if isinstance(a, dict) else None
    if not isinstance(em, dict):
        return None
    return em.get("name") if "name" in em else next(iter(em), None)


def prune_json(v):
    """A json output with only the annotations in JSON_ANNOTATIONS, and no equation sections."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k == "equation_section":
                continue
            if k == "annotation" and isinstance(x, list):
                x = [a for a in x if _ann_name(a) in JSON_ANNOTATIONS]
                if not x:
                    continue
            out[k] = prune_json(x)
        return out
    if isinstance(v, list):
        return [y for y in (prune_json(x) for x in v) if y != {}]
    return v


def pin_json(out_path, in_path, prune=False):
    """modelica-json's json output of one class or package, pinned: the machine-dependent keys dropped, the relative
    .mo path in forward slashes, CRLF to LF, keys sorted, and with `prune` only the annotations generate.py reads."""
    with open(in_path, encoding="utf-8") as f:
        doc = _lf(json.load(f))
    for k in MACHINE_KEYS:
        doc.pop(k, None)
    if isinstance(doc.get("modelicaFile"), str):
        doc["modelicaFile"] = doc["modelicaFile"].replace("\\", "/")
    if prune:
        doc = prune_json(doc)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")


G36_DIR = "Buildings/Controls/OBC/ASHRAE/G36/"


def pin_g36(run_dir, root):
    """Distribute one modelica-json run over the G36 classes (one run per class: a whole-package run crashes on
    MBL's subscripted connects) into the source directory: each class's CXF to <lib>/cxf/<path under G36>.jsonld
    and its json output, pruned, to <lib>/json/<same>.json. The previous pins are removed first, so a class MBL drops
    leaves nothing behind. Plants classes refuse: no open lib holds them."""
    import pathlib
    import shutil
    import generate
    run, root = pathlib.Path(run_dir), pathlib.Path(root)
    for lib in generate.G36_LIBS:
        for sub in ("cxf", "json"):
            shutil.rmtree(root / lib / sub, ignore_errors=True)
    n = {"cxf": 0, "json": 0}
    for kind, ext in (("cxf", ".jsonld"), ("json", ".json")):
        base = run / kind / G36_DIR
        for f in sorted(base.rglob("*" + ext)):
            rel = f.relative_to(base).as_posix()[:-len(ext)]
            cls = "Buildings.Controls.OBC.ASHRAE.G36." + rel.replace("/", ".")
            if rel.endswith("/package"):
                continue          # constants packages are pinned by name in regen_cxf.sh
            lib = generate.g36_lib(cls)
            out = root / lib / kind / (rel + ext)
            out.parent.mkdir(parents=True, exist_ok=True)
            if kind == "cxf":
                merge(out, [f])
            else:
                pin_json(out, f, prune=True)
            n[kind] += 1
    print("pinned %d CXF and %d json outputs" % (n["cxf"], n["json"]))


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3:])
    elif len(sys.argv) in (4, 5) and sys.argv[1] == "pinjson":
        pin_json(sys.argv[2], sys.argv[3], prune=len(sys.argv) == 5 and sys.argv[4] == "--prune")
    elif len(sys.argv) == 4 and sys.argv[1] == "pin-g36":
        pin_g36(sys.argv[2], sys.argv[3])
    else:
        sys.exit("usage: cxf.py merge <out.jsonld> <in.jsonld>... | cxf.py pinjson <out.json> <in.json> [--prune]"
                 " | cxf.py pin-g36 <run dir> <source dir>")
