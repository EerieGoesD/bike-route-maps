#!/usr/bin/env python3
"""Writes <id>.borders.json for one map, which the app downloads with it:

  outline    the area the map covers, to tell which map a place is in
  crossings  for each neighbouring map, points on the roads that cross into
             it: [lon, lat, road class]. A route that runs from one map into
             the next is planned in each map up to one of these points.

Geofabrik draws each map's area a little past the border, so neighbours
overlap in a strip about a kilometre wide and the roads there are in both
maps (each extract also keeps every road that leaves it whole, to its end).
A road crosses when, through the strip, it joins this map's side to the
neighbour's side; roads that only run along inside the strip do not count.
The crossing point is where the road is furthest from both edges of the
strip, so it is well inside both maps.

  borders.py <id> <extract.osm.pbf>

Needs osmium and shapely (pip install osmium shapely)."""

import json
import math
import sys

import osmium
import shapely
from shapely.geometry import LineString, box, shape

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
SAME_SPOT = 100  # metres: crossings of one class closer than this are one


def metres(a, b):
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * k, a[1] - b[1]) * 111_320


class Joins:
    """Which road nodes the strip's pieces of road join up."""

    def __init__(self):
        self.up = {}

    def find(self, x):
        root = x
        while self.up.get(root, root) != root:
            root = self.up[root]
        while self.up.get(x, x) != root:
            self.up[x], x = root, self.up[x]
        return root

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.up[ra] = rb


def main():
    map_id, pbf = sys.argv[1], sys.argv[2]
    rows = {r["id"]: r for r in json.load(open("build-list.json"))}
    outlines = json.load(open("outlines.json"))
    area = shapely.make_valid(shape(outlines[map_id]))
    shapely.prepare(area)
    edge = area.boundary

    strips = {}
    for other in rows[map_id]["neighbours"]:
        o = shapely.make_valid(shape(outlines[other]))
        s = area.intersection(o)
        if s.area > 0:
            shapely.prepare(s)
            shapely.prepare(o)
            strips[other] = {"strip": s, "area": o, "edge": o.boundary, "joins": Joins(), "sides": {}, "pieces": []}

    # The grid cells each strip touches.
    cells = {}
    for other, st in strips.items():
        s = st["strip"]
        x0, y0, x1, y1 = s.bounds
        for cx in range(math.floor(x0 / CELL), math.floor(x1 / CELL) + 1):
            for cy in range(math.floor(y0 / CELL), math.floor(y1 / CELL) + 1):
                if s.intersects(box(cx * CELL, cy * CELL, (cx + 1) * CELL, (cy + 1) * CELL)):
                    cells.setdefault((cx, cy), set()).add(other)

    def side(st, p):
        """"a" on this map's side of the strip, "b" on the neighbour's."""
        in_a = shapely.contains_xy(area, p[0], p[1])
        in_b = shapely.contains_xy(st["area"], p[0], p[1])
        return "a" if in_a and not in_b else "b" if in_b and not in_a else ""

    fp = osmium.FileProcessor(pbf).with_locations().with_filter(osmium.filter.KeyFilter("highway"))
    for way in fp:
        if not way.is_way():
            continue
        cls = CLASSES.get(way.tags.get("highway"))
        if cls is None:
            continue
        nodes = [(n.ref, (n.lon, n.lat)) for n in way.nodes if n.location.valid()]
        for (ida, a), (idb, b) in zip(nodes, nodes[1:]):
            near = set()
            for cx in range(math.floor(min(a[0], b[0]) / CELL), math.floor(max(a[0], b[0]) / CELL) + 1):
                for cy in range(math.floor(min(a[1], b[1]) / CELL), math.floor(max(a[1], b[1]) / CELL) + 1):
                    near |= cells.get((cx, cy), set())
            if not near:
                continue
            seg = LineString([a, b])
            for other in near:
                st = strips[other]
                piece = seg.intersection(st["strip"])
                if piece.is_empty or piece.length == 0:
                    continue
                st["joins"].join(ida, idb)
                for nid, p in ((ida, a), (idb, b)):
                    s = side(st, p)
                    if s:
                        st["sides"].setdefault(nid, set()).add(s)
                p = piece.interpolate(0.5, normalized=True) if piece.geom_type == "LineString" else piece.centroid
                score = min(p.distance(edge), p.distance(st["edge"]))
                st["pieces"].append((ida, cls, score, p.x, p.y))

    out = {}
    for other, st in strips.items():
        joins = st["joins"]
        reach = {}
        for nid, sides in st["sides"].items():
            reach.setdefault(joins.find(nid), set()).update(sides)
        # Per stretch of joined-up road that runs from one side to the other,
        # the best point of each road class on it.
        best = {}
        for nid, cls, score, x, y in st["pieces"]:
            group = joins.find(nid)
            if reach.get(group, set()) != {"a", "b"}:
                continue
            if (group, cls) not in best or score > best[(group, cls)][0]:
                best[(group, cls)] = (score, x, y)
        pts = sorted((cls, -score, x, y) for (_, cls), (score, x, y) in best.items())
        kept = []
        for cls, _, x, y in pts:
            if all(metres((x, y), (k[0], k[1])) > SAME_SPOT for k in kept if k[2] == cls):
                kept.append((round(x, 5), round(y, 5), cls))
        if kept:
            out[other] = kept

    simple = area.simplify(0.002, preserve_topology=True)
    outline = shapely.geometry.mapping(shapely.set_precision(simple, 1e-5))
    json.dump({"outline": outline, "crossings": out}, sys.stdout, separators=(",", ":"))
    print(f"{map_id}: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(out.items())), file=sys.stderr)


main()
