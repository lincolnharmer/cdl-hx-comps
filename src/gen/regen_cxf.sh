#!/usr/bin/env bash
# regen_cxf.sh -- rebuild the generator's inputs from MBL with modelica-json, and verify them.
#
#   MBL_DIR=<modelica-buildings clone> MJ_DIR=<modelica-json clone> bash src/gen/regen_cxf.sh
#
# MBL_DIR must be at the commit MBL's release tag peels to, and MJ_DIR at the modelica-json commit, both as
# stamp.json pins them. CXF carries no MBL version, so the pin lives in stamp.json and every generated file names it.
# modelica-json ships no lockfile; src/gen/package-lock.json pins its dependencies, and this script copies it into
# MJ_DIR and runs `npm ci` there, so MJ_DIR's node_modules is replaced.
#
# What it writes, into the source directory ($KW_CDL_SOURCE, else ~/.cache/kw-cdl/source), which it empties first:
#   kw.cdl/cdl-elementary.jsonld            CXF-Core of MBL's CDL package (the 132 Clause 7 blocks)
#   <g36 lib>/cxf/<path under G36>.jsonld   one CXF per G36 class outside Plants and Validation
#   <g36 lib>/json/<path under G36>.json    the same class's json output, pruned to the annotations generate.py
#                                           reads (cxf.py JSON_ANNOTATIONS)
#   kw.cdl.g36.common/json/Types/<P>.json   the four G36 packages of constants
# Then it checks every file against source_manifest.json. A file missing, differing or unlisted fails the run and is
# named. generate.py makes the same check before it reads anything.
#
# modelica-json runs once per G36 class: a run over the whole package fails on MBL's subscripted connect
# statements. Plants is not run: no lib here holds it.
#
# Runs in Git Bash on Windows and in bash elsewhere. On Windows modelica-json needs native backslash -f paths, so
# paths given to node go through cygpath when it exists.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${MBL_DIR:?set MBL_DIR to a modelica-buildings clone at the pinned commit}"
: "${MJ_DIR:?set MJ_DIR to a modelica-json clone at the pinned commit}"
# python3 where it runs, else python. On Windows `python3` can be a Store alias that only prints a hint, so try it.
if python3 -c "" >/dev/null 2>&1; then PY=python3; else PY=python; fi
stamp() { "$PY" -X utf8 -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8'))[sys.argv[2]])" \
  "$HERE/stamp.json" "$1"; }
MBL_VERSION=$(stamp mbl)
MBL_COMMIT=$(stamp mblCommit)
MJ_COMMIT=$(stamp modelicaJson)
[ "$(git -C "$MBL_DIR" rev-parse HEAD)" = "$MBL_COMMIT" ] || { echo "MBL_DIR is not at $MBL_COMMIT" >&2; exit 1; }
[ "$(git -C "$MJ_DIR" rev-parse HEAD)" = "$MJ_COMMIT" ] || { echo "MJ_DIR is not at $MJ_COMMIT" >&2; exit 1; }
if [ "$(git -C "$MBL_DIR" config --get core.autocrlf || true)" = "true" ]; then
  # MBL holds LF; an autocrlf checkout gives its .mo files CRLF, which modelica-json copies into documentation
  # strings. cxf.py normalizes them back to LF and drops the file checksum, so the output does not change.
  echo "warning: MBL_DIR has core.autocrlf=true; cxf.py normalizes the CRLF it introduces" >&2
fi
SRC="${KW_CDL_SOURCE:-$HOME/.cache/kw-cdl/source}"
# The script empties SRC before it writes, so SRC must be a directory it wrote itself (it holds MARK), or empty, or
# new, and never inside this repo.
MARK=".kw-cdl-source"
inside=$("$PY" -c "import pathlib,sys; s,r=(pathlib.Path(a).resolve() for a in sys.argv[1:]); print(s==r or r in s.parents)" \
  "$SRC" "$HERE/../..")
[ "$inside" = "False" ] || { echo "KW_CDL_SOURCE $SRC is inside the repo; choose a directory outside it" >&2; exit 1; }
if [ -d "$SRC" ] && [ -n "$(ls -A "$SRC")" ] && [ ! -f "$SRC/$MARK" ]; then
  echo "$SRC is not empty and was not written by this script (no $MARK); set KW_CDL_SOURCE to an empty or new directory" >&2
  exit 1
fi
cp "$HERE/package-lock.json" "$MJ_DIR/package-lock.json"
(cd "$MJ_DIR" && npm ci --ignore-scripts --omit=dev --no-audit --no-fund >/dev/null)
win() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }
APP="$(win "$MJ_DIR/app.js")"
export MODELICAPATH="$(win "$MBL_DIR")"
OUT="$(mktemp -d)"
LOG="$(mktemp)"
trap 'rm -rf "$OUT"' EXIT
mj() {  # mj <outdir> <path for node> [extra flags]
  mkdir -p "$1"
  (cd "$1" && MSYS_NO_PATHCONV=1 node "$APP" -l warn -f "$2" -o cxf -d . -p "${@:3}" 2>&1 \
     | grep -v 'INVALID_ALT_NUMBER\|trace-warnings' || true)
}
OBC="$MBL_DIR/Buildings/Controls/OBC"
G="$OBC/ASHRAE/G36"
rm -rf "$SRC"
mkdir -p "$SRC/kw.cdl"
touch "$SRC/$MARK"
# modelica-json reads lib/s231ClassesProperties.ttl relative to the working directory when it writes CXF-Core
# (lib/cxfExtractor.js, getCxfClassesProperties), so stage that one file beside the output.
mkdir -p "$OUT/elem/lib"
cp "$MJ_DIR/lib/s231ClassesProperties.ttl" "$OUT/elem/lib/"
mj "$OUT/elem" "$(win "$OBC/CDL")" --elementary --cxfCore
# CXF-Core.jsonld already aggregates every per-class file of the run plus the S231 vocabulary, and the per-class
# files spell the qudt prefix differently (qudt# against qudt/), so the aggregate is the one input.
f=$(find "$OUT/elem" -name 'CXF-Core.jsonld' | head -1)
[ -n "$f" ] || { echo "modelica-json wrote no CXF-Core.jsonld" >&2; exit 1; }
"$PY" -X utf8 "$HERE/cxf.py" merge "$SRC/kw.cdl/cdl-elementary.jsonld" "$f"
# Every G36 class outside Plants and Validation, one run each; a run that writes no CXF for its class stops here.
n=0
while read -r mo; do
  rel=${mo#$G/}; rel=${rel%.mo}
  mj "$OUT/g36" "$(win "$mo")" >> "$LOG"
  [ -f "$OUT/g36/cxf/Buildings/Controls/OBC/ASHRAE/G36/$rel.jsonld" ] \
    || { echo "modelica-json wrote no CXF for $rel (see $LOG)" >&2; exit 1; }
  n=$((n + 1))
done < <(find "$G" -name '*.mo' -not -path '*/Validation/*' -not -path '*/Plants/*' -not -name package.mo | LC_ALL=C sort)
echo "modelica-json: $n G36 classes"
"$PY" -X utf8 "$HERE/cxf.py" pin-g36 "$OUT/g36" "$SRC"
# A package of constants has no CXF node, so generate.py reads each from modelica-json's json output. The list is
# every Types package that is a package.mo directory.
for d in "$G"/Types/*/; do
  name=$(basename "$d")
  mkdir -p "$OUT/json-$name"
  (cd "$OUT/json-$name" && MSYS_NO_PATHCONV=1 node "$APP" -l warn -f "$(win "$d/package.mo")" \
     -o json -d . 2>&1 | grep -v 'INVALID_ALT_NUMBER\|trace-warnings' || true)
  f=$(find "$OUT/json-$name" -name 'package.json' | head -1)
  [ -n "$f" ] || { echo "modelica-json wrote no json for Types/$name" >&2; exit 1; }
  mkdir -p "$SRC/kw.cdl.g36.common/json/Types"
  "$PY" -X utf8 "$HERE/cxf.py" pinjson "$SRC/kw.cdl.g36.common/json/Types/$name.json" "$f" --prune
done
rm -f "$LOG"
echo "rebuilt the generator source in $SRC from MBL $MBL_VERSION"
"$PY" -X utf8 "$HERE/cxf_source.py" --check "$SRC"
