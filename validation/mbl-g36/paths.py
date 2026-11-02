# paths.py: where the harness reads MBL and writes its runs. Two environment variables set them:
#   MBL_HOME  the MBL 14.0.0 library that fetch_mbl.py extracted: the directory that holds Buildings' package.mo
#   G36_WORK  the work directory; each replay writes runs/<run>/ under it
# The CDL libraries are read from this repository's src/xeto.
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
XETO_SRC = os.path.join(REPO, "src", "xeto")

def _need(var):
    v = os.environ.get(var)
    if not v: raise SystemExit("set %s (see validation/mbl-g36/README.md)" % var)
    return v

def mbl():
    d = _need("MBL_HOME")
    if not os.path.isfile(os.path.join(d, "package.mo")):
        raise SystemExit("MBL_HOME=%s holds no package.mo; point it at the extracted library (fetch_mbl.py prints it)" % d)
    return d

def runs():
    return os.path.join(_need("G36_WORK"), "runs")
