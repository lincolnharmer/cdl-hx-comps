# gen_inputs.py <model> <controller instance> <step s> <run name> [tEnd]
#
# Rebuilds the source network of one MBL G36 validation model from its .mo (mo.py), evaluates every open-loop
# source block on the step grid t_k = k*h exactly as the CDL block defines it, and writes for the replay driver:
#   runs/<run>/scenario.json  the controller qname, its parameters from the .mo, the step, the end time, the
#                             input CSV, the feedback blocks (closed loops through the validation model), and the
#                             reference grid
#   runs/<run>/inputs.csv     t plus one column per controller input driven open loop, written only on rows where
#                             a value changes (the driver holds the last value)
#   runs/<run>/input-check.txt every generated input that the reference records, checked on the reference grid
# A block the evaluator does not know is refused by name. A parameter a block instance does not set takes the
# default its own .mo declares. runs/ is under G36_WORK; the model files are under MBL_HOME (paths.py).
import sys, os, json, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mo, refres, paths

LIBS = {"TerminalUnits": "kw.cdl.g36.terminal", "AHUs": "kw.cdl.g36.ahu", "FanCoilUnits": "kw.cdl.g36.ahu"}

def qname_of(typ):
    p = "Buildings.Controls.OBC.ASHRAE.G36."
    assert typ.startswith(p), typ
    path = typ[len(p):].split(".")
    lib = LIBS.get(path[0], "kw.cdl.g36.common")
    want = "".join(x[0].upper() + x[1:] for x in path)
    # the generator recases acronyms (AHUs -> Ahus, VAV -> Vav), so match the library's own spec names ignoring case
    import glob, re
    names = set()
    for f in glob.glob(os.path.join(paths.XETO_SRC, lib, "*.xeto")):
        names |= set(re.findall(r"^([A-Z]\w*)\s*:", open(f, encoding="utf-8").read(), re.M))
    hit = [n for n in names if n.lower() == want.lower()]
    if len(hit) != 1: raise ValueError("no unique spec for %s in %s: %s" % (want, lib, hit))
    return lib + "::" + hit[0]

def norm_type(typ):
    i = typ.find("CDL.")
    if i >= 0: return typ[i:]
    if typ.endswith("Controls.SetPoints.OccupancySchedule"): return "OccupancySchedule"
    return typ

# ---- block semantics on the grid ---------------------------------------------------------------------------------

def bool_pulse(kns, width, period, shift):
    """CDL Logical.Sources.Pulse on the grid (integer ns): true on [t0 + k*period, t0 + k*period + width*period)"""
    p = int(round(period * 1e9)); w = int(round(width * period * 1e9)); s = int(round(shift * 1e9))
    r = np.mod(kns - s, p)
    return (r < w).astype(float)

def occ_sched(t, occupancy, period, first):
    """Buildings.Controls.SetPoints.OccupancySchedule getOutput(t), evaluated at each grid time"""
    n = len(occupancy)
    occ = np.zeros(len(t)); tno = np.zeros(len(t)); tnn = np.zeros(len(t))
    for k, tk in enumerate(t):
        iSta = int(tk / period); iSto = iSta
        sta, sto = 1, 2
        for i in range(1, n, 2):
            if tk >= occupancy[i - 1] + iSta * period: sta = i + 2
        for i in range(2, n + 1, 2):
            if tk >= occupancy[i - 1] + iSto * period: sto = i + 2
        if sta > n: sta = 1; iSta += 1
        if sto > n: sto = 2; iSto += 1
        tOcc = occupancy[sta - 1] + iSta * period; tNon = occupancy[sto - 1] + iSto * period
        o = tNon < tOcc
        if not first: tOcc, tNon, o = tNon, tOcc, not o
        occ[k] = 1.0 if o else 0.0; tno[k] = tOcc - tk; tnn[k] = tNon - tk
    return {"occupied": occ, "tNexOcc": tno, "tNexNonOcc": tnn}

FEEDBACK_TYPES = {"CDL.Logical.Not", "CDL.Logical.Timer", "CDL.Logical.Latch"}

