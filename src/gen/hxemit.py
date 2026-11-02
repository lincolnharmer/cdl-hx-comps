"""The hx.comps form of the CDL libraries: CdlClass instances, the kw.cdl composites, and the G36 composites wired
from hx.comps comps.

A CDL elementary class is the hx.comps comp the class map names (classmap_table.py, checked by classmap.py). A G36
composite types each child as that comp, writes literal parameter values as comp slot values, converted per the
class map, keeps every value bound to a composite parameter as an expression in `cdlBind`, and writes each link on
hx.comps slot names. CDL names stay on the composite's own parameters and connectors. A class that compiles to a
link (Conversions.IntegerToReal, Logical.Pre) leaves a CdlWire record of the instance, and each link through it runs
from the instance's source with `cdlLinkVia` naming it. A parameter or connector the class map feeds through a comp
gets that comp as a sibling child named `<instance>_<name>`, carrying `cdlFeed`.

generate.py calls render_kw_cdl, render_classes and emit_mapped. parse_mapped reads the result back into CDL terms
for the round trip against MBL's source.
"""
import json
import pathlib
import re
from collections import OrderedDict

import classmap
import connector_points
import units
import cxf
import generate as g
from cxf import CxfError

HX = "hx.comps::"
WIRE_SPEC = "kw.cdl::CdlWire"
STATUS_TYPE = {"Real": HX + "StatusNumber", "Integer": HX + "StatusNumber", "Boolean": HX + "StatusBool",
               "String": HX + "StatusStr"}
MAPPED = ("native", "nativeParams", "const")


# ---- the class map, keyed for the generator ----

def rows_by_path(rows):
    return {e["cdlClass"]: dict(e, name=n) for n, e in rows.items()}


def conv_code(p):
    return classmap.CONVERT.get(p.get("convert"))


def table_row(name):
    return classmap.T[name]


# ---- values ----

def array_size(size):
    """A vectorized instance's size in the form a vector connector's cdlArraySize takes, CXF's own: in parentheses."""
    return "(%s)" % (size if isinstance(size, str) else ",".join(size))


def clean_num(v):
    """A number in its shortest exact-looking spelling: 277.55, not the float noise 277.54999999999995."""
    if isinstance(v, bool):
        return "true" if v else "false"
    f = float(v)
    if f.is_integer() and abs(f) < 1e15:
        return str(int(f))
    return "%.12g" % f


def literal_meta(store):
    """The meta that records a child's literals: cdlLiteralUnits (each literal's SI unit), cdlLiteralDelta (the
    ones that are differences) and cdlLiteralExprs (the MBL expression each evaluated literal was written as)."""
    out = []
    if store["units"]:
        out.append("cdlLiteralUnits:{" + ", ".join("%s:%s" % (k, g.xs(v)) for k, v in store["units"].items()) + "}")
    if store["delta"]:
        out.append("cdlLiteralDelta:" + g.xs(",".join(store["delta"])))
    if store["exprs"]:
        out.append("cdlLiteralExprs:{" + ", ".join("%s:%s" % (k, g.xs(v)) for k, v in store["exprs"].items()) + "}")
    return out


# Every literal the generator writes on a Real parameter: (composite, child, CDL parameter, unit or None, why it has
# none, the class's unit family). generate.py writes the units report from it.
LITERALS = []


def fmt_value(v, code=None, cdl_type=None, unit=None):
    """A literal CDL value as the Xeto value of the comp slot it is written to, converted per the class map: seconds
    to a Duration, a Real to a Float, an Integer to an Int, an enum key to the comp's key. `unit`, when given, is the
    Haystack symbol written after a number. Refuses a value the conversion cannot take."""
    if code is not None and code.startswith("enum"):
        pairs = dict(x.split("=") for x in code.split()[1:])
        if v not in pairs:
            raise CxfError("enum value %r is not one of %s" % (v, sorted(pairs)))
        return g.xs(pairs[v])
    if isinstance(v, bool):
        return g.xs("true" if v else "false")
    if isinstance(v, str):
        return g.xs(v)
    if code == "sec":
        return clean_num(v) + "sec"
    if code == "int":
        if float(v) != int(v):
            raise CxfError("%r is not a whole number for an Int slot" % v)
        return str(int(v))
    return clean_num(v) + (unit or "")


def fixed_value(v):
    if isinstance(v, bool):
        return g.xs("true" if v else "false")
    if isinstance(v, (int, float)):
        return g.fmt_num(v)
    if classmap.DURATION.match(v):
        return v
    return g.xs(v)


_CONSTANTS = {}


def package_constants():
    """Every G36 package constant's dotted name -> its value (Types.OperationModes.occupied is 1): design-time
    constants, so a binding written in them alone is a literal."""
    if not _CONSTANTS:
        _CONSTANTS.update(g.constant_names(g.load_constants(g.cxf_source.source_root())))
    return _CONSTANTS


def bind_value(bind, dtype):
    """(literal, expression) of one CXF binding: a literal number or Boolean, an enum item for a bare enum literal of
    the parameter's own enumeration, arithmetic of literals and package constants evaluated, else the expression
    text, which names a parameter of the composite."""
    val, expr = bind
    if val is not None:
        return val, None
    e = expr.strip()
    if dtype not in g.XETO_TYPE and re.fullmatch(r"[A-Za-z_][\w.]*", e) and "." in e \
            and e.rsplit(".", 1)[0].endswith(dtype.rsplit(".", 1)[1]):
        return e.rsplit(".", 1)[1], None
    if e in ("true", "false"):
        return e == "true", None
    consts = package_constants()
    try:
        if all(n in consts for n in cxf.names(e)):
            v = cxf.evaluate(e, {}, consts.get)
            if isinstance(v, (bool, float)):
                return v, None
    except CxfError:
        pass
    return None, e


def default_value(ci_sub, name, binds, row, seen=()):
    """(literal, expression) of a parameter's CDL default at one instance, with each parameter of the class it names
    replaced by that parameter's value at the instance: TrueFalseHold's falseHoldDuration defaults to
    trueHoldDuration, which may be bound to a number or to a parameter of the composite."""
    raw = row["cdlDefaults"][name]
    if name in seen:
        raise CxfError("%s: default of %s refers to itself" % (ci_sub.path, name))
    p = ci_sub.param(name)
    try:
        v = cxf.evaluate(raw, {}, lambda lit: None)
        if isinstance(v, (bool, float)):
            return v, None
    except CxfError:
        pass
    env, text = {}, raw
    for n in cxf.names(raw):
        q = ci_sub.param(n)
        if q is None:
            raise CxfError("%s: default %s of %s names %s, which is no parameter" % (ci_sub.path, raw, name, n))
        if n in binds:
            lit, expr = bind_value(binds[n], q.dtype)
        elif n in row["cdlDefaults"]:
            lit, expr = default_value(ci_sub, n, binds, row, seen + (name,))
        elif q.val is not None:
            lit, expr = q.val, None
        else:
            raise CxfError("%s: default %s of %s names %s, which has no value here" % (ci_sub.path, raw, name, n))
        if expr is None:
            env[n] = lit
        text = re.sub(r"(?<![\w.])%s(?![\w])" % re.escape(n), lit if expr is None and isinstance(lit, str)
                      else (g.fmt_num(lit) if expr is None else "(%s)" % expr), text)
    if all(n in env for n in cxf.names(raw)):
        return cxf.evaluate(raw, env, lambda lit: None), None
    del p
    return None, text


