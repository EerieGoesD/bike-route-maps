#!/usr/bin/env python3
"""Writes <id>.borders.json for one map, which the app downloads with it:

  outline    the area the map covers, to tell which map a place is in
  crossings  for each neighbouring map, points on the roads that cross into
             it: [lon, lat, road class]. A route that runs from one map into
             the next is planned in each map up to one of these points.

Geofabrik draws each map's area a little past the border, so neighbours
overlap in a strip about a kilometre wide and the roads there are in both
maps. A crossing is the point of a road in that strip furthest from the
strip's two edges, so it is well inside both maps.

  borders.py <id> <extract.osm.pbf>

Needs osmium and shapely (pip install osmium shapely)."""

import json
import math
import sys

import osmium
import shapely
from shapely.geometry import LineString, Point, box, shape

# Road classes, in the order the app ranks them.
CLASSES = {
    "motorway": 0, "motorway_link": 0,
    "trunk": 1, "trunk_link": 1,
    "primary": 2, "primary_link": 2,
    "secondary": 3, "secondary_link": 3,
    "tertiary": 4, "tertiary_link": 4,
    "unclassified": 5, "residential": 5, "living_street": 5, "road": 5,
    "service": 6,
    "track": 7,
    "cycleway": 8,
    "path": 9, "bridleway": 9,
    "footway": 10, "pedestrian": 10, "steps": 10,
}
CELL = 0.01  # degrees, for finding the road pieces near a strip quickly
SAME_SPOT = 100  # metres: crossings closer than this are one crossing


def metres(a, b):
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * k, a[1] - b[1]) * 111_320


def main():
    map_id, pbf = sys.argv[1], sys.argv[2]
    rows = {r["id"]: r for r in json.load(open("build-list.json"))}
    outlines = json.load(open("outlines.json"))
    area = shapely.make_valid(shape(outlines[map_id]))
    edge = area.boundary

    strips = {}
    for other in rows[map_id]["neighbours"]:
        o = shapely.make_valid(shape(outlines[other]))
        s = area.intersection(o)
        if s.area > 0:
            strips[other] = (s, o.boundary)
            shapely.prepare(s)

    # The grid cells each strip touches.
    cells = {}
    for other, (s, _) in strips.items():
        x0, y0, x1, y1 = s.bounds
        for cx in range(math.floor(x0 / CELL), math.floor(x1 / CELL) + 1):
            for cy in range(math.floor(y0 / CELL), math.floor(y1 / CELL) + 1):
                if s.intersects(box(cx * CELL, cy * CELL, (cx + 1) * CELL, (cy + 1) * CELL)):
                    cells.setdefault((cx, cy), set()).add(other)

    best = {}  # (way id, neighbour) -> (score, lon, lat, class)
    fp = osmium.FileProcessor(pbf).with_locations().with_filter(osmium.filter.KeyFilter("highway"))
    for way in fp:
        if not way.is_way():
            continue
        cls = CLASSES.get(way.tags.get("highway"))
        if cls is None:
            continue
        pts = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
        for a, b in zip(pts, pts[1:]):
            near = set()
            for cx in range(math.floor(min(a[0], b[0]) / CELL), math.floor(max(a[0], b[0]) / CELL) + 1):
                for cy in range(math.floor(min(a[1], b[1]) / CELL), math.floor(max(a[1], b[1]) / CELL) + 1):
                    near |= cells.get((cx, cy), set())
            if not near:
                continue
            seg = LineString([a, b])
            for other in near:
                s, other_edge = strips[other]
                piece = seg.intersection(s)
                if piece.is_empty or piece.length == 0:
                    continue
                p = piece.interpolate(0.5, normalized=True) if piece.geom_type == "LineString" else piece.centroid
                score = min(p.distance(edge), p.distance(other_edge))
                key = (way.id, other)
                if key not in best or score > best[key][0]:
                    best[key] = (score, p.x, p.y, cls)

    crossings = {}
    for (_, other), (score, x, y, cls) in best.items():
        crossings.setdefault(other, []).append((cls, -score, x, y))
    out = {}
    for other, pts in crossings.items():
        # Bigger roads first, so where two crossings are one, the bigger road
        # is the one kept.
        pts.sort()
        kept = []
        for cls, _, x, y in pts:
            if all(metres((x, y), (k[0], k[1])) > SAME_SPOT for k in kept if k[2] == cls):
                kept.append((round(x, 5), round(y, 5), cls))
        out[other] = kept

    simple = area.simplify(0.002, preserve_topology=True)
    outline = shapely.geometry.mapping(shapely.set_precision(simple, 1e-5))
    json.dump({"outline": outline, "crossings": out}, sys.stdout, separators=(",", ":"))
    print(f"{map_id}: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(out.items())), file=sys.stderr)


main()
