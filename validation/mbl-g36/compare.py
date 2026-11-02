# py <run> [...]: compare a replay trace with the MBL Dymola reference on the reference grid. Run it on
# traces made at a small step (0.1 s or less). Writes runs/<run>/txt and prints it.
#
# The comp value at a reference grid time is formed as buildingspy formed the reference: Dymola's raw output (the
# regular points k*rawDt plus every event time, holding the event's left limit) linearly resampled onto the grid.
# The raw interval rawDt comes from the model's .mos. The model's events are every logged change: point outputs
# and Boolean or Integer inputs (changes.csv, closed-loop inputs left out), every Boolean comp in the graph
# (events.csv), and the validation model's own time events (sourceEvents in the scenario).
#
# Each grid point of each recorded column gets one class:
#   strict   |comp - ref| <= RTOL * max(1, |ref|) (Real), or exact (Boolean or Integer; 1e-6 where the reference
#            interpolates).
#   window   only where a logged event lies within one step of a raw point the value is formed from. A Real then
#            passes if the reference lies in the range the comp value takes when those raw points move by one step,
#            or equals the slope-carried left limit 2c(t-h) - c(t-2h) at an event on the grid point. A Boolean or
#            Integer passes only on the TIMING check: the comp changed to the reference value within one step (h) of
#            the grid point, or, where the reference interpolates (fractional value), within h of the event time
#            the fraction implies.
#   mis      anything else.
#   funnel   reported apart: |comp - ref| <= max(1e-3, 1e-3 |ref|), the BuildingsPy regression tester's default
#            tol = 1e-3 as atoly and ltoly (ltoly relative to the local value), checked pointwise on the grid.
#            atolx is not used.
# An output counts as agreeing within 1e-5 when every grid point is strict, and within 1e-3 when every grid point
# passes the funnel check (summarize.py).
import sys, os, re, json, bisect, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refres, mo, gen_inputs, paths

RTOL = 1e-5

def num(s):
    if s in ("null", "absent", ""): return None
    return float(s.split(":")[0])

def load_trace(p):
    rows = [l.rstrip("\n").split(",") for l in open(p) if l.strip()]
    hdr = rows[0]
    t = [float(r[0]) for r in rows[1:]]
    cols = {h: [num(r[i]) for r in rows[1:]] for i, h in enumerate(hdr) if i > 0}
    stat = {h: sorted({r[i].split(":", 1)[1] for r in rows[1:] if ":" in r[i]}) for i, h in enumerate(hdr) if i > 0}
    return t, cols, stat

def load_changes(p):
    ch = {}
    for l in open(p).readlines()[1:]:
        t, c, v = l.rstrip("\n").split(",", 2)
        ch.setdefault(c, []).append((float(t), num(v)))
    return ch

def held_at(chlist, t):
    """the value a change list holds at time t"""
    ts = [x[0] for x in chlist]
    i = bisect.bisect_right(ts, t + 1e-9) - 1
    return None if i < 0 else chlist[i][1]

def raw_points(ti, raw, events):
    """the raw Dymola output points the reference value at ti comes from, as (time, weight, isEvent). buildingspy
    resamples Dymola's output, which holds the regular points k*raw and every event time with the event's left
    limit (the first of the two values stored there), linearly onto the reference grid."""
    q = ti / raw
    i = bisect.bisect_left(events, ti - 1e-9)
    if i < len(events) and abs(events[i] - ti) < 1e-9: return [(ti, 1.0, True)]
    if abs(q - round(q)) < 1e-9: return [(ti, 1.0, False)]
    ta, ea = math.floor(q) * raw, False
    if i > 0 and events[i - 1] > ta + 1e-9: ta, ea = events[i - 1], True
    elif i > 0 and abs(events[i - 1] - ta) < 1e-9: ea = True
    tb, eb = (math.floor(q) + 1) * raw, False
    if i < len(events) and events[i] < tb - 1e-9: tb, eb = events[i], True
    elif i < len(events) and abs(events[i] - tb) < 1e-9: eb = True
    wb = (ti - ta) / (tb - ta)
    return [(ta, 1.0 - wb, ea), (tb, wb, eb)]

def point_value(c, tidx, p, isev, exact, h):
    """the comp's value at a raw point: at an event its left limit (the step before; for a Real carried forward one
    step by its own slope), else the value at p"""
    def at(tt):
        j = tidx.get(round(tt, 6))
        return None if j is None else c[j]
    if not isev: return at(p)
    a1 = at(p - h)
    if exact or a1 is None: return a1
    a2 = at(p - 2 * h)
    return a1 if a2 is None else 2 * a1 - a2

def load_events(rd, sc):
    ch = load_changes(os.path.join(rd, "changes.csv"))
    fk = {"in:" + n for n in sc.get("feedbackInputs", {})}
    ev = {tt for col, lst in ch.items() if col not in fk for tt, _ in lst if tt > 0}
    # the validation model's own time events (pulse edges, ramp and sine start and end, sample instants, changes of
    # its Boolean and Integer sources), written into the scenario by gen_inputs.py
    for tt in sc.get("sourceEvents", []):
        if tt > 0: ev.add(float(tt))
    p = os.path.join(rd, "events.csv")
    if os.path.exists(p):
        for l in open(p).readlines()[1:]:
            tt = float(l.split(",", 1)[0])
            if tt > 0: ev.add(tt)
    return sorted(ev), ch