def status_typed(lines):
    """Generated spec lines with each scalar connector retyped to the hx.comps status type of its CDL type, the type
    a link from it into a comp slot carries. A vector connector stays a List."""
    out = []
    for line in lines:
        m = re.match(r"^(  \w+: )(Number|Bool|Str)\? (<(?:cdlInput|cdlOutput)[,>].*)$", line)
        if m:
            ctype = re.search(r'cdlType:"(\w+)"', m.group(3)).group(1)
            line = m.group(1) + STATUS_TYPE[ctype] + "? " + m.group(3)
        out.append(line)
    return out


# ---- point meta ----

def point_index():
    """(composite spec name, slot) -> (meta dict, scope) from the reviewed connector-to-point table."""
    out = {}
    for x in connector_points.load()["connectors"]:
        out[(x["composite"], x["slot"])] = (x.get("meta") or {}, x.get("scope"))
    return out


# (composite, instance, parameter, why) for each writeWhenUnit parameter left unwritten, for the units report
SKIPPED = []
# (composite, instance, parameter) of each literal whose unit came from a literalUnits decision
DECIDED = set()
PH_POINT_UNITS = pathlib.Path(__file__).resolve().parent / "ph_point_units.json"
_PH_UNITS = {}


def ph_point_unit(spec):
    """The unit Project Haystack gives a point spec (ph_point_units.json, read from the pinned ph source), or None."""
    if not _PH_UNITS:
        _PH_UNITS.update(json.loads(PH_POINT_UNITS.read_text(encoding="utf-8"))["specs"])
    return (_PH_UNITS.get(spec) or {}).get("unit")


def point_meta(spec, ci, names, points):
    """slot -> list of meta strings: cdlPointSpec or cdlPointSpecCases from the table, and cdlPointScope on every
    connector that carries either. Refuses a table row for a connector the composite does not have, and a point
    connector whose scope is outside connector_points.SCOPES. A connector with no point meta (a signal, an override,
    an alarm, a gap) carries no scope either, whatever the table records for it."""
    rows = {slot: v for (comp, slot), v in points.items() if comp == spec}
    slots = {names[c.name] for c in ci.conns}
    stray = sorted(set(rows) - slots)
    if stray:
        raise CxfError("%s: the point table names connectors %s that the composite does not have" % (spec, stray))
    specs = {}
    for slot, (meta, _scope) in rows.items():
        if "cdlPointSpec" in meta:
            specs[slot] = {meta["cdlPointSpec"]}
        elif "cdlPointSpecCases" in meta:
            specs[slot] = {c["spec"] for c in meta["cdlPointSpecCases"]}
    out = {}
    for slot, (meta, scope) in rows.items():
        m = []
        if "cdlPointSpec" in meta:
            m.append("cdlPointSpec:" + meta["cdlPointSpec"])
        elif "cdlPointSpecCases" in meta:
            m.append("cdlPointSpecCases:List {%s}" % ", ".join(
                "{when:%s, pointSpec:%s}" % (g.xs(c["when"]), c["spec"]) for c in meta["cdlPointSpecCases"]))
        conn = next((c for c in ci.conns if names[c.name] == slot), None)
        if m and conn is not None and conn.unit == "1":
            # a dimensionless connector on a point that carries a unit: a % point holds the fraction times 100, so
            # the binder scales by 0.01 (cdlPointScale); a count such as ppm needs a recorded pointUnits decision
            pu = sorted({str(ph_point_unit(s)) for s in specs[slot]})
            if getattr(conn, "point_unit", None):
                if pu != [conn.point_unit]:
                    raise CxfError("%s.%s: counted in %s, and its point specs carry %s" % (spec, slot, conn.point_unit, pu))
            elif pu == ["%"]:
                m += ["cdlPointUnit:" + g.xs("%"), "cdlPointScale:" + g.xs("0.01")]
            elif pu != ["None"]:
                raise CxfError("%s.%s: a unit \"1\" connector on points in %s, with no pointUnits decision"
                               % (spec, slot, pu))
        if m:
            if scope not in connector_points.SCOPES:
                raise CxfError("%s.%s: scope %r is not one cdlPointScope may carry" % (spec, slot, scope))
            m.append("cdlPointScope:" + g.xs(scope))
        if m:
            out[slot] = m
    return out


# ---- the kw.cdl composites the class map composes from other classes ----

def composed(classes, rows):
    """CDL class path -> a composite ClassInfo for each class graded `composite`: its own parameters and
    connectors, and the instances and links classmap_table composes it from, in CDL names."""
    out = {}
    for name, row in rows.items():
        if row["grade"] != "composite":
            continue
        base = classes[row["cdlClass"]]
        ci = g.ClassInfo(base.path, "composite", base.desc)
        ci.params, ci.conns = base.params, base.conns
        spec = table_row(row["name"])["compose"]
        for iname, cls, binds in spec["insts"]:
            ci.insts.append(g.Inst(iname, g.CDL_PREFIX + cls, {k: cxf.literal(v) for k, v in binds.items()}, None, None))
        ci.edges = list(spec["edges"])
        g.orient(ci, dict(classes, **{ci.path: ci}))
        out[ci.path] = ci
    return out


# ---- one composite on hx.comps ----

