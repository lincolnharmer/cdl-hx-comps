# fetch_mbl.py <dest dir> [zip]: download the Modelica Buildings Library 14.0.0 release, check its SHA-256, and
# extract the parts the harness reads. Prints the library directory to use as MBL_HOME.
#
# Nothing MBL publishes is kept in this repository. Every input series, parameter value and reference result the
# harness uses is derived at run time from these files:
#   Controls/OBC/...                                the validation models, the G36 sequences and the CDL blocks
#   Controls/SetPoints/...                          OccupancySchedule, which some validation models use
#   Resources/Scripts/Dymola/Controls/OBC/ASHRAE/G36/...   the .mos scripts (Dymola's output interval)
#   Resources/ReferenceResults/Dymola/Buildings_Controls_OBC_ASHRAE_G36_*.txt   the Dymola reference results
# A zip already in <dest dir>, or one named as the second argument (a copy downloaded before), is used instead of a
# download, and only if its SHA-256 matches.
import sys, os, hashlib, zipfile, urllib.request

URL = "https://github.com/lbl-srg/modelica-buildings/releases/download/v14.0.0/Buildings-v14.0.0.zip"
SHA256 = "e088afbb9582df183d978bd94615e209c714123130b84c20dd7d3593a6da31ad"
TOP = "Buildings 14.0.0/"
KEEP = ("package.mo", "Controls/OBC/", "Controls/SetPoints/", "Resources/Scripts/Dymola/Controls/OBC/ASHRAE/G36/",
        "Resources/ReferenceResults/Dymola/Buildings_Controls_OBC_ASHRAE_G36_")
# Windows without long paths opens no path over 259 characters. The deepest file this script extracts lies this many
# characters below <dest dir>, separator included, so <dest dir> may be at most 259 - DEEPEST = 79 characters long.
WINMAX = 259
DEEPEST = 180

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def too_long(dest, deepest):
    if os.name == "nt" and len(dest) + deepest > WINMAX:
        raise SystemExit("%s is %d characters long. On Windows the destination may be at most %d characters, because "
                         "the deepest extracted path is %d characters below it. Use a shorter directory; a zip already "
                         "downloaded can be reused from there: fetch_mbl.py <short dir> <zip>." % (
                         dest, len(dest), WINMAX - deepest, deepest))

def main():
    if len(sys.argv) not in (2, 3): raise SystemExit("usage: fetch_mbl.py <dest dir> [zip]")
    dest = os.path.abspath(sys.argv[1])
    too_long(dest, DEEPEST)
    os.makedirs(dest, exist_ok=True)
    zp = os.path.abspath(sys.argv[2]) if len(sys.argv) == 3 else os.path.join(dest, os.path.basename(URL))
    if not os.path.exists(zp):
        if len(sys.argv) == 3: raise SystemExit("no such zip: " + zp)
        print("downloading", URL)
        tmp = zp + ".part"
        with urllib.request.urlopen(URL) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b: break
                f.write(b)
        os.replace(tmp, zp)
    got = sha256(zp)
    if got != SHA256:
        raise SystemExit("SHA-256 mismatch for %s: got %s, want %s. Delete it and run again." % (zp, got, SHA256))
    print("sha256 ok", got)
    n = 0
    with zipfile.ZipFile(zp) as z:
        keep = [m for m in z.infolist() if not m.is_dir() and m.filename.startswith(TOP) and m.filename[len(TOP):].startswith(KEEP)]
        # the measured depth, in case it ever differs from DEEPEST
        too_long(dest, max(len(m.filename) + 1 for m in keep))
        for m in keep:
            out = os.path.realpath(os.path.join(dest, m.filename))
            if not out.startswith(os.path.realpath(dest) + os.sep): raise SystemExit("unsafe path in zip: " + m.filename)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(m) as src, open(out, "wb") as f: f.write(src.read())
            n += 1
    home = os.path.join(dest, TOP.rstrip("/"))
    print("extracted %d files" % n)
    print("MBL_HOME=%s" % home.replace("\\", "/"))

if __name__ == "__main__":
    main()
