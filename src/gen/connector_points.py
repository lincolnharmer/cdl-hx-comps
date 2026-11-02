#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""The G36 connector-to-point table the generator reads: connector-points.json.

The table resolves every connector of the 116 G36 composites to a class (point, signal or unclear), a Project Haystack
point spec or a gap, a binding scope, and the exact point meta the generator emits on it. The table was built and
reviewed outside the generator. The generator does not derive the point meta: it writes each connector's `meta` field
as the table holds it, and hxemit.point_index checks the table before it is used.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "connector-points.json"
# The scopes cdlPointScope may carry: the unit itself, the air handler upstream of it (optionally one deck), the
# zone, or one element of an array of them.
SCOPES = ("self", "upstreamAir", "upstreamAir(coldDeck)", "upstreamAir(hotDeck)", "zone", "perZone", "perReliefFan",
          "perSupplyFan")


def load():
    return json.loads(OUT.read_text(encoding="utf-8"))
