#!/usr/bin/env python3
#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""The CDL class-to-comp table: check it and write class-map.json.

  python -X utf8 src/gen/classmap.py              # check the table and rewrite src/gen/class-map.json
  python -X utf8 src/gen/classmap.py --out DIR    # write class-map.json to DIR

The table is hand-entered in classmap_table.py. Each of kw.cdl's 132 elementary classes is graded against the hx.comps
comp that runs it. The CDL side is read from the pinned CXF through generate.load_classes. The hx.comps side is read
from hx_comps_index.json, which hx_comps_index.py writes from the hx.comps Xeto source. The check refuses the table
unless every connector and parameter is mapped and every named slot exists. Nothing is written when a check fails.
"""
import argparse
import json
import pathlib
import re
import sys
from collections import Counter, OrderedDict

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cxf  # noqa: E402
import generate  # noqa: E402
from classmap_table import T  # noqa: E402

HX_INDEX = HERE / "hx_comps_index.json"
CLASS_MAP = HERE / "class-map.json"
BRANCH = 'haxall with pull requests #138 to #152 applied, src/xeto/hx.comps/'
COMMON = OrderedDict([
 ('null', 'CDL values are never null and carry no status. Every hx.comps comp has its own null and status rule, given among its departures. A G36 sequence sees the difference only when an input point is null, stale or faulted.'),
 ('unary', 'UnaryMath: a null `inA` gives null `out`. An invalid `inA` is still computed and its status is copied to `out` (UnaryMath.fan onExecute).'),
 ('binary', 'BinaryMath: a null input gives null `out`. An invalid input gives NaN with the merged status. A unit error gives NaN with fault (BinaryMath.fan onExecute).'),
 ('quad', 'QuadMath computes from the valid inputs and skips a null or invalid one. Fewer valid inputs than the comp needs give null `out`. Otherwise `out` merges the status of every input, valid or not, so an invalid status propagates as the spec doc says (QuadMath.fan:55-60, a bitwise OR in Status.fan:264; math.xeto:83-85). A unit error adds fault.'),
 ('quadLogic', 'QuadLogic computes from the valid inputs and skips a null or invalid one. Fewer non-null inputs than the comp needs give null `out`. Otherwise `out` merges the status of every input, so an invalid status propagates as the spec doc says (QuadLogic.fan:53-58, a bitwise OR in Status.fan:264; logic.xeto:20-22).'),
 ('compare', 'Comparison: a null input gives null `out`. An invalid input gives false with the merged status. Mismatched units give false with fault (Comparison.fan onExecute).'),
 ('equalUnit', 'Equal is false when the two inputs carry different non-null units (Comparison.fan Equal.eq). CDL Integers carry none, so an Integer that picked up a unit upstream compares unequal.'),
 ('switch', 'ValSwitch: a null `inSwitch` gives null `out`. An invalid `inSwitch` holds the last `out` (Switch.fan ValSwitch.onExecute).'),
 ('transientFeed', 'The target slot is transient, so a fixed value must arrive on a linked NumberConst. A value set on a transient slot is not saved (logic.xeto:75-76).'),
 ('nullHold', 'A null input gives null outputs and an invalid input holds them with the merged status, keeping the state (cited in the comp doc).'),
 ('ownClock', 'Timed comps see time only at executes, so an event resolves on the first execute at or after it. A step of the clock backward counts as no time. State is not persisted and restarts from initial values after a task rebuild.'),
 ('sampleGrid', 'Instants sit on a grid of whole periods from 1 Jan 1970 UTC, so a period of 1day aligns to 00:00 UTC, not local midnight (sampling.xeto:10-13). A period shorter than the cycle cannot be met.'),
 ('noDefaultPeriod', 'CDL `samplePeriod` has no default. The comp defaults `period` to 1min (sampling.xeto:62, 124).'),
 ('triggered', 'TriggeredComp reads the rise of `trigger` on execute. A `trigger` true on consecutive executes is one rise. A null input gives null `out` and an invalid input holds `out`. A rise while `in` is null, invalid or NaN takes no sample (triggered.xeto:9-21).'),
 ('pulseOneExecute', 'CDL gives a true output at the event instant only. The comp holds it true for one execute and clears it on the next cycle (logic.xeto:132-135).'),
 ('stall', 'The comp executes every cycle and steps on its own CycleClock. A step longer than both 1min and 10 times the longest of the last 8 steps is a stall or a gap. Results depend on the cycle length.'),
 ('roundRules', 'Round: a null `in` gives null `out` and an invalid `in` gives NaN with its status (math.xeto:187-188).'),
])
NULL_IS_CDL_DEFAULT = {('RealsLimitSlewRate', 'fallingSlewRate'), ('RealsLimitSlewRate', 'Td'), ('RealsRamp', 'fallingSlewRate'),
                       ('IntegersStage', 'h'), ('LogicalVariablePulse', 'minTruFalHol')}
NULL_READS = {('RealsRamp', 'Td'): 'raisingSlewRate*10 (continuous.xeto:104-105)'}
GRADES = ['native', 'nativeParams', 'const', 'link', 'composite', 'compileTime', 'array', 'none']
# Every conversion label the table may write, with the code the generator acts on. None: the value rides unchanged
# (a CDL Integer on a StatusNumber is a whole Number). A label outside this table refuses, so a misspelt conversion
# cannot drop out of the generated library.
CONVERT = {
    'Real seconds to Duration (n sec)': 'sec',
    'Real to Float': 'float',
    'Integer to Int': 'int',
    'TypesSimpleController key to PidControllerType: P->p, PI->pi, PD->pd, PID->pid': 'enum P=p PI=pi PD=pd PID=pid',
    'Integer to StatusNumber on NumberConst.out': None,
    'Integer to Number': None,
    'Integer to StatusNumber {val, status ok}': None,
    'Real to StatusNumber {val, status ok}': None,
    'Boolean to StatusBool {val, status ok}': None,
}
NUMERIC = ('Real', 'Integer')
STATUS = {'Real': ('StatusNumber?', 'StatusNumber'), 'Integer': ('StatusNumber?', 'StatusNumber'),
          'Boolean': ('StatusBool?', 'StatusBool')}
# A connector reached through a feed: the feed's spec, the CDL types it carries, and the comp slot types it fits
VIA = {'hx.comps::StatusNumberToNumber': (NUMERIC, ('Number',)), 'hx.comps::StatusBoolToBool': (('Boolean',), ('Bool',))}
# A parameter set directly on a slot, by conversion code: the CDL types it takes and the comp slot types it fits
SET = {'sec': (('Real',), ('Duration',)), 'float': (('Real',), ('Float',)), 'int': (('Integer',), ('Int',)),
       None: {'Real': ('Number', 'Number?'), 'Integer': ('Number', 'Number?'), 'Boolean': ('Bool',), 'String': ('Str',)}}
FEED = {'hx.comps::NumberConst': NUMERIC, 'hx.comps::BoolConst': ('Boolean',)}
DURATION = re.compile(r'^-?\d+(\.\d+)?(ns|ms|sec|min|hr|day)$')


def slot_fits(cdl_type, kind, slot_type, feed=None, via=None, code=None, enum_slot=False, const=False):
    """None when a CDL connector or parameter fits the comp slot it maps to, else the reason it does not. A maybe slot
    fits what its plain type fits. `const` marks the parameter of a constant class, which sets the comp's output."""
    slot_type = slot_type.rstrip('?')
    if const:
        types, slots = tuple(STATUS), tuple(x for x in STATUS.get(cdl_type, ()) if not x.endswith('?'))
    elif via is not None:
        if via not in VIA:
            return 'no feed rule for %s' % via
        types, slots = VIA[via]
    elif kind in ('input', 'output'):
        types, slots = tuple(STATUS), STATUS.get(cdl_type, ())
    elif feed is not None and feed != 'set':
        types, slots = FEED.get(feed, ()), ('StatusNumber?', 'StatusNumber') if feed == 'hx.comps::NumberConst' else ('StatusBool?', 'StatusBool')
    elif code is not None and code.startswith('enum'):
        return None if (cdl_type not in generate.XETO_TYPE and enum_slot) else 'an enum conversion needs a CDL enum and an hx.comps enum slot'
    elif code in SET:
        types, slots = SET[code] if code is not None else (tuple(SET[None]), SET[None].get(cdl_type, ()))
    else:
        return 'no rule for conversion %s' % code
    if cdl_type not in types or slot_type not in slots:
        return 'CDL %s does not fit slot type %s' % (cdl_type, slot_type)
    return None