def compare_run(run, quiet=False):
    rd = os.path.join(paths.runs(), run)
    sc = json.load(open(os.path.join(rd, "scenario.json")))
    model, inst, h = sc["model"], sc["instance"], sc["step"]
    raw = sc.get("rawDt") or h
    grid, ref = refres.load_ref(model)
    comps, _, _ = mo.parse(model)
    ports = gen_inputs.ctl_ports(comps[inst].typ)
    t, cols, stat = load_trace(os.path.join(rd, "trace.csv"))
    tidx = {round(x, 6): i for i, x in enumerate(t)}
    events, ch = load_events(rd, sc)
    def at(c, tt):
        j = tidx.get(round(tt, 6)); return None if j is None else c[j]
    def near_event(p):
        i = bisect.bisect_left(events, p - h - 1e-9)
        return i < len(events) and events[i] <= p + h + 1e-9
    def rng(c, tt):
        a = bisect.bisect_left(t, tt - h - 1e-9); b = bisect.bisect_right(t, tt + h + 1e-9)
        w = [c[k] for k in range(a, b) if c[k] is not None]
        return (min(w), max(w)) if w else None
    out = []; res = {}
    for col in sc["record"]:
        rk = inst + "." + col
        if rk not in ref: continue
        c = cols.get(col)
        if "." in col:
            dirn = "Intern"; vals = [v for v in (c or []) if v is not None]
            kind = "Boolean" if vals and all(v in (0.0, 1.0) for v in vals) else "Real"
        else:
            kind, dirn = ports.get(re.sub(r"\[\d+\]$", "", col), ("?", "?"))
            if dirn == "?": continue
        if c is None: continue
        r = ref[rk]; exact = kind in ("Boolean", "Integer")
        chl = ch.get(col) or ch.get("in:" + col) or []
        cnt = {"strict": 0, "window": 0, "mis": 0, "funnel_ok": 0}; bad = []; mx = 0.0; mxat = None; tim = []
        for i, ti in enumerate(grid):
            if ti > sc["tEnd"] + 1e-9: break
            rp = raw_points(ti, raw, events)
            onraw = len(rp) == 1
            vals = [point_value(c, tidx, p, ev, exact, h) for p, w, ev in rp]
            rv = r[i]
            if exact and onraw: rv = float(round(rv))
            if any(v is None for v in vals):
                cnt["mis"] += 1; bad.append((ti, None, rv, "null")); continue
            cv = sum(v * w for v, (p, w, ev) in zip(vals, rp))
            e = abs(cv - rv)
            if e <= max(1e-3, 1e-3 * abs(r[i])): cnt["funnel_ok"] += 1
            if e > mx: mx, mxat = e, ti
            tol = (0.0 if onraw else 1e-6) if exact else RTOL * max(1.0, abs(rv))
            if e <= tol + 1e-12: cnt["strict"] += 1; continue
            gated = any(near_event(p) for p, w, ev in rp)
            note = ""
            if gated and not exact:
                rs = [rng(c, p) for p, w, ev in rp]
                if all(x is not None for x in rs):
                    lo = sum(x[0] * w for x, (p, w, ev) in zip(rs, rp)); hi = sum(x[1] * w for x, (p, w, ev) in zip(rs, rp))
                    if lo - tol <= rv <= hi + tol: cnt["window"] += 1; continue
                if onraw:
                    a1 = at(c, ti - h); a2 = at(c, ti - 2 * h)
                    if a1 is not None and a2 is not None and abs(2 * a1 - a2 - rv) <= tol: cnt["window"] += 1; continue
            if gated and exact:
                if onraw:
                    # timing: the comp holds the reference value at some step within one step of the grid point
                    w = [x for x in (at(c, ti - h), at(c, ti), at(c, ti + h)) if x is not None]
                    if any(abs(x - rv) < 1e-9 for x in w): cnt["window"] += 1; tim.append((ti, "left-limit or one-step")); continue
                else:
                    # the fraction implies the event time; compare with the comp's own change of this column
                    ta = math.floor(ti / raw) * raw; tb = ta + raw
                    cha = [x for x in chl if ta - h <= x[0] <= tb + h]
                    if len(cha) == 1:
                        old = held_at(chl, cha[0][0] - h / 2); new = cha[0][1]
                        if old is not None and new != old:
                            phi = (r[i] - old) / (new - old)
                            if 0 < phi < 1:
                                te = (ti - phi * tb) / (1 - phi)
                                dt = cha[0][0] - te
                                tim.append((ti, "comp change %+.3f s from the reference event %.3f" % (dt, te)))
                                if -1e-6 <= dt <= h + 1e-6: cnt["window"] += 1; continue
                                note = "timing %+.3f s" % dt
            cnt["mis"] += 1; bad.append((ti, cv, rv, note or ("no logged event within one step" if not gated else "")))
        res[col] = (dirn, kind, cnt, mx, mxat, bad, tim, max(r) - min(r) < 1e-9)
        out.append("%-26s %-6s %-7s max|err| %-10.4g at %-8s strict %3d window %3d MISMATCH %3d | funnel %3d/%d%s" % (
            col, dirn, kind, mx, mxat, cnt["strict"], cnt["window"], cnt["mis"], cnt["funnel_ok"],
            cnt["strict"] + cnt["window"] + cnt["mis"], "  [ref constant]" if max(r) - min(r) < 1e-9 else ""))
        for b in bad: out.append("      t=%-8g comp=%-22s ref=%-22s %s" % b)
        for x in tim: out.append("      timing t=%-8g %s" % x)
    txt = "== %s step %s s raw %s s, %d logged events\n" % (run, h, raw, len(events)) + "\n".join(out) + "\n"
    open(os.path.join(rd, "compare.txt"), "w", encoding="utf-8", newline="\n").write(txt)
    if not quiet: print(txt)
    return res

if __name__ == "__main__":
    for r in sys.argv[1:]: compare_run(r)
