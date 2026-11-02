"""Read modelica-json's json output for what its CXF drops.

CXF (modelica-json 5460add3) writes no type for a parameter typed by an enumeration, and drops every Dialog and
__cdl annotation. The json output keeps all three. This module reads, for each declaration of each pinned G36 class:

- its type specifier, so an enumeration-typed parameter with no default gets its type;
- Dialog(enable, group, tab): the MBL author's statement of when a parameter applies and where a form shows it;
  the enable expression tree is rendered back to the CDL expression text both evaluators parse;
- __cdl(ValueInReference): whether a parameter's value is part of MBL's reference results.

The pinned copies are pruned to these annotations (cxf.py JSON_ANNOTATIONS). Every shape this reader does not know
refuses with the class, the declaration and the shape, never silently: a guessed enable gate would show a
configurator question that does not apply, or hide one that does.
"""
import json
import re

from cxf import CxfError


class Decl:
    """One declaration of a class, as the json output gives it."""

    def __init__(self, name, type_, prefix, protected, final=False):
        self.name, self.type, self.prefix, self.protected, self.final = name, type_, prefix, protected, final
        self.enable = self.group = self.tab = self.value_in_reference = None
        self.unit = self.quantity = self.displayUnit = None     # Modelica text, e.g. "K"; fill("K", n) on an array reads as "K"


def class_path(doc):
    """The class a json output defines: `within` plus the identifier of its one stored class."""
    defs = doc.get("stored_class_definitions") or []
    if len(defs) != 1:
        raise CxfError("a json output with %d class definitions; one is read" % len(defs))
    spec = defs[0]["class_specifier"]
    ident = (spec.get("long_class_specifier") or spec.get("short_class_specifier") or {}).get("identifier")
    if not ident:
        raise CxfError("a json output whose class has no identifier: %s" % sorted(spec))
    return (doc["within"] + "." if doc.get("within") else "") + ident


def _elements(defn):
    """(element, protected) for every element of a long class definition, public and protected."""
    comp = (defn["class_specifier"].get("long_class_specifier") or {}).get("composition") or {}
    out = [(e, False) for e in comp.get("element_list", [])]
    for sec in comp.get("element_sections", []):
        out += [(e, False) for e in sec.get("public_element_list", [])]
        out += [(e, True) for e in sec.get("protected_element_list", [])]
    return out


def read(doc):
    """Declaration name -> Decl for one json output. Refuses an annotation shape it does not know."""
    path = class_path(doc)
    out = {}
    for el, protected in _elements(doc["stored_class_definitions"][0]):
        cc = el.get("component_clause")
        if cc is None:
            continue                       # an import or extends clause; CXF reads those, or refuses them
        for comp in cc.get("component_list", []):
            name = comp["declaration"]["identifier"]
            # `final parameter` sits on the element, not the clause; CXF drops it on a protected parameter.
            d = Decl(name, cc.get("type_specifier"), cc.get("type_prefix"), protected, el.get("final") is True)
            _attrs(path, d, comp["declaration"].get("modification") or {})
            for a in ((comp.get("description") or {}).get("annotation") or []):
                em = (a.get("element_modification_or_replaceable") or {}).get("element_modification") or {}
                if em.get("name") == "Dialog":
                    _dialog(path, d, em)
                elif em.get("name") == "__cdl":
                    _cdl(path, d, em)
            out[name] = d
    return out


def _attrs(path, d, mod):
    """unit and quantity from a declaration's own modification, as written: a string literal, or fill(literal, n)
    for an array (CXF drops the unit of an array connector; the round trip checks it against MBL)."""
    for cm in mod.get("class_modification", []):
        e = (cm.get("element_modification_or_replaceable") or {}).get("element_modification") or {}
        if e.get("name") not in ("unit", "quantity", "displayUnit"):
            continue
        ex = ((e.get("modification") or {}).get("expression") or {}).get("simple_expression")
        if isinstance(ex, dict) and set(ex) == {"function_call"} and ex["function_call"].get("name") == "fill":
            args = ex["function_call"].get("arguments") or []
            ex = args[0].get("name") if args and isinstance(args[0], dict) else None
        setattr(d, e["name"], _string(ex, "%s.%s %s" % (path, d.name, e["name"])))


def _subs(path, d, em):
    for cm in (em.get("modification") or {}).get("class_modification", []):
        e = (cm.get("element_modification_or_replaceable") or {}).get("element_modification") or {}
        mod = e.get("modification") or {}
        if not mod.get("equal") or "expression" not in mod:
            raise CxfError("%s.%s: %s(%s) is not `name = expression`" % (path, d.name, em["name"], e.get("name")))
        yield e.get("name"), mod["expression"].get("simple_expression")