REQUIRES = ('linkAlways', 'loopCut', 'whenNull', 'writeWhenUnit', 'compoundGain')
# A note about the table or the generator, not about what a sequence sees.
NOT_BEHAVIOUR = ("generator", "requires.", "this table's rules", "may also grade", "so the mapping is", "has no behavior",
                 "stays unlinked")
AGREES = re.compile(r"\bas (?:MBL|CDL)\b")
DIFFERS = re.compile(r"\b(?:where|not|unlike|differ|instead|rejects|warns|lacks|ignores|only|depends|steps)\b")


CITES = re.compile(r"\.xeto|\.fan|\.mo\b|\.md\b|PR C\d|GAP|[A-Za-z]:\d")


def published(text):
    """A note as published text: each outermost parenthetical that cites a source dropped, nested parentheses
    included (`(UnaryMath.fan `Number(a.toFloat.asin)` and peers)`)."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "(":
            depth, j = 0, i
            while j < len(text):
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                if depth == 0:
                    break
                j += 1
            group = text[i:j + 1]
            if CITES.search(group):
                while out and out[-1] == " ":
                    out.pop()
                i = j + 1
                continue
            out.append(group)
            i = j + 1
            continue
        out.append(text[i])
        i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def departures_of(t, common):
    """Every way the comp behaves that MBL does not define or defines otherwise, as the row's notes record them: its
    stated departures, then each semantic note that does not merely agree with MBL and is not about the generator,
    then each shared note the row names. Citations are dropped from the published text."""
    out = [published(d) for d in t.get('departures', [])]
    for s in t['sem']:
        if any(w in s for w in NOT_BEHAVIOUR):
            continue
        if AGREES.search(s) and not DIFFERS.search(s):
            continue
        out.append(published(s))
    for k in t['common'] + (['null'] if t['grade'] in ('native', 'nativeParams') else []):
        out.append(published(common[k]))
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def unit_rule_violations(name, t, c):
    """Every way a row's unitRule names something the unit pass cannot act on: no rule on a class that runs, a
    family or an op it does not know, an op with no inputs or output, a name the class does not have, or a seed it
    cannot read."""
    import units
    r = t.get('unitRule')
    if r is None:
        return [] if t['grade'] == 'none' else ['%s: no unitRule; every class that runs needs one' % name]
    out, names = [], set(c['slots'])
    if r['family'] not in units.FAMILIES:
        out.append('%s: unitRule family %r is not one of %s' % (name, r['family'], units.FAMILIES))
    if r['op'] is not None and (r['op'] not in units.OPS or not r['ins'] or not r['out']):
        out.append('%s: unitRule op %r needs a known op, inputs and an output' % (name, r['op']))
    used = [n for k in r['keep'] for n in k] + list(r['ins']) + ([r['out']] if r['out'] else []) + list(r['seeds'])
    for n in used:
        if n not in names:
            out.append('%s: unitRule names %s, which the class does not have' % (name, n))
    for n, u in r['seeds'].items():
        if not isinstance(u, str) or not u:
            out.append('%s: unitRule seed %s=%r is no unit' % (name, n, u))
    return out


def compose_violations(name, t, c, cdl, table):
    """Every way a composite row names an instance, a binding or a connection that does not exist, or a class no
    comp runs; binds a value that names something other than the composite's own parameters; wires a connection
    from a sink or into a source; or leaves a composite output or an instance input undriven, or driven twice."""
    params_own = {k for k, s in c['slots'].items() if s['kind'] == 'param'}
    # A source is a composite input or an instance output; a sink is a composite output or an instance input.
    out, ends = [], {k: ('source' if s['kind'] == 'input' else 'sink') for k, s in c['slots'].items()
                     if s['kind'] in ('input', 'output')}
    if t['comp'] != 'kw.cdl::' + name:
        out.append('%s: a composite runs as kw.cdl::%s, not %s' % (name, name, t['comp']))
    for iname, cls, binds in t['compose']['insts']:
        sub = generate.spec_name(generate.CDL_PREFIX + cls, generate.CDL_PREFIX)
        if sub not in cdl:
            out.append('%s: instance %s of %s, which is no CDL elementary class' % (name, iname, cls))
            continue
        if table[sub]['grade'] not in ('native', 'nativeParams', 'const'):
            out.append('%s: instance %s of %s, graded %s, which no comp runs' % (name, iname, sub, table[sub]['grade']))
        params = {k for k, s in cdl[sub]['slots'].items() if s['kind'] == 'param'}
        for k, v in binds.items():
            if k not in params:
                out.append('%s: instance %s binds %s, which %s does not have' % (name, iname, k, sub))
            if isinstance(v, str):
                stray = [n for n in cxf.names(v) if n not in params_own]
                if stray:
                    out.append('%s: instance %s binds %s to %r, which names %s, no parameter of %s'
                               % (name, iname, k, v, ', '.join(stray), name))
        for k, s in cdl[sub]['slots'].items():
            if s['kind'] in ('input', 'output'):
                ends[iname + '.' + k] = 'sink' if s['kind'] == 'input' else 'source'
    driven = {}
    for a, b in t['compose']['edges']:
        for x, want in ((a, 'source'), (b, 'sink')):
            if x not in ends:
                out.append('%s: connection end %s names nothing' % (name, x))
            elif ends[x] != want:
                out.append('%s: connection %s -> %s runs %s %s, a %s' % (name, a, b, 'from' if want == 'source'
                                                                      else 'into', x, ends[x]))
        driven[b] = driven.get(b, 0) + 1
    for x, role in sorted(ends.items()):
        if role == 'sink' and driven.get(x, 0) != 1:
            out.append('%s: %s is driven %d times; each composite output and instance input is driven once'
                       % (name, x, driven.get(x, 0)))
    return out


def requires_violations(name, t, c, cslots, hx):
    """Every way a row's `requires` names something the generator cannot act on."""
    out, req = [], t.get('requires', {})
    inputs = {k for k, s in c['slots'].items() if s['kind'] == 'input'}
    for key in req:
        if key not in REQUIRES:
            out.append('%s: requires.%s is not a requirement the generator reads %s' % (name, key, REQUIRES))
    for k, v in req.get('linkAlways', {}).items():
        m = t['connectors'].get(k)
        if k not in inputs or not isinstance(m, str):
            out.append('%s: requires.linkAlways.%s names no CDL input on a comp slot' % (name, k))
        elif not isinstance(v, bool) or c['slots'][k]['cdlType'] != 'Boolean':
            out.append('%s: requires.linkAlways.%s: %r is not a value of CDL %s' % (name, k, v, c['slots'][k]['cdlType']))
    for k in req.get('writeWhenUnit', []):
        if k not in t['params'] or t['params'][k].get('feed') != 'set':
            out.append('%s: requires.writeWhenUnit names %s, which is no parameter set on a slot' % (name, k))
    cg = req.get('compoundGain')
    if cg is not None:
        comp = hx.get(cg.get('comp', '').split('::')[-1])
        names = list(cg.get('connectors', {}).values()) + [cg.get('gain'), cg.get('per')] + list(cg.get('zero', [])) \
            + list(cg.get('fixed', {}))
        if comp is None:
            out.append('%s: requires.compoundGain.comp %s is no hx.comps comp' % (name, cg.get('comp')))
        else:
            for s in names:
                if s not in comp['slots']:
                    out.append('%s: requires.compoundGain names %s, which is no slot of %s' % (name, s, cg['comp']))
        if cg.get('perGroup') not in cg.get('connectors', {}):
            out.append('%s: requires.compoundGain.perGroup %s names no CDL connector it maps' % (name, cg.get('perGroup')))
        if sorted(cg.get('connectors', {})) != sorted(k for k, v in t['connectors'].items() if isinstance(v, str)):
            out.append('%s: requires.compoundGain must map the same CDL connectors as the row' % name)
    for k in req.get('loopCut', []):
        if k not in inputs:
            out.append('%s: requires.loopCut names %s, which is no CDL input' % (name, k))
    for k, v in req.get('whenNull', {}).items():
        m = t['connectors'].get(k)
        via = m.get('via') if isinstance(m, dict) else None
        if k not in inputs or via is None:
            out.append('%s: requires.whenNull.%s names no CDL input reached through a feed' % (name, k))
        elif 'whenNull' not in hx[via.split('::')[1]]['slots']:
            out.append('%s: requires.whenNull.%s: the feed %s has no whenNull slot' % (name, k, via))
        elif fixed_fits(v, hx[via.split('::')[1]]['slots']['whenNull']['type'], None):
            out.append('%s: requires.whenNull.%s: %s' % (name, k, fixed_fits(v, hx[via.split('::')[1]]['slots']['whenNull']['type'], None)))
    return out


