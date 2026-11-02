#!/usr/bin/env python3
#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Generate the open libs from the pinned CXF: kw.cdl/blocks.xeto and kw.cdl.g36.{common,ahu,terminal}/g36.xeto.

Run from the repo root:

  python -X utf8 src/gen/generate.py                # regenerate src/xeto/kw.cdl*/ and the two reports in src/gen/
  python -X utf8 src/gen/generate.py --out DIR      # write a tree of the same shape under DIR: DIR/src/xeto/...
                                                    # and DIR/src/gen/...
  python -X utf8 src/gen/generate.py --no-fetch     # read MBL's .mo from the mbl_fetch.py cache only
  python -X utf8 src/gen/generate.py --collisions   # list generated slot names that are also Project Haystack ph
                                                    # tags, from ph_tags.json

The generator reads its inputs from the source directory cxf_source.py names, verified against source_manifest.json
first. Every generated file names the MBL version stamp.json pins (14.0.0); CXF carries no version. The state facts
read MBL's .mo, which mbl_fetch.py downloads at the release tag and verifies file by file against mbl_manifest.json:
a file missing or differing stops generation, naming it.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if __name__ == "__main__":
    sys.modules.setdefault("generate", sys.modules[__name__])   # classmap and hxemit import this module by name
import classmap  # noqa: E402
import cxf  # noqa: E402
import cxf_source  # noqa: E402
import hxemit  # noqa: E402
import mbl_fetch  # noqa: E402
import mjson  # noqa: E402
import mo_state  # noqa: E402
from cxf import CxfError, as_list, literal, local, resolve_class  # noqa: E402

# The repo root. The generated libs sit under src/xeto and the reports beside this file, both relative to it, so
# --out DIR writes a tree of the same shape.
REPO = HERE.parents[1]
LIBS = "src/xeto"
GEN = "src/gen"
OBC = "Buildings.Controls.OBC."
CLAUSE7 = {}
# Classes CXF-Core carries that are not blocks, skipped by name with the rule.
SKIP_CLASSES = {OBC + "CDL.Constants": "a package of constants, not a block; 231 Clause 7 lists no Constants block"}
# Parameter types CXF does not carry, as hand rules, each with its source line.
HAND_TYPES = {OBC + "CDL.Reals.Sources.CalendarTime.zerTim": OBC + "CDL.Types.ZeroTime"}   # CalendarTime.mo:4
# Connectors CXF does not type, as hand rules, each with its source line. modelica-json 5460add3
# writes a connector declared `discrete` as a node with no @type and leaves it off hasOutput, so CalendarTime
# would lose two outputs MBL declares. The node still carries its description, which the rule reads. A rule
# whose connector CXF already lists refuses, so a fixed modelica-json cannot produce a duplicate.
HAND_CONNECTORS = {OBC + "CDL.Reals.Sources.CalendarTime.year": "IntegerOutput",     # CalendarTime.mo:16
                   OBC + "CDL.Reals.Sources.CalendarTime.month": "IntegerOutput"}    # CalendarTime.mo:19
# Class constants CXF does not carry, as hand rules, each with its source line. modelica-json 5460add3 writes no node
# for an elementary block's protected `final constant`, so CalendarTime's yearRef(min=firstYear, max=lastYear) would
# name nothing. The bounds test reads both values from the .mo independently. A rule for a constant CXF already
# lists refuses, so a fixed modelica-json cannot carry two values.
HAND_CONSTANTS = {OBC + "CDL.Reals.Sources.CalendarTime.firstYear": 2010.0,   # CalendarTime.mo:39
                  OBC + "CDL.Reals.Sources.CalendarTime.lastYear": 2031.0}    # CalendarTime.mo:41, firstYear+21
CDL_PREFIX = OBC + "CDL."
G36_PREFIX = OBC + "ASHRAE.G36."

# Contained instances are maybe slots ("maybe"), never values on a record.
INSTANCE_SLOT = "maybe"
# The names Clause 7 prints differently from MBL, by clause number: Clause 7 as printed -> MBL 12.1.0.
NORMALIZE = {"7.5.29.1": "CDL.Reals.MultiSum", "7.5.29.2": "CDL.Integers.MultiSum", "7.5.39.2": "CDL.Integers.Change",
             "7.5.66.2": "CDL.Integers.LessThreshold", "7.5.71.1": "CDL.Integers.Stage",
             "7.5.82.3": "CDL.Logical.Sources.Constant", "7.5.83.3": "CDL.Logical.Sources.Pulse",
             # Two headings print a stray 7 before the package name.
             "7.5.65.1": "CDL.Integers.LessEqualThreshold", "7.5.76.1": "CDL.Logical.Timer"}


def load_stamp():
    """The MBL release and modelica-json commit the generator pins, which every generated file names."""
    return json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))


def clause7():
    """MBL class path -> (clause number, Clause 7 spelling or None when it matches)."""
    c7 = json.loads((HERE / "clause7.json").read_text(encoding="utf-8"))["classes"]
    out = {}
    for num, printed in c7.items():
        mbl = OBC + NORMALIZE.get(num, printed)
        out[mbl] = (num, None if NORMALIZE.get(num, printed) == printed else printed)
    return out
# The open libs. kw.cdl holds the CDL model: the block base, the Clause 7 blocks, the CDL enumerations and the CDL
# meta. The G36 sample library splits by MBL package into three libs, so ahu and terminal each depend on common and
# never on each other, which is G36's own direction. FanCoilUnits instantiates
# AHUs.SingleZone.VAV.SetPoints.ModeAndSetPoints, so it sits in ahu.
# Plants is in no lib: modelica-json crashes on 16 of its classes.
G36_LIBS = {"kw.cdl.g36.common": ("Generic", "Types", "ThermalZones", "VentilationZones", "ZoneGroups"),
            "kw.cdl.g36.ahu": ("AHUs", "FanCoilUnits"),
            "kw.cdl.g36.terminal": ("TerminalUnits",)}
OPEN_LIBS = ("kw.cdl",) + tuple(G36_LIBS)
# What each open lib may depend on: the CDL model, and common for ahu and terminal. Nothing else.
# test_open_libs.py reads every lib.xeto in the repo against this.
# kw.cdl depends on hx.comps, since a CDL elementary class is an hx.comps comp. The G36 libs also name Project
# Haystack point specs, so they depend on ph, ph.points and ph.points.x.
G36_DEPENDS = ("sys", "sys.comp", "hx.comps", "kw.cdl", "ph", "ph.points", "ph.points.x")
OPEN_DEPENDS = {"kw.cdl": ("sys", "sys.comp", "hx.comps"),
                "kw.cdl.g36.common": G36_DEPENDS,
                "kw.cdl.g36.ahu": G36_DEPENDS + ("kw.cdl.g36.common",),
                "kw.cdl.g36.terminal": G36_DEPENDS + ("kw.cdl.g36.common",)}


def g36_lib(cls):
    """The open lib that holds a G36 class, by its first package under G36."""
    if not cls.startswith(G36_PREFIX):
        raise CxfError("%s is not a G36 class" % cls)
    pkg = cls[len(G36_PREFIX):].split(".", 1)[0]
    for lib, pkgs in G36_LIBS.items():
        if pkg in pkgs:
            return lib
    raise CxfError("%s: G36 package %s belongs to no open lib" % (cls, pkg))


# Four G36 composites, in dependency order: TrimAndRespond before SupplyTemperature, which instantiates it. A link
# test anchors on them; generation covers every pinned G36 class.
G36 = ["Generic.TrimAndRespond", "AHUs.MultiZone.VAV.SetPoints.SupplyTemperature",
       "AHUs.MultiZone.VAV.SetPoints.SupplyFan", "TerminalUnits.Reheat.Subsequences.SystemRequests"]
# Packages of constants. `Types.OperationModes` is a package of `constant Integer`, not an enumeration, and
# modelica-json 5460add3's CXF writes no node for it, so a binding that names one (SupplyFan's conInt.k =
# ...Types.OperationModes.coolDown) resolves to nothing. The generator reads each package from modelica-json's json
# output, kw.cdl.g36.common/json/Types/<name>.json in the source directory, and emits one kw.cdl::CdlConstants
# instance per package. The resolver reads a dotted name through that table, never by string search.
G36_CONSTANTS = {"Types." + n: "Types/" + n for n in ("DemandLimitLevels", "FreezeProtectionStages", "OperationModes", "ZoneStates")}


def g36_sources(root, kind):
    """Every pinned G36 source of one kind ("cxf" or "json"), across the three G36 libs, sorted by path."""
    ext = ".jsonld" if kind == "cxf" else ".json"
    return sorted(f for lib in G36_LIBS for f in (root / lib / kind).rglob("*" + ext))

UNITS = {"K": "K", "SEC": "s", "UNITLESS": "1", "DEG_C": "°C", "PA": "Pa", "PERCENT": "%",
         "M3-PER-SEC": "m³/s", "W": "W", "HR": "h", "MIN": "min",
         # Sources.Sin's freqHz and phase, SunRiseSet's lat and lon: MBL writes Hz and rad.
         "HZ": "Hz", "RAD": "rad",
         # SpecificEnthalpy_TDryBulPhi's h, and the 1/s that modelica-json writes as S231:1/s
         # when qudt has no unit for it (LimitSlewRate and kin).
         "J-PER-KiloGM": "J/kg", "1/s": "1/s",
         # MBL 14.0.0: the gains and the change rate of the G36 controllers (AHU kTSup, the terminal units'
         # kVal and chaRat, the fan coil unit's kCoo), which modelica-json writes as S231:1/K and S231:s/K when qudt
         # has no unit for them.
         "1/K": "1/K", "s/K": "s/K"}
# Modelica unit strings, as the json output carries them, to the same symbols UNITS gives the qudt keys.
MODELICA_UNITS = {"K": "K", "s": "s", "1": "1", "Pa": "Pa", "m3/s": "m³/s", "degC": "°C", "W": "W", "h": "h",
                  "min": "min", "Hz": "Hz", "rad": "rad", "J/kg": "J/kg", "1/s": "1/s", "1/K": "1/K", "s/K": "s/K"}
# camelCase, from sys::UnitQuantity ("temperature differential" is a compile error)
QUANTITY = {"ThermodynamicTemperature": "temperature", "TemperatureDifference": "temperatureDifferential",
            "Time": "time", "VolumeFlowRate": "volumetricFlow"}
# Canonical Xeto `unit` meta, written beside cdlUnit (kept as CXF provenance) on every slot that has a cdlUnit
# (kw.cdl 0.4.0). Keyed on the cdlUnit symbol; K is keyed on the quantity too, because the
# temperature and temperature differential quantities share one dimension and only the quantity tells them apart.
# None means the `unitless` marker. A cdlUnit missing here, or a K with no quantity, refuses generation by name.
# A slot with no cdlUnit gets no unit and no unitless: absence means polymorphic, typed per instance.
XETO_UNIT = {"s": "sec", "1": None, "1/s": "/s", "Pa": "Pa", "Hz": "Hz", "rad": "rad", "J/kg": "J/kg",
             "m³/s": "m³/s"}
XETO_KELVIN = {"temperature": "K", "temperatureDifferential": "ΔK"}
# The units whose values a resolver shows in the unit of the point bound to them (a block shows values in the
# bound point's unit, anything else is SI). A slot in one of them carries cdlUnit and
# quantity but no Xeto `unit`, since `xeto fits` checks `unit` by exact match and would refuse the converted value.
# A temperature has one spelling, K, absolute or difference, as hx.comps takes it; cdlDelta marks a difference.
CONVERTED = ("K", "Pa", "m³/s", "J/kg", "/s")
# The quantity a unit implies on its own, filled where CXF carries no quantity kind or one with no Xeto quantity
# (PressureDifference, SpecificEnergy). Each name is a quantity section of the unit database (etc/sys/units.txt), so
# fits accepts a value converted into inH2O, cfm or BTU/lb and refuses one in another quantity.
IMPLIED_QUANTITY = {"s": "time", "Pa": "pressure", "J/kg": "specificEnthalpy", "m³/s": "volumetricFlow",
                    "1/s": "frequency"}


def converted_symbol(unit):
    """The unit symbol of a slot a resolver shows in the bound point's unit (CONVERTED), or None for any other."""
    if unit == "K":
        return "K"
    sym = XETO_UNIT.get(unit)
    return sym if sym in CONVERTED else None
# CDL units that have no symbol in Haystack's unit database (etc/sys/units.txt, 4.0.6: nothing per kelvin, and no
# second per kelvin), so no canonical Xeto `unit` can name them. Such a slot keeps cdlUnit as provenance and carries
# neither `unit` nor `unitless`: unit propagation reads it as a compound unit with no Haystack symbol, which stays
# unknown. Each entry says what MBL uses it for.
NO_HAYSTACK_UNIT = {"1/K": "a gain on a temperature error (kTSup, kVal, kCoo)",
                    "s/K": "seconds per kelvin, the terminal units' and TimeSuppression's change rate chaRat"}
CONNECTOR = {"RealInput": ("in", "Real"), "IntegerInput": ("in", "Integer"), "BooleanInput": ("in", "Boolean"),
             "RealOutput": ("out", "Real"), "IntegerOutput": ("out", "Integer"), "BooleanOutput": ("out", "Boolean")}
XETO_TYPE = {"Real": "Number", "Integer": "Int", "Boolean": "Bool", "String": "Str"}   # by CXF's isOfDataType
# Connector types in the open model: plain sys types, because the status types are an engine's, not CDL's. A CDL
# Integer connector is a Number, a shape that loads on sys and sys.comp alone and the shape an engine's StatusNumber
# carries; a parameter keeps XETO_TYPE. An engine binding may retype each connector to its status type.
CONN_TYPE = {"Real": "Number", "Integer": "Number", "Boolean": "Bool", "String": "Str"}


class Param:
    def __init__(self, name, dtype, val, expr, unit, qkind, protected, final, desc, vmin=None, vmax=None):
        self.name, self.dtype, self.val, self.expr = name, dtype, val, expr
        self.unit, self.qkind, self.protected, self.final, self.desc = unit, qkind, protected, final, desc
        self.vmin, self.vmax = vmin, vmax
        # Where a bound came from (kw.cdl 0.6.0): the MBL expression a constant-resolved bound was written with, a bound
        # written as an expression of the class's parameters (no static number), and the instance path of the block
        # parameter a propagated bound was taken from (propagate_bounds).
        self.min_const = self.max_const = self.min_expr = self.max_expr = None
        self.min_via = self.max_via = None
        self.min_own = self.max_own = self.min_when = self.max_when = None
        # From modelica-json's json output: Dialog(enable, group, tab), __cdl(ValueInReference)
        self.enable = self.group = self.tab = self.value_in_reference = None
        # An array's size: `raw_size` is sizeOfDimensions as CXF wrote it ("" when CXF gives none), which the
        # generator writes as cdlArraySize; `size` is the expression the expander evaluates.
        self.raw_size, self.size = None, None
        self.dims = 0                   # 0 scalar, 1 or 2; `size` is a pair for 2


class Conn:
    def __init__(self, name, direction, dtype, unit, qkind, cond, desc, cmin=None, cmax=None, raw_size=None, size=None,
                 dims=0):
        self.name, self.direction, self.dtype, self.unit = name, direction, dtype, unit
        self.qkind, self.cond, self.desc = qkind, cond, desc
        self.cmin, self.cmax, self.raw_size, self.size, self.dims = cmin, cmax, raw_size, size, dims
        self.min_const = self.max_const = self.min_expr = self.max_expr = None