class Mapper:
    """Emit one composite (G36, or a kw.cdl composite) with every elementary child on its hx.comps comp."""

    def __init__(self, ci, classes, rows, points=None):
        self.ci, self.classes, self.rows = ci, classes, rows
        self.points = points or {}
        self.names = g.slot_names([p.name for p in ci.params] + [c.name for c in ci.conns] + [i.name for i in ci.insts],
                                  ci.path)
        self.feeds = OrderedDict()        # feed slot name -> lines
        self.taken = set(self.names.values())

    # endpoints

    def row_of(self, inst):
        return self.rows.get(inst.cls)

    def kind(self, inst):
        r = self.row_of(inst)
        if r is None:
            return "composite"                          # a G36 composite
        return {"link": "wire", "composite": "composite", "array": "composite"}.get(r["grade"], r["grade"])

    def split(self, ep):
        """(instance or None, its index text, connector, connector index text)"""
        parts = ep.split(".")
        if len(parts) == 1:
            return None, "", g.base_name(parts[0]), parts[0][len(g.base_name(parts[0])):]
        head, conn = parts
        inst = self.ci.inst(g.base_name(head))
        return inst, head[len(g.base_name(head)):], g.base_name(conn), conn[len(g.base_name(conn)):]

    def mapped(self, ep):
        """A CDL endpoint in hx.comps names. A connector the class map reaches through a feed maps to the feed."""
        inst, iidx, conn, cidx = self.split(ep)
        if inst is None:
            return self.names[conn] + cidx
        iname = self.names[inst.name] + iidx
        k = self.kind(inst)
        if k == "composite":
            sub = self.classes[inst.cls]
            return iname + "." + g.slot_names([p.name for p in sub.params] + [c.name for c in sub.conns] +
                                              [x.name for x in sub.insts], sub.path)[conn] + cidx
        if k == "wire":
            raise CxfError("%s: a wire endpoint %s reached the mapper" % (self.ci.path, ep))
        if k not in MAPPED:
            raise CxfError("%s: %s is an instance of %s, graded %s, which no comp runs"
                           % (self.ci.path, inst.name, inst.cls, self.row_of(inst)["grade"]))
        m = self.row_of(inst)["connectors"][conn]
        if isinstance(m, dict):
            return self.feed_name(inst, conn) + iidx + ".out"
        return iname + "." + m + cidx

    def unit_model(self):
        """(model, solved groups) of this composite's static unit propagation (units.py): its own connectors and
        parameters, each child's connectors and parameters, seeded by their declared units, by cdlConnUnits and by
        the class's unitRule seeds, joined by the connections, by bare-name bindings and by the keep rules."""
        if getattr(self, "_units", None) is not None:
            return self._units
        m = units.Model()
        ci = self.ci

        def declared(port, x):
            if getattr(x, "dtype", None) != "Real":
                return
            u, _why = units.canonical(x.unit, x.qkind, getattr(x, "qinferred", None))
            m.find(port)
            if u is not None:
                m.seed(port, u, "declared")

        for c in ci.conns:
            declared("c:" + c.name, c)
        for p in ci.params:
            declared("p:" + p.name, p)
        for inst in ci.insts:
            sub = self.classes[inst.cls]
            at = lambda n: "i:%s.%s" % (inst.name, n)  # noqa: E731
            for x in sub.conns + sub.params:
                declared(at(x.name), x)
            for k, cu in (getattr(inst, "units", None) or {}).items():
                c = sub.conn(k)
                u, _why = units.canonical(cu, c.qkind if c is not None else None,
                                          getattr(c, "qinferred", None) if c is not None else None)
                if u is not None:
                    m.seed(at(k), u, "cdlConnUnits")
            row = self.row_of(inst)
            rule = table_row(row["name"]).get("unitRule") if row is not None else None
            if rule:
                for group in rule["keep"]:
                    for a, b in zip(group, group[1:]):
                        m.join(at(a), at(b))
                for n, u in rule["seeds"].items():
                    m.seed(at(n), units.seed_unit(u), "unitRule")
                if rule["op"]:
                    m.op(rule["op"], [at(n) for n in rule["ins"]], at(rule["out"]), inst.name)
            for k, (val, expr) in inst.binds.items():
                e = (expr or "").strip()
                if val is None and ci.param(e) is not None:
                    m.join(at(k), "p:" + e)                    # bound by bare name to a composite parameter
            for p in sub.params:
                e = (p.expr or "").strip()
                if p.name not in inst.binds and p.val is None and sub.param(e) is not None:
                    m.join(at(p.name), at(e))                  # a default naming a sibling parameter

        def ep(x):
            parts = [g.base_name(q) for q in x.split(".")]
            return ("c:" + parts[0]) if len(parts) == 1 else "i:%s.%s" % (parts[0], parts[1])
        for a, b in ci.edges:
            # A constant does not join the values it feeds: CDL lets one constant (a 0, a 1) feed values of several
            # units, and joining them through it would make each a conflict. Its own unit is read from them below.
            if not self.is_const(a):
                m.join(ep(a), ep(b))
        val = m.solve()
        # A constant whose own value has a known unit (bound by name to a parameter that declares one) passes it to
        # what it feeds. Repeat until nothing more joins, since a typed sink can type another constant's group.
        joined = set()
        while True:
            more = False
            for a, b in ci.edges:
                if self.is_const(a) and (a, b) not in joined and m.unit_of(val, ep(a))[0] is not None:
                    m.join(ep(a), ep(b))
                    joined.add((a, b))
                    more = True
            if not more:
                break
            val = m.solve()
        self._units = (m, val)
        return self._units

    def is_const(self, ep):
        inst = self.split(ep)[0]
        return inst is not None and (self.row_of(inst) or {}).get("grade") == "const"

    def literal_unit(self, inst, name):
        """(unit, None) or (None, why) for the literal on parameter `name` of child `inst`. A constant takes the
        one unit every value it feeds carries; when they differ, it stays unitless, since a unitless number fits any
        unit on hx.comps."""
        rec = g.LITERAL_UNITS.get("%s.%s.%s" % (self.ci.path, inst.name, name))
        if rec is not None:
            u = units.seed_unit(rec["unit"])
            DECIDED.add((self.ci.path, inst.name, name))
            return u, None
        m, val = self.unit_model()
        if (self.row_of(inst) or {}).get("grade") == "const":
            own = m.unit_of(val, "i:%s.%s" % (inst.name, name))
            if own[0] is not None or "two different units" in (own[1] or ""):
                return own
            found, unknown = set(), 0
            for a, b in self.ci.edges:
                if self.split(a)[0] is inst:
                    parts = [g.base_name(q) for q in b.split(".")]
                    port = ("c:" + parts[0]) if len(parts) == 1 else "i:%s.%s" % (parts[0], parts[1])
                    u, _why = m.unit_of(val, port)
                    if u is None:
                        unknown += 1
                    else:
                        found.add(u)
            syms = {u[0] for u in found}
            if len(syms) > 1:
                return None, "it feeds values of different units (%s)" % ", ".join(sorted(syms))
            if "K" in syms and len({u[1] for u in found}) > 1:
                return None, "it feeds both an absolute temperature and a temperature difference"
            if found:
                return (next(iter(syms)), any(u[1] for u in found)), None
            return None, "no declared unit reaches it"
        return m.unit_of(val, "i:%s.%s" % (inst.name, name))

    def note_literal(self, inst, key, name, dtype, lit, expr_text, store):
        """Record one literal: its unit in store["units"], whether it is a difference in store["delta"], the MBL
        expression it was evaluated from in store["exprs"], and a row in LITERALS for the units report. Returns
        the unit suffix to write, or None."""
        if expr_text is not None:
            store["exprs"][key] = expr_text
        if dtype != "Real" or isinstance(lit, (bool, str)):
            return None
        u, why = self.literal_unit(inst, name)
        family = (table_row(self.row_of(inst)["name"]).get("unitRule") or {}).get("family") \
            if self.row_of(inst) is not None else "composite"
        LITERALS.append((self.ci.path, inst.name, name, u, why, family))
        if u is None:
            return None
        store["units"][key] = u[0]
        if u[1]:
            store["delta"].append(key)
        return units.written_symbol(u)

    def feed_name(self, inst, name):
        return self.names[inst.name] + "_" + name

    def is_wire(self, ep):
        inst = self.split(ep)[0]
        return inst is not None and self.kind(inst) == "wire"

    # links

    def drivers(self):
        out = {}
        for a, b in self.ci.edges:
            out.setdefault(b, []).append(a)
        return out

    def resolve(self, src, drivers, via=(), cut=False):
        """A source through any wires: (CDL source, the wires passed, whether one of them cuts the loop)."""
        if not self.is_wire(src):
            return src, via, cut
        inst, iidx, conn, cidx = self.split(src)
        row = self.row_of(inst)
        if conn != row["link"]["to"]:
            raise CxfError("%s: %s reads %s, which is not its wire's output" % (self.ci.path, src, conn))
        into = inst.name + iidx + "." + row["link"]["from"]
        srcs = drivers.get(into, [])
        if len(srcs) != 1:
            raise CxfError("%s: wire %s has %d drivers; exactly one is supported" % (self.ci.path, inst.name, len(srcs)))
        cuts = row["link"]["from"] in table_row(row["name"]).get("requires", {}).get("loopCut", [])
        return self.resolve(srcs[0], drivers, via + (self.names[inst.name],), cut or cuts)

    def sinks(self):
        """CDL sink -> [(mapped source, wires passed, cut)], the first unconditional, as emit_class orders them."""
        drivers = self.drivers()
        for inst in self.ci.insts:
            if self.kind(inst) == "wire":
                into = inst.name + "." + self.row_of(inst)["link"]["from"]
                users = [b for a, b in self.ci.edges if self.split(a)[0] is inst]
                if not users:
                    raise CxfError("%s: wire %s drives nothing; its link would be lost" % (self.ci.path, inst.name))
                if into not in drivers:
                    raise CxfError("%s: wire %s has no driver" % (self.ci.path, inst.name))
        out = {}
        for b, srcs in drivers.items():
            if self.is_wire(b):
                continue
            srcs = sorted(srcs)
            primary = True
            if len(srcs) > 1:
                unconditional = [s for s in srcs if not g._conditional(self.ci, s)]
                if len(unconditional) > 1:
                    raise CxfError("%s: %s has two unconditional drivers: %s" % (self.ci.path, b, ", ".join(srcs)))
                if not unconditional:
                    # Every driver is guarded: the primary link is the one whose guard holds at the parameter
                    # defaults. When none or several do, or a guard cannot be read there, no driver is primary.
                    held = [s for s in srcs if self.guard_at_defaults(s) is True]
                    known = all(self.guard_at_defaults(s) is not None for s in srcs)
                    unconditional = held if known and len(held) == 1 else []
                    primary = bool(unconditional)
                srcs = unconditional + [s for s in srcs if s not in unconditional]
            resolved = [self.resolve(s, drivers) for s in srcs]
            out[b] = resolved if primary else [None] + resolved
        return out

    def enum_item(self, lit):
        """A dotted name's value: an enumeration item, or a G36 package constant; else None."""
        cls, _, item = lit.rpartition(".")
        ci = self.classes.get(cls)
        if ci is not None and ci.kind == "enum" and item in ci.items:
            return item
        return package_constants().get(lit)

    def defaults(self):
        """The composite's parameters at their defaults, as the expression evaluator takes them: a literal, an enum
        item for a bare enum literal, or an expression of the others evaluated in turn. A parameter with no default,
        or one whose default does not evaluate, is left out."""
        if getattr(self, "_defaults", None) is None:
            env, todo = {}, list(self.ci.params)
            while todo:
                left = []
                for p in todo:
                    if p.val is not None:
                        env[p.name] = p.val
                    elif p.expr is not None:
                        try:
                            v = cxf.evaluate(p.expr, env, self.enum_item)
                            if v is not None:
                                env[p.name] = v
                        except CxfError:
                            left.append(p)
                if len(left) == len(todo):
                    break
                todo = left
            self._defaults = env
        return self._defaults

    def guard_at_defaults(self, src):
        """Whether the guard on `src`'s instance or connector holds at the parameter defaults: True, False, or None
        when it cannot be read there."""
        head = g.base_name(src.split(".")[0])
        inst, conn = self.ci.inst(head), self.ci.conn(head)
        cond = inst.cond if inst is not None else (conn.cond if conn is not None else None)
        if cond is None:
            return True
        try:
            v = cxf.evaluate(cond, self.defaults(), self.enum_item)
        except CxfError:
            return None
        return v if isinstance(v, bool) else None

    def link_meta(self, entries, cut=False):
        if entries[0] is None:
            # no primary driver: every driver is an alternative, for the resolver to choose by the guards
            alts = entries[1:]
            if any(v or x for _, v, x in alts):
                raise CxfError("%s: an alternative driver passes a wire; only a primary driver may" % self.ci.path)
            return ["cdlAltLink:" + g.xs(",".join(self.mapped(s) for s, _, _ in alts))] + (["loopCut"] if cut else [])
        (src, via, c), alts = entries[0], entries[1:]
        if any(v or x for _, v, x in alts):
            raise CxfError("%s: an alternative driver passes a wire; only the first driver may" % self.ci.path)
        meta = ["link:" + g.xs(self.mapped(src))]
        if c or cut:
            meta.append("loopCut")
        if alts:
            meta.append("cdlAltLink:" + g.xs(",".join(self.mapped(s) for s, _, _ in alts)))
        if via:
            meta.append("cdlLinkVia:" + g.xs(",".join(via)))
        return meta

    # emit

    def emit(self, stamp, spec_name, base, expand):
        ci = self.ci
        out = ["// " + ci.desc] if ci.desc else []
        out += g.header(ci.path, stamp)
        tags = "cdlClass:%s" % g.xs(ci.path) + (", cdlExpand" if expand else "")
        out.append("%s: %s <%s> {" % (spec_name, base, tags))
        for p in ci.params:
            out += g.emit_param(p, self.names[p.name], self.classes, ci.path)
        sinks = self.sinks()
        pmeta = point_meta(spec_name, ci, self.names, self.points) if self.points else {}
        for c in ci.conns:
            out += self.emit_conn(c, sinks.get(c.name) if c.direction == "out" else None, pmeta.get(self.names[c.name], []))
        for inst in ci.insts:
            out += self.emit_inst(inst, sinks)
        for name, lines in self.feeds.items():
            out += lines
        out.append("}")
        return out

    def emit_conn(self, c, entries, pmeta):
        lines = g.emit_conn(c, self.names[c.name], None, self.ci.path)
        if c.raw_size is None:
            lines[-1] = re.sub(r"^(  \w+: )(Number|Bool|Str)\?", lambda m: m.group(1) + STATUS_TYPE[c.dtype] + "?",
                               lines[-1], count=1)
        extra = list(pmeta)
        if entries:
            extra += self.link_meta(entries)
        if extra:
            lines[-1] = lines[-1][:-1] + ", " + ", ".join(extra) + ">"
        return lines

    def emit_inst(self, inst, sinks):
        k = self.kind(inst)
        sub = self.classes[inst.cls]
        subnames = g.slot_names([p.name for p in sub.params] + [c.name for c in sub.conns] + [x.name for x in sub.insts],
                                sub.path)
        slot = self.names[inst.name]
        meta = ["cdlInstance", "cdlName:" + g.xs(inst.name)]
        row = self.row_of(inst)
        if row is not None:
            meta.append("cdlOf:@kw.cdl::cdl-" + row["name"])
        body = []
        binds, defaulted = OrderedDict(), []
        store = {"units": OrderedDict(), "delta": [], "exprs": OrderedDict()}
        if k in ("composite", "wire"):
            for key in sorted(inst.binds):
                val, expr = inst.binds[key]
                binds[subnames[key]] = expr if expr is not None else g.fmt_num(val)
                p = sub.param(key)
                if val is not None and p is not None and k == "composite":
                    self.note_literal(inst, subnames[key], key, p.dtype, val, None, store)
            if k == "composite":
                for b in sorted(sinks):
                    sinst, _iidx, conn, cidx = self.split(b)
                    if sinst is inst:
                        body.append("    %s%s: <%s>" % (subnames[conn], cidx, ", ".join(self.link_meta(sinks[b]))))
            typ = WIRE_SPEC if k == "wire" else (g.spec_ref(inst.cls) if row is None else "kw.cdl::" + row["name"])
        else:
            typ = row["comp"]
            cg = self.compound_gain(inst, row)
            if cg is not None:
                row, typ = cg["row"], cg["row"]["comp"]
            body, binds, defaulted = self.comp_body(inst, sub, subnames, row, sinks, store)
            if cg is not None:
                body += self.compound_points(inst, cg)
                meta.append("cdlCompoundGain:" + xdict(OrderedDict([
                    ("unit", g.xs(cg["unit"])), ("gain", g.xs(cg["gain"])), ("per", g.xs(cg["per"])),
                    ("perGroup", g.xs(cg["perGroup"]))])))
        if binds:
            meta.append("cdlBind:{" + ", ".join("%s:%s" % (n, g.xs(v)) for n, v in binds.items()) + "}")
        if defaulted:
            meta.append("cdlDefaulted:" + g.xs(",".join(defaulted)))
        meta += literal_meta(store)
        if inst.finals:
            meta.append("cdlFinalBind:" + g.xs(",".join(sorted(subnames[x] for x in inst.finals))))
        if getattr(inst, "units", None):
            meta.append("cdlConnUnits:{" + ", ".join("%s:%s" % (subnames[x], g.xs(inst.units[x])) for x in sorted(inst.units)) + "}")
        if inst.cond:
            meta.append("cdlCondition:" + g.xs(inst.cond))
        if inst.size is not None:
            meta.append("cdlArraySize:" + g.xs(array_size(inst.size)))
        lines = ["  // " + inst.desc] if inst.desc else []
        if body:
            lines.append("  %s: %s? <%s> {" % (slot, typ, ", ".join(meta)))
            lines += body
            lines.append("  }")
        else:
            lines.append("  %s: %s? <%s>" % (slot, typ, ", ".join(meta)))
        return lines

    def add_feed(self, inst, name, spec, meta_extra, body):
        fname = self.feed_name(inst, name)
        if fname in self.taken:
            raise CxfError("%s: feed name %s collides with a slot" % (self.ci.path, fname))
        self.taken.add(fname)
        meta = ["cdlFeed:" + g.xs(inst.name + "." + name)] + meta_extra
        if inst.cond:
            meta.append("cdlCondition:" + g.xs(inst.cond))
        if inst.size is not None:
            meta.append("cdlArraySize:" + g.xs(array_size(inst.size)))
        if body:
            self.feeds[fname] = ["  %s: %s? <%s> {" % (fname, spec, ", ".join(meta))] + body + ["  }"]
        else:
            self.feeds[fname] = ["  %s: %s? <%s>" % (fname, spec, ", ".join(meta))]
        return fname

    def compound_gain(self, inst, row):
        """None, or how an instance runs when its gain is bound to a unit the unit database lacks (classmap_table
        requires.compoundGain): the row it runs on, the lines that fix the line's other points, and the units."""
        cg = table_row(row["name"]).get("requires", {}).get("compoundGain")
        if cg is None:
            return None
        k = next(iter(row["params"]))
        val, expr = inst.binds.get(k, (None, None))
        p = self.ci.param(expr.strip()) if val is None and expr and g.BARE_NAME.fullmatch(expr.strip()) else None
        unit = p.unit if p is not None else None
        if unit not in g.NO_HAYSTACK_UNIT or "/" not in unit:
            return None
        num, den = unit.split("/", 1)
        alt = dict(row)
        alt["comp"] = cg["comp"]
        alt["connectors"] = dict(cg["connectors"])
        alt["params"] = {k: dict(row["params"][k], slot=cg["gain"])}
        alt["fixedSlots"] = dict(cg["fixed"])
        alt["skipSlots"] = list(cg["zero"]) + [cg["per"]]
        return {"row": alt, "zero": list(cg["zero"]), "per": cg["per"], "perGroup": cg["perGroup"], "gain": cg["gain"],
                "fixed": cg["fixed"], "den": den, "num": num, "unit": unit}

    def compound_points(self, inst, cg):
        """The body lines that give a compound gain's line its other points: each through a NumberConst feed, like
        every fixed value, so a save, reload or flatten keeps them (Line's points are transient slots). The `per`
        point, 1 in the gain's denominator unit, is a difference the resolver converts with the group of `perGroup`;
        its feed records the SI unit and the delta mark."""
        st = HX + "StatusNumber"
        body = []
        for z in cg["zero"]:
            fname = self.add_feed(inst, z, HX + "NumberConst", [], ["    out: %s { val: 0 }" % st])
            body.append("    %s: <link:%s>" % (z, g.xs(fname + ".out")))
        fname = self.add_feed(inst, cg["per"], HX + "NumberConst",
                              ["cdlLiteralUnits:{out:%s}" % g.xs(cg["den"]), "cdlLiteralDelta:" + g.xs("out"),
                               "cdlUnitGroup:" + g.xs(inst.name + "." + cg["perGroup"])],
                              ["    out: %s { val: 1%s }" % (st, cg["den"])])
        body.append("    %s: <link:%s>" % (cg["per"], g.xs(fname + ".out")))
        body += ["    %s: %s" % (s, fixed_value(v)) for s, v in cg["fixed"].items()]
        return body

    def comp_body(self, inst, sub, subnames, row, sinks, store):
        """(body lines, cdlBind, defaulted parameter names) of a child on its hx.comps comp. Each literal's unit goes
        into `store`, for the child's literal meta."""
        trow = table_row(row["name"])
        req = trow.get("requires", {})
        values, binds, defaulted, body = OrderedDict(), OrderedDict(), [], []
        for k, pm in row["params"].items():
            p = sub.param(k)
            expr_text = None
            if k in inst.binds and p.dtype == "String":
                lit, expr = (inst.binds[k][1] or "").strip(), None      # a String parameter binds a literal text
            elif k in inst.binds:
                lit, expr = bind_value(inst.binds[k], p.dtype)
                raw = inst.binds[k][1]
                if expr is None and raw is not None and raw.strip() not in ("true", "false") \
                        and not (isinstance(lit, str) and raw.strip().endswith("." + lit)):
                    expr_text = raw.strip()                    # arithmetic or a package constant, evaluated
            elif k in row["cdlDefaults"]:
                lit, expr = default_value(sub, k, inst.binds, row)
                defaulted.append(subnames[k])
            elif pm["cdlDefault"] is None and pm["feed"] == "set" and pm["defaultStatus"] == "cdlRequired":
                raise CxfError("%s: %s leaves %s unbound, and CDL gives it no default" % (self.ci.path, inst.name, k))
            else:
                continue
            if expr is not None:
                binds[subnames[k]] = expr
                if pm["feed"] != "set":
                    fname = self.add_feed(inst, k, pm["feed"], [], [])
                    values[pm["slot"]] = "<link:%s>" % g.xs(fname + ".out")
                continue
            code = conv_code(pm)
            if row["grade"] == "const":
                st = STATUS_TYPE[p.dtype]
                sym = self.note_literal(inst, pm["slot"], k, p.dtype, lit, expr_text, store)
                values[pm["slot"]] = "%s { val: %s }" % (st, fmt_value(lit, None, p.dtype, sym))
            elif pm["feed"] == "set":
                # a Float, Int or Duration slot holds no unit suffix: the unit is recorded beside it only
                sym = self.note_literal(inst, pm["slot"], k, p.dtype if code in (None, "float", "sec") else None, lit,
                                        expr_text, store)
                values[pm["slot"]] = fmt_value(lit, code, p.dtype, sym if code is None else None)
            else:
                st = HX + ("StatusBool" if pm["feed"] == HX + "BoolConst" else "StatusNumber")
                fstore = {"units": OrderedDict(), "delta": [], "exprs": OrderedDict()}
                sym = self.note_literal(inst, "out", k, p.dtype, lit, expr_text, fstore)
                fname = self.add_feed(inst, k, pm["feed"], literal_meta(fstore),
                                      ["    out: %s { val: %s }" % (st, fmt_value(lit, None, None, sym))])
                values[pm["slot"]] = "<link:%s>" % g.xs(fname + ".out")
        for k in req.get("writeWhenUnit", []):
            pm = row["params"][k]
            if pm["slot"] in values or subnames[k] in binds:
                continue
            u, why = self.literal_unit(inst, k)
            p = sub.param(k)
            if u is None or u[0] == "1" or p.val is None:
                # not written: named in the units report, so a PID whose group lost its unit cannot pass unseen
                SKIPPED.append((self.ci.path, inst.name, k, "no CDL default" if p.val is None else
                                "its group is dimensionless" if u is not None else why))
                continue
            # the CDL default, written so a resolver sees the parameter and converts it with its unit group
            sym = self.note_literal(inst, pm["slot"], k, p.dtype if conv_code(pm) in (None, "float") else None,
                                    p.val, None, store)
            values[pm["slot"]] = fmt_value(p.val, conv_code(pm), p.dtype, sym if conv_code(pm) is None else None)
            defaulted.append(subnames[k])
        for fs, fv in trow["fixed"].items():
            values[fs] = fixed_value(fv)
        # links into the child, on comp slot names
        cuts = set(req.get("loopCut", []))
        linked = set()
        for b in sorted(sinks):
            sinst, _iidx, conn, cidx = self.split(b)
            if sinst is not inst:
                continue
            if cidx:
                raise CxfError("%s: %s links an element of %s, which has no array connector" % (self.ci.path, b, conn))
            linked.add(conn)
            m = row["connectors"][conn]
            meta = self.link_meta(sinks[b], cut=conn in cuts)
            if isinstance(m, dict):
                wn = req.get("whenNull", {})
                fbody = ["    in: <%s>" % ", ".join(meta)]
                if conn in wn:
                    fbody.append("    whenNull: %s" % fixed_value(wn[conn]))
                fname = self.add_feed(inst, conn, m["via"], [], fbody)
                values[m["slot"]] = "<link:%s>" % g.xs(fname + ".out")
            else:
                values[m] = "<%s>" % ", ".join(meta)
        for conn, v in req.get("linkAlways", {}).items():
            if conn in linked:
                continue
            fname = self.add_feed(inst, conn, HX + "BoolConst", [], ["    out: %s { val: %s }" % (HX + "StatusBool", fixed_value(v))])
            values[row["connectors"][conn]] = "<link:%s>" % g.xs(fname + ".out")
        for s, v in values.items():
            body.append("    %s: %s" % (s, v))
        return body, binds, defaulted