def fixed_fits(value, slot_type, items):
    """None when a fixed value has the comp slot's type, else the reason it does not."""
    t = slot_type.rstrip('?')
    if items is not None:
        return None if value in items else '%r is not an item of %s %s' % (value, t, items)
    ok = {'Int': lambda v: isinstance(v, int) and not isinstance(v, bool),
          'Number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          'Float': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          'Bool': lambda v: isinstance(v, bool),
          'Str': lambda v: isinstance(v, str),
          'Duration': lambda v: isinstance(v, str) and bool(DURATION.match(v))}.get(t)
    if ok is None:
        return 'no rule for a fixed %s' % t
    return None if ok(value) else '%r is not a %s' % (value, t)


def cdl_slots(classes):
    """kw.cdl's elementary classes as the table reads them: spec name -> {cdlClass, slots}, where each slot is a CDL
    connector or parameter with its kind, CDL type, default and unit, in declaration order. A parameter's `default` is
    the value its generated slot carries (a literal, or the item of a bare enum literal) and `cdlDefault` the
    expression it keeps otherwise, as emit_param writes them."""
    out = {}
    for path in sorted(p for p in classes if p in generate.CLAUSE7):
        ci = classes[path]
        slots, n = OrderedDict(), 0
        for p in ci.params:
            dflt, cdef = None, None
            if p.val is not None:
                dflt = generate.fmt_num(p.val)
            elif p.expr is not None:
                if p.dtype not in generate.XETO_TYPE and p.raw_size is None and re.fullmatch(r"[A-Za-z_][\w.]*", p.expr.strip()) \
                        and p.expr.rsplit(".", 1)[0].endswith(p.dtype.rsplit(".", 1)[1]):
                    dflt = p.expr.rsplit(".", 1)[1]
                else:
                    cdef = p.expr
            ctype = p.dtype if p.dtype in generate.XETO_TYPE else generate.spec_ref(p.dtype)
            slots[p.name] = {'kind': 'param', 'cdlType': ctype, 'default': dflt, 'cdlDefault': cdef,
                             'array': p.raw_size is not None, 'line': n, 'unit': p.unit}
            n += 1
        for c in ci.conns:
            slots[c.name] = {'kind': 'input' if c.direction == 'in' else 'output', 'cdlType': c.dtype, 'default': None,
                             'cdlDefault': None, 'array': c.raw_size is not None, 'line': n, 'unit': c.unit}
            n += 1
        out[generate.spec_name(path, generate.CDL_PREFIX)] = {'cdlClass': path, 'slots': slots}
    return out


