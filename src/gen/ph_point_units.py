#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""The unit each Project Haystack point spec carries, read from the ph Xeto source at a pinned commit.

  python -X utf8 src/gen/ph_point_units.py <haystack xeto repo> [commit]   # rewrites ph_point_units.json

Reads the `ph`, `ph.points` and `ph.points.x` libs at the commit with `git show`, so the working tree is never
read or changed. A spec's unit is the `unit` slot its own body declares, else the first one found walking its
supertypes left to right, depth first. Each record says where the unit came from and whether it is `invariant` (a
point must carry exactly that unit) or only a quantity. The generator reads the JSON, never the repo, so CI needs no
Haystack checkout.
"""
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "ph_point_units.json"
LIBS = ("ph", "ph.points", "ph.points.x")
COMMIT = "8ba9d7ffc3fe8ace52070f9b0bdc9239ad36a9f5"
SPEC = re.compile(r"^([A-Z]\w*)\s*:\s*([^<{\n]+?)\s*(<[^>]*>)?\s*(\{.*)?$")
UNIT = re.compile(r'^\s+unit\s*:\s*(?:Unit\s*)?(<[^>]*>)?\s*(?:"([^"]*)")?\s*$')


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def read_specs(repo, commit):
    """qname -> (supertype qnames as written, unit record or None) for every top-level spec of the libs."""
    specs = {}
    for lib in LIBS:
        for f in git(repo, "ls-tree", "--name-only", commit, "src/xeto/%s/" % lib).split():
            if not f.endswith(".xeto") or f.endswith("lib.xeto"):
                continue
            lines = git(repo, "show", "%s:%s" % (commit, f)).split("\n")
            i = 0
            while i < len(lines):
                m = SPEC.match(lines[i])
                i += 1
                if not m:
                    continue
                name, supers, has_body = m.group(1), [s.strip() for s in m.group(2).split("&")], m.group(4)
                unit = None
                if has_body and has_body.count("{") > has_body.count("}"):
                    depth = 1
                    while i < len(lines) and depth > 0:
                        line = lines[i]
                        u = UNIT.match(line) if depth == 1 else None
                        if u:
                            meta = u.group(1) or ""
                            q = re.search(r'quantity\s*:\s*"([^"]*)"', meta)
                            # a `unit` slot naming neither a unit nor a quantity (NumberPoint's) says nothing
                            if u.group(2) or q:
                                unit = {"unit": u.group(2), "invariant": "invariant" in meta,
                                        "quantity": q.group(1) if q else None}
                        depth += line.count("{") - line.count("}")
                        i += 1
                specs["%s::%s" % (lib, name)] = (supers, unit)
    return specs


def resolve(specs):
    """qname -> {unit, invariant, quantity, from}: the effective unit of each spec, or None."""
    names = {q.split("::")[1]: q for q in specs}
    memo = {}

    def walk(q, seen):
        if q in memo:
            return memo[q]
        if q in seen or q not in specs:
            return None
        supers, unit = specs[q]
        out = dict(unit, **{"from": q}) if unit else None
        for s in supers if out is None else ():
            sq = s if "::" in s else names.get(s)
            got = walk(sq, seen | {q}) if sq else None
            if got:
                out = got
                break
        memo[q] = out
        return out
    return {q: walk(q, frozenset()) for q in sorted(specs)}


def main(argv):
    repo = pathlib.Path(argv[1])
    commit = argv[2] if len(argv) > 2 else COMMIT
    units = resolve(read_specs(repo, commit))
    doc = {"schema": "kw.cdl: the unit of each Project Haystack point spec, by ph_point_units.py",
           "commit": commit, "libs": list(LIBS),
           "specs": {q: u for q, u in units.items() if u is not None}}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8",
                   newline="\n")
    print("%d specs, %d with a unit, written to %s" % (len(units), len(doc["specs"]), OUT.name))


if __name__ == "__main__":
    main(sys.argv)