class Inst:
    def __init__(self, name, cls, binds, cond, desc, finals=None, size=None, dims=0):
        self.name, self.cls, self.binds, self.cond, self.desc = name, cls, binds, cond, desc
        self.finals = finals or set()   # modifier names CXF marked S231:isFinal
        self.units = {}                 # sub-connector name -> CDL unit, MBL's per-instance `u1(unit="Pa")`
        self.size = size                # a vectorized instance name[size]: the size expression
        self.dims = dims                # 1 for a vectorized instance; 2 is refused in a design class


class Unsupported(CxfError):
    """A class the generator leaves out of the generated set, with a report line."""


class ClassInfo:
    def __init__(self, path, kind, desc):
        self.path, self.kind, self.desc = path, kind, desc
        self.params, self.conns, self.insts, self.edges, self.items = [], [], [], [], []

    def conn(self, name):
        return next((c for c in self.conns if c.name == name), None)

    def inst(self, name):
        return next((i for i in self.insts if i.name == name), None)

    def param(self, name):
        return next((p for p in self.params if p.name == name), None)


def one_line(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def spec_name(cls, prefix):
    if not cls.startswith(prefix):
        raise CxfError("%s is not under %s" % (cls, prefix))
    out = []
    for seg in cls[len(prefix):].split("."):
        m = re.match(r"^([A-Z]+)(.*)$", seg)
        if m and len(m.group(1)) >= 2:
            run, rest = m.group(1), m.group(2)
            if rest and rest[0].islower() and len(rest) > 1:
                rest = run[-1] + rest
                run = run[:-1]
            seg = run[0] + run[1:].lower() + rest
        out.append(seg[0].upper() + seg[1:])
    name = "".join(out)
    if not re.match(r"^[A-Z][A-Za-z0-9_]*$", name):
        raise CxfError("spec name %s from %s is not a Xeto spec name" % (name, cls))
    return name


def lower(name):
    return name[0].lower() + name[1:] if name and name[0].isupper() else name


def slot_names(names, owner):
    seen = {}
    for n in names:
        s = lower(n)
        if s in seen:
            raise CxfError("%s: slot names %s and %s collide after lowering" % (owner, seen[s], n))
        seen[s] = n
    return {v: k for k, v in seen.items()}


def lower_path(path):
    return ".".join(lower(p) for p in path.split("."))


def _qudt(node, name):
    """A qudt property under either namespace spelling: modelica-json's design CXF binds qudt to
    .../qudt#, its committed CXF-Core.jsonld to .../qudt/ (measured at 5460add3)."""
    v = node.get(cxf.QUDT + name)
    return v if v is not None else node.get(cxf.QUDT[:-1] + "/" + name)


def _unit(node, doc):
    u = _qudt(node, "hasUnit")
    if u is None:
        return None
    key = local(u["@id"]) if "#" in u["@id"] else u["@id"].rsplit("/", 1)[-1]
    if key not in UNITS:
        # A raw qudt key is not a Haystack unit (HZ, RAD and J-PER-KiloGM each shipped that way once), so an
        # unmapped key refuses by name instead of passing through.
        raise CxfError("%s: unit %s has no Haystack symbol in generate.UNITS" % (local(node["@id"]), key))
    return UNITS[key]


def _qkind(node):
    q = _qudt(node, "hasQuantityKind")
    return None if q is None else (local(q["@id"]) if "#" in q["@id"] else q["@id"].rsplit("/", 1)[-1])


# The CDL.Constants package (eps, small) as the pinned CXF carries it: full name -> number. A bound MBL writes with
# one (PIDWithReset.k: min=100*Constants.eps) resolves through this table. load_classes fills it from the CXF
# document that holds the package. pi is written as a function call (2*Modelica.Math.asin(1)) and stays out, so a
# bound that named it would refuse rather than guess.
CDL_CONSTANTS = {}


def _cdl_constant(name, scope):
    """A dotted name in a bound, looked up the within chain of `scope` among CDL_CONSTANTS (Constants.eps from inside
    the CDL package, or the full Buildings.Controls.OBC.CDL.Constants.eps). None when it names no constant."""
    parts = scope.split(".")
    for cand in [".".join(parts[:i]) + "." + name for i in range(len(parts), 0, -1)] + [name]:
        if cand in CDL_CONSTANTS:
            return CDL_CONSTANTS[cand]
    return None


def _class_constants(ci):
    """The class's own constants (S231:hasConstant, read as protected parameters) that evaluate to a number, as the
    environment for its bounds, plus any HAND_CONSTANTS rule for the class (CalendarTime's firstYear and lastYear)."""
    env, todo = {}, [p for p in ci.params if getattr(p, "constant", False)]
    for full, v in sorted(HAND_CONSTANTS.items()):
        owner, _, name = full.rpartition(".")
        if owner == ci.path:
            if ci.param(name) is not None:
                raise CxfError("%s: hand rule for constant %s, which CXF already lists; drop the rule" % (ci.path, name))
            env[name] = v
    while todo:
        left = []
        for p in todo:
            if p.val is not None and not isinstance(p.val, bool):
                env[p.name] = p.val
                continue
            try:
                v = cxf.evaluate(p.expr, env, lambda n: _cdl_constant(n, ci.path)) if p.expr else None
            except CxfError:
                left.append(p)
                continue
            if isinstance(v, float):
                env[p.name] = v
        if len(left) == len(todo):
            break                                     # the rest name parameters or functions: not numbers here
        todo = left
    return env


def _bound(raw, where, ci, env):
    """One min or max as CXF writes it, as (number, constant expression, parameter expression).

    A literal is the number alone. An expression that names only CDL constants and the class's own constants
    resolves to its number and keeps the expression as provenance, which a reviewer traces back to MBL (Constants.eps
    is 1E-15 at the pin). Plain arithmetic of literals (100*1E-15) is the number alone, as before 0.6.0. An
    expression that names a parameter of the class (min=outDamPhy_min, max=0.5/n) has no static number: it comes
    back as the parameter expression. Anything else refuses by name, so a bound is never dropped silently."""
    if raw is None:
        return None, None, None
    val, expr = literal(raw)
    if val is not None:
        return val, None, None
    expr = expr.strip()
    names = cxf.names(expr)
    for n in names:
        if "." in n and _cdl_constant(n, ci.path) is None:
            raise CxfError("%s: bound %s names %s, which is no CDL constant" % (where, expr, n))
    free = [n for n in names if "." not in n and n not in env]
    if free:
        params = {p.name for p in ci.params}
        missing = [n for n in free if n not in params]
        if missing:
            raise CxfError("%s: bound %s names %s, which is neither a constant nor a parameter of %s"
                           % (where, expr, ", ".join(missing), ci.path))
        return None, None, expr
    v = cxf.evaluate(expr, env, lambda n: _cdl_constant(n, ci.path))
    if not isinstance(v, float):
        raise CxfError("%s: bound %s is not a number" % (where, expr))
    return v, (expr if names else None), None


def _enum_of(lit, scope, enums):
    """The enumeration a literal like Buildings...Types.HeatingCoil.WaterBased names, by within-chain lookup."""
    owner = lit.rpartition(".")[0]
    if not owner:
        return None
    try:
        return resolve_class(owner, scope, enums)
    except CxfError:
        return None


def strip_size(raw):
    """The size expression from sizeOfDimensions or cdlArraySize: ONE outer pair of parentheses stripped,
    whitespace kept as written ("(nZon)" gives "nZon", "(5)" gives "5")."""
    return raw[1:-1] if raw.startswith("(") and raw.endswith(")") else raw


def split_size(raw, path, name):
    """A two-dimensional size "(a,b)" as the pair of its expressions, each stripped."""
    inner, depth, parts, start = strip_size(raw), 0, [], 0
    for i, ch in enumerate(inner):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
    parts.append(inner[start:])
    if len(parts) != 2 or not all(x.strip() for x in parts):
        raise CxfError("%s: %s has two dimensions but its size %s is not two expressions" % (path, name, raw))
    return tuple(x.strip() for x in parts)


def _array(doc, node, path, name, design, valued=False):
    """(raw_size, size, dims) of a parameter, connector or instance node; (None, None, 0) when it is not an array.
    `size` is the expression for one dimension, the pair of expressions for two, and None for an unsized array
    (`K[:,:]`, sized by its value).

    A design class refuses what the expander cannot expand, by name: more than two dimensions, or no size on anything
    but a parameter with a value. A class from the pinned MBL CXF is read as its generated spec carries it
    (cdlArraySize), so generation is unchanged; an MBL array the expander cannot use refuses there."""
    if not doc.get(node, "isArray"):
        return None, None, 0
    dims = doc.get(node, "sizeOfDimensions")
    nd = doc.get(node, "numberDimensions")
    nd = int(nd) if isinstance(nd, (int, float)) and not isinstance(nd, bool) else 1
    if design:
        if nd not in (1, 2):
            raise CxfError("%s: %s has %s dimensions; one or two are supported" % (path, name, nd))
        if dims is None and not valued:
            raise CxfError("%s: %s is an array with no size" % (path, name))
    raw = str(dims) if dims is not None else ""          # "" when CXF gives no size
    if dims is None:
        return raw, None, nd
    return raw, (split_size(raw, path, name) if nd == 2 else strip_size(raw)), nd


def base_name(part):
    """`u[3]` -> `u`: an endpoint part with its index stripped, to find the connector or instance."""
    return part.split("[", 1)[0]


def read_class(doc, cid, known, enums, decls=None, design=False):
    """One CXF class node into ClassInfo. `known` holds every class path the generator knows. `decls` is the class's
    declarations from modelica-json's json output (mjson.read), None for a class with no pinned json output (the
    CDL elementary blocks: Dialog meta is generated for the G36 libs). `design` marks a class from a design package,
    read under the array refusals of _array."""
    node = doc.node(cid)
    path = local(cid)
    t = local(node.get("@type", ""))
    if node.get("@type") == cxf.S231 + "EnumerationType":
        ci = ClassInfo(path, "enum", one_line(doc.get(node, "description")))
        for n in doc.nodes.values():
            owner = local(n["@id"]).rpartition(".")[0]
            if not owner or n["@id"] == cid:
                continue
            try:
                if resolve_class(owner, path, {path}) == path:
                    ci.items.append(local(n["@id"]).rsplit(".", 1)[1])
            except CxfError:
                pass
        ci.items.sort()
        return ci
    for refused in ("extends", "redeclare"):
        if doc.get(node, refused) is not None:
            raise Unsupported("%s uses S231:%s, refused by name" % (path, refused))
    for k in node:
        lk = k.lower()
        if lk.endswith("hasfmupath") or "extensionblock" in lk or "extenstion" in lk:
            # 231 5.9 spells the annotation extensionBlock and 6.7 misspells it extenstion; both mean an
            # FMU-backed extension block, which the generator does not read.
            raise Unsupported("%s is an extension block (%s), which the generator does not read" % (path, k))
    # Clause 7 membership decides elementary versus composite, never the presence of containsBlock: MBL builds
    # some Clause 7 blocks (Reals.Greater, GreaterThreshold, Less, LessThreshold, PID, PIDWithReset) from
    # internal, often conditional, instances, and 231 defines them as elementary. Their internals
    # are MBL's implementation, not part of the type, and are never read.
    kind = "elementary" if path in CLAUSE7 else ("composite" if doc.ids(node, "containsBlock") else "elementary")
    ci = ClassInfo(path, kind, one_line(doc.get(node, "description")))
    # S231:hasConstant (231 Table 6-2) is read like a parameter and marked protected: a constant is part of
    # the class's environment, never a value on a record.
    consts = set(doc.ids(node, "hasConstant"))
    for pid in doc.ids(node, "hasParameter") + sorted(consts):
        p = doc.node(pid)
        name = local(pid).rsplit(".", 1)[1]
        if "[" in name:
            raise Unsupported("%s: parameter id %s carries a subscript" % (path, name))
        raw = doc.get(p, "value")
        raw_size, size, dims = _array(doc, p, path, name, design, raw is not None)
        if isinstance(raw, list):                  # an array default: kept as text, typed by cdlArraySize
            val, expr = None, json.dumps(raw)
        else:
            val, expr = (None, None) if raw is None else literal(raw)
            expr = expr.strip() if isinstance(expr, str) else expr      # CXF writes " if a then b else c"
        dt = doc.get(p, "isOfDataType")
        if dt is not None and dt["@id"].startswith(cxf.S231):
            dtype = dt["@id"][len(cxf.S231):]
        elif dt is not None:
            dtype = resolve_class(local(dt["@id"]), path, known | enums)
        elif expr is not None and _enum_of(expr, path, enums):
            # An enum-typed parameter has no @type and no isOfDataType.
            # Its default literal names the enumeration.
            dtype = _enum_of(expr, path, enums)
        elif decls is not None and name in decls and decls[name].type:
            # CXF drops an enumeration type, and with no default nothing in CXF names it. The json
            # output keeps the declaration's type specifier; it must resolve to an enumeration the generator knows.
            dtype = resolve_class(decls[name].type, path, enums | known)
            if dtype not in enums:
                raise Unsupported("%s: parameter %s has no CXF type, and its json type %s is no enumeration"
                                  % (path, name, decls[name].type))
        elif path + "." + name in HAND_TYPES:
            # An enum-typed parameter with no default carries no type at all in CXF. The
            # recorded hand rule names its type; the round trip checks it against the .mo independently.
            dtype = HAND_TYPES[path + "." + name]
        else:
            raise Unsupported("%s: parameter %s has no data type, no value and no hand rule" % (path, name))
        ci.params.append(Param(name, dtype, val, expr, _unit(p, doc), _qkind(p),
                               doc.get(p, "accessSpecifier") == "protected" or pid in consts, bool(doc.get(p, "isFinal")),
                               one_line(doc.get(p, "description"))))
        ci.params[-1].raw_size, ci.params[-1].size, ci.params[-1].dims = raw_size, size, dims
        ci.params[-1].constant = pid in consts
        ci.params[-1].raw_bounds = (doc.get(p, "min"), doc.get(p, "max"))
        if decls is not None:
            d = decls.get(name)
            if d is None:
                # The two outputs of one modelica-json run must agree on what the class declares.
                raise CxfError("%s: parameter %s is in the CXF but not in the json output" % (path, name))
            if dt is not None and dt["@id"].startswith(cxf.S231) and d.type != dtype:
                raise CxfError("%s: parameter %s is %s in the CXF and %s in the json output" % (path, name, dtype, d.type))
            pm = ci.params[-1]
            pm.enable, pm.group, pm.tab, pm.value_in_reference = d.enable, d.group, d.tab, d.value_in_reference
            pm.unit, pm.unit_mbl = unit_override(path, name, pm.unit)
            pm.uinferred = infer_unit(path, name, pm.unit, pm.qkind)
            if pm.uinferred:
                pm.unit = pm.uinferred
            pm.qinferred = infer_quantity(path, name, pm.unit, pm.qkind, d)
            pm.point_unit = point_unit(path, name, pm.unit)
            if pm.point_unit and pm.unit is None:
                pm.unit = pm.uinferred = "1"
            # CXF drops `final` on a `final parameter` declaration (Economizers.Subsequences.Enable's protected
            # cutoffs); the json output keeps it on the element.
            pm.final = pm.final or d.final
    for prop in ("hasInput", "hasOutput"):
        for k in doc.ids(node, prop):
            c = doc.node(k)
            t = c.get("@type", "")
            if not t.startswith(cxf.S231) or t[len(cxf.S231):] not in CONNECTOR:
                raise CxfError("%s: connector %s has type %s" % (path, local(k), t))
            direction, dtype = CONNECTOR[t[len(cxf.S231):]]
            cname = local(k).rsplit(".", 1)[1]
            raw_size, size, dims = _array(doc, c, path, cname, design)
            unit, qkind = _unit(c, doc), _qkind(c)
            d = (decls or {}).get(cname)
            if d is not None and unit is None and d.unit is not None:
                # CXF writes no unit for an array connector declared `unit=fill("K", n)` (measured on MBL 14.0.0,
                # ZoneGroups and the outdoor-air SumZone blocks); the json output keeps it.
                if d.unit not in MODELICA_UNITS:
                    raise CxfError("%s: connector %s has unit %s, which has no symbol in generate.MODELICA_UNITS"
                                   % (path, cname, d.unit))
                unit = MODELICA_UNITS[d.unit]
            if d is not None and qkind is None and d.quantity is not None:
                qkind = d.quantity
            uinferred = infer_unit(path, cname, unit, qkind)
            if uinferred:
                unit = uinferred
            ci.conns.append(Conn(cname, direction, dtype, unit, qkind,
                                 doc.get(c, "conditionalExpression"), one_line(doc.get(c, "description")), raw_size=raw_size, size=size, dims=dims))
            ci.conns[-1].uinferred = uinferred
            ci.conns[-1].qinferred = infer_quantity(path, cname, unit, qkind, d)
            ci.conns[-1].point_unit = point_unit(path, cname, unit)
            if ci.conns[-1].point_unit and unit is None:
                ci.conns[-1].unit = ci.conns[-1].uinferred = "1"
            ci.conns[-1].raw_bounds = (doc.get(c, "min"), doc.get(c, "max"))
    for full, ctype in sorted(HAND_CONNECTORS.items()):
        owner, _, name = full.rpartition(".")
        if owner != path:
            continue
        if ci.conn(name) is not None:
            raise CxfError("%s: hand rule for connector %s, which CXF already lists; drop the rule" % (path, name))
        c = next((n for nid, n in doc.nodes.items() if local(nid) == full), None)
        if c is None or "@type" in c:
            raise CxfError("%s: hand rule for connector %s, but CXF has no untyped node for it" % (path, name))
        direction, dtype = CONNECTOR[ctype]
        ci.conns.append(Conn(name, direction, dtype, _unit(c, doc), _qkind(c), doc.get(c, "conditionalExpression"),
                             one_line(doc.get(c, "description"))))
    # Bounds resolve once every parameter and constant of the class is read: a bound may name a class constant
    # (CalendarTime's firstYear) or another parameter (min=outDamPhy_min).
    env = _class_constants(ci)
    for x in ci.params + ci.conns:
        lo, hi = getattr(x, "raw_bounds", (None, None))
        where = "%s.%s" % (path, x.name)
        lo, x.min_const, x.min_expr = _bound(lo, where, ci, env)
        hi, x.max_const, x.max_expr = _bound(hi, where, ci, env)
        if isinstance(x, Param):
            x.vmin, x.vmax = lo, hi
        else:
            x.cmin, x.cmax = lo, hi
    for iid in (doc.ids(node, "containsBlock") if kind == "composite" else []):
        inode = doc.node(iid)
        cls = resolve_class(local(inode["@type"]), path, known)
        binds, finals, units = {}, set(), {}
        iname = local(iid).rsplit(".", 1)[1]
        _, isize, idims = _array(doc, inode, path, iname, design)
        if design and idims == 2:
            raise CxfError("%s: instance %s has 2 dimensions; a vectorized instance has one" % (path, iname))
        for child in doc.ids(inode, "hasInstance"):
            if "[" in local(child).rsplit(".", 1)[1]:
                # An indexed leaf (u[1]) is an endpoint modelica-json lists, never a modifier.
                # A node for it carrying anything but a connection refuses below, with the edges.
                continue
            cn = doc.nodes.get(child)
            if cn is not None and doc.get(cn, "value") is None and _qudt(cn, "hasUnit") is not None:
                # A unit set on one connector of this instance (ReliefDamper's conErr(u1(final unit="Pa"), ...)):
                # MBL's own per-instance typing of a polymorphic block. Kept as cdlConnUnits.
                units[local(child).rsplit(".", 1)[1]] = _unit(cn, doc)
            if cn is not None and doc.get(cn, "value") is not None:
                name = local(child).rsplit(".", 1)[1]
                binds[name] = literal(doc.get(cn, "value"))
                if doc.get(cn, "isFinal"):
                    finals.add(name)
        ci.insts.append(Inst(iname, cls, binds, doc.get(inode, "conditionalExpression"),
                             one_line(doc.get(inode, "description")), finals, isize, idims))
        ci.insts[-1].units = units
    if kind == "elementary":
        return ci                                     # internals of an elementary block are not read
    prefix = path + "."
    connect_keys = {"@id"} | {cxf.S231 + p for p in cxf.CONNECT}
    for nid, n in doc.nodes.items():
        if not local(nid).startswith(prefix):
            continue
        if "[" in local(nid):
            for k in sorted(n):
                if k not in connect_keys:
                    raise CxfError("%s: %s is an array element carrying %s; only connections may name an element"
                                   % (doc.name, local(nid), k.rsplit("#", 1)[-1]))
        for pred in cxf.CONNECT:                      # isConnectedTo (modelica-json) and connectedTo (231)
            for b in as_list(doc.get(n, pred)):
                ci.edges.append((local(nid)[len(prefix):], local(b["@id"])[len(prefix):]))
    return ci


def orient(ci, classes):
    """Orient every connect() by connector kind: CXF keys an edge by connect()'s first argument.

    Modelica connects connectors into connection sets, and a set holds at most one driver. An input-to-input
    connect (MBL's single-zone Economizers.Subsequences.Modulation: connect(HeaCoi.u, retDamPos.u)) joins two sinks
    into one set, so both read the set's driver. Each sink-to-sink edge therefore becomes one
    edge from every driver of the merged set to each of its sinks; the alternative-driver rule in emit_class then
    applies as for any sink. A set with sinks and no driver refuses (an input nothing drives), as does a
    source-to-source connect."""
    direct, joins = [], []
    for a, b in ci.edges:
        ka, kb = _kind(ci, a, classes), _kind(ci, b, classes)
        if ka == "src" and kb == "sink":
            direct.append((a, b))
        elif ka == "sink" and kb == "src":
            direct.append((b, a))
        elif ka == kb == "sink":
            joins.append((a, b))
        else:
            raise CxfError("%s: connect(%s, %s) joins %s to %s" % (ci.path, a, b, ka, kb))
    if joins:
        parent = {}

        def find(x):
            while parent.get(x, x) != x:
                x = parent[x]
            return x
        for a, b in joins:
            parent[find(a)] = find(b)
        members = {}
        for a, b in joins:
            for x in (a, b):
                members.setdefault(find(x), set()).add(x)
        for root, sinks in members.items():
            drivers = sorted({s for s, t in direct if t in sinks})
            if not drivers:
                raise CxfError("%s: the connected inputs %s have no driver" % (ci.path, ", ".join(sorted(sinks))))
            for t in sorted(sinks):
                for s in drivers:
                    direct.append((s, t))
    ci.edges = sorted(set(direct))


def _kind(ci, ep, classes):
    parts = [base_name(p) for p in ep.split(".")]     # an element orients as its connector
    if len(parts) == 1 and ci.conn(parts[0]):
        return "src" if ci.conn(parts[0]).direction == "in" else "sink"
    if len(parts) == 2 and ci.inst(parts[0]):
        sub = classes[ci.inst(parts[0]).cls]
        c = sub.conn(parts[1])
        if c:
            return "sink" if c.direction == "in" else "src"
    raise CxfError("%s: %s is not a connector" % (ci.path, ep))


def load_classes(root, override=None):
    """Every class the generator knows, from the pinned CXF. `override` maps a class path to a CXF document (tests)."""
    override = override or {}
    docs = [cxf.Cxf.load(root / "kw.cdl/cdl-elementary.jsonld")]
    for f in g36_sources(root, "cxf"):
        docs.append(cxf.Cxf.load(f))
    decls, bad_json = {}, {}
    for f in g36_sources(root, "json"):
        jdoc = json.loads(f.read_text(encoding="utf-8"))
        cls = mjson.class_path(jdoc)
        try:
            decls[cls] = mjson.read(jdoc)
        except CxfError as e:
            bad_json[cls] = e
    for cls, d in override.items():
        docs = [x for x in docs if cxf.S231 not in x.nodes.get("http://example.org#" + cls, {}).get("@type", "x")] \
            + [cxf.Cxf(d)]
    global CLAUSE7, QUANTITY_DECISIONS, POINT_UNITS
    CDL_CONSTANTS.clear()
    for d in docs:
        for nid, n in d.nodes.items():
            if local(nid).startswith(CDL_PREFIX + "Constants.") and n.get("@type") == cxf.S231 + "Constant":
                v = d.get(n, "value")
                if v is not None and not isinstance(v, str):
                    CDL_CONSTANTS[local(nid)] = literal(v)[0]
    CLAUSE7 = clause7()
    quantities = json.loads((HERE / "quantities.json").read_text(encoding="utf-8"))
    QUANTITY_DECISIONS, POINT_UNITS = quantities["decisions"], quantities.get("pointUnits", {})
    LITERAL_UNITS.clear()
    LITERAL_UNITS.update(quantities.get("literalUnits", {}))
    UNIT_OVERRIDES.clear()
    UNIT_OVERRIDES.update(quantities.get("unitOverrides", {}))
    known, enums, where = set(), set(), {}
    for d in docs:
        for nid, n in d.nodes.items():
            t = n.get("@type", "")
            if t in (cxf.S231 + "Block", cxf.S231 + "ElementaryBlock"):
                known.add(local(nid))
                where[local(nid)] = (d, nid)
            elif t == cxf.S231 + "EnumerationType":
                enums.add(local(nid))
                where[local(nid)] = (d, nid)
    for cls, d in override.items():
        doc = cxf.Cxf(d)
        where[cls] = (doc, "http://example.org#" + cls)
    classes, report = {}, []
    for path in sorted(known | enums):
        if path in SKIP_CLASSES:
            report.append("%s: skipped by rule (%s)" % (path, SKIP_CLASSES[path]))
            continue
        d, nid = where[path]
        try:
            if path in bad_json:
                raise bad_json[path]
            classes[path] = read_class(d, nid, known, enums, decls.get(path) if path.startswith(G36_PREFIX) else None)
        except CxfError as e:
            # A class the generator cannot read is left out with its reason, never half-emitted (zero
            # refusals, or each one named). Unsupported is the named, expected kind; any other CxfError is a
            # reader refusal and reads the same way in the report.
            report.append(str(e))
    for path, err in infer_bound_units(classes).items():
        report.append(str(err))
        del classes[path]
    oriented, emitted = set(), set()
    stamp = load_stamp()
    while True:
        # A composite whose instance names a class that was left out is left out too, naming that class, and an
        # orient refusal leaves its class out; repeat until nothing more drops. orient is idempotent, so a class
        # oriented in an earlier round is not oriented again.
        dropped = False
        for p in sorted(classes):
            ci = classes[p]
            if ci.kind != "composite":
                continue
            gone = sorted({i.cls for i in ci.insts if i.cls not in classes})
            if gone:
                report.append("%s: instantiates %s, left out above" % (p, ", ".join(gone)))
                del classes[p]
                dropped = True
        for p in sorted(classes):
            ci = classes[p]
            if ci.kind != "composite" or p in oriented:
                continue
            if any(i.cls not in classes for i in ci.insts):
                continue                              # an instance's class dropped this round; the next round names it
            try:
                orient(ci, classes)
                oriented.add(p)
            except CxfError as e:
                report.append(str(e))
                del classes[p]
                dropped = True
        for p in sorted(classes):
            # A class that reads but that emit_class refuses (a unit with no canonical form) is
            # left out here with emit's reason, so main() never meets a refusal halfway through writing a lib.
            if p in emitted or classes[p].kind == "composite" and p not in oriented:
                continue
            if any(i.cls not in classes for i in classes[p].insts):
                continue                              # an instance's class dropped this round; the next round names it
            try:
                emit_class(classes[p], classes, stamp)
                emitted.add(p)
            except CxfError as e:
                report.append(str(e))
                del classes[p]
                dropped = True
        if not dropped:
            break
    load_classes.report = report
    load_classes.bounds = propagate_bounds(classes)
    return classes


BARE_NAME = re.compile(r"[A-Za-z_]\w*")
IDENT = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def propagate_bounds(classes):
    """Lift every bound a parameter meets downstream onto the parameter (kw.cdl 0.6.0).

    A parameter bound by bare name into a contained instance (`conTSup(k=kVal)`) takes that block parameter's bound:
    Modelica checks PIDWithReset.k's min=100*Constants.eps on the value kVal passes, so kVal's effective bound is
    the intersection of its own and of every block parameter it reaches, walked through nested composites. For a
    min the tightest is the largest, for a max the smallest. On a tie the parameter's own bound wins, then the first
    path in sorted order. The chosen path is kept on the parameter (min_via, max_via, emitted as cdlMinVia and
    cdlMaxVia) so a reviewer can walk it to the declaring block.

    The intersection applies to a parameter's own bound too: where a block downstream is tighter, the tighter number
    is emitted and MBL's own value is kept as min_own/max_own (cdlMinOwn/cdlMaxOwn), named in the "tightened"
    section. MBL 14.0.0 has three: SupplyFan.Td and Ti, and ReliefDamper.k, own min=0 feeding a PID whose min is
    100*Constants.eps: a value the PID refuses is no valid answer.

    A bound that only a guarded instance imposes is not a hard bound: when the guard removes the instance the
    parameter is unused, and a hard minVal could refuse a harmless value, even a G36 default. Such a bound, where it
    is tighter than every unguarded one, goes on min_when/max_when as {val, cond, via} (cdlMinWhen/cdlMaxWhen): cond is
    the condition under which some path to it exists, a CDL expression in the parameter's own class, built by lifting
    each guard through the bindings of the instances above it (lift_guard); via lists those paths. A guard that cannot
    be lifted is named in the "guard" section and its path left out of cond.

    Not followed, each named in the returned report instead of guessed: a binding through an expression (k=2*x,
    k=-triAmo); a bound written as an expression of the block's own parameters (min=outDamPhy_min), which has no
    number to lift. A binding whose two ends declare different units is carried (Modelica passes the number
    unconverted) and named. Returns the report as {section: sorted lines}: disagree, tightened, conditional, guard,
    expression, reference, unit."""
    report = {"disagree": set(), "tightened": set(), "conditional": set(), "tautology": set(), "guard": set(),
              "expression": set(), "reference": set(), "unit": set()}
    own = {(c, p.name): ((p.vmin, p.min_const), (p.vmax, p.max_const))
           for c, ci in classes.items() if ci.kind != "enum" for p in ci.params}
    memo = {}

    def reach(path, name):
        """(path, name) -> {"min": [(value, via, guards)], "max": [...]}: every candidate bound, own first. guards is
        a tuple of conditions in `path`'s names, one per guarded instance on the way (None where one cannot be
        lifted), empty for an unguarded path."""
        if (path, name) in memo:
            return memo[(path, name)]
        memo[(path, name)] = {"min": [], "max": []}
        ci, p = classes[path], classes[path].param(name)
        out = {"min": [], "max": []}
        for i, side in enumerate(("min", "max")):
            if own[(path, name)][i][0] is not None:
                out[side].append((own[(path, name)][i][0], None, ()))
        for inst in sorted(ci.insts, key=lambda x: x.name):
            for k in sorted(inst.binds):
                val, expr = inst.binds[k]
                if val is not None or expr is None or expr.strip() != name:
                    continue
                tp = classes[inst.cls].param(k)
                if tp is None or getattr(tp, "constant", False) or tp.raw_size is not None or p.raw_size is not None:
                    continue
                hop = "%s.%s" % (lower(inst.name), lower(k))
                if p.unit and tp.unit and p.unit != tp.unit and (reach(inst.cls, k)["min"] or reach(inst.cls, k)["max"]):
                    # Modelica passes the number through a binding unconverted, so the bound holds on it whatever the
                    # two declarations say; the mismatch is MBL's own and is named, not repaired.
                    report["unit"].add("%s.%s (%s) binds into %s (%s): carried, MBL declares the two units differently"
                                       % (path, name, p.unit, hop, tp.unit))
                for side in ("min", "max"):
                    texpr = tp.min_expr if side == "min" else tp.max_expr
                    if texpr:
                        report["reference"].add("%s.%s binds into %s, whose %s is the expression %s: not lifted"
                                                % (path, name, hop, side, texpr))
                    for v, via, guards in reach(inst.cls, k)[side]:
                        lifted = tuple(None if g is None else lift_guard(g, inst, classes[inst.cls]) for g in guards)
                        if inst.cond is not None:
                            lifted = (inst.cond.strip(),) + lifted
                        out[side].append((v, lower(inst.name) + "." + (via or lower(k)), lifted))
        memo[(path, name)] = out
        return out

    tighter = {"min": max, "max": min}

    def is_tighter(side, a, b):
        return b is None or (a > b if side == "min" else a < b)

    for path in sorted(classes):
        ci = classes[path]
        if ci.kind == "enum":
            continue
        for p in ci.params:
            p.min_own = p.max_own = p.min_when = p.max_when = None
            if getattr(p, "constant", False) or p.raw_size is not None:
                continue
            r = reach(path, p.name)
            for side in ("min", "max"):
                cands = r[side]
                if not cands:
                    continue
                hard = [c for c in cands if not c[2]]
                v = via = None
                if hard:
                    v = tighter[side](c[0] for c in hard)
                    at = [c for c in hard if c[0] == v]
                    via = None if any(c[1] is None for c in at) else sorted(c[1] for c in at)[0]
                # Guarded paths whose guards, together, hold in every configuration bound the parameter everywhere
                # (DualDuctSnapActing's kDam reaches a PID through damDuaSen when have_duaSen and through damSinSen
                # when not). always_bound decides it by enumerating the Bool and enum parameters the guards name.
                lifted = [c for c in cands if c[2] and all(g is not None for g in c[2])]
                for c in cands:
                    if c[2] and any(g is None for g in c[2]):
                        report["guard"].add("%s.%s %s %s via %s: a guard on the way does not lift into %s's names; "
                                            "the path is left out" % (path, p.name, side, fmt_num(c[0]), c[1], path))
                if lifted:
                    sure, why = always_bound(side, ci, classes, [c[0] for c in hard],
                                             [(c[0], _conj(c[2])) for c in lifted])
                    if why:
                        report["guard"].add("%s.%s %s: %s; the guarded bounds stay conditional" % (
                            path, p.name, side, why))
                    elif sure is not None and is_tighter(side, sure, v):
                        at = sorted(c[1] for c in lifted if c[0] == sure)
                        v, via = sure, at[0]
                        report["tautology"].add("%s.%s %s %s: the guards of %s cover every configuration (%s)" % (
                            path, p.name, side, fmt_num(sure), ", ".join(at),
                            " or ".join(sorted({_paren(_conj(c[2])) for c in lifted if c[0] == sure}))))
                if v is not None:
                    mine = [c for c in hard if c[1] is None]
                    if via is not None and mine:
                        setattr(p, side + "_own", mine[0][0])
                        report["tightened"].add("%s.%s %s: own %s tightened to %s from %s" % (
                            path, p.name, side, fmt_num(mine[0][0]), fmt_num(v), via))
                    setattr(p, side + "_via", via)
                    if via is not None:
                        setattr(p, side + "_const", None)
                setattr(p, "vmin" if side == "min" else "vmax", v)
                # Every guarded bound tighter than the hard one, one {val, cond, via} per value, tightest first: the
                # configurator applies each whose cond holds.
                pairs = []
                for gv in sorted({c[0] for c in lifted if is_tighter(side, c[0], v)}, reverse=(side == "min")):
                    at = sorted((c for c in lifted if c[0] == gv), key=lambda c: c[1])
                    conds = []
                    for c in at:
                        if _conj(c[2]) not in conds:
                            conds.append(_conj(c[2]))
                    cond = conds[0] if len(conds) == 1 else " or ".join(_paren(x) for x in conds)
                    pairs.append({"val": gv, "cond": cond, "via": ",".join(c[1] for c in at)})
                    report["conditional"].add("%s.%s %s %s when %s (via %s)" % (
                        path, p.name, side, fmt_num(gv), cond, ",".join(c[1] for c in at)))
                setattr(p, side + "_when", pairs or None)
                if len({c[0] for c in cands}) > 1:
                    pick = v if v is not None else None
                    others = sorted({"%s from %s" % (fmt_num(c[0]), c[1] or "its own declaration")
                                     for c in cands if not (c[0] == pick and not c[2])})
                    report["disagree"].add("%s.%s %s: %s; also %s" % (
                        path, p.name, side, ("%s from %s" % (fmt_num(v), via or "its own declaration"))
                        if v is not None else "no unguarded bound", ", ".join(others)))
        for inst in ci.insts:
            sub_ci = classes[inst.cls]
            for k, (val, expr) in sorted(inst.binds.items()):
                if val is not None or expr is None or BARE_NAME.fullmatch(expr.strip()):
                    continue
                used = sorted({n for n in IDENT.findall(expr) if ci.param(n) is not None
                               and not getattr(ci.param(n), "constant", False)})
                tp = sub_ci.param(k)
                if not used or tp is None:
                    continue
                r = reach(inst.cls, k)
                bounds = ["%s %s" % (side, fmt_num(tighter[side](c[0] for c in r[side]))) for side in ("min", "max")
                          if r[side]]
                bounds += ["%s %s" % (side, e) for side, e in (("min", tp.min_expr), ("max", tp.max_expr)) if e]
                if bounds:
                    report["expression"].add("%s: %s.%s = %s (%s): the block parameter is bounded %s; not followed"
                                             % (path, lower(inst.name), lower(k), expr, ", ".join(used),
                                                ", ".join(bounds)))
    return {k: sorted(v) for k, v in report.items()}


def _conj(guards):
    """The conjunction of one path's lifted guards, as CDL text."""
    return guards[0] if len(guards) == 1 else " and ".join(_paren(g) for g in guards)


ASSIGNMENT_LIMIT = 100000


def always_bound(side, ci, classes, hard, guarded):
    """The bound that holds in every configuration of `ci`, from the unguarded values `hard` and the guarded
    (value, condition) pairs, by enumerating every assignment of the Bool and enumeration parameters the conditions
    name: in each, the bound is the tightest of the hard values and of the guarded ones whose condition holds, and
    the result is the loosest of those (None where some assignment has none). Returns (bound, None), or (None, why)
    when a condition names something else or the assignments exceed ASSIGNMENT_LIMIT."""
    names = []
    for _, cond in guarded:
        try:
            found = cxf.names(cond)
        except CxfError as e:
            return None, "the condition %s is outside the grammar (%s)" % (cond, e)
        for n in found:
            if "." not in n and n not in names:
                names.append(n)
    domains = []
    for n in names:
        p = ci.param(n)
        if p is None:
            return None, "the condition names %s, which is no parameter of the class" % n
        if p.dtype == "Boolean":
            domains.append([True, False])
        elif p.dtype in classes and classes[p.dtype].kind == "enum":
            domains.append(list(classes[p.dtype].items))
        else:
            return None, "the condition names %s, a %s, which is not enumerated" % (n, p.dtype)
    total = 1
    for d in domains:
        total *= len(d)
    if total > ASSIGNMENT_LIMIT:
        return None, "%d assignments exceed the limit %d" % (total, ASSIGNMENT_LIMIT)

    def item(lit):
        cls, _, name = lit.rpartition(".")
        c = classes.get(cls)
        return name if c is not None and c.kind == "enum" and name in c.items else None
    pick = max if side == "min" else min
    loose = min if side == "min" else max
    worst = None
    for k in range(total):
        env, rest = {}, k
        for n, d in zip(names, domains):
            env[n] = d[rest % len(d)]
            rest //= len(d)
        vals = list(hard)
        for v, cond in guarded:
            try:
                ok = cxf.evaluate(cond, env, item)
            except CxfError as e:
                return None, "the condition %s does not evaluate (%s)" % (cond, e)
            if ok is True:
                vals.append(v)
        if not vals:
            return None, None
        here = pick(vals)
        worst = here if worst is None else loose(worst, here)
    return worst, None


def _paren(e):
    return e if IDENT.fullmatch(e.strip()) else "(" + e.strip() + ")"


KEYWORDS = {"and", "or", "not", "true", "false"}


def lift_guard(expr, inst, sub_ci, depth=0):
    """A condition written in the names of `sub_ci` (an instance's own class), rewritten in the names of the class
    that holds `inst`: each parameter of sub_ci becomes what the instance binds it to, or its default where it is not
    bound. Enumeration literals and other dotted names pass through. None when a name has neither a binding nor a
    default, or the defaults recurse too deep."""
    if depth > 10:
        return None
    failed = []

    def one(m):
        n = m.group(0)
        if "." in n or n in KEYWORDS:
            return n
        p = sub_ci.param(n)
        if p is None:
            failed.append(n)
            return n
        if n in inst.binds:
            val, ex = inst.binds[n]
            return fmt_num(val) if val is not None else _paren(ex)
        if p.val is not None:
            return fmt_num(p.val)
        if p.expr is not None:
            inner = lift_guard(p.expr, inst, sub_ci, depth + 1)
            if inner is None:
                failed.append(n)
                return n
            return _paren(inner)
        failed.append(n)
        return n

    out = IDENT.sub(one, expr.strip())
    return None if failed else out


CONSTANT_TYPES = {"Integer": "Number", "Real": "Number", "Boolean": "Bool"}


def load_constants(root, files=None):
    """Package path -> {"type", "desc", "items": {name: (value, desc)}}, read from modelica-json's json output.

    `files` maps a G36 package (relative to G36_PREFIX) to its json file under <lib>/json in the source directory; the
    default is G36_CONSTANTS. Anything that is not a scalar `constant` with a literal value refuses by name."""
    out = {}
    for rel, f in (G36_CONSTANTS if files is None else files).items():
        path = G36_PREFIX + rel
        doc = json.loads((root / g36_lib(path) / "json" / (f + ".json")).read_text(encoding="utf-8"))
        defs = doc.get("stored_class_definitions") or []
        if len(defs) != 1:
            raise CxfError("%s: expected one class definition in %s.json, found %d" % (path, f, len(defs)))
        spec = defs[0]["class_specifier"]["long_class_specifier"]
        if doc.get("within", "") + "." + spec["identifier"] != path or defs[0].get("class_prefixes") != "package":
            raise CxfError("%s: %s.json defines %s %s.%s, not the package" % (
                path, f, defs[0].get("class_prefixes"), doc.get("within"), spec["identifier"]))
        items, types = {}, set()
        for el in spec["composition"]["element_list"]:
            cc = el.get("component_clause")
            if cc is None or cc.get("type_prefix") != "constant":
                raise CxfError("%s: an element that is not a constant declaration: %s" % (path, sorted(el)))
            t = cc["type_specifier"]
            if t not in CONSTANT_TYPES:
                raise CxfError("%s: constant of type %s; only Integer, Real and Boolean are read" % (path, t))
            for comp in cc["component_list"]:
                d = comp["declaration"]
                expr = ((d.get("modification") or {}).get("expression") or {}).get("simple_expression")
                if expr is None:
                    raise CxfError("%s.%s has no literal value" % (path, d["identifier"]))
                v = cxf.evaluate(expr, {}, lambda lit: None)
                if (t == "Boolean") != isinstance(v, bool):
                    raise CxfError("%s.%s = %s is not a %s" % (path, d["identifier"], expr, t))
                items[d["identifier"]] = (v, (comp.get("description") or {}).get("description_string"))
            types.add(t)
        if len(types) != 1:
            raise CxfError("%s: constants of several types %s; one CdlConstants carries one" % (path, sorted(types)))
        out[path] = {"type": types.pop(), "desc": one_line(spec.get("description_string")), "items": items}
    return out


def constant_names(consts):
    """Every constant's full dotted name -> its value: the table the resolver reads."""
    return {p + "." + n: v for p, c in consts.items() for n, (v, _) in c["items"].items()}


def emit_constants(path, c, stamp):
    """One kw.cdl::CdlConstants instance for a package of constants."""
    lines = ["// " + c["desc"]] if c["desc"] else []
    lines.append("// GENERATED from %s (modelica-json json output), MBL %s (%s). Do not edit."
                 % (path, stamp["mbl"], stamp["mblCommit"][:8]))
    # Xeto data takes no comment after a dict item, so each constant's MBL description goes in the header.
    for n in sorted(c["items"]):
        if c["items"][n][1]:
            lines.append("//   %s: %s" % (n, one_line(c["items"][n][1])))
    lines.append("@%s: kw.cdl::CdlConstants {" % lower(spec_name(path, G36_PREFIX)))   # an instance name starts lower case
    lines.append("  cdlClass: " + xs(path))
    lines.append("  cdlType: " + xs(c["type"]))
    lines.append("  cdlConstants: {")
    for n in sorted(c["items"]):
        lines.append("    %s: %s %s" % (n, CONSTANT_TYPES[c["type"]], xs(fmt_num(c["items"][n][0]))))
    lines += ["  }", "}"]
    return lines


DOTTED = re.compile(r"\b(Buildings(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")


def unresolved_names(classes, paths, consts):
    """Every dotted name a generated default, binding or guard names that is neither an enumeration item nor a
    generated constant, as readable lines. The resolver would refuse such a name at expansion;
    the generator refuses it here, so a constants package nobody generated is named at generation."""
    known = set(constant_names(consts))
    for p, ci in classes.items():
        if ci.kind == "enum":
            known.update(p + "." + i for i in ci.items)
    bad = []
    for p in paths:
        ci = classes[p]
        exprs = [("parameter " + x.name, x.expr) for x in ci.params] + [("connector " + x.name, x.cond) for x in ci.conns]
        for i in ci.insts:
            exprs.append(("instance " + i.name, i.cond))
            exprs += [("%s.%s" % (i.name, k), v[1]) for k, v in sorted(i.binds.items())]
        for where, e in exprs:
            for name in DOTTED.findall(e or ""):
                if name not in known:
                    bad.append("%s %s names %s, which is no enumeration item and no generated constant" % (p, where, name))
    return bad


def fmt_num(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(int(v)) if float(v).is_integer() and abs(v) < 1e15 else repr(float(v))


def xs(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def header(cls, stamp):
    return ["// GENERATED from %s, MBL %s (%s). Do not edit." % (cls, stamp["mbl"], stamp["mblCommit"][:8])]


# A K slot that CXF and MBL leave without a quantity (133 slots in the 126 G36 classes of MBL 14.0.0; 0 in the
# 0.4.0 set) cannot say whether it is a temperature or a temperature difference, and the generator refuses a
# guess. MBL's own displayUnit decides where it is written: degC is how MBL shows an absolute temperature (38
# slots), K how it shows a difference (6 slots). The 89 with no displayUnit are decided one by one in
# quantities.json, each with the MBL description that says it is a difference; a new one refuses until
# someone records it there. Every such slot carries cdlQuantityInferred, so a reader can tell it from a CXF quantity.
DISPLAY_QUANTITY = {"degC": "temperature", "K": "temperatureDifferential"}
QUANTITY_DECISIONS = {}
# A slot MBL declares unit "1" whose number is counted in a unit, recorded in quantities.json's
# pointUnits (MBL 14.0.0: the CO2 concentration and its hysteresis in ThermalZones.Alarms, parts per million). The
# slot carries cdlPointUnit, so a binder binds a point in that unit as it is, where a "1" slot bound to a % point
# would take a scale (cdlPointScale). A slot MBL leaves with no unit (the ventilation setpoints' and controllers'
# ppmCO2 and ppmCO2Set, Alarms' CO2Set) takes "1" as an inferred unit, carrying cdlUnitInferred. A pointUnits
# decision on a slot in another unit refuses: it has rotted.
POINT_UNITS = {}
# The unit of a literal the static propagation cannot reach, recorded in quantities.json's literalUnits
# (MBL 14.0.0: the BooleanToReal factors that multiply a setpoint adjustment or a fan speed, and TrimAndRespond's
# sign gain k=-1). Keyed class.instance.parameter in CDL names; hxemit.Mapper.literal_unit reads it first.
LITERAL_UNITS = {}
# A unit MBL declares wrongly, corrected after review in quantities.json's unitOverrides (MBL 14.0.0:
# SeriesFanCVF and SeriesFanVVF DamperValves.damPosHys, a damper-position hysteresis declared m3/s). The slot carries
# the corrected cdlUnit and cdlUnitOverride naming MBL's; the round trip compares MBL's. An override whose slot no
# longer declares the unit it overrides refuses, so a fixed MBL fails loudly instead of being overridden twice.
UNIT_OVERRIDES = {}


def unit_override(cls, name, unit):
    """(unit to write, MBL's unit) for a slot, applying a reviewed unitOverrides entry; (unit, None) without one."""
    rec = UNIT_OVERRIDES.get(cls + "." + name)
    if rec is None:
        return unit, None
    if unit != rec["from"]:
        raise CxfError("%s.%s: quantities.json overrides unit %s, but MBL now declares %s; remove the "
                       "override" % (cls, name, rec["from"], unit))
    return rec["unit"], unit


def point_unit(cls, name, unit):
    rec = POINT_UNITS.get(cls + "." + name)
    if rec is None:
        return None
    if unit not in ("1", None):
        raise CxfError("%s.%s: quantities.json counts it in %s, but its unit is %s, not \"1\""
                       % (cls, name, rec["unit"], unit))
    return rec["unit"]


def infer_quantity(cls, name, unit, qkind, decl):
    """The quantity of a K slot with no quantity kind, from MBL's displayUnit or a recorded decision; else None."""
    if unit != "K" or qkind is not None or decl is None:
        return None
    if decl.displayUnit in DISPLAY_QUANTITY:
        return DISPLAY_QUANTITY[decl.displayUnit]
    rec = QUANTITY_DECISIONS.get(cls + "." + name)
    return rec["quantity"] if rec else None


# A slot MBL declares with neither unit nor quantity, which its description and the connector or parameter it feeds
# show to be a temperature difference (MBL 14.0.0: the occupant setpoint adjustments and the demand-limit offsets of
# the single-zone AHU sequences, which ThermalZones.Setpoints declares as K/TemperatureDifference). A recorded
# decision in quantities.json that carries `unit` supplies the CDL unit; the slot then takes the same
# path as a K slot without a quantity (infer_quantity) and carries cdlUnitInferred, which holds the unit, beside
# cdlQuantityInferred. It carries no cdlUnit, since CXF states none, so the round trip against MBL still sees no
# declared unit. A decided unit other than K needs no quantity (MBL 14.0.0: the economizer enable's J/kg cutoff). A decision
# with `unit` on a slot CXF already gives a unit refuses: the decision has rotted.
def infer_unit(cls, name, unit, qkind):
    """The CDL unit of a slot declared with no unit and no quantity, from a recorded decision carrying `unit`; else
    None. Refuses when the decision carries a unit for a slot CXF already types."""
    rec = QUANTITY_DECISIONS.get(cls + "." + name)
    if not rec or "unit" not in rec:
        return None
    if unit is not None or qkind is not None:
        raise CxfError("%s.%s: quantities.json records unit %s for a slot CXF already types as %s %s; "
                       "remove the decision's unit" % (cls, name, rec["unit"], unit, qkind))
    return rec["unit"]


# A Real parameter MBL declares with no unit and no quantity often passes, by bare name, into a parameter of a
# contained block that declares one: MBL 14.0.0's multi-zone AHU controllers declare dpAbsMinOutDam=5 with no unit
# and bind it, through the economizer controller, into Limits.SeparateWithDP's dpAbsMinOutDam(unit="Pa"). Modelica
# passes the number through unconverted, so the value is in the unit the binding target declares.
# infer_bound_units gives such a parameter that unit, the target's quantity and its difference mark, walking each
# bare-name binding down the tree until a declared unit answers. The parameter carries cdlUnitInferred, holding the
# unit, and cdlUnitVia, the instance path to the declaring parameter (the first in sorted order where several
# agree), and no cdlUnit, since MBL states none. Two declared targets that disagree on unit or quantity refuse the
# class, naming both. A recorded decision in quantities.json is applied first and is not overridden.
def bound_quantity(p):
    """The Xeto quantity a parameter declares or was given: from its quantity kind, its unit, or infer_quantity."""
    return QUANTITY.get(p.qkind) or IMPLIED_QUANTITY.get(p.unit) or getattr(p, "qinferred", None)


def infer_bound_units(classes):
    """Type every Real parameter with no unit from the units it is bound into by bare name. Returns {class path:
    CxfError} for the classes whose targets disagree; the caller leaves those out.

    Two sources answer, repeated until neither types anything more. A composite target that declares a unit, or that
    was typed in an earlier round, answers directly, walked down the tree. An elementary target answers through its
    class's unitRule: the composite's static unit propagation (hxemit.Mapper.unit_model) joins the parameter with
    the target, and the rule joins the target with the block's connectors, whose units the composite's links supply.
    PlantRequests' THys reaches RealsGreaterThreshold.h, which the rule makes a difference of `u`, a temperature, so
    THys is a K difference. Targets that name two units, or a K absolute beside a K difference, refuse the class; a
    quantity one target names and another leaves out is not a disagreement."""
    refused = {}
    rows = mapped = allc = None

    def elem_unit(path, p):
        """(unit, quantity, via) from the composite's unit model, for a parameter bound into an elementary block."""
        nonlocal rows, mapped, allc
        hops = []
        for inst in sorted(classes[path].insts, key=lambda x: x.name):
            if inst.cls not in classes or classes[inst.cls].kind == "composite":
                continue
            for k in sorted(inst.binds):
                val, expr = inst.binds[k]
                if val is None and expr is not None and expr.strip() == p.name:
                    hops.append("%s.%s" % (lower(inst.name), lower(k)))
        if not hops:
            return None
        if rows is None:
            import hxemit
            rows, mapped = hx_rows(classes)
            allc = dict(classes, **hxemit.composed(classes, mapped))
        import hxemit
        m, val = hxemit.Mapper(classes[path], allc, mapped).unit_model()
        u, why = m.unit_of(val, "p:" + p.name)
        if u is None and "two different units" in (why or ""):
            # the rule ties the parameter to connectors of two units: a disagreement, refused like any other
            refused[path] = CxfError("%s.%s: bound into %s, whose unit rule joins two different units"
                                     % (path, p.name, ", ".join(hops)))
            return None
        if u is None:
            return None
        sym, delta = u
        cdl = {v: k for k, v in XETO_UNIT.items() if v}.get(sym, "1" if sym == "1" else sym)
        q = ("temperatureDifferential" if delta else "temperature") if sym == "K" else None
        return cdl, q, hops[0]

    def targets(path, name, seen, memo):
        """[(unit, quantity, via)]: every unit reached from (path, name) through bare-name bindings."""
        if (path, name) in memo:
            return memo[(path, name)]
        if (path, name) in seen:
            return []
        out = []
        for inst in sorted(classes[path].insts, key=lambda x: x.name):
            if inst.cls not in classes:
                continue
            for k in sorted(inst.binds):
                val, expr = inst.binds[k]
                if val is not None or expr is None or expr.strip() != name:
                    continue
                tp = classes[inst.cls].param(k)
                if tp is None or tp.dtype != "Real" or tp.raw_size is not None:
                    continue
                hop = "%s.%s" % (lower(inst.name), lower(k))
                if tp.unit and not getattr(tp, "uvia", None):
                    out.append((tp.unit, bound_quantity(tp), hop))
                else:
                    out += [(u, q, lower(inst.name) + "." + via)
                            for u, q, via in targets(inst.cls, k, seen | {(path, name)}, memo)]
        memo[(path, name)] = out
        return out

    def apply(path, p, found):
        units_ = sorted({u for u, _, _ in found})
        if len(units_) > 1 or (units_ == ["K"] and len({q for _, q, _ in found}) > 1):
            refused[path] = CxfError("%s.%s: bound by bare name into parameters that declare different units: %s"
                                     % (path, p.name, "; ".join("%s %s via %s" % (u, q, v) for u, q, v in found)))
            return False
        q = next((q for _, q, _ in found if q), None)
        p.unit = p.uinferred = units_[0]
        p.uvia = sorted(v for _, _, v in found)[0]
        if q and not IMPLIED_QUANTITY.get(p.unit):
            p.qinferred = q
        elif p.unit == "K":
            refused[path] = CxfError("%s.%s: bound into a K parameter whose quantity is not known (%s)"
                                     % (path, p.name, p.uvia))
        return True

    def untyped(p):
        return p.dtype == "Real" and not p.unit and not p.qkind and p.raw_size is None

    grew = True
    while grew:
        grew = False
        memo = {}
        for path in sorted(classes):
            ci = classes[path]
            if ci.kind == "enum" or path in refused:
                continue
            for p in ci.params:
                if untyped(p):
                    found = targets(path, p.name, frozenset(), memo)
                    if found and apply(path, p, found):
                        grew = True
        for path in sorted(classes):
            ci = classes[path]
            if ci.kind != "composite" or path in refused:
                continue
            for p in ci.params:
                if untyped(p):
                    got = elem_unit(path, p)
                    if got is not None and apply(path, p, [got]):
                        grew = True
    return refused


def unit_meta(cls, name, unit, qkind, inferred=None, uinferred=False, via=None, point_unit=None, unit_mbl=None):
    """The unit meta for one slot: cdlUnit, cdlQuantityKind, quantity (from CXF, implied by the unit, or inferred for a
    K slot by infer_quantity), then the canonical unit or the unitless marker. A unit infer_unit supplied carries
    cdlUnitInferred, holding that unit, and no cdlUnit. Refuses by class, slot and unit when the unit has no canonical form."""
    if not unit:
        meta = ["cdlQuantityKind:" + xs(qkind)] if qkind else []
        if QUANTITY.get(qkind) == "temperatureDifferential":
            meta.append("cdlDelta")
        elif qkind in QUANTITY:
            meta.append("quantity:" + xs(QUANTITY[qkind]))
        return meta
    meta = ["cdlUnitInferred:" + xs(unit)] if uinferred else ["cdlUnit:" + xs(unit)]
    if unit_mbl:
        meta.append("cdlUnitOverride:" + xs(unit_mbl))
    if point_unit:
        meta.append("cdlPointUnit:" + xs(point_unit))
    if via:
        meta.append("cdlUnitVia:" + xs(via))
    if qkind:
        meta.append("cdlQuantityKind:" + xs(qkind))
    quantity = QUANTITY.get(qkind) or IMPLIED_QUANTITY.get(unit) or inferred
    # A temperature difference carries cdlDelta, not quantity: fits holds a quantity to the value's unit, and the SI
    # spelling of a difference is K, whose quantity is temperature, while its Fahrenheit form is a difference unit.
    # No one quantity fits both, so the mark that says "difference" is cdlDelta alone.
    if quantity and not (unit == "K" and quantity == "temperatureDifferential"):
        meta.append("quantity:" + xs(quantity))
    if inferred and quantity == inferred and not QUANTITY.get(qkind):
        meta.append("cdlQuantityInferred")
    if unit == "K":
        if quantity not in XETO_KELVIN:
            raise CxfError("%s.%s: unit K with quantity kind %s is neither a temperature nor a temperature difference, "
                           "so it has no canonical unit (generate.XETO_KELVIN)" % (cls, name, qkind))
        if quantity == "temperatureDifferential":
            meta.append("cdlDelta")
    elif unit in NO_HAYSTACK_UNIT:
        pass                                          # provenance only: no Haystack symbol exists (NO_HAYSTACK_UNIT)
    elif unit not in XETO_UNIT:
        raise CxfError("%s.%s: unit %s has no canonical Xeto unit in generate.XETO_UNIT" % (cls, name, unit))
    elif XETO_UNIT[unit] is None:
        meta.append("unitless")
    elif XETO_UNIT[unit] in CONVERTED:
        pass                                          # shown in the bound point's unit: cdlUnit carries the SI unit
    else:
        meta.append("unit:" + xs(XETO_UNIT[unit]))
    return meta


def dialog_meta(p):
    """cdlEnable, cdlGroup, cdlTab and cdlValueInReference for a parameter, from the json output."""
    meta = []
    if getattr(p, "enable", None):
        meta.append("cdlEnable:" + xs(p.enable))
    if getattr(p, "group", None):
        meta.append("cdlGroup:" + xs(p.group))
    if getattr(p, "tab", None):
        meta.append("cdlTab:" + xs(p.tab))
    if getattr(p, "value_in_reference", None) is not None:
        meta.append("cdlValueInReference:" + xs("true" if p.value_in_reference else "false"))
    return meta


def bound_meta(x):
    """Where a slot's minVal/maxVal (a connector's cdlMin/cdlMax) came from, kw.cdl 0.6.0. No meta: the number is the
    one the slot's own MBL declaration writes. cdlMinConst/cdlMaxConst: the MBL expression a constant-resolved bound
    was written with, as CXF carries it. cdlMinVia/cdlMaxVia: the instance path, in Xeto slot names, of the block
    parameter a propagated bound was taken from (propagate_bounds). cdlMinOwn/cdlMaxOwn: MBL's own, looser value where
    a block downstream tightened it. cdlMinWhen/cdlMaxWhen: a bound only a guarded instance imposes, as {val, cond,
    via}, never a minVal. cdlMinExpr/cdlMaxExpr: a parameter's bound written as an expression of the class's other
    parameters (min=outDamPhy_min), which no static minVal can hold."""
    meta = []
    if x.min_const:
        meta.append("cdlMinConst:" + xs(x.min_const))
    if x.max_const:
        meta.append("cdlMaxConst:" + xs(x.max_const))
    if getattr(x, "min_via", None):
        meta.append("cdlMinVia:" + xs(x.min_via))
    if getattr(x, "max_via", None):
        meta.append("cdlMaxVia:" + xs(x.max_via))
    if isinstance(x, Param):
        for side in ("min", "max"):
            o = getattr(x, side + "_own", None)
            if o is not None:
                meta.append("cdl%sOwn:%s" % (side.capitalize(), xs(fmt_num(o))))
        for side in ("min", "max"):
            ws = getattr(x, side + "_when", None)
            if ws:
                meta.append("cdl%sWhen:List {%s}" % (side.capitalize(), ", ".join(
                    "CdlBoundWhen {val:Number %s, cond:%s, via:%s}" % (xs(fmt_num(w["val"])), xs(w["cond"]), xs(w["via"]))
                    for w in ws)))
        # A bound written as an expression of the class's parameters has no static number. It goes out as text for the
        # configurator to evaluate against the answers; a connector's is named in the report instead.
        if x.min_expr:
            meta.append("cdlMinExpr:" + xs(x.min_expr))
        if x.max_expr:
            meta.append("cdlMaxExpr:" + xs(x.max_expr))
    return meta


def emit_param(p, slot, classes, cls):
    if p.raw_size is not None:
        # An array parameter (for example MultiSum's k): typed as a List and never compiled.
        meta = ["cdlParam", "cdlName:" + xs(p.name), "cdlType:" + xs(p.dtype), "cdlArraySize:" + xs(p.raw_size)]
        if p.expr is not None:
            meta.append("cdlDefault:" + xs(p.expr))
        meta += dialog_meta(p)
        return (["  // " + p.desc] if p.desc else []) + ["  %s: List? <%s>" % (slot, ", ".join(meta))]
    meta = ["cdlParam", "cdlName:" + xs(p.name)]
    if p.dtype in XETO_TYPE:
        xtype = XETO_TYPE[p.dtype]
        meta.append("cdlType:" + xs(p.dtype))
    else:
        xtype = spec_ref(p.dtype)                     # CDL.Types enums live in kw.cdl, G36 ones in common
        meta.append("cdlType:" + xs(xtype))
    meta += unit_meta(cls, p.name, p.unit, p.qkind, getattr(p, "qinferred", None),
                      bool(getattr(p, "uinferred", None)), getattr(p, "uvia", None), getattr(p, "point_unit", None),
                      getattr(p, "unit_mbl", None))
    if p.protected:
        meta.append("cdlProtected")
    if p.final:
        meta.append("cdlFinal")
    # fits compares minVal and maxVal as bare numbers, so on a slot a resolver converts they would hold an SI bound
    # against a value in the point's unit (30 Pa against 30 inH2O). There the bound goes to cdlSiMin and cdlSiMax, a
    # Number in the SI unit, which a resolver checks before it converts.
    si = converted_symbol(p.unit)
    if si is not None:
        if p.vmin is not None:
            meta.append("cdlSiMin:" + xs(fmt_num(p.vmin) + si))
        if p.vmax is not None:
            meta.append("cdlSiMax:" + xs(fmt_num(p.vmax) + si))
    elif p.vmin is not None:
        meta.append("minVal:" + xs(fmt_num(p.vmin)))
    if si is None and p.vmax is not None:
        meta.append("maxVal:" + xs(fmt_num(p.vmax)))
    meta += bound_meta(p)
    meta += dialog_meta(p)
    default = ""
    # A defaulted parameter is a MAYBE slot: on 4.0.6 a default does not make a slot optional.
    # A parameter with no default stays required, so fits catches it.
    maybe = "?" if (p.val is not None or p.expr is not None or p.protected) else ""
    if p.val is not None:
        default = " " + xs(fmt_num(p.val))
    elif p.expr is not None:
        # Only a bare enum literal becomes the slot's value. An expression that merely ends in one (Reheat
        # Controller's heaCoi = if have_hotWatCoi then ...WaterBased else ...Electric) stays an expression; reading
        # its last literal would fix the else branch as the default (found by the round trip).
        if p.dtype not in XETO_TYPE and re.fullmatch(r"[A-Za-z_][\w.]*", p.expr.strip()) \
                and p.expr.rsplit(".", 1)[0].endswith(p.dtype.rsplit(".", 1)[1]):
            default = " " + xs(p.expr.rsplit(".", 1)[1])
        else:
            meta.append("cdlDefault:" + xs(p.expr))
    lines = ["  // " + p.desc] if p.desc else []
    lines.append("  %s: %s%s <%s>%s" % (slot, xtype, maybe, ", ".join(meta), default))
    return lines


def _conditional(ci, ep):
    """True when the endpoint's owning instance, or the connector itself, carries a guard."""
    head = ep.split(".")[0]
    inst = ci.inst(head)
    if inst is not None:
        return inst.cond is not None
    conn = ci.conn(head)
    return conn is not None and conn.cond is not None


def emit_conn(c, slot, link, cls, alt=None):
    meta = ["cdlInput" if c.direction == "in" else "cdlOutput", "cdlName:" + xs(c.name), "cdlType:" + xs(c.dtype)]
    meta += unit_meta(cls, c.name, c.unit, c.qkind, getattr(c, "qinferred", None),
                      bool(getattr(c, "uinferred", None)), point_unit=getattr(c, "point_unit", None))
    if c.cond:
        meta.append("cdlCondition:" + xs(c.cond))
    if c.cmin is not None:
        meta.append("cdlMin:" + xs(fmt_num(c.cmin)))
    if c.cmax is not None:
        meta.append("cdlMax:" + xs(fmt_num(c.cmax)))
    meta += bound_meta(c)
    if c.raw_size is not None:
        meta.append("cdlArraySize:" + xs(c.raw_size))
    if c.direction == "out":
        # An output is computed, never stored: transient and readonly, both sys and sys.comp meta. The axon lib's
        # `output` flag is an engine's (hx.comps re-executes a block on a change to any slot not flagged output),
        # so the open model leaves it to an engine binding.
        meta += ["transient", "readonly"]
    if link:
        meta.append("link:" + xs(link))
    if alt:
        meta.append("cdlAltLink:" + xs(alt))
    lines = ["  // " + c.desc] if c.desc else []
    xtype = "List" if c.raw_size is not None else CONN_TYPE[c.dtype]
    lines.append("  %s: %s? <%s>" % (slot, xtype, ", ".join(meta)))
    return lines


def spec_ref(cls):
    if cls.startswith(CDL_PREFIX):
        return "kw.cdl::" + spec_name(cls, CDL_PREFIX)
    return g36_lib(cls) + "::" + spec_name(cls, G36_PREFIX)


def lib_refs(text):
    """Every lib a generated text names in a qualified spec reference (`kw.cdl.g36.common::X`)."""
    return set(re.findall(r"\b(kw\.cdl(?:\.[a-z0-9]+)*)::", text))


def state_facts(src_dir, elem):
    """{class path: mo_state.Fact} for each elementary class in `elem`, read from its .mo under `src_dir` (MBL's CDL
    directory, as mbl_fetch.source_dir verifies it against mbl_manifest.json). A class with no .mo, or a .mo for no
    elementary class, refuses by name: a class is never generated without its fact, and the fact is never guessed."""
    src = mo_state.load(src_dir)
    missing, stray = sorted(set(elem) - set(src)), sorted(set(src) - set(elem))
    if missing or stray:
        raise CxfError("the pinned .mo under %s does not match the elementary classes: %s"
                       % (src_dir, "; ".join(["no pin for " + c for c in missing] +
                                             ["a pin for no elementary class: " + c for c in stray])))
    return mo_state.facts(src)


def state_meta(fact):
    """The spec meta of one state fact (kw.cdl/meta.xeto): cdlState always; cdlStateInit on a stateful class only;
    cdlStateInitBasis on a noInput class only; cdlStateBasis unless the class is stateless. Basis items are joined
    with "; ", since a reason may hold a comma."""
    tags = ", cdlState:%s" % xs(fact.state)
    if fact.init is not None:
        tags += ", cdlStateInit:%s" % xs(fact.init)
    if fact.init_basis is not None:
        tags += ", cdlStateInitBasis:%s" % xs(fact.init_basis)
    if fact.basis:
        tags += ", cdlStateBasis:%s" % xs("; ".join(fact.basis))
    return tags


def emit_class(ci, classes, stamp, facts=None):
    out = ["// " + ci.desc] if ci.desc else []
    out += header(ci.path, stamp)
    if ci.kind == "enum":
        name = spec_name(ci.path, CDL_PREFIX if ci.path.startswith(CDL_PREFIX) else G36_PREFIX)
        out.append("%s: Enum <cdlClass:%s> {" % (name, xs(ci.path)))
        for item in ci.items:
            out.append("  %s <key:%s>" % (lower(item), xs(item)))
        out.append("}")
        return out
    prefix = CDL_PREFIX if ci.kind == "elementary" else G36_PREFIX
    name = spec_name(ci.path, prefix)
    names = slot_names([p.name for p in ci.params] + [c.name for c in ci.conns] + [i.name for i in ci.insts], ci.path)
    base = "kw.cdl::CdlBlock" if prefix == G36_PREFIX else "CdlBlock"
    tags = "cdlClass:%s%s" % (xs(ci.path), ", cdlElementary" if ci.kind == "elementary" else "")
    if ci.kind == "elementary":
        num, printed = CLAUSE7[ci.path]
        tags += ", cdlClause:%s" % xs(num) + (", cdl231Name:%s" % xs(printed) if printed else "")
        if facts is not None:
            tags += state_meta(facts[ci.path])
    out.append("%s: %s <%s> {" % (name, base, tags))
    for p in ci.params:
        out += emit_param(p, names[p.name], classes, ci.path)
    # A sink may have several drivers only when every driver but at most one sits on a conditional
    # instance or connector (MBL wires mutually exclusive alternatives, for example TrimAndRespond's
    # notHol.u from truHol.y if have_hol and from fal.y otherwise). The first is the `link`; the rest are
    # `cdlAltLink`, comma-separated. The expander keeps whichever survives the guards, and refuses two.
    drivers = {}
    for a, b in ci.edges:
        drivers.setdefault(b, []).append(a)
    sinks, alts = {}, {}
    for b, srcs in drivers.items():
        srcs = sorted(srcs)
        if len(srcs) > 1:
            unconditional = [s for s in srcs if not _conditional(ci, s)]
            if len(unconditional) > 1:
                raise CxfError("%s: %s has two unconditional drivers: %s" % (ci.path, b, ", ".join(srcs)))
            srcs = unconditional + [s for s in srcs if s not in unconditional]
        sinks[b] = lower_path(srcs[0])
        if len(srcs) > 1:
            alts[b] = ",".join(lower_path(s) for s in srcs[1:])
    for c in ci.conns:
        out += emit_conn(c, names[c.name], sinks.get(c.name) if c.direction == "out" else None, ci.path,
                         alts.get(c.name) if c.direction == "out" else None)
    for i in ci.insts:
        sub = classes[i.cls]
        subnames = slot_names([p.name for p in sub.params] + [c.name for c in sub.conns] +
                              [x.name for x in sub.insts], sub.path)
        # cdlName is the exact Modelica instance name (TDea, not the lowered slot tDea), so an importer never
        # reconstructs it from the slot.
        meta = ["cdlInstance", "cdlName:" + xs(i.name)]
        if i.binds:
            pairs = []
            for k in sorted(i.binds):
                val, expr = i.binds[k]
                pairs.append("%s:%s" % (subnames[k], xs(expr if expr is not None else fmt_num(val))))
            meta.append("cdlBind:{" + ", ".join(pairs) + "}")
        if i.finals:
            # The bindings CXF marks S231:isFinal, fixed values a design must not override.
            meta.append("cdlFinalBind:" + xs(",".join(sorted(subnames[k] for k in i.finals))))
        if getattr(i, "units", None):
            meta.append("cdlConnUnits:{" + ", ".join("%s:%s" % (subnames[k], xs(i.units[k])) for k in sorted(i.units)) + "}")
        if i.cond:
            meta.append("cdlCondition:" + xs(i.cond))
        links = [(subnames[b.split(".")[1]], sinks[b], alts.get(b)) for b in sorted(sinks) if b.split(".")[0] == i.name]
        if i.desc:
            out.append("  // " + i.desc)
        if links:
            out.append("  %s: %s%s <%s> {" % (names[i.name], spec_ref(i.cls), "?" if INSTANCE_SLOT == "maybe" else "",
                                               ", ".join(meta)))
            for slot, src, alt in links:
                out.append("    %s: <link:%s%s>" % (slot, xs(src), (", cdlAltLink:" + xs(alt)) if alt else ""))
            out.append("  }")
        else:
            out.append("  %s: %s%s <%s>" % (names[i.name], spec_ref(i.cls), "?" if INSTANCE_SLOT == "maybe" else "",
                                             ", ".join(meta)))
    out.append("}")
    return out


# The licensing notice AFL-3.0 asks for, adjacent to the copyright notice (AFL-3.0 preamble). Every
# .xeto file of an open lib opens with these two lines, the generated ones included (test_open_libs.py).
COPYRIGHT = "// Copyright (c) 2026, kW Engineering"
AFL_NOTICE = "// Licensed under the Academic Free License version 3.0"

# Each open lib's pragma: its doc and version. Its depends are OPEN_DEPENDS[lib]. render_pragma is the one writer of
# the pragma, so check_open_libs.py can accept a lib.xeto only in exactly this form.
LIB_PRAGMAS = {
    "kw.cdl": ("The ANSI/ASHRAE 231-2026 Clause 7 elementary block set on hx.comps: the CDL meta, the CDL "
               "enumerations, the block base, and one CdlClass instance per class naming the comp that runs it", "0.8.0"),
    "kw.cdl.g36.common": ("The Generic, Types, ThermalZones, VentilationZones and ZoneGroups packages of LBNL's "
                          "Guideline 36 sample library, generated from the Modelica Buildings Library and wired from "
                          "hx.comps comps", "0.8.0"),
    "kw.cdl.g36.ahu": ("The AHUs and FanCoilUnits packages of LBNL's Guideline 36 sample library, generated from the "
                       "Modelica Buildings Library and wired from hx.comps comps", "0.8.0"),
    "kw.cdl.g36.terminal": ("The TerminalUnits package of LBNL's Guideline 36 sample library, generated from the "
                            "Modelica Buildings Library and wired from hx.comps comps", "0.8.0"),
}
PRAGMA_LINE = "pragma: Lib <"


def render_pragma(doc, version, depends, publish=()):
    """The lib.xeto pragma, from `pragma: Lib <` to the end of the file, exactly as the generator writes it.
    `publish` lists lib file patterns the packer ships beside the .xeto sources (xetoc's Scanner packs a lib's
    .xeto files and chapters, and anything else only when a `publish` or `include` pattern names it)."""
    lines = [PRAGMA_LINE, "  doc: " + json.dumps(doc, ensure_ascii=False), '  version: "%s"' % version,
             "  depends: {"] + ['    { lib: "%s" }' % d for d in depends] + ["  }"]
    if publish:
        lines.append("  publish: {%s}" % ", ".join(json.dumps(p) for p in publish))
    return "\n".join(lines + [">", ""])


# Every open lib ships MBL's licence in NOTICE, so every pragma publishes it: "/NOTICE"
# is LibFilePattern's file form, the exact lib-relative path, as hx.test.xeto publishes "/pub-root.txt".
PUBLISH = ("/NOTICE",)


def lib_pragma(lib):
    doc, version = LIB_PRAGMAS[lib]
    return render_pragma(doc, version, OPEN_DEPENDS[lib], PUBLISH)


def split_lib_xeto(text):
    """A lib.xeto as (header, pragma): the hand-written comment header, and everything from the `pragma: Lib <`
    line on. Raises ValueError when no line is exactly `pragma: Lib <`."""
    if text.startswith(PRAGMA_LINE + "\n"):
        return "", text
    i = text.find("\n" + PRAGMA_LINE + "\n")
    if i < 0:
        raise ValueError("no line is exactly '%s'" % PRAGMA_LINE)
    return text[:i + 1], text[i + 1:]


def lib_xeto_files():
    """Every open lib's lib.xeto, relative to the repo root. The header is hand-written; the pragma is generated."""
    return [LIBS + "/" + lib + "/lib.xeto" for lib in OPEN_LIBS]


def render(classes, paths, stamp, title, facts=None, emit=None):
    """A generated file: the header, then each class in `paths` through `emit` (emit_class by default)."""
    emit = emit or (lambda ci: emit_class(ci, classes, stamp, facts))
    lines = [COPYRIGHT, AFL_NOTICE, "//",
             "// %s" % title,
             "// GENERATED from MBL %s (%s) via modelica-json %s. Do not edit."
             % (stamp["mbl"], stamp["mblCommit"][:8], stamp["modelicaJson"][:8]),
             "// CXF carries no MBL version; the version above is pinned by the generator.",
             "// MBL's class names, descriptions and defaults are redistributed under MBL's license: see NOTICE.", ""]
    for p in paths:
        lines += emit(classes[p])
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO))
    ap.add_argument("--collisions", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    if a.collisions:
        print("\n".join(sorted(tag_collisions(REPO))))
        return
    stamp = load_stamp()
    src = cxf_source.verify()
    classes = load_classes(src)
    skip = (".Validation.", ".Obsolete.", ".Interfaces.", ".Types.", ".Constants.")   # no Clause 7 blocks
    elem = [p for p in sorted(classes) if p.startswith(CDL_PREFIX) and classes[p].kind == "elementary"
            and not any(s in p for s in skip)]
    outside = [c for c in elem if c not in CLAUSE7]
    if outside:
        # A block MBL has that Clause 7 lacks belongs in kw.cdl.mbl (reserved, not built).
        raise CxfError("not in 231 Clause 7, so not in kw.cdl (kw.cdl.mbl is reserved): " + ", ".join(outside))
    if load_classes.report:
        print("left out, with reasons:\n  " + "\n  ".join(load_classes.report))
    out = pathlib.Path(a.out)
    for lib in OPEN_LIBS:
        (out / LIBS / lib).mkdir(parents=True, exist_ok=True)
        # The hand-written header from the repo's lib.xeto, then the pragma render_pragma writes.
        header, _ = split_lib_xeto((REPO / LIBS / lib / "lib.xeto").read_text(encoding="utf-8"))
        (out / LIBS / lib / "lib.xeto").write_text(header + lib_pragma(lib), encoding="utf-8", newline="\n")
    cdl_enums = sorted(p for p in classes if p.startswith(CDL_PREFIX + "Types.") and classes[p].kind == "enum")
    facts = state_facts(mbl_fetch.source_dir(fetch_missing=not a.no_fetch), elem)
    del hxemit.LITERALS[:]
    del hxemit.SKIPPED[:]
    hxemit.DECIDED.clear()
    rows, mapped = hx_rows(classes)
    arrays = [p for p in elem if mapped[p]["grade"] == "array"]
    comps = hxemit.composed(classes, mapped)
    allc = dict(classes, **comps)

    def kw_cdl_emit(ci):
        if ci.kind == "enum":
            return emit_class(ci, classes, stamp)
        if ci.path in comps:
            return hxemit.Mapper(ci, allc, mapped).emit(stamp, spec_name(ci.path, CDL_PREFIX), "CdlBlock", False)
        lines = emit_class(ci, classes, stamp, facts)
        i = next(n for n, x in enumerate(lines) if x.startswith(spec_name(ci.path, CDL_PREFIX) + ": CdlBlock <"))
        lines[i] = re.sub(r'(<cdlClass:"[^"]*")', lambda m: m.group(1) + ", abstract, cdlExpand", lines[i], count=1)
        return hxemit.status_typed(lines)
    (out / LIBS / "kw.cdl/blocks.xeto").write_text(
        render(allc, cdl_enums + arrays + sorted(comps), stamp,
               "kw.cdl: the CDL.Types enumerations, the array classes, and the classes composed from other classes",
               emit=kw_cdl_emit), encoding="utf-8", newline="\n")
    (out / LIBS / "kw.cdl/classes.xeto").write_text(hxemit.render_classes(rows, facts, stamp, classes), encoding="utf-8",
                                             newline="\n")
    # Every pinned G36 class the generator reads (the 126 classes outside Plants), enumerations first, each lib's
    # classes in path order. A class left out is named in the report above, never dropped silently.
    g36 = sorted((p for p in classes if p.startswith(G36_PREFIX)), key=lambda p: (classes[p].kind != "enum", p))
    consts = load_constants(src)
    bad = unresolved_names(classes, g36 + elem, consts)
    if bad:
        raise CxfError("dotted names that resolve to nothing:\n  " + "\n  ".join(bad))
    counts, libs = [], [("kw.cdl", elem)]
    points = hxemit.point_index()
    expand = expanding(allc, mapped)

    def g36_emit(ci):
        if ci.kind == "enum":
            return emit_class(ci, classes, stamp)
        return hxemit.Mapper(ci, allc, mapped, points).emit(stamp, spec_name(ci.path, G36_PREFIX), "kw.cdl::CdlBlock",
                                                           ci.path in expand)
    known = {spec_name(p, G36_PREFIX) for p in g36}
    stray = sorted({c for c, _ in points} - known)
    if stray:
        raise CxfError("the point table names composites the generator has not: " + ", ".join(stray))
    for lib in G36_LIBS:
        mine = [p for p in g36 if g36_lib(p) == lib]
        mc = sorted(c for c in consts if g36_lib(c) == lib)
        text = render(allc, mine, stamp, "%s: %s" % (lib, G36_TITLES[lib]), emit=g36_emit)
        for p in mc:
            text += "\n" + "\n".join(emit_constants(p, consts[p], stamp)) + "\n"
        check_lib_refs(lib, text)
        (out / LIBS / lib / "g36.xeto").write_text(text, encoding="utf-8", newline="\n")
        counts.append("%s: %d specs and %d constants packages" % (lib, len(mine), len(mc)))
        libs.append((lib, [p for p in mine if classes[p].kind != "enum"]))
    (out / UNITS_REPORT).parent.mkdir(parents=True, exist_ok=True)
    unused = sorted(set(LITERAL_UNITS) - {"%s.%s.%s" % d for d in hxemit.DECIDED})
    if unused:
        # a literalUnits decision that names no literal the generator writes has rotted (MBL renamed or removed it)
        raise CxfError("quantities.json literalUnits names no literal: " + ", ".join(unused))
    (out / UNITS_REPORT).write_text(units_report(hxemit.LITERALS, hxemit.SKIPPED), encoding="utf-8", newline="\n")
    rep = bounds_report(classes, libs, load_classes.bounds)
    (out / BOUNDS_REPORT).parent.mkdir(parents=True, exist_ok=True)
    (out / BOUNDS_REPORT).write_text(rep, encoding="utf-8", newline="\n")
    print("bounds: " + rep.split("\n")[[i for i, l in enumerate(rep.split("\n")) if l.startswith("all ")][0]].strip())
    print("kw.cdl: %d elementary block classes and %d enumerations; %s; left out: %d"
          % (len(elem), len(cdl_enums), "; ".join(counts), len(load_classes.report)))


# One phrase per G36 lib, after the lib name in its generated file's title.
G36_TITLES = {"kw.cdl.g36.common": "the Generic, Types, ThermalZones, VentilationZones and ZoneGroups packages of "
                                   "LBNL's G36 sample library",
              "kw.cdl.g36.ahu": "the AHUs and FanCoilUnits packages of LBNL's G36 sample library",
              "kw.cdl.g36.terminal": "the TerminalUnits package of LBNL's G36 sample library"}


def check_lib_refs(lib, text):
    """A generated lib names only specs of itself and of the libs it may depend on (OPEN_DEPENDS): ahu never names
    terminal, and no lib names one outside the open set. Refuses by lib and by the libs it reached."""
    bad = sorted(r for r in lib_refs(text) if r != lib and r not in OPEN_DEPENDS[lib])
    if bad:
        raise CxfError("%s names specs of %s, which it may not depend on" % (lib, ", ".join(bad)))


BOUNDS_REPORT = GEN + "/bounds-report.txt"
UNITS_REPORT = GEN + "/units-report.txt"


def units_report(literals, skipped=()):
    """The units report: every literal the generator writes on a Real parameter, counted by what unit it got and
    by the unit family of its class, then each literal left with no unit and why."""
    from collections import Counter
    import units as u
    written, dimensionless, none = Counter(), Counter(), Counter()
    reasons, fams, lines = Counter(), Counter(), []
    for comp, inst, name, unit, why, family in literals:
        fams[(family, "unit" if unit is not None else "none")] += 1
        if unit is None:
            none[family] += 1
            reasons[why] += 1
            lines.append("  %s %s.%s: %s" % (comp[len(G36_PREFIX):] if comp.startswith(G36_PREFIX) else comp, inst,
                                            name, why))
        elif unit == u.DIMENSIONLESS:
            dimensionless[family] += 1
        else:
            written[unit[0] + (" difference" if unit[1] else "")] += 1
    total = len(literals)
    out = ["# The literals the generator writes on Real parameters, and their SI units. GENERATED by",
           "# src/gen/generate.py. A unit comes from static propagation over each composite (units.py).",
           "",
           "literals %d: with a unit %d, dimensionless %d, no unit %d" % (
               total, sum(written.values()), sum(dimensionless.values()), sum(none.values())), "",
           "by unit:"]
    out += ["  %-24s %d" % (k, v) for k, v in sorted(written.items())]
    out += ["", "by family (unit or dimensionless / no unit):"]
    for fam in sorted({f for f, _ in fams}):
        out.append("  %-10s %d / %d" % (fam, fams[(fam, "unit")], fams[(fam, "none")]))
    out += ["", "PID error scales r left unwritten (requires.writeWhenUnit): %d" % len(skipped)]
    out += ["  %s %s.%s: %s" % (c[len(G36_PREFIX):] if c.startswith(G36_PREFIX) else c, i, k, why)
            for c, i, k, why in sorted(set(skipped))]
    out += ["", "why no unit:"]
    out += ["  %-60s %d" % (k, v) for k, v in reasons.most_common()]
    out += ["", "each literal with no unit:"] + sorted(lines)
    return "\n".join(out) + "\n"
REPORT_SECTIONS = [
    ("param-expr", "Parameter bounds written as an expression of the class's parameters, emitted as cdlMinExpr/"
                   "cdlMaxExpr for the configurator to evaluate"),
    ("conn-expr", "Connector bounds written as an expression of the class's parameters, not emitted (only a "
                  "parameter's is emitted)"),
    ("disagree", "Paths that disagree. The tightest unguarded bound is minVal/maxVal"),
    ("tightened", "Own bounds tightened by a block downstream (the intersection; MBL's own value is cdlMinOwn/cdlMaxOwn)"),
    ("conditional", "Bounds only a guarded instance imposes, emitted as cdlMinWhen/cdlMaxWhen and never as "
                    "minVal/maxVal"),
    ("tautology", "Guarded bounds whose guards together cover every configuration, emitted as minVal/maxVal"),
    ("guard", "Guards that do not lift into the parameter's class or cannot be enumerated"),
    ("unit", "Bindings across which MBL declares two different units (the bound is carried: Modelica passes the "
             "number unconverted)"),
    ("expression", "Bindings through an expression, not followed (the block parameter's bound is not lifted)"),
    ("reference", "Block bounds written as an expression of the block's parameters, not lifted"),
]


def bound_counts(classes, paths):
    """{(kind, side): count} over the parameters of `paths`: kind is own (the slot's own literal), const (resolved
    from a constant expression), via (propagated) or expr (an expression of parameters, cdlMinExpr/cdlMaxExpr, which
    a parameter may carry beside a number from elsewhere); side is min or max."""
    out = {}
    for path in paths:
        for p in classes[path].params:
            if p.raw_size is not None:
                continue
            for side, v, const, via in (("min", p.vmin, p.min_const, p.min_via), ("max", p.vmax, p.max_const, p.max_via)):
                if (p.min_expr if side == "min" else p.max_expr):
                    out[("expr", side)] = out.get(("expr", side), 0) + 1
                if getattr(p, side + "_when", None):
                    out[("when", side)] = out.get(("when", side), 0) + len(getattr(p, side + "_when"))
                if v is None:
                    continue
                kind = "via" if via else "const" if const else "own"
                out[(kind, side)] = out.get((kind, side), 0) + 1
    return out


def bounds_report(classes, libs, report):
    """The generator's bounds report: counts per lib, every bound written as an expression of parameters, then every
    choice propagate_bounds made and every bound it did not follow, one line each. Deterministic, so it regenerates
    byte-identical with the libs."""
    report = dict(report, **{"param-expr": [], "conn-expr": []})
    for lib, paths in libs:
        for path in paths:
            ci = classes[path]
            for x in ci.params + ci.conns:
                key = "param-expr" if isinstance(x, Param) else "conn-expr"
                for side, e in (("min", x.min_expr), ("max", x.max_expr)):
                    if e:
                        report[key].append("%s.%s %s = %s" % (path, x.name, side, e))
    lines = ["Parameter bounds in the open CDL libs. GENERATED by src/gen/generate.py with the libs. Do not edit.",
             "",
             "A minVal/maxVal is own (the slot's own MBL declaration, a literal), const (an MBL expression of a CDL or",
             "class constant, kept as cdlMinConst/cdlMaxConst) or via (propagated from the block parameter named by",
             "cdlMinVia/cdlMaxVia, an instance path in Xeto slot names). when counts cdlMinWhen/cdlMaxWhen: a bound",
             "only a guarded instance imposes, with its condition, never a minVal/maxVal. expr counts",
             "cdlMinExpr/cdlMaxExpr: a bound written as an expression of the class's parameters. The configurator",
             "evaluates when and expr. Counts are bounds, a min and a max apart.",
             ""]
    total = {}
    for lib, paths in libs:
        c = bound_counts(classes, paths)
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
        lines.append("%-20s %s" % (lib, _count_line(c)))
    lines.append("%-20s %s" % ("all", _count_line(total)))
    for key, title in REPORT_SECTIONS:
        rows = sorted(report.get(key, []))
        lines += ["", "## %s: %d" % (title, len(rows))] + ["  " + r for r in rows]
    return "\n".join(lines) + "\n"


def _count_line(c):
    return "  ".join("%s %d min %d max" % (k, c.get((k, "min"), 0), c.get((k, "max"), 0))
                     for k in ("own", "const", "via", "when", "expr"))


def generated_files():
    """Every generated .xeto file, relative to the repo root."""
    return [LIBS + "/kw.cdl/blocks.xeto", LIBS + "/kw.cdl/classes.xeto"] + [LIBS + "/" + lib + "/g36.xeto" for lib in G36_LIBS]


def hx_rows(classes):
    """(class map rows by kw.cdl spec name, the same rows by CDL class path). A table that fails its checks stops
    generation, naming every failure."""
    doc, errors = classmap.build(classes)
    if errors:
        raise CxfError("the class-to-comp table fails its checks:\n  " + "\n  ".join(errors))
    return doc["classes"], hxemit.rows_by_path(doc["classes"])


def expanding(classes, mapped):
    """The composites that expand when a sequence is instantiated for a building: each that holds a vector
    connector, a vectorized instance, an instance of an array class, or an instance of another such composite."""
    out, grew = set(), True
    while grew:
        grew = False
        for p, ci in classes.items():
            if ci.kind != "composite" or p in out:
                continue
            if any(c.raw_size is not None for c in ci.conns) or any(
                    i.size is not None or (mapped.get(i.cls) or {}).get("grade") == "array" or i.cls in out
                    for i in ci.insts):
                out.add(p)
                grew = True
    return out


# ---- round trip support (the reading side of what emit_class writes) ----

_MAPPED = {}


def mapped_classes(root, override=None):
    """(every class, the composed kw.cdl composites included; the class map rows by class path), cached per root."""
    key = (str(root), json.dumps(override, sort_keys=True, default=str) if override else None)
    if key not in _MAPPED:
        classes = load_classes(root, override)
        _, mapped = hx_rows(classes)
        _MAPPED[key] = (dict(classes, **hxemit.composed(classes, mapped)), mapped)
    return _MAPPED[key]


def read_generated(root, cls):
    """The generated Xeto for `cls`, read back into the shape mo_reader.read returns. A composite (G36, or a kw.cdl
    class composed from others) reads through hxemit.parse_mapped, which turns its hx.comps children back into CDL."""
    rel = "kw.cdl/blocks.xeto" if cls.startswith(CDL_PREFIX) else g36_lib(cls) + "/g36.xeto"
    text = (root / LIBS / rel).read_text(encoding="utf-8")
    allc, mapped = mapped_classes(cxf_source.source_root())
    if allc[cls].kind == "composite":
        return hxemit.parse_mapped(text, cls, mapped, allc)
    return parse_generated(text, cls)


def read_generated_from_sources(root, cls, override):
    stamp = load_stamp()
    allc, mapped = mapped_classes(root, override)
    ci = allc[cls]
    if ci.kind == "composite":
        lines = hxemit.Mapper(ci, allc, mapped).emit(stamp, spec_name(cls, G36_PREFIX), "kw.cdl::CdlBlock", False)
        return hxemit.parse_mapped("\n".join(lines), cls, mapped, allc)
    return parse_generated("\n".join(emit_class(ci, allc, stamp)), cls)


def _meta(s):
    """Parse '<a, b:"x", c:{d:"y"}>' into a dict, string-aware (a CDL expression may contain '>')."""
    out, i, n = {}, 1, len(s)
    while i < n and s[i] != ">":
        m = re.match(r"\s*([A-Za-z_]\w*)", s[i:])
        key = m.group(1)
        i += m.end()
        if i < n and s[i] == ":":
            i += 1
            if s[i] == '"':
                j = i + 1
                while s[j] != '"':
                    j += 2 if s[j] == "\\" else 1
                out[key] = json.loads(s[i:j + 1])
                i = j + 1
            elif s.startswith("List {", i):
                j, depth, inq = i + 5, 0, False
                while True:
                    ch = s[j]
                    if ch == '"' and s[j - 1] != "\\":
                        inq = not inq
                    elif not inq and ch == "{":
                        depth += 1
                    elif not inq and ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                items = re.findall(r'\{((?:[^{}"]|"(?:[^"\\]|\\.)*")*)\}', s[i + 6:j])
                out[key] = [{k: json.loads(v) for k, v in re.findall(r'(\w+):(?:[A-Z]\w* )?("(?:[^"\\]|\\.)*")', it)}
                            for it in items]
                i = j + 1
            elif s[i] == "{":
                j, depth, inq = i, 0, False
                while True:
                    ch = s[j]
                    if ch == '"' and s[j - 1] != "\\":
                        inq = not inq
                    elif not inq and ch == "{":
                        depth += 1
                    elif not inq and ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                out[key] = {k: json.loads(v) for k, v in re.findall(r'(\w+):("(?:[^"\\]|\\.)*")', s[i + 1:j])}
                i = j + 1
            else:
                # a bare value: a ref (@kw.cdl::cdl-RealsAdd) or a spec qname (ph.points::ZoneAirTempSensor)
                m = re.match(r"[^,>\s]+", s[i:])
                out[key] = m.group(0)
                i += m.end()
        else:
            out[key] = True
        while i < n and s[i] in " ,":
            i += 1
    return out, i + 1


def parse_generated(text, cls):
    start = text.find('cdlClass:"%s"' % cls)
    if start < 0:
        raise CxfError("no generated spec for " + cls)
    body = text[text.index("{", start) + 1:]
    res = {"params": {}, "inputs": {}, "outputs": {}, "components": {}, "connects": set(), "links": set()}
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1
        if line == "}":
            break
        m = re.match(r"^  (\w+): (\S+?)(\?)? (<.*)$", line)
        if not m:
            continue
        slot, typ, rest = m.group(1), m.group(2), m.group(4)
        meta, end = _meta(rest)
        tail = rest[end:].strip()
        cdl = meta.get("cdlName", slot)
        if "cdlParam" in meta:
            dflt = json.loads(tail) if tail.startswith('"') else meta.get("cdlDefault")
            dialog = {k: meta[m] for k, m in (("enable", "cdlEnable"), ("group", "cdlGroup"), ("tab", "cdlTab"))
                      if m in meta}
            if "cdlValueInReference" in meta:
                dialog["valueInReference"] = meta["cdlValueInReference"] == "true"
            # a reviewed override (cdlUnitOverride) keeps MBL's unit for the comparison with MBL's source
            res["params"][cdl] = {"default": dflt, "unit": meta.get("cdlUnitOverride", meta.get("cdlUnit")),
                                  "protected": "cdlProtected" in meta,
                                  "type": meta.get("cdlType"), "xeto": typ, "final": "cdlFinal" in meta,
                                  "dialog": dialog}
        elif "cdlInput" in meta or "cdlOutput" in meta:
            # a scalar connector rides its hx.comps status type; the round trip reads it as the plain type it carries
            plain = {"hx.comps::StatusNumber": "Number", "hx.comps::StatusBool": "Bool", "hx.comps::StatusStr": "Str"}
            res["inputs" if "cdlInput" in meta else "outputs"][cdl] = {
                "type": meta.get("cdlType"), "unit": meta.get("cdlUnit"), "xeto": plain.get(typ, typ)}
            for src in ([meta["link"]] if "link" in meta else []) + \
                    (meta["cdlAltLink"].split(",") if "cdlAltLink" in meta else []):
                res["connects"].add(frozenset((lower_path(src), lower_path(slot))))
                res["links"].add((lower_path(src), lower_path(slot)))
        elif "cdlInstance" in meta:
            res["components"][slot] = {"class": typ, "binds": meta.get("cdlBind", {}), "cond": meta.get("cdlCondition"),
                                       "finals": set(filter(None, meta.get("cdlFinalBind", "").split(","))),
                                       "cdlName": meta.get("cdlName"), "units": meta.get("cdlConnUnits", {})}
            if tail.startswith("{"):
                while not lines[i].strip() == "}":
                    lm = re.match(r'^\s+(\w+): (<.*>)\s*$', lines[i])
                    sub, _ = _meta(lm.group(2))
                    for src in [sub["link"]] + (sub["cdlAltLink"].split(",") if "cdlAltLink" in sub else []):
                        res["connects"].add(frozenset((lower_path(src), slot + "." + lm.group(1))))
                        res["links"].add((lower_path(src), slot + "." + lm.group(1)))
                    i += 1
                i += 1
    return res


def _norm(e):
    """Whitespace and quote characters do not carry meaning in a modifier's text (an Assert message
    arrives from CXF without its Modelica quotes)."""
    return None if e is None else re.sub(r"[\s\"']+", "", str(e))


def _num_norm(v):
    """Every numeric literal in one spelling (1E-3 and 0.001, 0.0 and 0 are one number), alone or inside an
    expression (`fill(1E-4,nZon)`); a digit inside a name (k1) is not a literal."""
    if v is None:
        return v
    return re.sub(r"(?<![\w.])\d+(?:\.\d*)?(?:[eE][-+]?\d+)?(?![\w.])", lambda m: repr(float(m.group(0))), v)


def _bind_norm(v):
    """A binding's text for comparison. Arithmetic of literals and G36 package constants (273.15+27.0,
    Types.OperationModes.occupied) is its value, since the hx.comps form writes a literal binding as the comp slot's
    value; anything naming a parameter keeps its normalized text."""
    t = _norm(v)
    consts = hxemit.package_constants()
    try:
        if t and all(n in consts for n in cxf.names(t)):
            x = cxf.evaluate(t, {}, consts.get)
            if isinstance(x, bool):
                return repr(x)
            if isinstance(x, float):
                return "%.12g" % x                   # the written value is the clean spelling (277.55)
    except CxfError:
        pass
    return _num_norm(t)


def _cdl_type(t):
    """mo_reader's declared type in the generator's cdlType spelling: a primitive stays, a class becomes its spec."""
    return t if t in XETO_TYPE else spec_ref(t)


def compare(want, got, elementary=False):
    """Differences between mo_reader's view of a class and the generated spec, as readable lines.
    For an elementary block, MBL's protected parameters, internal instances and internal connections are
    its implementation, not the type 231 Clause 7 defines, and are not compared."""
    if elementary:
        want = dict(want, components={}, connects=set(),
                    params={k: v for k, v in want["params"].items() if not v["protected"]})
        # A class kw.cdl composes from other classes (Nand, Nor, the pulse sources) has internals of its own, which
        # are not MBL's and are not compared either: its interface is.
        got = dict(got, components={}, connects=set(), links=set())
    problems = []
    for kind in ("params", "inputs", "outputs"):
        for name in sorted(set(want[kind]) | set(got[kind])):
            if name not in got[kind]:
                problems.append("%s %s dropped" % (kind, name))
            elif name not in want[kind]:
                problems.append("%s %s invented" % (kind, name))
            else:
                # Type, Xeto slot type and, for a connector, unit: a compare that read neither would pass a Real
                # input emitted as Bool.
                w, g = want[kind][name], got[kind][name]
                wt = _cdl_type(w["type"])
                if wt != g["type"]:
                    problems.append("%s %s type %s became %s" % (kind, name, wt, g["type"]))
                # A connector rides its status type on hx.comps (CONN_TYPE); a parameter keeps XETO_TYPE.
                xmap = XETO_TYPE if kind == "params" else CONN_TYPE
                wx = "List" if w["array"] else xmap.get(wt, wt)
                if wx != g["xeto"]:
                    problems.append("%s %s Xeto type %s became %s" % (kind, name, wx, g["xeto"]))
                if kind != "params" and w["unit"] != g["unit"]:
                    problems.append("%s %s unit %s became %s" % (kind, name, w["unit"], g["unit"]))
                if kind == "params" and w["final"] != g["final"]:
                    problems.append("param %s final %s became %s" % (name, w["final"], g["final"]))
    for name, w in want["params"].items():
        g = got["params"].get(name)
        if g is None:
            continue
        wd, gd = _norm(w["default"]), _norm(g["default"])
        if wd is not None and wd.startswith(OBC):
            wd = wd.rsplit(".", 1)[1]
        try:
            same = float(wd) == float(gd)
        except (TypeError, ValueError):
            same = wd == gd
        if not same:
            problems.append("param %s default %s became %s" % (name, w["default"], g["default"]))
        if w["unit"] != g["unit"]:
            problems.append("param %s unit %s became %s" % (name, w["unit"], g["unit"]))
        if not elementary:
            # Dialog and __cdl, read from MBL's source by mo_reader and from the json output by the generator.
            # Whitespace carries no meaning in an enable expression; its tokens, parentheses and order do.
            wd_, gd_ = dict(w.get("dialog") or {}), dict(g.get("dialog") or {})
            for dd in (wd_, gd_):
                if "enable" in dd:
                    dd["enable"] = re.sub(r"\s+", "", dd["enable"])
            if wd_ != gd_:
                problems.append("param %s Dialog %s became %s" % (name, wd_, gd_))
    wc = {lower(k): dict(v, name=k) for k, v in want["components"].items()}
    for name in sorted(set(wc) | set(got["components"])):
        if name not in got["components"]:
            problems.append("component %s dropped" % name)
        elif name not in wc:
            problems.append("component %s invented" % name)
        else:
            w, g = wc[name], got["components"][name]
            if w["name"] != g["cdlName"]:
                problems.append("component %s CDL name %s became %s" % (name, w["name"], g["cdlName"]))
            if spec_ref(w["class"]) != g["class"]:
                problems.append("component %s class %s became %s" % (name, w["class"], g["class"]))
            if _norm(w["cond"]) != _norm(g["cond"]):
                problems.append("component %s guard %s became %s" % (name, w["cond"], g["cond"]))
            wb = {lower(k): _bind_norm(v) for k, v in w["binds"].items()}
            gb = {k: _bind_norm(v) for k, v in g["binds"].items()}
            if wb != gb:
                problems.append("component %s bindings %s became %s" % (name, wb, gb))
            wf = {lower(k) for k in w["finals"]}
            wu = {lower(k): v for k, v in (w.get("units") or {}).items()}
            if wu != (g.get("units") or {}):
                problems.append("component %s connector units %s became %s" % (name, wu, g.get("units") or {}))
            if wf != g["finals"]:
                problems.append("component %s final bindings %s became %s" % (name, sorted(wf), sorted(g["finals"])))
    # Connections compare pair by pair. The one exception is MBL's input-to-input connect
    # (connect(HeaCoi.u, retDamPos.u)), which the generator emits as a link from the inputs' common driver to each:
    # a source pair joining two generated sinks is accounted for when one link drives both, and a generated link to
    # a sink is accounted for when the source joins that sink to another sink the same link drives. A generated
    # endpoint that both drives and is driven is refused, so a link moved to another source cannot hide in a set.
    wcon = {frozenset(lower_path(x) for x in pair) for pair in want["connects"]}
    # Directed links, as parse_generated reads them. No fallback from the unordered `connects`:
    # it would order each pair alphabetically and feed that order to the direction check below.
    links = got["links"]
    driver = {}
    for s, t in links:
        driver.setdefault(t, set()).add(s)
    for x in sorted(set(driver) & {s for s, _ in links}):
        problems.append("%s is both driven and a driver in the generated links" % x)
    sink_sets = _conn_sets([c for c in wcon if all(x in driver for x in c)])
    for c in sorted(wcon, key=sorted):
        if c in got["connects"]:
            continue
        p, q = sorted(c) if len(c) == 2 else (next(iter(c)),) * 2
        if not (p in driver and q in driver and driver[p] & driver[q]):
            problems.append("connect(%s) dropped" % ", ".join(sorted(c)))
    for s, t in sorted(links):
        if frozenset((s, t)) in wcon:
            continue
        mates = [u for u in sink_sets if sink_sets[u] == sink_sets.get(t) and u != t]
        if not any(frozenset((s, u)) in wcon for u in mates):
            problems.append("connect(%s) invented" % ", ".join(sorted((s, t))))
    # Direction. The pairs above are unordered, so a reversed link (an instance input driving an
    # instance output) or an output driving a composite input passed whenever the endpoint had no other link. Each
    # generated link must run FROM a composite input or an instance output INTO a composite output or an instance
    # input, by MBL's declared causality: the class's own connectors, and mo_reader's `ports` for its instances.
    # An endpoint with no declared causality refuses, so an instance whose class mo_reader cannot read is not
    # waved through. Pinned by test_the_round_trip_refuses_a_link_that_runs_against_causality.
    role = {lower(n): "source" for n in want["inputs"]}
    role.update({lower(n): "sink" for n in want["outputs"]})
    role.update({lower_path(k): "source" if v == "out" else "sink" for k, v in (want.get("ports") or {}).items()})
    for s, t in sorted(links):
        for x, need, way in ((s, "source", "from"), (t, "sink", "into")):
            r = role.get(re.sub(r"\[[^\]]*\]", "", x))
            if r is None:
                problems.append("link %s -> %s: no declared causality for %s" % (s, t, x))
            elif r != need:
                problems.append("link %s -> %s runs %s %s, a %s-side connector" % (s, t, way, x, r))
    return problems


def _conn_sets(pairs):
    """Endpoint -> a representative of its connection set, over pairs of connected endpoints."""
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for pair in pairs:
        a, b = (sorted(pair) * 2)[:2]
        parent[find(a)] = find(b)
    return {x: find(x) for pair in pairs for x in pair}


PH_TAGS = HERE / "ph_tags.json"


def ph_tags(src):
    """The tag names Project Haystack's ph lib declares, read from a Project Haystack xeto checkout's src/xeto
    directory: every lower-case name before a colon in ph's .xeto files."""
    tags = set()
    for f in sorted((pathlib.Path(src) / "ph").glob("*.xeto")):
        for m in re.finditer(r"^\s*\*?([a-z][A-Za-z0-9]*)\s*:", f.read_text(encoding="utf-8"), re.M):
            tags.add(m.group(1))
    return sorted(tags)


def tag_collisions(root):
    """Slot names in the generated libs under `root` that are also ph tag names (ph_tags.json)."""
    tags = set(json.loads(PH_TAGS.read_text(encoding="utf-8"))["tags"])
    slots = set()
    for lib in generated_files():
        for m in re.finditer(r"^  ([a-z]\w*): ", (root / lib).read_text(encoding="utf-8"), re.M):
            slots.add(m.group(1))
    return sorted(slots & tags)


if __name__ == "__main__":
    main()