def g36_counts(classes):
    """CDL class path -> how many instances of it the G36 composites hold, read from the pinned CXF."""
    return Counter(i.cls for p, c in classes.items() if p.startswith(generate.G36_PREFIX) for i in c.insts)


def hx_index():
    return json.loads(HX_INDEX.read_text(encoding="utf-8"))


def build(classes, table=None, hx=None):
    """(doc, errors): the class map as class-map.json holds it, and every check that failed."""
    table = T if table is None else table
    hx = hx_index() if hx is None else hx
    cdl = cdl_slots(classes)
    counts = g36_counts(classes)

    def hx_type(comp, slot):
        return hx[comp.split('::')[1]]['slots'][slot]['type']

    def hx_default(comp, slot):
        raw = hx[comp.split('::')[1]]['slots'][slot]['raw']
        rest = re.sub(r'^\w+:\s*[\w:?]+\s*', '', raw)
        rest = re.sub(r'^<[^>]*>\s*', '', rest).strip()
        return rest.strip('"') if rest else None

    def hx_loc(comp, slot=None):
        c = hx[comp.split('::')[1]]
        if slot is None:
            return '%s:%d' % (c['file'], c['line'])
        s = c['slots'][slot]
        return '%s:%d' % (s['file'], s['line'])

    errors = []
    if set(table) != set(cdl):
        errors.append('table and kw.cdl differ: %s' % sorted(set(table) ^ set(cdl)))
        return None, errors
    classes_out = OrderedDict()
    for name in sorted(cdl):
        t = table[name]; c = cdl[name]; g = t['grade']
        if g not in GRADES:
            errors.append('%s: unknown grade %s' % (name, g))
            continue
        is_array = any(s['array'] for s in c['slots'].values())
        if is_array != (g == 'array'):
            errors.append('%s: array mismatch' % name)
        e = OrderedDict()
        e['cdlClass'] = c['cdlClass']
        e['grade'] = g
        e['comp'] = t['comp']
        conns = OrderedDict(); params = OrderedDict(); typeNotes = []; sem = list(t['sem'])
        defaultsToWrite = OrderedDict()
        if g in ('native', 'nativeParams', 'const'):
            comp = t['comp']
            if comp.split('::')[1] not in hx:
                errors.append('%s: no comp %s' % (name, comp))
                continue
            cslots = hx[comp.split('::')[1]]['slots']
            cdl_conn = {k for k, s in c['slots'].items() if s['kind'] in ('input', 'output')}
            cdl_par = {k for k, s in c['slots'].items() if s['kind'] == 'param'}
            if set(t['connectors']) != cdl_conn:
                errors.append('%s: connectors %s vs CDL %s' % (name, sorted(t['connectors']), sorted(cdl_conn)))
            if set(t['params']) != cdl_par:
                errors.append('%s: params %s vs CDL %s' % (name, sorted(t['params']), sorted(cdl_par)))
            for k in sorted((k for k in t['connectors'] if k in c['slots']), key=lambda k: c['slots'][k]['line']):
                v = t['connectors'][k]; s = c['slots'][k]
                slot = v if isinstance(v, str) else v['slot']
                if slot not in cslots:
                    errors.append('%s: comp %s has no slot %s' % (name, comp, slot)); continue
                why = slot_fits(s['cdlType'], s['kind'], hx_type(comp, slot), via=v['via'] if isinstance(v, dict) else None)
                if why:
                    errors.append('%s: connector %s -> %s: %s' % (name, k, slot, why))
                if isinstance(v, dict):
                    via = v['via'].split('::')[1]
                    if via not in hx:
                        errors.append('%s: no via comp %s' % (name, via))
                    conns[k] = OrderedDict([('slot', slot), ('via', v['via']), ('slotType', hx_type(comp, slot)), ('at', hx_loc(comp, slot))])
                else:
                    conns[k] = slot
                typeNotes.append('%s %s (CDL %s%s) -> %s %s' % (s['kind'], k, s['cdlType'], (', ' + s['unit']) if s['unit'] else '', slot, hx_type(comp, slot)))
            for k in sorted((k for k in t['params'] if k in c['slots']), key=lambda k: c['slots'][k]['line']):
                v = t['params'][k]; s = c['slots'][k]; slot = v['slot']
                if slot not in cslots:
                    errors.append('%s: comp %s has no slot %s' % (name, comp, slot)); continue
                feed = v['feed']
                if feed != 'set' and feed.split('::')[1] not in hx:
                    errors.append('%s: no feed comp %s' % (name, feed))
                cdef = s['default'] if s['default'] is not None else s['cdlDefault']
                hdef = hx_default(comp, slot) if feed == 'set' else None
                p = OrderedDict([('slot', slot), ('feed', feed), ('slotType', hx_type(comp, slot) if feed == 'set' else 'StatusNumber? on %s.out, linked to %s %s' % (feed, slot, hx_type(comp, slot)))])
                if 'convert' in v:
                    p['convert'] = v['convert']
                    if v['convert'] not in CONVERT:
                        errors.append('%s: param %s: unknown conversion %r' % (name, k, v['convert']))
                code = CONVERT.get(v.get('convert'))
                stype = hx_type(comp, slot)
                why = slot_fits(s['cdlType'], 'param', stype, feed=feed, code=code,
                                enum_slot='items' in hx.get(stype.rstrip('?'), {}), const=g == 'const')
                if why:
                    errors.append('%s: param %s -> %s: %s' % (name, k, slot, why))
                p['cdlDefault'] = cdef
                p['compDefault'] = hdef
                p['at'] = hx_loc(comp, slot)
                params[k] = p
                typeNotes.append('param %s (CDL %s%s) -> %s %s via %s' % (k, s['cdlType'], (', ' + s['unit']) if s['unit'] else '', slot, hx_type(comp, slot), feed))
                if feed == 'set':
                    norm = lambda x: None if x is None else str(x).lower().replace('sec', '').replace('"', '').strip()  # noqa: E731
                    if cdef is None:
                        st = 'cdlRequired'
                    elif (name, k) in NULL_IS_CDL_DEFAULT and hdef is None:
                        st = 'compNullIsCdlDefault'
                    elif hdef is not None and norm(cdef) == norm(hdef):
                        st = 'same'
                    else:
                        st = 'differs'
                    p['defaultStatus'] = st
                    if st == 'differs':
                        defaultsToWrite[k] = 'CDL default %s, comp default %s' % (cdef, hdef if hdef is not None else 'null, read as %s' % NULL_READS.get((name, k), 'no value'))
                else:
                    p['defaultStatus'] = 'feed' if cdef is not None else 'cdlRequired'
            for fs, fv in t['fixed'].items():
                if fs not in cslots:
                    errors.append('%s: no fixed slot %s' % (name, fs))
                    continue
                ftype = hx_type(comp, fs)
                why = fixed_fits(fv, ftype, hx.get(ftype.rstrip('?'), {}).get('items'))
                if why:
                    errors.append('%s: fixed %s: %s' % (name, fs, why))
            for us in t['unused']:
                if us not in cslots:
                    errors.append('%s: no unused slot %s' % (name, us))
                elif not any(f in cslots[us]['raw'] for f in ('transient', 'output')):
                    errors.append('%s: unused %s is a config slot; name it in keep with a reason' % (name, us))
            for ks in t.get('keep', {}):
                if ks not in cslots:
                    errors.append('%s: no kept slot %s' % (name, ks))
            # One CDL name per comp slot: two connectors, or a connector and a parameter, on one slot would merge
            # two CDL signals into one.
            taken = {}
            for k, v in list(t['connectors'].items()) + list(t['params'].items()):
                sl = v if isinstance(v, str) else v['slot']
                taken.setdefault(sl, []).append(k)
            for k in t['fixed']:
                taken.setdefault(k, []).append('fixed')
            for sl, who in sorted(taken.items()):
                # A constant's parameter sets the output its one connector reads: the single shared slot is the class.
                if len(who) > 1 and not (g == 'const' and len(who) == 2 and set(who) == set(t['connectors']) | set(t['params'])):
                    errors.append('%s: comp slot %s carries %s; the map must be one to one' % (name, sl, ', '.join(who)))
            # A comp slot that is not transient is configuration. Each one is set by a parameter or a fixed value,
            # or left at the comp default by name in keep.
            setters = {v['slot'] for v in t['params'].values()} | set(t['fixed']) | set(t.get('keep', {})) |                 {v if isinstance(v, str) else v['slot'] for v in t['connectors'].values()}
            unset = [sl for sl, sv in cslots.items() if sl not in setters
                     and not any(f in sv['raw'] for f in ('transient', 'readonly', 'output'))]
            if unset:
                errors.append('%s: config slots %s are left unset; set, fix or keep each one' % (name, unset))
            errors += requires_violations(name, t, c, cslots, hx)
            # every comp input slot must be linked, set, fixed or declared unused
            used = {v if isinstance(v, str) else v['slot'] for v in t['connectors'].values()} | {v['slot'] for v in t['params'].values()} | set(t['fixed']) | set(t['unused'])
            stray = [sl for sl, sv in cslots.items() if sl not in used and 'transient' in sv['raw'] and 'readonly' not in sv['raw']]
            stray_out = [sl for sl, sv in cslots.items() if sl not in used and 'output' in sv['raw']]
            if stray or stray_out:
                errors.append('%s: comp slots not accounted %s %s' % (name, stray, stray_out))
        if g == 'link':
            e['link'] = t['link']
            cdl_conn = {k for k, s in c['slots'].items() if s['kind'] in ('input', 'output')}
            cdl_par = {k for k, s in c['slots'].items() if s['kind'] == 'param'}
            if {t['link']['from'], t['link']['to']} != cdl_conn:
                errors.append('%s: a link joins %s, and the class has connectors %s' % (name, t['link'], sorted(cdl_conn)))
            if set(t.get('dropped', {})) != cdl_par:
                errors.append('%s: a link drops parameters %s, and the class has %s' % (name, sorted(t.get('dropped', {})), sorted(cdl_par)))
            e['dropped'] = t.get('dropped', {})
            errors += requires_violations(name, t, c, {}, hx)
        if g == 'composite':
            errors += compose_violations(name, t, c, cdl, table)
            e['compose'] = t['compose']
        e['connectors'] = conns
        e['params'] = params
        e['fixedSlots'] = t['fixed']
        e['unusedCompSlots'] = t['unused']
        e['keptCompDefaults'] = t.get('keep', {})
        e['defaultsDiffer'] = defaultsToWrite
        # The CDL defaults the generator writes when a CDL instance leaves the parameter unbound: every parameter fed
        # through a constant comp (whose output has no default, so the feed would be null), and every parameter set
        # on a slot whose comp default differs from CDL's.
        e['cdlDefaults'] = OrderedDict((k, p['cdlDefault']) for k, p in params.items() if p['cdlDefault'] is not None
                                       and (p['feed'] != 'set' or p.get('defaultStatus') == 'differs'))
        e['typeNotes'] = typeNotes
        e['semanticNotes'] = sem
        e['departures'] = departures_of(t, COMMON)
        e['unitRule'] = t.get('unitRule')
        errors += unit_rule_violations(name, t, c)
        e['requires'] = t.get('requires', {})
        e['commonNotes'] = t['common'] + (['null'] if g in ('native', 'nativeParams') else [])
        for f in ('reason', 'closest', 'composition', 'expansion'):
            if f in t:
                e[f] = t[f]
        e['g36TextRefs'] = counts.get(c['cdlClass'], 0)
        ev = []
        if t['comp'] and t['comp'].startswith('hx.comps::'):
            ev.append('hx.comps ' + hx_loc(t['comp']))
        ev += t['ev']
        e['evidence'] = ev
        classes_out[name] = e
    if errors:
        return None, errors
    doc = OrderedDict()
    doc['schema'] = 'kw.cdl class-to-comp table. classmap.py checks classmap_table.py and writes this file.'
    doc['hxCompsSource'] = BRANCH
    doc['kwCdlSource'] = 'the pinned CXF, MBL 14.0.0 (ad48324b) via modelica-json 5460add3'
    doc['commonNotes'] = COMMON
    doc['counts'] = OrderedDict((g, sum(1 for e in classes_out.values() if e['grade'] == g)) for g in GRADES)
    doc['classes'] = classes_out
    return doc, []


def render(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args(argv)
    doc, errors = build(generate.load_classes(generate.cxf_source.verify()))
    if errors:
        print("\n".join(errors))
        return 1
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "class-map.json").write_text(render(doc), encoding="utf-8", newline="\n")
    print(dict(doc['counts']), sum(doc['counts'].values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