def _dialog(path, d, em):
    for key, ex in _subs(path, d, em):
        if key == "enable":
            d.enable = render(ex, "%s.%s" % (path, d.name))
        elif key in ("group", "tab"):
            setattr(d, key, _string(ex, "%s.%s Dialog(%s)" % (path, d.name, key)))
        else:
            raise CxfError("%s.%s: Dialog(%s) is not read (enable, group and tab are)" % (path, d.name, key))


def _cdl(path, d, em):
    for key, ex in _subs(path, d, em):
        if key != "ValueInReference" or ex not in ("true", "false"):
            raise CxfError("%s.%s: __cdl(%s = %s) is not read (ValueInReference = true or false is)"
                           % (path, d.name, key, ex))
        d.value_in_reference = ex == "true"


def _string(ex, where):
    if not (isinstance(ex, str) and len(ex) >= 2 and ex[0] == ex[-1] == '"'):
        raise CxfError("%s: %r is not a string literal" % (where, ex))
    return json.loads(ex)


# ---- the enable expression, rendered to the CDL expression text CdlExprParser and cxf.evaluate read ----

def render(ex, where):
    """The text of a simple_expression: a string as modelica-json wrote it, or a logical expression tree."""
    if isinstance(ex, str):
        # A plain expression as modelica-json wrote it: only names, enum literals, not, and, or, the relations,
        # parentheses and Boolean or number literals, the forms both evaluators parse.
        toks = re.findall(r"==|<>|<=|>=|[<>()]|[A-Za-z_][A-Za-z0-9_.]*|[0-9.eE+-]+|\S", ex)
        call = re.search(r"(?<![\w.])(?!(?:not|and|or)\b)[A-Za-z_][A-Za-z0-9_.]*\s*\(", ex)    # f(x); not (a) is fine
        allowed = r"==|<>|<=|>=|[<>()]|[A-Za-z_][A-Za-z0-9_.]*|[0-9][0-9.eE+-]*"
        if call or not all(re.fullmatch(allowed, t) for t in toks):
            raise CxfError("%s: Dialog(enable) text %r holds a token the evaluators do not read" % (where, ex))
        return ex.strip()
    if isinstance(ex, dict) and set(ex) == {"logical_expression"}:
        return _or(ex["logical_expression"], where)
    raise CxfError("%s: Dialog(enable) expression of shape %s is not read" % (where, _shape(ex)))


def _or(le, where):
    if set(le) != {"logical_or"}:
        raise CxfError("%s: logical expression of shape %s is not read" % (where, _shape(le)))
    return " or ".join(_and(a, where) for a in le["logical_or"])


def _and(a, where):
    if set(a) != {"logical_and"}:
        raise CxfError("%s: logical term of shape %s is not read" % (where, _shape(a)))
    return " and ".join(_factor(f, where) for f in a["logical_and"])


def _factor(f, where):
    if not set(f) <= {"arithmetic_expressions", "relation_operator", "not"}:
        raise CxfError("%s: logical factor of shape %s is not read" % (where, _shape(f)))
    ae = f["arithmetic_expressions"]
    op = f.get("relation_operator")
    if op is None and len(ae) != 1 or op is not None and len(ae) != 2:
        raise CxfError("%s: %d operands for relation %s" % (where, len(ae), op))
    if op is not None and op not in ("==", "<>", "<", "<=", ">", ">="):
        raise CxfError("%s: relation %s is not read" % (where, op))
    text = (" %s " % op).join(_arith(x, where) for x in ae) if op else _arith(ae[0], where)
    return ("not " if f.get("not") else "") + text


def _arith(x, where):
    """One operand: a name or literal as text, or a parenthesized sub-expression."""
    if isinstance(x, str):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*|[-+]?[0-9.eE+-]+|true|false", x.strip()):
            raise CxfError("%s: operand %r is not a name or a literal" % (where, x))
        return x.strip()
    # Explicit checks, not assert, which python -O strips.
    ok = isinstance(x, dict) and set(x) == {"terms"} and isinstance(x["terms"], list) and len(x["terms"]) == 1
    t = x["terms"][0] if ok else None
    ok = ok and isinstance(t, dict) and set(t) == {"factors"} and len(t["factors"]) == 1
    fa = t["factors"][0] if ok else None
    ok = ok and isinstance(fa, dict) and set(fa) == {"primary1"} and len(fa["primary1"]) == 1
    pr = fa["primary1"][0] if ok else None
    ok = ok and isinstance(pr, dict) and set(pr) == {"simple_expression"}
    if not ok:
        raise CxfError("%s: operand of shape %s is not read" % (where, _shape(x)))
    return "(" + render(pr["simple_expression"], where) + ")"


def _shape(v, depth=2):
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (k, _shape(x, depth - 1) if depth else "...") for k, x in sorted(v.items())) + "}"
    if isinstance(v, list):
        return "[%d items]" % len(v)
    return type(v).__name__