# ---- the CdlClass instances ----

def key(n):
    return n[0].lower() + n[1:]


def xdict(d):
    return "{" + ", ".join("%s:%s" % (k, v) for k, v in d.items()) + "}"


def state_fields(fact):
    """The state facts of one class (kw.cdl/meta.xeto's cdlState family) as CdlClass fields."""
    f = OrderedDict()
    if fact is None:
        return f
    f["state"] = g.xs(fact.state)
    if fact.init is not None:
        f["stateInit"] = g.xs(fact.init)
    if fact.init_basis is not None:
        f["stateInitBasis"] = g.xs(fact.init_basis)
    if fact.basis:
        f["stateBasis"] = g.xs("; ".join(fact.basis))
    return f


def bound_fields(ci):
    """CDL name (first letter lowered) -> {meta key: value} of each bound the class's own declarations give its
    parameters and connectors: the minVal, maxVal, cdlMin and cdlMax its elementary spec carried, with where each
    came from. An elementary class has no guarded bound; one would refuse."""
    out = OrderedDict()
    for x in ci.params + ci.conns:
        m = OrderedDict()
        lo, hi = (x.vmin, x.vmax) if isinstance(x, g.Param) else (x.cmin, x.cmax)
        lk, hk = ("minVal", "maxVal") if isinstance(x, g.Param) else ("cdlMin", "cdlMax")
        if lo is not None:
            m[lk] = g.xs(g.fmt_num(lo))
        if hi is not None:
            m[hk] = g.xs(g.fmt_num(hi))
        for item in g.bound_meta(x):
            k, v = item.split(":", 1)
            if k in ("cdlMinWhen", "cdlMaxWhen"):
                raise CxfError("%s.%s: an elementary class with a guarded bound" % (ci.path, x.name))
            m[k] = v
        if m:
            out[key(x.name)] = xdict(m)
    return out


