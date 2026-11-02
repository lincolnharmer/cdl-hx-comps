# refres.py: read an MBL Dymola reference result (.txt) into {var: [values]} on its uniform grid.
# A two-value array is a constant and is expanded. Used by gen_inputs.py and compare.py.
import re, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

PFX = "Buildings_Controls_OBC_ASHRAE_G36_"

def ref_path(model):
    """model: e.g. 'TerminalUnits.CoolingOnly.Validation.Controller'"""
    return os.path.join(paths.mbl(), "Resources/ReferenceResults/Dymola", PFX + model.replace(".", "_") + ".txt")

def load_ref(model):
    txt = open(ref_path(model), encoding="utf-8").read()
    d = {}
    for m in re.finditer(r"^([A-Za-z_][\w.\[\],]*)=\[([^\]]*)\]", txt, re.M):
        d[m.group(1)] = [float(x) for x in m.group(2).replace("\n", " ").split(",") if x.strip()]
    t0, t1 = d.pop("time")
    n = max(len(v) for v in d.values())
    for k, v in list(d.items()):
        if len(v) == 2 and n != 2: d[k] = [v[0]] * n
        elif len(v) != n: raise ValueError("%s: %s has %d points, grid has %d" % (model, k, len(v), n))
    grid = [t0 + (t1 - t0) * i / (n - 1) for i in range(n)]
    return grid, d
