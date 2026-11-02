# summarize.py <run> [...]: the totals over the controller outputs of the given runs, after compare.py's rules.
#
# Per run: the outputs, how many are strict (every grid point within 1e-5 x max(1, |ref|), Boolean and Integer
# exact), window (no mismatch, at least one point passed only by the event window), mismatch (at least one point
# outside both), and funnel-ok (every grid point within 1e-3 x max(1, |ref|)); each output with a mismatch is listed
# as name(points, max |comp - ref|).
# Then the power of the references against a timing lag (lagpower.py): the outputs whose reference would reveal a
# lag of one replay step, and whether every one of them is among the outputs that are not strict.
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare, lagpower, paths

def main(runs):
    tot = dict(out=0, strict=0, window=0, mis=0, funnel=0, const=0, p_strict=0, p_window=0, p_mis=0, p_funnel=0, pts=0)
    notstrict = set()
    for run in runs:
        res = compare.compare_run(run, quiet=True)
        row = dict(out=0, strict=0, window=0, mis=0, funnel=0)
        mis_cols = []
        for col, (dirn, kind, cnt, mx, mxat, bad, tim, const) in res.items():
            if dirn != "Output": continue
            n = cnt["strict"] + cnt["window"] + cnt["mis"]
            row["out"] += 1; tot["out"] += 1; tot["const"] += const; tot["pts"] += n
            tot["p_strict"] += cnt["strict"]; tot["p_window"] += cnt["window"]; tot["p_mis"] += cnt["mis"]; tot["p_funnel"] += cnt["funnel_ok"]
            if cnt["funnel_ok"] == n: row["funnel"] += 1; tot["funnel"] += 1
            if cnt["mis"]: row["mis"] += 1; tot["mis"] += 1; mis_cols.append("%s(%d, max %.2g)" % (col, cnt["mis"], mx))
            elif cnt["window"]: row["window"] += 1; tot["window"] += 1
            else: row["strict"] += 1; tot["strict"] += 1
            if cnt["strict"] != n: notstrict.add((run, col))
        print("%-34s outputs %2d strict %2d window %2d mismatch %2d funnel-ok %2d  %s" % (run, row["out"], row["strict"], row["window"], row["mis"], row["funnel"], " ".join(mis_cols)))
    print("TOTAL", tot)
    lagged = []
    for run in runs:
        h = json.load(open(os.path.join(paths.runs(), run, "scenario.json")))["step"]
        for col, (kind, best, const) in lagpower.lag_of(run).items():
            if best <= h + 1e-9: lagged.append((run, col))
    among = sum(1 for x in lagged if x in notstrict)
    print()
    print("outputs                                                      %d" % tot["out"])
    print("within 1e-5 x max(1, |ref|) at every sample (strict)         %d" % tot["strict"])
    print("within 1e-3 x max(1, |ref|) at every sample (funnel)         %d" % tot["funnel"])
    print("outputs whose reference would reveal a one-step lag          %d, of which %d are among the %d not strict" % (
        len(lagged), among, len(notstrict)))

if __name__ == "__main__":
    if len(sys.argv) < 2: raise SystemExit("usage: summarize.py <run> [...]")
    main(sys.argv[1:])
