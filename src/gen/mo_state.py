#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""What MBL's source says about the state of a CDL elementary class: the reader behind kw.cdl's cdlState,
cdlStateInit, cdlStateInitBasis and cdlStateBasis.

It reads the .mo of each elementary class, which mbl_fetch.py downloads at MBL's release tag and verifies against
the sha256 mbl_manifest.json pins for each file (the version and commit src/gen/stamp.json pins). These are
"the pins" below. modelica-json 5460add3 cannot carry this: its json and raw-json outputs write every when-equation
as an empty node, so a when body's assignments and its pre() calls are lost, and the CXF carries no equations at
all. It shares no code with mo_reader.py (the round trip's independent reader) or cxf.py.

The facts, per class:

  state   "stateful" when its own equations, algorithms or declarations use pre(), edge(), change(), a when-clause,
          der(), delay(), sample() or reinit(), declare a discrete variable, or declare a parameter computed at
          initialization (fixed=false); or when it contains an instance, conditional or not, of a stateful class.
          "undecided" when no such construct appears and some part of it cannot be read: an instance of a class
          outside the pins, an impure function, any call outside CLASSIFIED_CALLS (never read as pure), or a parse
          failure. "stateless" otherwise.
  init    on a stateful class only. "readsInput" when at least one output's value at the initial instant reads an
          input connector, in every configuration of its conditional instances, through the initial equations and
          the equations active at that instant (those outside when-clauses, and a when branch whose condition holds
          initial()). A native hx.comps comp computes all its outputs in one execute that waits on its inputs, so
          one such output holds the whole comp. "noInput" otherwise: MBL alone shows no initial output that reads an
          input, which says nothing about whether a comp could. "undecided" when an unclassified
          call, an unread instance or an unproven conditional path stands in the way.
  why     on a noInput class only, why no input is read at the initial instant. "noInputConnector": the class
          declares no input connector. "preDelayed": after the initial instant every output reads the inputs only
          through pre(), and one does (MBL's loop-breaking idiom: no direct feedthrough). "parameterInit": the class
          reads an input after the initial instant, but its initial outputs come from parameters, start values or
          time; MBL does not say whether a comp would wait for that input. "undecided": a class with inputs and
          contained instances, whose paths this reading does not follow.
  basis   the constructs behind the state verdict, in a fixed order, then each stateful instance by name, then each
          reason a part of the class went unread.

A reference to `time` is not state: CivilTime's y = time recomputes at every instant.
"""
import pathlib
import re

CDL = "Buildings.Controls.OBC.CDL."
CLASS_KW = ("block", "model", "function", "package", "record", "connector", "type", "class", "operator")
CLASS_PREFIX = ("partial", "encapsulated", "final", "replaceable", "redeclare", "impure", "pure", "expandable",
                "inner", "outer")
COMP_PREFIX = ("final", "parameter", "constant", "discrete", "input", "output", "flow", "stream", "inner", "outer",
               "replaceable", "redeclare", "each")
KEYWORDS = {"if", "then", "else", "elseif", "and", "or", "not", "true", "false", "end", "for", "in", "loop", "when",
            "elsewhen", "while", "connect", "der", "initial", "each", "final", "return", "break"}
CONNECTORS = {"RealInput": "in", "IntegerInput": "in", "BooleanInput": "in",
              "RealOutput": "out", "IntegerOutput": "out", "BooleanOutput": "out"}
BUILTIN = {"Real", "Integer", "Boolean", "String"}
# The fixed order of the own constructs in cdlStateBasis.
OWN_ORDER = ("pre", "edge", "change", "when", "der", "delay", "sample", "reinit", "discrete", "initialParameter")
STATE_CALLS = ("pre", "edge", "change", "der", "delay", "sample", "reinit")
# Every call this reader has classified: the state operators above, initial(), and the pure functions and
# operators the 132 pinned classes call. A call outside this set (previous(), hold(), spatialDistribution(), a
# function outside the pins) is unread, so its class is undecided, never stateless. A function a class declares
# itself is classified by that declaration: pure unless declared impure. test_state.py pins this set to the corpus.
CLASSIFIED_CALLS = STATE_CALLS + ("initial",) + (
    "Buildings.Utilities.Math.Functions.round", "Buildings.Utilities.Psychrometrics.Functions.saturationPressure",
    "Modelica.Math.BooleanVectors.andTrue", "Modelica.Math.BooleanVectors.index", "Modelica.Math.Vectors.sort",
    "Modelica.Math.acos", "Modelica.Math.asin", "Modelica.Math.atan", "Modelica.Math.atan2", "Modelica.Math.cos",
    "Modelica.Math.exp", "Modelica.Math.log", "Modelica.Math.log10", "Modelica.Math.sin", "Modelica.Math.tan",
    "String", "abs", "assert", "ceil", "fill", "floor", "getInstanceName", "homotopy", "integer", "max", "min", "mod",
    "noEvent", "ones", "sin", "size", "smooth", "sqrt", "sum", "zeros")


class MoError(Exception):
    """A source this reader cannot read. The class is undecided, with this message as its reason."""


# ---- tokens ----

TOKEN = re.compile(r'''
    (?P<ws>\s+)
  | (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<op>:=|==|<>|<=|>=|\.\+|\.-|\.\*|\./|\.\^|[()\[\]{};,=+\-*/^<>:.])
''', re.S | re.X)


def tokens(text):
    """Modelica tokens: (kind, text) with kind str, num, id or op. Comments go; annotation(...) clauses go."""
    out, i = [], 0
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m:
            raise MoError("cannot tokenize at %r" % text[i:i + 30])
        i = m.end()
        kind = m.lastgroup
        if kind in ("ws", "lc", "bc"):
            continue
        out.append((kind, m.group(kind)))
    return drop_annotations(out)


def drop_annotations(toks):
    out, i = [], 0
    while i < len(toks):
        if toks[i] == ("id", "annotation") and i + 1 < len(toks) and toks[i + 1] == ("op", "("):
            j = close(toks, i + 1)
            i = j + 1
            continue
        out.append(toks[i])
        i += 1
    return out


def close(toks, i):
    """The index of the bracket that closes the one at toks[i]."""
    pair = {"(": ")", "[": "]", "{": "}"}
    depth, j = 0, i
    while j < len(toks):
        t = toks[j]
        if t[0] == "op" and t[1] in pair:
            depth += 1
        elif t[0] == "op" and t[1] in pair.values():
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise MoError("an unclosed %s" % toks[i][1])


# ---- expressions ----

class Expr:
    """What an expression references: component names (the first segment of a dotted name, with the instance
    connector kept for `inst.port`), the calls it makes, the names under pre(), edge() or change(), and initial()."""

    def __init__(self):
        self.refs, self.pre, self.der, self.calls, self.initial = set(), set(), set(), set(), False

    def merge(self, o):
        self.refs |= o.refs
        self.pre |= o.pre
        self.der |= o.der
        self.calls |= o.calls
        self.initial = self.initial or o.initial
        return self


def scan(toks):
    """An Expr over a token list. Named arguments (round(x=..., n=6)) are not references."""
    e, i, n = Expr(), 0, len(toks)
    while i < n:
        kind, text = toks[i]
        if kind == "id" and (text not in KEYWORDS or text in ("der", "initial")):
            call = i + 1 < n and toks[i + 1] == ("op", "(")
            named = (i + 1 < n and toks[i + 1] == ("op", "=") and i > 0 and toks[i - 1][1] in ("(", ","))
            if call:
                j = close(toks, i + 1)
                e.calls.add(text)
                inner = scan(toks[i + 2:j])
                if text == "initial":
                    e.initial = True
                elif text in ("pre", "edge", "change"):
                    e.pre |= inner.refs | inner.pre
                    e.calls |= inner.calls
                    if text != "pre":
                        e.refs |= inner.refs      # edge(u) = u and not pre(u): it reads u now too
                elif text == "der":
                    e.der |= inner.refs
                    e.calls |= inner.calls
                else:
                    e.merge(inner)
                i = j + 1
                continue
            if not named:
                e.refs.add(text)
        i += 1
    return e


# ---- the parse ----

class Comp:
    def __init__(self, name, typ, prefixes, public, mods, binding, cond):
        self.name, self.typ, self.prefixes, self.public = name, typ, set(prefixes), public
        self.mods, self.binding, self.cond = mods, binding, cond   # mods: {name: tokens}; binding, cond: tokens

    @property
    def is_param(self):
        return bool(self.prefixes & {"parameter", "constant"})


class Eq:
    """One equation or statement, flattened out of when, if and for. `phase` is "init" (an initial section), "always"
    (outside any when-clause) or "when"; `init_when` marks a when branch whose condition holds initial()."""

    def __init__(self, kind, lhs, rhs, phase, init_when, conds, toks=None):
        self.kind, self.lhs, self.rhs, self.phase, self.init_when, self.conds = kind, lhs, rhs, phase, init_when, conds
        self.toks = toks


class Cls:
    def __init__(self, name, kind, prefixes):
        self.name, self.kind, self.prefixes = name, kind, set(prefixes)
        self.comps, self.nested, self.eqs, self.whens, self.unknown = {}, {}, [], 0, []
        self.within = None


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ("eof", "")

    def at(self, *words):
        return self.peek()[0] == "id" and self.peek()[1] in words

    def take(self, want=None):
        tok = self.peek()
        if tok[0] == "eof":
            raise MoError("unexpected end of source")
        if want is not None and tok[1] != want:
            raise MoError("expected %r, found %r" % (want, tok[1]))
        self.i += 1
        return tok

    def until(self, stops):
        """Tokens up to (not including) the first depth-0 op in `stops`."""
        out, depth = [], 0
        while True:
            tok = self.peek()
            if tok[0] == "eof":
                raise MoError("unexpected end of source")
            if depth == 0 and tok[0] == "op" and tok[1] in stops:
                return out
            if tok[0] == "op" and tok[1] in "([{":
                depth += 1
            elif tok[0] == "op" and tok[1] in ")]}":
                depth -= 1
            out.append(tok)
            self.i += 1

    def file(self):
        within = None
        if self.at("within"):
            self.take()
            within = self.take()[1]
            self.take(";")
        c = self.class_def()
        c.within = within
        return c

    def class_def(self):
        prefixes = []
        while self.at(*CLASS_PREFIX):
            prefixes.append(self.take()[1])
        kind = self.take()[1]
        if kind not in CLASS_KW:
            raise MoError("expected a class definition, found %r" % kind)
        if kind == "operator" and self.at("record", "function"):
            kind = self.take()[1]
        name = self.take()[1]
        c = Cls(name, kind, prefixes)
        if self.peek() == ("op", "="):
            self.until((";",))              # a short class definition: type X = Y(...)
            self.take(";")
            return c
        while self.peek()[0] == "str":
            self.take()
        self.composition(c)
        return c

    def composition(self, c):
        public, phase, mode = True, None, "elements"
        while True:
            if self.at("end") and self.peek(1) == ("id", c.name):
                self.take()
                self.take()
                self.take(";")
                return
            if self.at("public", "protected"):
                public, mode = self.take()[1] == "public", "elements"
                continue
            if self.at("equation"):
                self.take()
                mode, phase = "equation", "always"
                continue
            if self.at("algorithm"):
                self.take()
                mode, phase = "algorithm", "always"
                continue
            if self.at("initial") and self.peek(1)[1] in ("equation", "algorithm"):
                self.take()
                mode, phase = self.take()[1], "init"
                continue
            if self.at("external"):
                self.until((";",))
                self.take(";")
                continue
            if mode == "elements":
                self.element(c, public)
            else:
                c.eqs += self.equation(c, phase, False, [], mode == "algorithm")

    def element(self, c, public):
        if self.at("import"):
            self.until((";",))
            self.take(";")
            return
        if self.at("extends"):
            self.take()
            base = self.take()[1]
            self.until((";",))
            self.take(";")
            c.unknown.append("it extends %s, which this reader does not follow" % base)
            return
        j = 0
        while self.peek(j)[0] == "id" and self.peek(j)[1] in CLASS_PREFIX:
            j += 1
        if self.peek(j)[0] == "id" and self.peek(j)[1] in CLASS_KW:
            n = self.class_def()
            c.nested[n.name] = n
            return
        prefixes = []
        while self.at(*COMP_PREFIX):
            prefixes.append(self.take()[1])
        typ = self.take()[1]
        if self.peek() == ("op", "["):
            self.i = close(self.t, self.i) + 1
        while True:
            name = self.take()[1]
            if self.peek() == ("op", "["):
                self.i = close(self.t, self.i) + 1
            mods = {}
            if self.peek() == ("op", "("):
                j = close(self.t, self.i)
                mods = modifiers(self.t[self.i + 1:j])
                self.i = j + 1
            binding = None
            if self.peek()[1] in ("=", ":="):
                self.take()
                binding = self.expr_until_condition()
            cond = None
            if self.at("if"):
                self.take()
                cond = self.until((";", ","))
                cond = [t for t in cond if t[0] != "str"]
            while self.peek()[0] == "str":
                self.take()
            c.comps[name] = Comp(name, typ, prefixes, public, mods, binding, cond)
            if self.peek() == ("op", ","):
                self.take()
                continue
            self.take(";")
            return

    def expr_until_condition(self):
        """A binding expression, up to `;`, `,`, a description string, or the `if` of a condition attribute (an `if`
        with no `then` before the end of the declaration)."""
        out, depth = [], 0
        while True:
            tok = self.peek()
            if tok[0] == "eof":
                raise MoError("unexpected end of source")
            if depth == 0 and (tok[0] == "str" or tok[0] == "op" and tok[1] in ";,"):
                return out
            if depth == 0 and tok == ("id", "if") and not self.if_has_then():
                return out
            if tok[0] == "op" and tok[1] in "([{":
                depth += 1
            elif tok[0] == "op" and tok[1] in ")]}":
                depth -= 1
            out.append(tok)
            self.i += 1

    def if_has_then(self):
        depth, j = 0, self.i + 1
        while j < len(self.t):
            k, x = self.t[j]
            if k == "op" and x in "([{":
                depth += 1
            elif k == "op" and x in ")]}":
                depth -= 1
            elif depth == 0 and (k == "op" and x in ";," or k == "str"):
                return False
            elif depth == 0 and (k, x) == ("id", "then"):
                return True
            j += 1
        return False

    def equation(self, c, phase, init_when, conds, stmt):
        """The flattened equations or statements of one item at the current position."""
        if self.at("when"):
            self.take()
            c.whens += 1
            out = []
            while True:
                cond = scan(self.until_kw("then"))
                self.take("then")
                body = []
                while not self.at("elsewhen") and not (self.at("end") and self.peek(1) == ("id", "when")):
                    body += self.equation(c, "when", cond.initial, conds + [cond], stmt)
                for e in body:
                    e.init_when = e.init_when or cond.initial
                    e.phase = "when"
                out += body
                if self.at("elsewhen"):
                    self.take()
                    continue
                self.take("end")
                self.take("when")
                self.take(";")
                return out
        if self.at("if"):
            self.take()
            out = []
            while True:
                cond = None
                if not self.at("else"):
                    cond = scan(self.until_kw("then"))
                    self.take("then")
                else:
                    self.take()
                sub = conds + ([cond] if cond else [])
                while not self.at("elseif", "else") and not (self.at("end") and self.peek(1) == ("id", "if")):
                    out += self.equation(c, phase, init_when, sub, stmt)
                if self.at("elseif"):
                    self.take()
                    continue
                if self.at("else"):
                    continue
                self.take("end")
                self.take("if")
                self.take(";")
                return out
        if self.at("for", "while"):
            word = self.take()[1]
            cond = scan(self.until_kw("loop"))
            self.take("loop")
            out = []
            while not (self.at("end") and self.peek(1) == ("id", word)):
                out += self.equation(c, phase, init_when, conds + [cond], stmt)
            self.take("end")
            self.take(word)
            self.take(";")
            return out
        if self.at("connect"):
            self.take()
            self.take("(")
            a = self.until((",",))
            self.take(",")
            b = self.until((")",))
            self.take(")")
            self.take(";")
            return [Eq("connect", name_of(a), name_of(b), phase, init_when, conds)]
        if self.at("return", "break"):
            self.take()
            self.take(";")
            return []
        toks = self.until((";",))
        self.take(";")
        for k, sep in enumerate(toks):
            if sep[0] == "op" and sep[1] in ("=", ":=") and depth_at(toks, k) == 0:
                return [Eq("eq", scan(toks[:k]), scan(toks[k + 1:]), phase, init_when, conds, toks)]
        return [Eq("call", Expr(), scan(toks), phase, init_when, conds, toks)]

    def until_kw(self, word):
        out, depth = [], 0
        while True:
            tok = self.peek()
            if tok[0] == "eof":
                raise MoError("expected %r" % word)
            if depth == 0 and tok == ("id", word):
                return out
            if tok[0] == "op" and tok[1] in "([{":
                depth += 1
            elif tok[0] == "op" and tok[1] in ")]}":
                depth -= 1
            out.append(tok)
            self.i += 1


def depth_at(toks, k):
    depth = 0
    for t in toks[:k]:
        if t[0] == "op" and t[1] in "([{":
            depth += 1
        elif t[0] == "op" and t[1] in ")]}":
            depth -= 1
    return depth


def name_of(toks):
    """A connect endpoint's name with its subscripts dropped: u, greHys.u, conMax.u[1] -> conMax.u."""
    out, depth = [], 0
    for t in toks:
        if t == ("op", "["):
            depth += 1
        elif t == ("op", "]"):
            depth -= 1
        elif depth == 0 and (t[0] == "id" or t[1] == "."):
            out.append(t[1])
    return "".join(out).strip(".")


def modifiers(toks):
    """{name: value tokens} of a modification's top-level `name = value` arguments (final and each dropped)."""
    out, start = {}, 0
    parts, depth = [], 0
    for k, t in enumerate(toks):
        if t[0] == "op" and t[1] in "([{":
            depth += 1
        elif t[0] == "op" and t[1] in ")]}":
            depth -= 1
        elif depth == 0 and t == ("op", ","):
            parts.append(toks[start:k])
            start = k + 1
    parts.append(toks[start:])
    for p in parts:
        p = [t for t in p if t not in (("id", "final"), ("id", "each"))]
        if len(p) >= 2 and p[0][0] == "id" and p[1] == ("op", "="):
            out[p[0][1]] = [t for t in p[2:] if t[0] != "str"]
    return out


def parse(text):
    """The top-level class of one .mo file."""
    return Parser(tokens(text)).file()


# ---- the facts ----

class Fact:
    def __init__(self, state, init, basis, outs=None, unread=False, init_basis=None):
        self.state, self.init, self.basis, self.init_basis = state, init, basis, init_basis
        self.outs = outs or {}      # output name -> the inputs its initial value reads (for instance summaries)
        self.unread = unread        # True when some output's initial dependence could not be read

    def __repr__(self):
        return "Fact(%r, %r, %r, %r)" % (self.state, self.init, self.init_basis, self.basis)


def path_of(rel):
    """Reals/Greater.mo, relative to the pins -> Buildings.Controls.OBC.CDL.Reals.Greater"""
    return CDL + rel.replace("\\", "/")[:-len(".mo")].replace("/", ".")


def load(src_dir):
    """{class path: .mo text} of every pinned elementary class."""
    src_dir = pathlib.Path(src_dir)
    return {path_of(f.relative_to(src_dir).as_posix()): f.read_text(encoding="utf-8")
            for f in sorted(src_dir.rglob("*.mo"))}


def packages(paths):
    out = {"Buildings", "Modelica"}
    for p in paths:
        parts = p.split(".")
        for k in range(1, len(parts)):
            out.add(".".join(parts[:k]))
    return out | {CDL + "Interfaces", CDL + "Types", CDL + "Constants"}


def resolve(typ, scope, known, pkgs):
    """A type name's class path by Modelica's lookup: the first segment is looked up in the enclosing scopes from the
    innermost out, then at the top level. None when it names no known class or package."""
    head = typ.split(".")[0]
    parts = scope.split(".")
    for k in range(len(parts), 0, -1):
        cand = ".".join(parts[:k]) + "." + head
        if cand in known or cand in pkgs:
            return ".".join(parts[:k]) + "." + typ
    return typ if head in ("Buildings", "Modelica") else None


def facts(sources):
    """{class path: Fact} for every class in `sources` ({class path: .mo text})."""
    known = set(sources)
    pkgs = packages(known)
    parsed, memo, out = {}, {}, {}
    for p, text in sources.items():
        try:
            parsed[p] = parse(text)
        except MoError as e:
            parsed[p] = e

    def fact_of(p, stack=()):
        if p in memo:
            return memo[p]
        if p in stack:
            raise MoError("a cycle of instances through %s" % p)
        c = parsed[p]
        if isinstance(c, MoError):
            memo[p] = Fact("undecided", None, ["unread: the source does not parse (%s)" % c])
        else:
            try:
                memo[p] = analyse(c, p, lambda q: fact_of(q, stack + (p,)), known, pkgs)
            except MoError as e:
                memo[p] = Fact("undecided", None, ["unread: %s" % e])
        return memo[p]

    for p in sorted(sources):
        out[p] = fact_of(p)
    return out


def class_calls(c):
    """Every call a parsed class makes: in its equations and algorithms, its declarations' bindings, modifiers and
    conditions, and the bodies of the classes it declares."""
    calls = set()
    for e in c.eqs:
        for x in ((e.lhs, e.rhs) if e.kind != "connect" else ()) + tuple(e.conds):
            calls |= x.calls
    for comp in c.comps.values():
        for toks in [comp.binding, comp.cond] + list(comp.mods.values()):
            if toks:
                calls |= scan(toks).calls
    for n in c.nested.values():
        calls |= class_calls(n)
    return calls


def corpus_calls(sources):
    """Every call the classes in `sources` ({class path: .mo text}) make, the functions they declare included."""
    out = set()
    for text in sources.values():
        out |= class_calls(parse(text))
    return out


def analyse(c, path, fact_of, known, pkgs, funcs=frozenset()):
    """The Fact of one parsed class. Nested classes are analysed in place, by the same rules. `funcs` are the pure
    functions the enclosing classes declare."""
    scope = path
    funcs = set(funcs) | {n.name for n in c.nested.values() if n.kind == "function" and "impure" not in n.prefixes}
    own, unread = set(), list(c.unknown)
    if "impure" in c.prefixes:
        unread.append("it is impure")
    insts, conns = {}, {}
    for comp in c.comps.values():
        base = comp.typ.split(".")[-1]
        if comp.is_param:
            if "fixed" in comp.mods and [t[1] for t in comp.mods["fixed"]] == ["false"]:
                own.add("initialParameter")
            continue
        if base in CONNECTORS and (comp.typ == base or "Interfaces" in comp.typ):
            conns[comp.name] = CONNECTORS[base]
            if "discrete" in comp.prefixes:
                own.add("discrete")
            continue
        if comp.typ in BUILTIN:
            if "discrete" in comp.prefixes:
                own.add("discrete")
            continue
        if comp.typ in c.nested:
            n = c.nested[comp.typ]
            if n.kind == "function":
                continue
            insts[comp.name] = ("local", n, comp)
            continue
        target = resolve(comp.typ, scope, known, pkgs)
        if target in known:
            insts[comp.name] = ("cdl", target, comp)
        elif target and (target.startswith(CDL + "Types.") or target.startswith(CDL + "Interfaces.")):
            if "discrete" in comp.prefixes:
                own.add("discrete")
            continue
        else:
            insts[comp.name] = ("unknown", comp.typ, comp)
    for n in c.nested.values():
        if n.kind == "function" and "impure" in n.prefixes:
            unread.append("its function %s is impure" % n.name)

    # the own constructs
    calls = set()
    for e in c.eqs:
        for x in ((e.lhs, e.rhs) if e.kind != "connect" else ()) + tuple(e.conds):
            calls |= x.calls
    for comp in c.comps.values():
        if comp.binding is not None and not comp.is_param:
            calls |= scan(comp.binding).calls      # Boolean s = sample(t0, period) declares and defines at once
    for k in STATE_CALLS:
        if k in calls:
            own.add(k)
    if c.whens:
        own.add("when")
    unclassified = sorted(class_calls(c) - set(CLASSIFIED_CALLS) - funcs)
    for name in unclassified:
        unread.append("a call to %s, which this reader has not classified" % name)

    # contained instances
    sub, inst_basis = {}, []
    for name, (how, target, comp) in sorted(insts.items()):
        if how == "local":
            f = analyse(target, path + "." + target.name, fact_of, known, pkgs, funcs)
        elif how == "cdl":
            f = fact_of(target)
        else:
            f = None
            unread.append("instance %s is of %s, which the pinned source does not hold" % (name, target))
        sub[name] = (f, comp)
        cond = " (conditional)" if comp.cond else ""
        if f is not None and f.state == "stateful":
            inst_basis.append("instance %s%s" % (name, cond))
        elif f is not None and f.state == "undecided":
            unread.append("instance %s%s is of an undecided class" % (name, cond))

    basis = [k for k in OWN_ORDER if k in own] + inst_basis
    if basis:
        state = "stateful"
    elif unread:
        state = "undecided"
    else:
        state = "stateless"
    outs, out_unread = initial_reads(c, conns, sub)
    has_inputs = any(d == "in" for d in conns.values())
    init = why = None
    if state == "stateful":
        reads = set().union(*outs.values()) if outs else set()
        if unclassified:
            init = "undecided"        # previous(u) at the initial instant reads the start value, not u
        elif reads:
            init = "readsInput"
        elif out_unread and has_inputs:
            init = "undecided"
        else:
            init = "noInput"
            why = "noInputConnector" if not has_inputs else ("undecided" if sub else operating_basis(c, conns))
    return Fact(state, init, basis + ["unread: " + u for u in unread], outs, out_unread or bool(unclassified), why)


def operating_basis(c, conns):
    """Why a noInput class with inputs and no instances reads no input at the initial instant: "preDelayed" when,
    in the equations active after it (outside the initial sections, every when branch included), every output reads
    the inputs only through pre() and at least one does; "parameterInit" otherwise."""
    inputs = {n for n, d in conns.items() if d == "in"}
    edges = {}           # node -> [(dep node, through pre)]

    def add(a, b, delayed=False):
        edges.setdefault(a, []).append((b, delayed))

    for e in c.eqs:
        if e.phase == "init":
            continue
        conds = Expr()
        for cnd in e.conds:
            conds.merge(cnd)
        if e.kind == "call" and e.toks and e.toks[0] == ("id", "reinit"):
            args, depth, cur = [], 0, []
            for tok in e.toks[2:-1]:
                if tok[0] == "op" and tok[1] in "([{":
                    depth += 1
                elif tok[0] == "op" and tok[1] in ")]}":
                    depth -= 1
                if depth == 0 and tok == ("op", ","):
                    args.append(cur)
                    cur = []
                else:
                    cur.append(tok)
            args.append(cur)
            targets, rhs = scan(args[0]).refs, scan(sum(args[1:], []))
        elif e.kind == "eq":
            targets, rhs = e.lhs.refs, e.rhs
        else:
            continue
        deps = [(r, False) for r in rhs.refs | conds.refs] + [(r, True) for r in rhs.pre | conds.pre]
        if targets and targets <= inputs:
            continue        # an input on the left (u = der(mu)) defines nothing
        for tgt in targets:
            for d, delayed in deps:
                add(tgt, d, delayed)
    for comp in c.comps.values():
        if comp.binding is not None and not comp.is_param:
            b = scan(comp.binding)
            for r in b.refs:
                add(comp.name, r)
            for r in b.pre:
                add(comp.name, r, True)
    direct, delayed_any = False, False
    for o in sorted(n for n, d in conns.items() if d == "out"):
        todo, seen = [(o, False)], set()
        while todo:
            n, through = todo.pop()
            if (n, through) in seen:
                continue
            seen.add((n, through))
            if n in inputs and n != o:
                if through:
                    delayed_any = True
                else:
                    direct = True
            for d, delayed in edges.get(n, []):
                todo.append((d, through or delayed))
    return "preDelayed" if delayed_any and not direct else "parameterInit"


def initial_reads(c, conns, sub):
    """({output: inputs its initial value reads in every configuration}, unread): the initial-system dependence of
    each output connector on the input connectors, through the equations active at the initial instant and each
    instance's own summary. `unread` is True when a path ran into something this reader cannot follow."""
    inputs = {n for n, d in conns.items() if d == "in"}
    outputs = sorted(n for n, d in conns.items() if d == "out")
    edges = {}           # node -> [(dep node, guard)]  guard: tuple of instance names the edge needs present
    unknown = set()      # nodes whose dependence is unknown

    def add(a, b, guard=()):
        edges.setdefault(a, []).append((b, guard))

    def node(ref):
        head = ref.split(".")[0]
        if head in sub:
            parts = ref.split(".")
            return head + "." + parts[1] if len(parts) > 1 else head
        return head

    defined = set()
    for e in c.eqs:
        active = e.phase in ("init", "always") or e.init_when
        if not active:
            continue
        if e.kind == "connect":
            a, b = connect_flow(e.lhs, e.rhs, conns, sub)
            if a is None:
                unknown.add(node(e.lhs))
                unknown.add(node(e.rhs))
                continue
            add(a, b, tuple(x for x in (a.split(".")[0], b.split(".")[0]) if x in sub and sub[x][1].cond))
            defined.add(a)
            continue
        if e.kind != "eq":
            continue
        targets = {node(r) for r in e.lhs.refs} | {"pre:" + node(r) for r in e.lhs.pre}
        if not targets and not e.lhs.der:
            raise MoError("an equation with no variable on its left side")
        deps = {node(r) for r in e.rhs.refs} | {"pre:" + node(r) for r in e.rhs.pre}
        for cnd in e.conds:
            deps |= {node(r) for r in cnd.refs} | {"pre:" + node(r) for r in cnd.pre}
        if targets and targets <= inputs:
            # An input on the left (MovingAverage's u = der(mu)) defines nothing: the equation is read right to left.
            for d in deps:
                defined.add(d)
                for t in targets:
                    add(d, t)
            continue
        for t in targets:
            defined.add(t)
            for d in deps:
                add(t, d)
    for comp in c.comps.values():
        if comp.binding is not None and not comp.is_param:
            b = scan(comp.binding)
            defined.add(comp.name)
            for r in b.refs:
                add(comp.name, node(r))
            for r in b.pre:
                add(comp.name, "pre:" + node(r))
        if "start" in comp.mods:
            s = scan(comp.mods["start"])
            for r in s.refs:
                add("pre:" + comp.name, node(r))
                if comp.name not in defined:
                    add(comp.name, node(r))
    # A variable a when-clause assigns, with no equation for it at the initial instant, starts at its pre() value
    # (Modelica 3.6, 8.6): Stage's y starts at pre(y) = pre_y_start, FirstOrderHold's pre_uSample at pre(...) = u.
    for e in c.eqs:
        if e.kind == "eq" and e.phase == "when":
            for r in e.lhs.refs:
                v = node(r)
                if v not in defined:
                    add(v, "pre:" + v)
    for name, (f, comp) in sub.items():
        if f is None:
            unknown.add(name)
            continue
        if f.unread:
            unknown.add(name)
        for o, ins in f.outs.items():
            for p in ins:
                add(name + "." + o, name + "." + p)

    def reach(start):
        """{input: [guards of each path]} reachable from `start`, and whether an unknown node was touched."""
        found, touched, seen = {}, False, set()
        todo = [(start, ())]
        while todo:
            n, guard = todo.pop()
            if (n, guard) in seen:
                continue
            seen.add((n, guard))
            if n in unknown or n.split(".")[0] in unknown:
                touched = True
            if n in inputs:
                found.setdefault(n, set()).add(guard)
            for d, g in edges.get(n, []):
                todo.append((d, tuple(sorted(set(guard) | set(g)))))
        return found, touched

    outs, unread = {}, False
    for o in outputs:
        found, touched = reach(o)
        reads = set()
        for p, guards in found.items():
            if covers(guards, sub):
                reads.add(p)
            else:
                unread = True
        outs[o] = reads
        unread = unread or (touched and not reads)
    return outs, unread


def covers(guards, sub):
    """True when the paths' guards hold in every configuration: one path needs no conditional instance, or two paths
    are each guarded by one instance, under conditions that are the syntactic negation of each other."""
    if () in guards:
        return True
    single = [g[0] for g in guards if len(g) == 1]
    conds = {g: tuple(t[1] for t in sub[g][1].cond) for g in single}
    for a in single:
        for b in single:
            ca, cb = conds[a], conds[b]
            if cb == ("not",) + ca or ca == ("not",) + cb:
                return True
    return False


def connect_flow(a, b, conns, sub):
    """(sink, source) of a connect: the value flows from an outer input or an instance output into an outer output or
    an instance input. (None, None) when a direction cannot be read (an instance of a class this reader cannot
    read)."""
    def role(x):
        parts = x.split(".")
        if len(parts) == 1:
            d = conns.get(x)
            return None if d is None else ("source" if d == "in" else "sink")
        f = sub.get(parts[0], (None, None))[0]
        if f is None:
            return None
        d = f.outs.get(parts[1])
        return "source" if d is not None else "sink"
    ra, rb = role(a), role(b)
    if ra is None or rb is None:
        return None, None
    if ra == "sink" and rb == "source":
        return a, b
    if rb == "sink" and ra == "source":
        return b, a
    if ra == rb == "sink":
        # an outer output feeding an instance input: the instance reads the output, which is defined elsewhere
        inner = a if "." in a else b
        outer = b if inner == a else a
        return inner, outer
    return None, None
