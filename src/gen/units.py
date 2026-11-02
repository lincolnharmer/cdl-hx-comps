"""Static unit propagation over one CDL composite, to give every literal on a signal path its SI unit.

A unit is a pair (symbol, delta): the Haystack symbol of the canonical SI unit (`K`, `Pa`, `m³/s`, `1` for a
dimensionless value), and whether the value is a difference. A temperature difference is (`K`, True). The
distinction matters to whatever converts a value into a building point's unit: an absolute temperature converts
with the offset (K to °F), a difference by scale alone (K to Δ°F).

The rules are each CDL class's `unitRule` in the class-to-comp table (classmap_table.UNIT_RULES):
  keep   groups of CDL names that carry one unit, solved in both directions
  op     `add`, `sub`, `mul`, `div`, `sum` or `delta`, from the names in `ins` to the name in `out`, forward only
  seeds  CDL names to the unit they always carry
A connector's or parameter's declared unit (its cdlUnit and quantity) seeds it too. Ports join into groups through
the composite's connections, bare-name bindings and the keep rules. Every group holds unknown, one unit, or a
conflict: two different units joined into one group make a conflict, and a conflict never resolves. An op maps its
input groups to its output group, and a conflict in gives a conflict out, so the fixpoint does not depend on order.

Beyond the forward rules, an op of two inputs also solves backward where the arithmetic fixes the answer: Add and
Subtract need one unit on both inputs (hx.comps faults otherwise), so a literal added to a temperature is a
temperature difference; and a Multiply or Divide whose output and one input are known gives the other input's unit,
so a gain between two values of one unit is dimensionless. Only a kelvin has an offset, so only a temperature's
absolute or difference matters to a conversion; two units that differ only in that, for any other symbol, join as a
difference rather than a conflict.
"""
import generate as g

UNKNOWN = None
CONFLICT = ("conflict", None)
DIMENSIONLESS = ("1", False)
OPS = ("add", "sub", "mul", "div", "sum", "delta")
FAMILIES = ("A", "B", "C", "D", "E", "F", "array")


def canonical(cdl_unit, qkind, inferred=None):
    """The SI unit a declared CDL unit names, as (symbol, delta), or (None, reason) when it names none: a kelvin
    with no quantity, or a unit with no Haystack symbol."""
    if cdl_unit is None:
        return None, "no declared unit"
    if cdl_unit == "K":
        q = g.QUANTITY.get(qkind) or inferred
        if q == "temperature":
            return ("K", False), None
        if q == "temperatureDifferential":
            return ("K", True), None
        return None, "a kelvin with no quantity"
    if cdl_unit in g.NO_HAYSTACK_UNIT:
        return None, "%s has no Haystack symbol" % cdl_unit
    if cdl_unit not in g.XETO_UNIT:
        return None, "%s has no canonical Haystack unit" % cdl_unit
    sym = g.XETO_UNIT[cdl_unit]
    return ((sym, False) if sym else DIMENSIONLESS), None


def seed_unit(text):
    """A rule seed written as text: "1", "K", "ΔK" or a Haystack symbol."""
    if text == "ΔK":
        return ("K", True)
    return (text, False) if text != "1" else DIMENSIONLESS


def cell(op, a, b=None):
    """One arithmetic step on known units: the unit out, or (None, why) when the step gives no unit."""
    (au, ad) = a
    if op == "delta":
        return (au, True), None
    (bu, bd) = b
    if op in ("add", "sum"):
        if au != bu:
            return None, "adds %s to %s" % (au, bu)
        if not ad and not bd:
            if au == "K":
                return None, "adds two absolute temperatures"
            return (au, False), None
        return (au, ad and bd), None
    if op == "sub":
        if au != bu:
            return None, "subtracts %s from %s" % (bu, au)
        if ad and not bd:
            return None, "subtracts an absolute value from a difference"
        # absolute less absolute is a difference, absolute less a difference stays absolute, and a difference
        # less a difference is a difference
        return (au, not (not ad and bd)), None
    if op == "mul":
        if a == DIMENSIONLESS:
            return (None, "scales an absolute temperature") if (bu == "K" and not bd) else (b, None)
        if b == DIMENSIONLESS:
            return (None, "scales an absolute temperature") if (au == "K" and not ad) else (a, None)
        return None, "the product %s·%s has no Haystack symbol" % (au, bu)
    if op == "div":
        if b == DIMENSIONLESS:
            return (None, "scales an absolute temperature") if (au == "K" and not ad) else (a, None)
        if au == bu:
            return DIMENSIONLESS, None
        return None, "the quotient %s/%s has no Haystack symbol" % (au, bu)
    raise ValueError("unknown unit op " + op)


def backward(op, i, other, y):
    """The unit of input `i` of a two-input op, from the other input's unit and the output's (UNKNOWN when not yet
    solved), or None when the arithmetic does not fix it."""
    (ou, od) = other
    if op == "add":
        if y is UNKNOWN:
            return (ou, True) if (ou == "K" and not od) else ((ou, False) if ou != "K" else None)
        (yu, yd) = y
        if yu != ou:
            return None
        if not od and not yd:
            return (ou, True)                          # absolute plus a difference is absolute
        if od and yd:
            return (ou, True)
        if od and not yd:
            return (ou, False)
        return None
    if op == "sub":
        if y is UNKNOWN:
            if ou != "K":
                return (ou, False)
            if i == 0 and not od:
                return (ou, False)                     # a - b, b absolute: a difference less an absolute is invalid
            if i == 1 and od:
                return (ou, True)                      # a - b, a a difference: b must be a difference too
            return None
        (yu, yd) = y
        if yu != ou:
            return None
        if i == 1:                                     # y = a - b, a known
            return (ou, False) if (not od and yd) else ((ou, True) if (not od and not yd) or (od and yd) else None)
        return (ou, False) if (yd and not od) or (not yd and od) else ((ou, True) if (yd and od) else None)
    if y is UNKNOWN:
        return None
    if op == "mul":
        u, _ = cell("div", y, other)
        return u
    if op == "div":
        if i == 0:                                     # y = a / b, b known: a = y * b
            u, _ = cell("mul", y, other)
            return u
        u, _ = cell("div", other, y)                   # b = a / y
        return u
    return None