def unit_rule_xeto(r):
    """A unitRule as CdlClass data: keep groups as text, `;` between groups and `,` within one."""
    d = OrderedDict([("family", g.xs(r["family"]))])
    if r["keep"]:
        d["keep"] = g.xs(";".join(",".join(k) for k in r["keep"]))
    if r["op"]:
        d["op"] = g.xs(r["op"])
        d["ins"] = g.xs(",".join(r["ins"]))
        d["out"] = g.xs(r["out"])
    if r["seeds"]:
        d["seeds"] = xdict(OrderedDict((k, g.xs(v)) for k, v in sorted(r["seeds"].items())))
    if r.get("note"):
        d["note"] = g.xs(r["note"])
    return xdict(d)


def render_classes(rows, facts, stamp, classes):
    """kw.cdl/classes.xeto: one CdlClass instance per CDL elementary class some spec runs, and the refused list."""
    lines = [g.COPYRIGHT, g.AFL_NOTICE, "//",
             "// kw.cdl: the CdlClass instance of each CDL elementary class, and the classes refused by name",
             "// GENERATED from MBL %s (%s) via modelica-json %s and the class-to-comp table. Do not edit."
             % (stamp["mbl"], stamp["mblCommit"][:8], stamp["modelicaJson"][:8]),
             "// The comps are hx.comps with the additions of haxall pull requests #138 to #152.",
             "// MBL's class names and defaults are redistributed under MBL's license: see NOTICE.", ""]
    refused = []
    for name, e in rows.items():
        if e["grade"] == "none":
            refused.append((name, e))
            continue
        t = table_row(name)
        f = OrderedDict()
        f["cdlClass"] = g.xs(e["cdlClass"])
        f["grade"] = g.xs(e["grade"])
        num, printed = g.CLAUSE7[e["cdlClass"]]
        f["clause"] = g.xs(num)
        if printed:
            f["name231"] = g.xs(printed)
        if e["grade"] in ("composite", "array"):
            f["comp"] = "kw.cdl::" + name
        elif e["comp"]:
            f["comp"] = e["comp"]
        conn, feeds, prm, conv, names, cdef = (OrderedDict() for _ in range(6))
        for k, v in e["connectors"].items():
            if key(k) != k:
                names[key(k)] = g.xs(k)
            if isinstance(v, str):
                conn[key(k)] = g.xs(v)
            else:
                feeds[key(k)] = "{slot:%s, via:%s}" % (g.xs(v["slot"]), v["via"])
        for k, v in e["params"].items():
            if key(k) != k:
                names[key(k)] = g.xs(k)
            if v["feed"] == "set":
                prm[key(k)] = g.xs(v["slot"])
            else:
                feeds[key(k)] = "{slot:%s, via:%s}" % (g.xs(v["slot"]), v["feed"])
            code = conv_code(v)
            if code:
                conv[key(k)] = g.xs(code)
        for k, v in e["cdlDefaults"].items():
            cdef[key(k)] = g.xs(v)
        if conn:
            f["connectors"] = xdict(conn)
        if prm:
            f["params"] = xdict(prm)
        if feeds:
            f["feeds"] = xdict(feeds)
        if conv:
            f["convert"] = xdict(conv)
        if e["fixedSlots"]:
            f["fixed"] = xdict(OrderedDict((k, fixed_value(v)) for k, v in e["fixedSlots"].items()))
        if cdef:
            f["cdlDefaults"] = xdict(cdef)
        req = e.get("requires", {})
        if req.get("linkAlways"):
            f["linkAlways"] = xdict(OrderedDict((key(k), fixed_value(v)) for k, v in req["linkAlways"].items()))
        if req.get("loopCut"):
            f["loopCut"] = g.xs(",".join(key(k) for k in req["loopCut"]))
        if req.get("whenNull"):
            f["whenNull"] = xdict(OrderedDict((key(k), fixed_value(v)) for k, v in req["whenNull"].items()))
        if req.get("writeWhenUnit"):
            f["writeWhenUnit"] = g.xs(",".join(key(k) for k in req["writeWhenUnit"]))
        if req.get("compoundGain"):
            cg = req["compoundGain"]
            f["compoundGain"] = xdict(OrderedDict([
                ("comp", g.xs(cg["comp"])), ("gain", g.xs(cg["gain"])), ("per", g.xs(cg["per"])),
                ("perGroup", g.xs(cg["perGroup"])),
                ("zero", g.xs(",".join(cg["zero"]))),
                ("fixed", xdict(OrderedDict((k, fixed_value(v)) for k, v in cg["fixed"].items())))]))
        if e["grade"] == "link":
            f["linkFrom"] = g.xs(e["link"]["from"])
            f["linkTo"] = g.xs(e["link"]["to"])
        if e.get("departures"):
            f["departures"] = "{" + ", ".join(g.xs(d) for d in e["departures"]) + "}"
        if e.get("unitRule"):
            f["unitRule"] = unit_rule_xeto(e["unitRule"])
        if names:
            f["cdlNames"] = xdict(names)
        # an array or composed class keeps its bounds on its own kw.cdl spec
        bounds = bound_fields(classes[e["cdlClass"]]) if e["grade"] not in ("array", "composite") else None
        if bounds:
            f["bounds"] = xdict(bounds)
        f.update(state_fields(facts.get(e["cdlClass"]) if facts else None))
        lines.append("@cdl-%s: CdlClass {" % name)
        lines += ["  %s: %s" % (k, v) for k, v in f.items()]
        lines.append("}")
        lines.append("")
    lines.append("// The CDL elementary classes no hx.comps comp or composition runs, and no G36 sequence uses.")
    lines.append("@cdl-refused: CdlRefused {")
    lines.append("  classes: {")
    for name, e in refused:
        reason = e["reason"].split(". ")[0].rstrip(".")
        reason = re.sub(r"\s*\([^)]*(\.xeto|\.fan|GAP|PR )[^)]*\)", "", reason)
        f = OrderedDict([("name", g.xs(name)), ("cdlClass", g.xs(e["cdlClass"]))])
        num, printed = g.CLAUSE7[e["cdlClass"]]
        f["clause"] = g.xs(num)
        if printed:
            f["name231"] = g.xs(printed)
        f["reason"] = g.xs(reason)
        f.update(state_fields(facts.get(e["cdlClass"]) if facts else None))
        lines.append("    CdlRefusal {%s}" % ", ".join("%s:%s" % kv for kv in f.items()))
    lines += ["  }", "}", ""]
    return "\n".join(lines)


