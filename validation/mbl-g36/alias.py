# alias.py: map an internal signal a reference records (conSupFan.staPreSetRes.y) to the cdlPath of the flat comp
# whose `out` carries it. Walks the MBL source: the declared type of each instance on the path, and, where the
# last instance is a composite, the connect that drives the named output connector, until an elementary CDL block.
import re, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mo, paths

def root():
    return os.path.join(paths.mbl(), "Controls/OBC")

def mo_of(typ):
    assert typ.startswith("Buildings.Controls.OBC."), typ
    p = os.path.join(root(), *typ[len("Buildings.Controls.OBC."):].split(".")) + ".mo"
    # MBL writes some connects as connect(gai.y,supTim. u1): close the gap after a dot
    return re.sub(r"\.\s+(?=\w)", ".", mo.strip_comments(open(p, encoding="utf-8").read()))

def type_of(cls_typ, inst):
    src = mo_of(cls_typ)
    m = re.search(r"((?:Buildings\.Controls\.OBC|CDL)\.[\w.]+)\s+%s\b" % re.escape(inst), src)
    if not m: raise ValueError("%s declares no instance %s" % (cls_typ, inst))
    t = m.group(1)
    return t if t.startswith("Buildings.") else "Buildings.Controls.OBC." + t

def driver(cls_typ, port):
    src = mo_of(cls_typ)
    m = re.search(r"connect\(\s*([\w.\[\]]+)\s*,\s*%s\s*\)" % re.escape(port), src) or \
        re.search(r"connect\(\s*%s\s*,\s*([\w.\[\]]+)\s*\)" % re.escape(port), src)
    if not m: raise ValueError("%s: nothing drives %s" % (cls_typ, port))
    return m.group(1)

LINKS = {"Buildings.Controls.OBC.CDL.Conversions.IntegerToReal": "u"}

def is_input(cls_typ, port):
    return re.search(r"Interfaces\.\w+Input\s+%s(?!\w)" % re.escape(port), mo_of(cls_typ)) is not None

def resolve(ctl_typ, sig):
    """ctl_typ: the controller's Modelica type; sig: 'a.b.port'. Returns the flat cdlPath."""
    parts = sig.split(".")
    types = [ctl_typ]; path = []
    for inst in parts[:-1]:
        types.append(type_of(types[-1], inst)); path.append(inst)
    port = parts[-1]
    typ = types[-1]
    # an input connector of a composite carries what its parent connects to it
    if not typ.startswith("Buildings.Controls.OBC.CDL.") and is_input(typ, port):
        parent = types[-2]; me = path[-1]
        src = mo_of(parent)
        m = re.search(r"connect\(\s*([\w.\[\]]+)\s*,\s*%s\.%s\s*\)" % (re.escape(me), re.escape(port)), src) or             re.search(r"connect\(\s*%s\.%s\s*,\s*([\w.\[\]]+)\s*\)" % (re.escape(me), re.escape(port)), src)
        if not m or "." not in m.group(1): raise ValueError("%s.%s: no instance drives it in %s" % (me, port, parent))
        return resolve(ctl_typ, ".".join(path[:-1] + [m.group(1)]))
    # an input of an elementary block carries what its parent connects to it
    if typ.startswith("Buildings.Controls.OBC.CDL.") and is_input(typ, port):
        parent = types[-2]; me = path[-1]
        src = mo_of(parent)
        m = re.search(r"connect\(\s*([\w.\[\]]+)\s*,\s*%s\.%s\s*\)" % (re.escape(me), re.escape(port)), src) or             re.search(r"connect\(\s*%s\.%s\s*,\s*([\w.\[\]]+)\s*\)" % (re.escape(me), re.escape(port)), src)
        if not m or "." not in m.group(1): raise ValueError("%s.%s: no instance drives it in %s" % (me, port, parent))
        return resolve(ctl_typ, ".".join(path[:-1] + [m.group(1)]))
    while not typ.startswith("Buildings.Controls.OBC.CDL."):
        d = driver(typ, port)
        if "." not in d: raise ValueError("%s.%s is driven by the connector %s" % (".".join(path), port, d))
        inst, port = d.split(".", 1)
        typ = type_of(typ, inst); path.append(inst)
    if typ in LINKS:
        raise ValueError("%s is a link class" % typ)
    return ".".join(path)

if __name__ == "__main__":
    print(resolve(sys.argv[1], sys.argv[2]))
