# mo.py: a small reader for MBL validation models. It takes the component declarations (type, name, array dims,
# modifiers) and the connect equations of one model, enough to rebuild its source network. Not a Modelica parser:
# it refuses what it does not understand rather than guessing.
import re, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

def mo_path(model):
    """'TerminalUnits.CoolingOnly.Validation.Controller' -> the .mo under G36"""
    return os.path.join(paths.mbl(), "Controls/OBC/ASHRAE/G36", *model.split(".")) + ".mo"

def strip_comments(s):
    out = []; i = 0; n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == '\\' else 1
            out.append(s[i:j + 1]); i = j + 1
        elif s.startswith("//", i):
            j = s.find("\n", i); i = n if j < 0 else j
        elif s.startswith("/*", i):
            j = s.find("*/", i); i = n if j < 0 else j + 2
        else:
            out.append(c); i += 1
    return "".join(out)

def split_top(s, sep):
    """split s on sep at paren/brace/bracket depth 0 and outside strings"""
    parts = []; d = 0; cur = []; i = 0; n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == '\\' else 1
            cur.append(s[i:j + 1]); i = j + 1; continue
        if c in "([{": d += 1
        elif c in ")]}": d -= 1
        if c == sep and d == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts

def drop_strings(s):
    return re.sub(r'"(?:[^"\\]|\\.)*"', "", s)

def drop_annotations(s):
    """remove every annotation(...) clause"""
    out = []; i = 0
    while True:
        m = re.search(r"\bannotation\s*\(", s[i:])
        if not m:
            out.append(s[i:]); break
        a = i + m.start(); out.append(s[i:a])
        j = i + m.end(); d = 1
        while d > 0:
            if s[j] == "(": d += 1
            elif s[j] == ")": d -= 1
            elif s[j] == '"':
                j += 1
                while s[j] != '"': j += 2 if s[j] == '\\' else 1
            j += 1
        i = j
    return "".join(out)

class Comp:
    def __init__(self, typ, name, dims, mods):
        self.typ = typ; self.name = name; self.dims = dims; self.mods = mods
    def __repr__(self): return "Comp(%s %s%s %s)" % (self.typ, self.name, self.dims or "", self.mods)

def parse_mods(s):
    """'final a=1, b(c=2)=3, each d=4' -> {a: '1', b: '3', d: '4'} (nested modifiers are refused)"""
    mods = {}
    s = s.strip()
    if not s: return mods
    for item in split_top(s, ","):
        item = drop_strings(item).strip()
        item = re.sub(r"^(final\s+|each\s+|redeclare\s+)+", "", item)
        # a nested modifier with no value (y(unit="K"), a unit or display attribute) sets no parameter
        if re.match(r"^[A-Za-z_]\w*\s*\([^=]*(=[^=]*)*\)$", item) and not re.search(r"\)\s*=", item):
            if not re.search(r"\b(unit|displayUnit|quantity|start|fixed|min|max)\s*=", item):
                raise ValueError("nested modifier not understood: %r" % item)
            continue
        item = re.sub(r"^([A-Za-z_]\w*)\s*\([^()]*\)\s*=", r"\1=", item)
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", item, re.S)
        if not m:
            raise ValueError("modifier not understood: %r" % item)
        mods[m.group(1)] = " ".join(m.group(2).split())
    return mods

def parse(model):
    src = strip_comments(open(mo_path(model), encoding="utf-8").read())
    m = re.search(r"\b(?:model|block)\s+(\w+)", src)
    body = src[m.end():]
    eq = re.search(r"\bequation\b", body)
    decl, eqs = body[:eq.start()], body[eq.end():]
    end = re.search(r"\bend\s+%s\s*;" % m.group(1), eqs)
    eqs = eqs[:end.start()]
    decl = drop_annotations(decl); eqs = drop_annotations(eqs)
    comps = {}; params = {}
    for st in split_top(decl, ";"):
        st = st.strip()
        st = re.sub(r'^"(?:[^"\\]|\\.)*"\s*', "", st)   # the model's own description string
        if not st: continue
        st = re.sub(r"^\s*(final\s+|protected\s+|public\s+)+", "", st)
        pm = re.match(r"^parameter\s+([\w.]+)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*", st)
        if pm:
            rest = st[pm.end():]
            if rest.startswith("("):       # a modifier such as (final unit="K", ...): skip it, balanced
                d = 0
                for j, ch in enumerate(rest):
                    if ch == "(": d += 1
                    elif ch == ")":
                        d -= 1
                        if d == 0: break
                rest = rest[j + 1:]
            rest = drop_strings(rest).strip()
            if not rest.startswith("="): raise ValueError("parameter without a value: %r" % st[:120])
            params[pm.group(2)] = " ".join(rest[1:].split())
            continue
        cm = re.match(r"^([A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*", st)
        if not cm:
            raise ValueError("declaration not understood: %r" % st[:200])
        rest = st[cm.end():].strip()
        mods = ""
        if rest.startswith("("):
            d = 0
            for j, c in enumerate(rest):
                if c == "(": d += 1
                elif c == ")":
                    d -= 1
                    if d == 0: break
            mods = rest[1:j]; rest = rest[j + 1:]
        if drop_strings(rest).strip():
            raise ValueError("trailing text in %s: %r" % (cm.group(2), rest))
        dims = cm.group(3)[1:-1].strip() if cm.group(3) else None
        comps[cm.group(2)] = Comp(cm.group(1), cm.group(2), dims, parse_mods(mods))
    conns = []
    for st in split_top(eqs, ";"):
        st = " ".join(st.split())
        if not st: continue
        cm = re.match(r"^connect\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$", st)
        if not cm:
            raise ValueError("equation not understood: %r" % st)
        conns.append((cm.group(1).replace(" ", ""), cm.group(2).replace(" ", "")))
    return comps, params, conns