# ---- the round trip: read a mapped composite back into CDL terms ----

NUMBER_UNIT = re.compile(r"^(-?\d[\d.]*(?:[eE][-+]?\d+)?)(.*)$")


def _unconvert(text, code, dtype, unit=None):
    """The CDL literal a slot value was converted from, as its CXF modifier text. A number written with a unit
    suffix must carry the unit the child's cdlLiteralUnits records for it (`unit`), or nothing when none is recorded."""
    t = text.strip()
    m = NUMBER_UNIT.match(t)
    if m and code not in ("sec",) and not t.startswith('"'):
        suffix = m.group(2)
        want = units.written_symbol((unit, False)) if unit else None
        if (suffix or None) != want:
            raise CxfError("the literal %s carries unit %r; its recorded unit writes %r" % (t, suffix or None, want))
        return m.group(1)
    if t.startswith('"'):
        t = json.loads(t)
        if code is not None and code.startswith("enum"):
            back = {v: k for k, v in (x.split("=") for x in code.split()[1:])}
            return dtype + "." + back[t]
        return t
    if code == "sec":
        # a Duration slot holds seconds written with their unit; a bare number lost its conversion
        if not t.endswith("sec"):
            raise CxfError("a seconds value %r was written without its unit" % t)
        return t[:-3]
    return t


