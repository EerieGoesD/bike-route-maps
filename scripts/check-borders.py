#!/usr/bin/env python3
"""Checks a border file the way the app uses it: every crossing from map A
into map B must be reachable by bike in both maps. Asks the engine (in the
Valhalla image, valhalla_service) for the times from each crossing to a
point well inside A, in map A, and to a point well inside B, in map B.

  check-borders.py <a> <b> <work dir holding a.tar, b.tar, a.borders.json>"""

import json
import subprocess
import sys

import shapely
from shapely.geometry import shape

a, b, work = sys.argv[1], sys.argv[2], sys.argv[3]
outlines = json.load(open("outlines.json"))
area_a = shapely.make_valid(shape(outlines[a]))
area_b = shapely.make_valid(shape(outlines[b]))
crossings = json.load(open(f"{work}/{a}.borders.json"))["crossings"].get(b, [])[:200]
print(f"{a} -> {b}: {len(crossings)} crossings")


def inside(area, other):
    p = area.difference(other).representative_point()
    return {"lat": p.y, "lon": p.x}


def times(map_id, target):
    config = f"{work}/{map_id}.config.json"
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{work}:/work", "ghcr.io/valhalla/valhalla:3.9.1", "sh", "-c",
         f"valhalla_build_config --mjolnir-tile-extract /work/{map_id}.tar"
         f" --service-limits-bicycle-max-matrix-distance 2000000 > /work/{map_id}.config.json"],
        check=True,
    )
    req = {
        "sources": [{"lat": c[1], "lon": c[0]} for c in crossings],
        "targets": [target],
        "costing": "bicycle",
        "verbose": True,
    }
    out = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{work}:/work", "ghcr.io/valhalla/valhalla:3.9.1",
         "valhalla_service", f"/work/{map_id}.config.json", "sources_to_targets", json.dumps(req)],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = json.loads(out[out.index("{"):])["sources_to_targets"]
    return [r[0]["time"] for r in rows]


in_a = times(a, inside(area_a, area_b))
in_b = times(b, inside(area_b, area_a))
both = 0
for c, ta, tb in zip(crossings, in_a, in_b):
    ok = ta is not None and tb is not None
    both += ok
    if not ok:
        print(f"  not in both: {c} in {a}: {ta} in {b}: {tb}")
print(f"{both} of {len(crossings)} reachable in both maps")