# ---- expressions -------------------------------------------------------------------------------------------------

def to_py(expr):
    e = expr
    # a G36 type value is an Integer constant of a Types package (OperationModes, ZoneStates, ...), read from MBL, or
    # an enumeration value, kept as its name
    e = re.sub(r"Buildings\.Controls\.OBC\.ASHRAE\.G36\.Types\.(\w+)\.(\w+)", _g36_type, e)
    e = re.sub(r"Buildings\.Controls\.OBC\.CDL\.Types\.SimpleController\.(\w+)", r"'\1'", e)
    e = re.sub(r"Buildings\.Controls\.OBC\.CDL\.Types\.(\w+)\.(\w+)", r"'\2'", e)
    e = re.sub(r"Buildings\.Controls\.OBC\.CDL\.Constants\.pi", "math.pi", e)
    if "Buildings." in e:
        raise ValueError("unknown reference in %r" % expr)
    # a Modelica array {..} is elementwise in arithmetic (2*{1,3} is {2,6}), so it becomes a numpy array
    e = e.replace("^", "**").replace("{", "_arr([").replace("}", "])")
    e = re.sub(r"\btrue\b", "True", e); e = re.sub(r"\bfalse\b", "False", e)
    e = re.sub(r"\band\b", " and ", e); e = re.sub(r"\bor\b", " or ", e); e = re.sub(r"\bnot\b", " not ", e)
    return e

_intconst = {}
def int_constants(pkg):
    """the Integer constants a G36 Types package declares in Types/<pkg>/package.mo; {} for an enumeration type"""
    if pkg not in _intconst:
        p = os.path.join(paths.mbl(), "Controls/OBC/ASHRAE/G36/Types", pkg, "package.mo")
        d = {}
        if os.path.isfile(p):
            src = strip_comments(open(p, encoding="utf-8").read())
            d = {m.group(1): int(m.group(2)) for m in re.finditer(r"\bconstant\s+Integer\s+(\w+)\s*=\s*(-?\d+)", src)}
        _intconst[pkg] = d
    return _intconst[pkg]

def _g36_type(m):
    c = int_constants(m.group(1))
    if not c: return "'%s'" % m.group(2)
    if m.group(2) not in c: raise ValueError("Types.%s declares no constant %s" % (m.group(1), m.group(2)))
    return str(c[m.group(2)])

def _arr(l):
    import numpy as np
    return np.array(l)

def plain(x):
    """a numpy value as plain JSON-able Python"""
    if hasattr(x, "tolist"): return x.tolist()
    return x

def fill(v, *n):
    if not n: return v
    return [fill(v, *n[1:]) for _ in range(int(n[0]))]

def ev(expr, env):
    # eval of MBL's own model text (from the release fetch_mbl.py checked by SHA-256), with builtins removed
    g = {"math": math, "fill": fill, "__builtins__": {}, "abs": abs, "max": max, "min": min, "_arr": _arr}
    g.update(env)
    return eval(to_py(expr), g)

def eval_params(params):
    env = {}
    pending = dict(params)
    for _ in range(len(pending) + 1):
        for k, v in list(pending.items()):
            try:
                env[k] = ev(v, env); del pending[k]
            except NameError:
                pass
    if pending: raise ValueError("model parameters not evaluable: %s" % pending)
    return env

# ---- block parameter defaults ------------------------------------------------------------------------------------

def block_path(ty):
    """a normalized block type ('CDL.Reals.Sources.Ramp', 'OccupancySchedule') -> its .mo in MBL"""
    if ty == "OccupancySchedule": return os.path.join(paths.mbl(), "Controls/SetPoints/OccupancySchedule.mo")
    if not ty.startswith("CDL."): raise ValueError("no block file for %s" % ty)
    return os.path.join(paths.mbl(), "Controls/OBC", *ty.split(".")) + ".mo"

_defaults = {}
def block_defaults(ty):
    """{name: value} for every parameter the block declares with a default, read from the block's own .mo. A Real
    default is a float. A default that is not a plain expression (one naming another class) is left out."""
    if ty in _defaults: return _defaults[ty]
    src = drop_annotations(strip_comments(open(block_path(ty), encoding="utf-8").read()))
    out = {}
    for st in split_top(src, ";"):
        st = drop_strings(st)
        pm = re.search(r"\bparameter\s+([\w.]+)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*", st)
        if not pm: continue
        rest = st[pm.end():]
        if rest.startswith("("):
            d = 0
            for j, ch in enumerate(rest):
                if ch == "(": d += 1
                elif ch == ")":
                    d -= 1
                    if d == 0: break
            rest = rest[j + 1:]
        rest = rest.strip()
        if not rest.startswith("="): continue
        try: v = ev(" ".join(rest[1:].split()), {})
        except (NameError, ValueError, SyntaxError): continue
        if pm.group(1) == "Real" and not pm.group(3): v = float(v)
        out[pm.group(2)] = v
    _defaults[ty] = out
    return out
