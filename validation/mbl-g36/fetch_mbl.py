# fetch_mbl.py <dest dir>: download the Modelica Buildings Library 14.0.0 release, check its SHA-256, and extract
# the parts the harness reads. Prints the library directory to use as MBL_HOME.
#
# Nothing MBL publishes is kept in this repository. Every input series, parameter value and reference result the
# harness uses is derived at run time from these files:
#   Controls/OBC/...                                the validation models, the G36 sequences and the CDL blocks
#   Controls/SetPoints/...                          OccupancySchedule, which some validation models use
#   Resources/Scripts/Dymola/Controls/OBC/ASHRAE/G36/...   the .mos scripts (Dymola's output interval)
#   Resources/ReferenceResults/Dymola/Buildings_Controls_OBC_ASHRAE_G36_*.txt   the Dymola reference results
# A zip already in <dest dir> is reused only if its SHA-256 matches.
import sys, os, hashlib, zipfile, urllib.request

URL = "https://github.com/lbl-srg/modelica-buildings/releases/download/v14.0.0/Buildings-v14.0.0.zip"
SHA256 = "e088afbb9582df183d978bd94615e209c714123130b84c20dd7d3593a6da31ad"
TOP = "Buildings 14.0.0/"
KEEP = ("package.mo", "Controls/OBC/", "Controls/SetPoints/", "Resources/Scripts/Dymola/Controls/OBC/ASHRAE/G36/",
        "Resources/ReferenceResults/Dymola/Buildings_Controls_OBC_ASHRAE_G36_")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def main():
    if len(sys.argv) != 2: raise SystemExit("usage: fetch_mbl.py <dest dir>")
    dest = os.path.abspath(sys.argv[1]); os.makedirs(dest, exist_ok=True)
    zp = os.path.join(dest, os.path.basename(URL))
    if not os.path.exists(zp):
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
        longest = max(len(os.path.join(dest, m.filename)) for m in keep)
        if os.name == "nt" and longest > 259:
            raise SystemExit("the deepest extracted path would be %d characters, over the Windows limit of 259. Use a "
                             "destination at most %d characters long." % (longest, len(dest) - (longest - 259)))
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
