#!/usr/bin/env bash
# run.sh <work dir> all | <name>...: for each named instance (instances.txt), generate the scenario and inputs from
# MBL, replay them through cdlResolve and hx.comps (one JVM per instance, one at a time), and compare the trace
# with MBL's reference. Then prints the totals over the instances run (summarize.py). An instance whose generated
# inputs disagree with the reference, or whose replay or comparison fails, is reported and makes the exit status 1.
#
# Environment:
#   FAN_HOME   the Fantom installation that runs your Haxall build
#   MBL_HOME   the MBL 14.0.0 library fetch_mbl.py extracted
#   STEP       the replay step in seconds (default 0.1, the step the published counts are for)
#   PYTHON     the Python 3 interpreter (default python3, else python); it needs numpy
# Writes <work dir>/runs/<name>-<step>s/: scenario.json, inputs.csv, input-check.txt, trace.csv, changes.csv,
# events.csv, graph.xeto, driver.txt, run.log and compare.txt. Needs <work dir>/env from build.sh.
set -uo pipefail
[ $# -ge 2 ] || { echo "usage: run.sh <work dir> all | <name>..." >&2; exit 2; }
: "${FAN_HOME:?set FAN_HOME}" "${MBL_HOME:?set MBL_HOME}"
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
WORK=$(cd "$1" && pwd); shift
[ -f "$WORK/env/lib/fan/cdlResolve.pod" ] || { echo "no $WORK/env: run build.sh first" >&2; exit 2; }
STEP=${STEP:-0.1}
if [ -z "${PYTHON:-}" ]; then
  if python3 -c "" >/dev/null 2>&1; then PYTHON=python3; else PYTHON=python; fi
fi
osp() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
export G36_WORK=$(osp "$WORK") MBL_HOME
export G36_HARNESS_REV=$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo unknown)

names=("$@")
[ "${names[0]}" = all ] && names=($(grep -v '^#' "$HERE/instances.txt" | awk 'NF {print $1}'))
runs=(); rc=0
for name in "${names[@]}"; do
  read -r model inst <<< "$(awk -v n="$name" '$1 == n {print $2, $3}' "$HERE/instances.txt")"
  [ -n "${model:-}" ] || { echo "$name: not in instances.txt" >&2; rc=2; continue; }
  run=$name-${STEP}s; rd=$WORK/runs/$run
  echo "== $run: $model $inst"
  "$PYTHON" "$HERE/gen_inputs.py" "$model" "$inst" "$STEP" "$run" | tail -1     || { echo "$run: input generation failed, or an input disagrees with the reference (see $rd/input-check.txt)" >&2; rc=1; continue; }
  ( cd "$WORK/env" && "$FAN_HOME/bin/fan" "$(osp "$HERE/G36Replay.fan")" "$(osp "$rd/scenario.json")" ) > "$rd/run.log" 2>&1
  r=$?; echo "rc=$r" >> "$rd/run.log"
  grep -E '^(ran |REFUSED|RUN ERR|ERROR)' "$rd/run.log"
  [ $r -eq 0 ] || { echo "$run: replay failed (rc $r), see $rd/run.log" >&2; rc=1; continue; }
  "$PYTHON" "$HERE/compare.py" "$run" > /dev/null || { echo "$run: compare failed" >&2; rc=1; continue; }
  runs+=("$run")
done
if [ ${#runs[@]} -gt 0 ]; then
  "$PYTHON" "$HERE/summarize.py" "${runs[@]}" || { echo "summarize.py failed" >&2; rc=1; }
fi
exit $rc