def _status_val(text):
    m = re.search(r"val: (.*) \}$", text)
    if m is None:
        raise CxfError("a constant value %r is not `Status... { val: x }`" % text)
    return m.group(1)


def parse_mapped(text, cls, mapped, classes):
    """The generated spec of `cls` read back into the shape mo_reader.read returns, with each hx.comps child turned
    back into its CDL class: slot names to CDL connectors and parameters, slot values to bindings (each CDL default
    the generator wrote, named in cdlDefaulted, dropped), feeds folded into the child they supply, and each link
    through a CdlWire restored as the two connections MBL wrote."""
    start = text.find('cdlClass:"%s"' % cls)
    if start < 0:
        raise CxfError("no generated spec for " + cls)
    body = text[text.index("{", start) + 1:]
    res = {"params": {}, "inputs": {}, "outputs": {}, "components": {}, "connects": set(), "links": set()}
    lines = body.split("\n")
    kids, conn_links, i = OrderedDict(), [], 0
    plain = {STATUS_TYPE["Real"]: "Number", STATUS_TYPE["Boolean"]: "Bool", STATUS_TYPE["String"]: "Str"}
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1
        if line == "}":
            break
        m = re.match(r"^  (\w+): (\S+?)(\?)? (<.*)$", line)
        if not m:
            continue
        slot, typ, rest = m.group(1), m.group(2), m.group(4)
        meta, end = g._meta(rest)
        tail = rest[end:].strip()
        sub = OrderedDict()
        if tail.startswith("{"):
            while lines[i].strip() != "}":
                sm = re.match(r"^    (\w+(?:\[[^\]]*\])?): (.*)$", lines[i])
                v = sm.group(2).strip()
                sub[sm.group(1)] = g._meta(v)[0] if v.startswith("<") else v
                i += 1
            i += 1
        cdl = meta.get("cdlName", slot)
        if "cdlParam" in meta:
            dflt = json.loads(tail) if tail.startswith('"') else meta.get("cdlDefault")
            dialog = {k: meta[x] for k, x in (("enable", "cdlEnable"), ("group", "cdlGroup"), ("tab", "cdlTab")) if x in meta}
            if "cdlValueInReference" in meta:
                dialog["valueInReference"] = meta["cdlValueInReference"] == "true"
            # a reviewed override (cdlUnitOverride) keeps MBL's unit for the comparison with MBL's source
            res["params"][cdl] = {"default": dflt, "unit": meta.get("cdlUnitOverride", meta.get("cdlUnit")),
                                  "protected": "cdlProtected" in meta,
                                  "type": meta.get("cdlType"), "xeto": typ, "final": "cdlFinal" in meta, "dialog": dialog}
        elif "cdlInput" in meta or "cdlOutput" in meta:
            res["inputs" if "cdlInput" in meta else "outputs"][cdl] = {
                "type": meta.get("cdlType"), "unit": meta.get("cdlUnit"), "xeto": plain.get(typ, typ)}
            if "link" in meta or "cdlAltLink" in meta:
                conn_links.append((slot, meta))
        else:
            kids[slot] = (typ, meta, sub)
    feeds = {s: k for s, k in kids.items() if "cdlFeed" in k[1]}
    by_name = {r["name"]: r for r in mapped.values()}
    rows = {s: (by_name[k[1]["cdlOf"].split("::cdl-", 1)[1]] if k[1].get("cdlOf") else None)
            for s, k in kids.items() if s not in feeds}
    for s, row in list(rows.items()):
        cg = table_row(row["name"]).get("requires", {}).get("compoundGain") if row is not None else None
        if cg is not None and "cdlCompoundGain" in kids[s][1]:
            # read back on the comp it runs on: the gain on the line's second point, the other points skipped
            k = next(iter(row["params"]))
            rows[s] = dict(row, connectors=dict(cg["connectors"]), params={k: dict(row["params"][k], slot=cg["gain"])},
                           fixedSlots=dict(cg["fixed"]), skipSlots=list(cg["zero"]) + [cg["per"]])
    rev = {}
    for s, row in rows.items():
        if row is not None and row["grade"] in MAPPED:
            r = {v: k for k, v in row["connectors"].items() if isinstance(v, str)}
            r.update({v["slot"]: k for k, v in row["connectors"].items() if isinstance(v, dict)})
            rev[s] = r

    def unmap(src):
        parts = src.split(".")
        if len(parts) == 1:
            return src
        head, slot = parts
        if head in feeds:
            raise CxfError("%s: a link reads the feed %s outside its child" % (cls, src))
        row = rows.get(g.base_name(head))
        if row is None or row["grade"] not in MAPPED:
            return src
        return head + "." + g.lower(rev[g.base_name(head)][slot])

    def add_link(src, tgt, meta):
        if src is None:
            for alt in [x for x in meta.get("cdlAltLink", "").split(",") if x]:
                res["connects"].add(frozenset((unmap(alt), tgt)))
                res["links"].add((unmap(alt), tgt))
            return
        vias = [v for v in meta.get("cdlLinkVia", "").split(",") if v]
        chain = [tgt] + [v + "." + g.lower(rows[v]["link"]["from"]) for v in vias]
        froms = [v + "." + g.lower(rows[v]["link"]["to"]) for v in vias] + [unmap(src)]
        for a, b in zip(froms, chain):
            res["connects"].add(frozenset((a, b)))
            res["links"].add((a, b))
        for alt in [x for x in meta.get("cdlAltLink", "").split(",") if x]:
            res["connects"].add(frozenset((unmap(alt), tgt)))
            res["links"].add((unmap(alt), tgt))

    for s, row in rows.items():
        typ, meta, sub = kids[s]
        comp = {"binds": dict(meta.get("cdlBind", {})), "cond": meta.get("cdlCondition"),
                "finals": set(filter(None, meta.get("cdlFinalBind", "").split(","))), "cdlName": meta.get("cdlName"),
                "units": meta.get("cdlConnUnits", {})}
        res["components"][s] = comp
        if row is None or row["grade"] not in MAPPED:
            comp["class"] = typ if row is None else g.spec_ref(row["cdlClass"])
            for k, v in sub.items():
                if isinstance(v, dict) and ("link" in v or "cdlAltLink" in v):
                    add_link(v.get("link"), s + "." + k, v)
            continue
        comp["class"] = g.spec_ref(row["cdlClass"])
        sub_ci = classes[row["cdlClass"]]
        subnames = g.slot_names([p.name for p in sub_ci.params] + [c.name for c in sub_ci.conns], sub_ci.path)
        by_slot = {pm["slot"]: (k, pm) for k, pm in row["params"].items()}
        for fs, fv in row["fixedSlots"].items():
            # a fixed slot is the class, not the instance: it must be written, and with the table's value
            if sub.get(fs) != fixed_value(fv):
                raise CxfError("%s.%s: fixed slot %s is %r, the class map fixes it at %s"
                               % (cls, s, fs, sub.get(fs), fixed_value(fv)))
        for k, v in sub.items():
            if k in row["fixedSlots"] or k in row.get("skipSlots", ()):
                continue
            if isinstance(v, dict) and "link" in v and v["link"].endswith(".out") and v["link"][:-4] in feeds:
                ftyp, fmeta, fsub = feeds[v["link"][:-4]]
                feed_of = fmeta["cdlFeed"].split(".", 1)[1]
                if feed_of in row["params"]:
                    if "out" in fsub:
                        comp["binds"][subnames[feed_of]] = _unconvert(_status_val(fsub["out"]), None,
                                                                      sub_ci.param(feed_of).dtype,
                                                                      fmeta.get("cdlLiteralUnits", {}).get("out"))
                elif isinstance(fsub.get("in"), dict):
                    add_link(fsub["in"].get("link"), s + "." + g.lower(feed_of), fsub["in"])
                continue
            if isinstance(v, dict) and ("link" in v or "cdlAltLink" in v):
                add_link(v.get("link"), s + "." + g.lower(rev[s][k]), v)
                continue
            if k in by_slot:
                name, pm = by_slot[k]
                p = sub_ci.param(name)
                text_v = _status_val(v) if row["grade"] == "const" else v
                comp["binds"][subnames[name]] = _unconvert(text_v, None if row["grade"] == "const" else conv_code(pm),
                                                           p.dtype, meta.get("cdlLiteralUnits", {}).get(k)
                                                           if row["grade"] == "const" or conv_code(pm) is None else None)
                continue
            raise CxfError("%s.%s: slot %s maps to no CDL name" % (cls, s, k))
        for d in filter(None, meta.get("cdlDefaulted", "").split(",")):
            comp["binds"].pop(d, None)
    for slot, meta in conn_links:
        add_link(meta.get("link"), slot, meta)
    return res
