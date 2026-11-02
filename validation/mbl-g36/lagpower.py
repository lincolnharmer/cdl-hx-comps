# lagpower.py <run> [...]: how small a lag each recorded output's reference can reveal (the power of any comparison
# against it). For a Real output, a lag L moves the value at grid point t by about L*|slope(t)|; it shows once that
# exceeds the tolerance there, so the smallest detectable lag is min over grid points of tol(t)/|slope(t)| (slope from
# the comp's own trace, one step either side; grid points with a logged event within one step are skipped). For a
# Boolean or Integer output, a lag L shows only if some change of the output at tc has a raw point in (tc, tc + L];
# a change ON a raw point is printed as its left limit, so a lag of it never shows. Smallest detectable lag: min over
# changes of (next raw point after tc) - tc.
import sys, os, json, re, math, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare, refres, mo, gen_inputs, paths

def lag_of(run):
    rd = os.path.join(paths.runs(), run)
    sc = json.load(open(os.path.join(rd, "scenario.json")))
    h = sc["step"]; raw = sc.get("rawDt") or h
    g, ref = refres.load_ref(sc["model"]); inst = sc["instance"]
    comps, _, _ = mo.parse(sc["model"]); ports = gen_inputs.ctl_ports(comps[inst].typ)
    t, c, _ = compare.load_trace(os.path.join(rd, "trace.csv")); ix = {round(x, 6): i for i, x in enumerate(t)}
    events, ch = compare.load_events(rd, sc)
    out = {}
    for col in sc["record"]:
        kind, d = ports.get(re.sub(r"\[\d+\]$", "", col), ("?", "?"))
        if d != "Output" or inst + "." + col not in ref: continue
        r = ref[inst + "." + col]
        if kind == "Real":
            best = math.inf
            for i, ti in enumerate(g):
                # a jump at an event on the grid point is printed as its left limit and hides a lag: skip those
                k = bisect.bisect_left(events, ti - h - 1e-9)
                if k < len(events) and events[k] <= ti + h + 1e-9: continue
                a = ix.get(round(ti - h, 6)); b = ix.get(round(ti + h, 6))
                if a is None or b is None or c[col][a] is None or c[col][b] is None: continue
                s = abs(c[col][b] - c[col][a]) / (2 * h)
                if s > 0: best = min(best, 1e-5 * max(1, abs(r[i])) / s)
        else:
            best = math.inf
            rawpts = sorted(set([k * raw for k in range(int(g[-1] / raw) + 2)] + list(g)))
            for tc, v in ch.get(col, []):
                if tc <= 0: continue
                j = bisect.bisect_right(rawpts, tc + 1e-9)
                if j < len(rawpts) and abs(rawpts[j - 1] - tc) > 1e-9: best = min(best, rawpts[j] - tc)
        out[col] = (kind, best, max(r) - min(r) < 1e-9)
    return out

if __name__ == "__main__":
    allr = []
    for run in sys.argv[1:]:
        for col, (kind, best, const) in lag_of(run).items():
            allr.append((run, col, kind, best, const))
            print("%-30s %-18s %-7s smallest detectable lag %s%s" % (run, col, kind, ("%.3g s" % best) if best < math.inf else "none (no slope or no change off a raw point)", "  [ref constant]" if const else ""))
    for L in (0.1, 1.0, 10.0):
        n = sum(1 for x in allr if x[3] <= L)
        print("outputs where a lag of %g s can show: %d of %d" % (L, n, len(allr)))