class Model:
    """Ports, the groups that join them, the seeds and the ops of one composite."""

    def __init__(self):
        self.parent = {}
        self.seeds = []          # (port, unit, why)
        self.ops = []            # (op, [in ports], out port, where)
        self.reasons = {}        # port -> why it has no unit, for a port an op could not type

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def seed(self, port, unit, why):
        self.find(port)
        self.seeds.append((port, unit, why))

    def op(self, op, ins, out, where):
        for x in ins + [out]:
            self.find(x)
        self.ops.append((op, ins, out, where))

    def solve(self):
        """{group root: unknown, a unit, or CONFLICT}, at the least fixpoint."""
        val = {}

        def put(root, u):
            old = val.get(root, UNKNOWN)
            if u is CONFLICT or old is CONFLICT:
                new = CONFLICT
            elif old is UNKNOWN or old == u:
                new = u
            elif old[0] == u[0] and old[0] != "K":
                new = (old[0], old[1] or u[1])         # no offset: absolute and difference convert alike
            else:
                new = CONFLICT
            if new != old:
                val[root] = new
                return True
            return False
        for port, unit, _why in self.seeds:
            put(self.find(port), unit)
        changed = True
        while changed:
            changed = False
            for op, ins, out, where in self.ops:
                vs = [val.get(self.find(x), UNKNOWN) for x in ins]
                if any(v is CONFLICT for v in vs):
                    changed |= put(self.find(out), CONFLICT)
                    continue
                if any(v is UNKNOWN for v in vs):
                    continue
                if op == "delta":
                    u, why = cell("delta", vs[0])
                else:
                    u, why = vs[0], None
                    for v in vs[1:]:
                        if u is None:
                            break
                        u, why = cell(op, u, v)
                if u is None:
                    self.reasons.setdefault(out, why)
                    continue
                changed |= put(self.find(out), u)
            for op, ins, out, where in self.ops:
                if len(ins) != 2:
                    continue
                vs = [val.get(self.find(x), UNKNOWN) for x in ins]
                y = val.get(self.find(out), UNKNOWN)
                for i in (0, 1):
                    if vs[i] is not UNKNOWN or vs[1 - i] in (UNKNOWN, CONFLICT) or y is CONFLICT:
                        continue
                    u = backward(op, i, vs[1 - i], y)
                    if u is not None:
                        changed |= put(self.find(ins[i]), u)
        return val

    def unit_of(self, val, port):
        """(unit, None) or (None, why) for one port after solve."""
        v = val.get(self.find(port), UNKNOWN)
        if v is CONFLICT:
            return None, "its group joins two different units"
        if v is UNKNOWN:
            return None, self.reasons.get(port) or "no declared unit reaches it"
        return v, None


# What each comp wants, read from the hx.comps source hx_comps_index.json was written from:
#   - Number arithmetic (src/core/haystack/fan/Number.fan:319-327 plusUnit, :335-345 minusUnit): K plus K is K, K
#     minus K is K, and K plus ΔK throws UnitErr. Only °F and °C have a delta unit there (Δ°F, Δ°C). So a temperature
#     difference meeting a K signal must itself be written K.
#   - The comparator deadband, CDL h (src/ext/hxComps/fan/logic/ComparisonHys.fan:81-88 isFault): it fits when its
#     unit equals inB's or Number.minusUnit(inB, inB), which is K for K. A ΔK deadband against a K threshold faults,
#     so the deadband is written K and recorded as a difference.
#   - Hysteresis uLow and uHigh (src/ext/hxComps/fan/logic/Hysteresis.fan:70-73 fits): equal units or unitless, no
#     conversion. They are absolute values in the unit of `in`, written K for a temperature, so a °F `in` faults.
#   - Limiter uMax and uMin, and Line's axes (src/xeto/hx.comps/math.xeto:120-160): converted to the unit of `in`,
#     an offset included. An absolute K literal there is right against any temperature unit. A difference would be
#     converted with the offset too, and so come out wrong; none of the 72 Limiter and Line children of the G36 libs
#     at MBL 14.0.0 carries one.
#   - CdlPid k, r, yMax, yMin, xiStart, ydStart and yReset (src/xeto/hx.comps/util.xeto:197-218): Float slots, which
#     carry no unit. r is the error scale, a difference in the unit of u_s; it is recorded in cdlLiteralUnits and
#     cdlLiteralDelta only, and a missed conversion is a departure the comp cannot catch (the RealsPid rows say so).
def written_symbol(unit):
    """The unit suffix a literal is written with on an hx.comps slot, or None for a dimensionless value. A
    temperature is written in K whether it is absolute or a difference: hx.comps takes K minus K as K
    (haystack Number.minusUnit) and refuses K plus ΔK, so a ΔK literal would fault in Add, Subtract and the
    comparator deadbands. Whether it is a difference is recorded beside it in cdlLiteralDelta."""
    if unit is None or unit[0] == "1":
        return None
    return unit[0]
