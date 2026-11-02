#!/usr/bin/env bash
# build.sh <work dir>: make a Haxall path environment at <work dir>/env that holds this repo's CDL libraries and
# the cdlResolve pod, compiled with Haxall's own tools. run.sh replays in that environment.
#
# Environment:
#   FAN_HOME     the Fantom installation that runs your Haxall build (its bin/fan is used)
#   HX_ENV_PATH  the path entries of your Haxall environment, separated by ';' (the directories that hold the
#                Haxall pods and xeto libraries with the hx.comps changes; see README.md)
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: build.sh <work dir>" >&2; exit 2; }
: "${FAN_HOME:?set FAN_HOME}" "${HX_ENV_PATH:?set HX_ENV_PATH}"
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
osp() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

LIBS="kw.cdl kw.cdl.g36.common kw.cdl.g36.ahu kw.cdl.g36.terminal kw.cdl.resolve"
mkdir -p "$1"; WORK=$(cd "$1" && pwd); ENVD=$WORK/env
rm -rf "$ENVD/src" "$ENVD/lib"
mkdir -p "$ENVD/src/xeto" "$ENVD/src/fan" "$ENVD/lib/xeto" "$ENVD/lib/fan"
for l in $LIBS; do cp -r "$REPO/src/xeto/$l" "$ENVD/src/xeto/"; done
cp -r "$REPO/src/fan/cdlResolve" "$ENVD/src/fan/"
printf 'path=%s;%s\n' "$(osp "$ENVD")" "$HX_ENV_PATH" > "$ENVD/fan.props"
echo "repo $(git -C "$REPO" describe --always --dirty 2>/dev/null || echo unknown)" > "$ENVD/build.log"

cd "$ENVD"
"$FAN_HOME/bin/fan" xeto build $LIBS >> build.log 2>&1 || { tail -20 build.log; echo "xeto build failed" >&2; exit 1; }
for l in $LIBS; do [ -f "lib/xeto/$l.xetolib" ] || { echo "missing lib/xeto/$l.xetolib" >&2; exit 1; }; done
"$FAN_HOME/bin/fan" src/fan/cdlResolve/build.fan compile >> build.log 2>&1 || { tail -20 build.log; echo "cdlResolve build failed" >&2; exit 1; }
[ -f lib/fan/cdlResolve.pod ] || { echo "missing lib/fan/cdlResolve.pod" >&2; exit 1; }
echo "built: $ENVD (log: $ENVD/build.log)"
