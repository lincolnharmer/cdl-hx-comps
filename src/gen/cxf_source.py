#!/usr/bin/env python3
#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""The generator's inputs: modelica-json's output for MBL's classes, rebuilt on each machine and verified, never
committed.

  python -X utf8 src/gen/cxf_source.py --check            # verify the source directory against the manifest
  python -X utf8 src/gen/cxf_source.py --write            # rewrite the manifest from the source directory

regen_cxf.sh runs modelica-json over MBL and writes its output into the source directory: $KW_CDL_SOURCE when set,
else ~/.cache/kw-cdl/source. The layout is

  kw.cdl/cdl-elementary.jsonld          CXF-Core of MBL's CDL package, the 132 elementary blocks
  <g36 lib>/cxf/<path under G36>.jsonld   the CXF of one G36 class
  <g36 lib>/json/<path under G36>.json    modelica-json's json output for the same class, pruned to the annotations
                                          the generator reads, and for the four G36 packages of constants

source_manifest.json holds the sha256 of every one of those files, as regen_cxf.sh writes them from MBL 14.0.0
with modelica-json at the pinned commit. The hashes are facts about the files, not MBL material. A file missing, a
hash that differs, or a file the manifest does not list stops generation, naming the file. Nothing falls back to
another source.

--write is for a maintainer moving the pins (a new MBL release or modelica-json commit): it records what the
directory holds now, so run it only on a directory regen_cxf.sh has just written.
"""
import hashlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "source_manifest.json"
REGEN = "bash src/gen/regen_cxf.sh"


class SourceError(Exception):
    """The source directory is missing, or differs from the manifest."""


class SourceAbsent(SourceError):
    """No source directory exists at all: regen_cxf.sh has not run on this machine."""


def source_root():
    env = os.environ.get("KW_CDL_SOURCE")
    return pathlib.Path(env) if env else pathlib.Path.home() / ".cache" / "kw-cdl" / "source"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def manifest(path=None):
    return json.loads(pathlib.Path(path or MANIFEST).read_text(encoding="utf-8"))


def files(src):
    """Every file under `src`, as posix paths relative to it, sorted."""
    src = pathlib.Path(src)
    return sorted(f.relative_to(src).as_posix() for f in src.rglob("*") if f.is_file())


def problems(src, man):
    """Every way the directory `src` differs from manifest `man`: a file missing, a hash that differs, or a file the
    manifest does not list."""
    src = pathlib.Path(src)
    out = []
    for rel, want in sorted(man["files"].items()):
        f = src / rel
        if not f.is_file():
            out.append("%s: missing" % rel)
            continue
        got = sha256(f.read_bytes())
        if got != want:
            out.append("%s: sha256 %s, the manifest pins %s" % (rel, got, want))
    listed = set(man["files"])
    out += ["%s: a file the manifest does not list" % rel for rel in files(src) if rel not in listed]
    return out


def verify(src=None, man=None):
    """The verified source directory. Raises SourceAbsent when it does not exist or is empty, and SourceError naming
    every file that differs from the manifest."""
    src = pathlib.Path(src) if src else source_root()
    man = man or manifest()
    if not src.is_dir() or not any(f.is_file() for f in src.rglob("*")):
        raise SourceAbsent("no generator source in %s; run: %s" % (src, REGEN))
    bad = problems(src, man)
    if bad:
        raise SourceError("the generator source in %s does not verify against %s (rerun %s):\n  %s"
                          % (src, MANIFEST.name, REGEN, "\n  ".join(bad)))
    return src


def write_manifest(src=None):
    src = pathlib.Path(src) if src else source_root()
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    rels = files(src)
    if not rels:
        raise SourceAbsent("no generator source in %s; run: %s" % (src, REGEN))
    out = {"mbl": stamp["mbl"], "mblCommit": stamp["mblCommit"], "modelicaJson": stamp["modelicaJson"],
           "note": "The sha256 of each file regen_cxf.sh writes into the generator's source directory: modelica-json's "
                   "output for MBL's CDL package and the G36 classes, pinned by cxf.py. Facts about the files, not "
                   "MBL material: the files are rebuilt on each machine and verified against these hashes.",
           "files": {rel: sha256((src / rel).read_bytes()) for rel in rels}}
    MANIFEST.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("wrote %d hashes for MBL %s via modelica-json %s" % (len(rels), stamp["mbl"], stamp["modelicaJson"][:8]))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args[:1] == ["--check"] and len(args) <= 2:
            src = verify(args[1] if len(args) == 2 else None)
            print("generator source verified in %s: %d files" % (src, len(manifest()["files"])))
        elif args[:1] == ["--write"] and len(args) <= 2:
            write_manifest(args[1] if len(args) == 2 else None)
        else:
            sys.exit("usage: cxf_source.py --check [dir] | --write [dir]")
    except SourceError as e:
        print("cxf_source: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