def main():
    model, inst, h, run = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    comps, mparams, conns = mo.parse(model)
    env = mo.eval_params(mparams)
    grid, ref = refres.load_ref(model)
    tEnd = float(sys.argv[5]) if len(sys.argv) > 5 else grid[-1]
    tStart = grid[0]          # a validation model may start before 0 (TimeSuppressionNegativeStartTime)
    N = int(round((tEnd - tStart) / h))
    hns = int(round(h * 1e9))
    kns = int(round(tStart * 1e9)) + np.arange(N + 1, dtype=np.int64) * hns
    t = kns / 1e9
    ctl = comps[inst]
    qn = qname_of(ctl.typ)

    # what drives what: dest "a.u" -> src "b.y"
    drv = {}
    for a, b in conns:
        # connect is undirected in text; the source side is a known output port
        for s, d in ((a, b), (b, a)):
            sc, sp = s.split(".", 1); dc, dp = d.split(".", 1)
            if is_output(comps, sc, sp, inst):
                drv[d] = s; break
        else:
            raise ValueError("cannot orient connect(%s, %s)" % (a, b))

    # blocks downstream of a controller output are closed loop
    closed = set()
    changed = True
    while changed:
        changed = False
        for d, s in drv.items():
            dc = d.split(".")[0]; sc = s.split(".")[0]
            if dc == inst: continue
            if (sc == inst or sc in closed) and dc not in closed:
                closed.add(dc); changed = True

    cache = {}
    tev = set()     # the validation model's own time events (Dymola stores a raw output point at each)
    def pulse_edges(width, period, shift):
        t0 = math.fmod(shift, period)
        k0 = math.floor((t[0] - t0) / period) - 1
        while t0 + k0 * period <= t[-1]:
            for e in (t0 + k0 * period, t0 + k0 * period + width * period):
                if t[0] < e <= t[-1]: tev.add(round(e, 9))
            k0 += 1
    def val(port):
        """the open-loop series of an output port 'blk.y'"""
        if port in cache: return cache[port]
        c, p = port.split(".", 1)
        b = comps[c]; ty = norm_type(b.typ); m = dict(mo.block_defaults(ty)); m.update({k: mo.ev(v, env) for k, v in b.mods.items()})
        def inp(name):
            src = drv.get(c + "." + name)
            if src is None: raise ValueError("%s.%s is unconnected" % (c, name))
            return val(src)
        if c in closed: raise ValueError("%s is closed loop and has no open-loop series" % port)
        if ty == "CDL.Reals.Sources.Constant" or ty == "CDL.Integers.Sources.Constant":
            y = np.full(len(t), float(m["k"]))
        elif ty == "CDL.Logical.Sources.Constant":
            y = np.full(len(t), 1.0 if m["k"] else 0.0)
        elif ty == "CDL.Reals.Sources.Ramp":
            st = m["startTime"]; du = m["duration"]; hi = m["height"]; of = m["offset"]
            y = of + np.where(t < st, 0.0, np.where(t < st + du, (t - st) * hi / du, hi))
            tev.update(round(e, 9) for e in (st, st + du) if t[0] < e <= t[-1])
        elif ty == "CDL.Reals.Sources.Sin":
            st = m["startTime"]; am = m["amplitude"]; f = m["freqHz"]; ph = m["phase"]; of = m["offset"]
            y = of + np.where(t < st, 0.0, am * np.sin(2 * math.pi * f * (t - st) + ph))
            if t[0] < st <= t[-1]: tev.add(round(st, 9))
        elif ty == "CDL.Logical.Sources.Pulse":
            y = bool_pulse(kns, m["width"], m["period"], m["shift"])
            pulse_edges(m["width"], m["period"], m["shift"])
        elif ty in ("CDL.Reals.Sources.Pulse", "CDL.Integers.Sources.Pulse"):
            y = m["offset"] + m["amplitude"] * bool_pulse(kns, m["width"], m["period"], m["shift"])
            pulse_edges(m["width"], m["period"], m["shift"])
        elif ty == "CDL.Conversions.RealToInteger":
            u = inp("u"); y = np.where(u > 0, np.floor(u + 0.5), np.ceil(u - 0.5))
        elif ty == "CDL.Conversions.BooleanToReal":
            u = inp("u"); y = np.where(u > 0.5, m["realTrue"], m["realFalse"])
        elif ty == "CDL.Conversions.IntegerToReal":
            y = inp("u")
        elif ty == "CDL.Reals.Round":
            fac = 10.0 ** m["n"]; u = inp("u")
            y = np.where(u > 0, np.floor(u * fac + 0.5) / fac, np.ceil(u * fac - 0.5) / fac)
        elif ty == "CDL.Reals.Abs":
            y = np.abs(inp("u"))
        elif ty == "CDL.Reals.Add":
            y = inp("u1") + inp("u2")
        elif ty == "CDL.Reals.Switch":
            y = np.where(inp("u2") > 0.5, inp("u1"), inp("u3"))
        elif ty == "CDL.Reals.Subtract":
            y = inp("u1") - inp("u2")
        elif ty == "CDL.Reals.Multiply":
            y = inp("u1") * inp("u2")
        elif ty == "CDL.Reals.AddParameter":
            y = inp("u") + m["p"]
        elif ty == "CDL.Reals.MultiplyByParameter":
            y = inp("u") * m["k"]
        elif ty == "CDL.Conversions.BooleanToInteger":
            u = inp("u"); y = np.where(u > 0.5, m["integerTrue"], m["integerFalse"]).astype(float)
        elif ty == "CDL.Discrete.UnitDelay":
            # samples u at k*T and puts out the previous sample: y_start on [0, T), then u(floor(t/T)*T - T)
            T = m["samplePeriod"]; u = inp("u"); ys = m["y_start"]
            kT = int(round(T / h)); assert abs(kT * h - T) < 1e-9, "samplePeriod %s is not a whole number of steps" % T
            tev.update(round(k * T, 9) for k in range(int(math.ceil(t[0] / T)), int(t[-1] // T) + 1) if t[0] < k * T)
            inst_t = np.floor(t / T + 1e-9) * T - T          # the previous sample instant, in model time
            idx = np.round((inst_t - tStart) / h).astype(np.int64)
            y = np.where(inst_t < tStart - 1e-9, ys, u[np.clip(idx, 0, len(t) - 1)])
        elif ty in ("CDL.Reals.GreaterThreshold", "CDL.Reals.Greater", "CDL.Reals.LessThreshold", "CDL.Reals.Less"):
            # y = (not pre(y) and u > t) or (pre(y) and u > t - h); Less mirrors it; pre(y) starts at pre_y_start
            two = not ty.endswith("Threshold")
            u = inp("u1") if two else inp("u")
            thr = inp("u2") if two else np.full(len(t), float(m["t"]))
            hh = float(m["h"]); pre = bool(m["pre_y_start"]); y = np.zeros(len(t))
            gt = "Greater" in ty
            for k in range(len(t)):
                if gt: pre = (not pre and u[k] > thr[k]) or (pre and u[k] > thr[k] - hh)
                else: pre = (not pre and u[k] < thr[k]) or (pre and u[k] < thr[k] + hh)
                y[k] = 1.0 if pre else 0.0
        elif ty == "CDL.Reals.Sin":
            y = np.sin(inp("u"))
        elif ty in ("CDL.Logical.And", "CDL.Logical.Or"):
            a, b = inp("u1") > 0.5, inp("u2") > 0.5
            y = ((a & b) if ty.endswith("And") else (a | b)).astype(float)
        elif ty == "CDL.Logical.Timer" and p == "passed" or ty == "CDL.Logical.Timer":
            u = inp("u"); th = float(m["t"]); ent = t[0]; pas = th <= 0; prevU = None
            yy = np.zeros(len(t)); pp = np.zeros(len(t))
            for k in range(len(t)):
                uk = u[k] > 0.5
                if prevU is None: ent = t[k]
                elif uk and not prevU: ent = t[k]; pas = th <= 0
                elif uk and t[k] >= th + ent: pas = True
                elif not uk and prevU: pas = False
                prevU = uk; yy[k] = t[k] - ent if uk else 0.0; pp[k] = 1.0 if pas else 0.0
            cache[c + ".y"] = yy; cache[c + ".passed"] = pp
            return cache[port]
        elif ty == "CDL.Logical.Not":
            y = 1.0 - inp("u")
        elif ty == "OccupancySchedule":
            res = occ_sched(t, list(m["occupancy"]), m["period"], m["firstEntryOccupied"])
            for k, v in res.items(): cache[c + "." + k] = v
            return cache[port]
        else:
            raise ValueError("block type %s (%s) is not modelled" % (ty, c))
        cache[port] = y
        return y

    # controller inputs
    cols = {}; fb_inputs = {}
    for d, s in drv.items():
        dc, dp = d.split(".", 1)
        if dc != inst: continue
        sc = s.split(".")[0]
        if sc == inst or sc in closed:
            fb_inputs[dp] = s
        else:
            cols[dp] = val(s)
    # feedback blocks, in dependency order
    fb = []
    for c in sorted(closed):
        b = comps[c]; ty = norm_type(b.typ)
        if ty not in FEEDBACK_TYPES: raise ValueError("closed-loop block %s is a %s, which the driver does not model" % (c, ty))
        ins = {}
        for d, s in drv.items():
            dc, dp = d.split(".", 1)
            if dc != c: continue
            sc = s.split(".")[0]
            if sc == inst: ins[dp] = "out:" + s.split(".", 1)[1]
            elif sc in closed: ins[dp] = "blk:" + s
            else:
                name = "src:" + s; cols[name] = val(s); ins[dp] = "in:" + name
        fp = {k: mo.plain(v) for k, v in mo.block_defaults(ty).items()}
        fp.update({k: mo.plain(mo.ev(v, env)) for k, v in b.mods.items()})
        fb.append({"name": c, "type": ty.split(".")[-1], "params": fp, "inputs": ins})
    # dependency order: a block after every block it reads
    order = []; left = list(fb)
    while left:
        for b in left:
            deps = {v[4:].split(".")[0] for v in b["inputs"].values() if v.startswith("blk:")}
            if deps <= {x["name"] for x in order}:
                order.append(b); left.remove(b); break
        else:
            raise ValueError("feedback blocks form a loop with no output between them: %s" % [b["name"] for b in left])
    fb = order
    fbin = {}
    for dp, s in fb_inputs.items():
        sc = s.split(".")[0]
        fbin[dp] = ("out:" + s.split(".", 1)[1]) if sc == inst else ("blk:" + s)
    # the initial value of a closed-loop input: MBL's own, from the reference, where recorded
    fbinit = {}
    for dp in fbin:
        rk = inst + "." + dp
        fbinit[dp] = ref[rk][0] if rk in ref else None

    # events: the explicit time events, plus every change of a Boolean or Integer signal of the source network
    for port, ser in list(cache.items()):
        if np.all(ser == np.round(ser)):
            ch = np.nonzero(np.diff(ser))[0] + 1
            tev.update(round(float(t[k]), 9) for k in ch)
    srcEvents = sorted(tev)
    params = {}
    for k, v in ctl.mods.items():
        params[k] = mo.plain(mo.ev(v, env))
    rd = os.path.join(paths.runs(), run); os.makedirs(rd, exist_ok=True)
    names = sorted(cols)
    with open(os.path.join(rd, "inputs.csv"), "w", newline="\n") as f:
        f.write(",".join(["t"] + names) + "\n")
        prev = None
        arr = np.array([cols[n] for n in names]) if names else np.zeros((0, len(t)))
        for k in range(len(t)):
            row = tuple(arr[:, k])
            if row != prev or k == len(t) - 1:
                f.write(",".join([repr(float(t[k]))] + [repr(float(x)) for x in row]) + "\n")
                prev = row
    outs = sorted(k[len(inst) + 1:] for k in ref if k.startswith(inst + "."))
    # Dymola's raw output interval, from the model's .mos (outputInterval, else stopTime/numberOfIntervals, default
    # 500). The reference is buildingspy's linear resample of that raw output onto its grid, so a grid point that
    # is not a raw point is an interpolation between the two raw points around it: record those too.
    import alias as aliasmod
    aliases = {o: aliasmod.resolve(ctl.typ, o) for o in outs if "." in o}
    rawDt = raw_interval(model, grid[-1])
    extra = []
    for ti in grid:
        q = ti / rawDt
        if abs(q - round(q)) < 1e-9: continue
        ta = math.floor(q) * rawDt; extra += [ta, ta + rawDt]
    sc = {"model": model, "instance": inst, "qname": qn, "params": params, "step": h, "tEnd": tEnd,
          "inputsCsv": os.path.join(rd, "inputs.csv").replace("\\", "/"),
          "trace": os.path.join(rd, "trace.csv").replace("\\", "/"),
          "changes": os.path.join(rd, "changes.csv").replace("\\", "/"),
          "grid": grid, "window": 10, "record": outs, "rawDt": rawDt, "tStart": tStart, "sourceEvents": srcEvents, "extraTimes": extra, "alias": aliases, "dense": False,
          "feedback": fb, "feedbackInputs": fbin, "feedbackInit": fbinit,
          "startIso": "2025-10-15T00:00:00Z"}
    json.dump(sc, open(os.path.join(rd, "scenario.json"), "w"), indent=1)

    # input check against the reference's recorded inputs
    lines = []
    allok = True
    for n in names:
        rk = inst + "." + n
        if rk not in ref: lines.append("%-22s not recorded by the reference" % n); continue
        r = ref[rk]; y = cols[n]; bad = []; evb = []; mx = 0.0; mxat = None
        # a Boolean or Integer input (every generated value whole) compares with the reference rounded, as
        # compare.py does: buildingspy resamples Dymola's output linearly, so an event between two output points
        # prints a fraction between 0 and 1
        if np.all(y == np.round(y)): r = [float(round(v)) for v in r]
        for i, ti in enumerate(grid):
            k = int(round((ti - tStart) / h))
            if k >= len(y): break
            e = abs(y[k] - r[i]); tol = 1e-5 * max(1.0, abs(r[i]))
            if e > mx: mx, mxat = e, ti
            if e <= tol: continue
            win = y[max(0, k - 1):k + 2]
            if win.min() - tol <= r[i] <= win.max() + tol: evb.append(ti)
            else: bad.append((ti, y[k], r[i]))
        ok = not bad; allok &= ok
        lines.append("%-22s %s  max|err| %.3g at %s  event-bound %s%s" % (n, "OK      " if ok else "MISMATCH", mx, mxat, evb,
                     "" if ok else "  bad " + str(bad[:6])))
    for dp, s in fbin.items():
        lines.append("%-22s closed loop via %s, initial %s" % (dp, s, fbinit[dp]))
    open(os.path.join(rd, "input-check.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("%s: %s inputs open loop, %d feedback blocks, %d recorded columns, %d rows on %d steps; inputs %s" %
          (run, len(names), len(fb), len(outs), N + 1, N + 1, "OK" if allok else "MISMATCH"))

def raw_interval(model, stop):
    import re
    p = os.path.join(paths.mbl(), "Resources/Scripts/Dymola/Controls/OBC/ASHRAE/G36", *model.split(".")) + ".mos"
    txt = open(p, encoding="utf-8").read()
    sim = re.search(r"simulateModel\((.*?)\);", txt, re.S).group(1)
    m = re.search(r"outputInterval\s*=\s*([0-9.eE+-]+)", sim)
    if m: return float(m.group(1))
    m = re.search(r"numberOfIntervals\s*=\s*([0-9]+)", sim)
    st = float(re.search(r"stopTime\s*=\s*([0-9.eE+-]+)", sim).group(1))
    assert abs(st - stop) < 1e-6, (st, stop)
    return st / (int(m.group(1)) if m else 500)

_ctl_ports = {}
def ctl_ports(typ):
    """the controller's connectors {name: (Real|Boolean|Integer, Input|Output)} from its own .mo"""
    if typ not in _ctl_ports:
        import re
        path = typ[len("Buildings.Controls.OBC.ASHRAE.G36."):]
        src = mo.strip_comments(open(mo.mo_path(path), encoding="utf-8").read())
        _ctl_ports[typ] = {m.group(3): (m.group(1), m.group(2)) for m in
            re.finditer(r"CDL\.Interfaces\.(Real|Boolean|Integer)(Input|Output)\s+(\w+)", src)}
    return _ctl_ports[typ]

def is_output(comps, c, p, inst):
    if c not in comps: raise ValueError("unknown component %s" % c)
    ty = norm_type(comps[c].typ)
    if ty.startswith("Buildings.Controls.OBC.ASHRAE.G36."):
        ports = ctl_ports(comps[c].typ)
        if p not in ports: raise ValueError("%s has no connector %s" % (c, p))
        return ports[p][1] == "Output"
    if ty == "OccupancySchedule": return p in ("occupied", "tNexOcc", "tNexNonOcc")
    if ty == "CDL.Logical.Timer": return p in ("y", "passed")
    return p == "y"

if __name__ == "__main__":
    main()
