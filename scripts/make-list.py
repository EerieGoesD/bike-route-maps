#!/usr/bin/env python3
"""Writes build-list.json: every map to build, one per country, with the big
countries split into their regions or states so each map stays well under
GitHub's 2 GiB limit per release file. Also writes outlines.json, the area
each map covers, which borders.py reads.

The countries and their parts come from Geofabrik's index of OpenStreetMap
extracts. A part is used when the country's extract is over SPLIT_AT bytes
(the built map comes out at about 1.4 times the extract).

Needs shapely (pip install shapely)."""

import json
import math
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

INDEX = "https://download.geofabrik.de/index-v1.json"
SPLIT_AT = 1.2e9
ROOTS = ["europe", "north-america", "asia", "africa", "south-america", "central-america", "australia-oceania", "russia"]
# Groups of countries, or a country again under another name; their parts are
# built on their own.
SKIP = {
    "alps", "britain-and-ireland", "dach", "great-britain", "us", "us-midwest", "us-northeast",
    "us-pacific", "us-south", "us-west", "sea", "south-africa-and-lesotho", "azores",
}


def size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req) as res:
        return int(res.headers["Content-Length"])


def bbox(geometry):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for k in c:
                walk(k)

    walk(geometry["coordinates"])
    return [
        math.floor(min(xs) * 1e4) / 1e4,
        math.floor(min(ys) * 1e4) / 1e4,
        math.ceil(max(xs) * 1e4) / 1e4,
        math.ceil(max(ys) * 1e4) / 1e4,
    ]


def main():
    with urllib.request.urlopen(INDEX) as res:
        features = json.load(res)["features"]
    regions = {f["properties"]["id"]: f for f in features}
    kids = {}
    for i, f in regions.items():
        kids.setdefault(f["properties"].get("parent"), []).append(i)
    with ThreadPoolExecutor(24) as pool:
        sizes = dict(zip(regions, pool.map(lambda i: size(regions[i]["properties"]["urls"]["pbf"]), regions)))

    def clean(i):
        name = regions[i]["properties"]["name"]
        # "Nord-Norge<br />(Northern Norway)": the English name.
        m = re.search(r"<br\s*/?>\s*\((.*)\)", name)
        if m:
            return m.group(1)
        # The US states are named by their id: "us/new-york".
        if name.startswith("us/"):
            words = name[3:].split("-")
            return " ".join(w if w in ("of",) else w.capitalize() for w in words)
        return name

    def name(i):
        parent = regions[i]["properties"].get("parent")
        if i.startswith("us/") and parent == "north-america":
            return clean(i) + " (United States)"
        if parent == "russia":
            return clean(i) + " (Russia)"
        if parent in ROOTS:
            return clean(i)
        return clean(i) + " (" + clean(parent) + ")"

    def map_id(i):
        parent = regions[i]["properties"].get("parent")
        s = i.replace("/", "-")
        if parent == "russia":
            return "russia-" + s
        if parent and parent not in ROOTS:
            p = parent.replace("/", "-")
            if not s.startswith(p + "-"):
                s = p + "-" + s
        return s

    picked = []

    def take(i):
        if i in SKIP:
            return
        parts = [c for c in kids.get(i, []) if c not in SKIP]
        if sizes[i] > SPLIT_AT and parts:
            for c in parts:
                take(c)
            return
        picked.append(i)

    for root in ROOTS:
        for c in kids[root]:
            take(c)

    rows = [
        {
            "id": map_id(i),
            "name": name(i),
            "pbf": regions[i]["properties"]["urls"]["pbf"],
            "pbf_bytes": sizes[i],
            "bbox": bbox(regions[i]["geometry"]),
        }
        for i in picked
    ]
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "two maps with the same id"
    assert all(re.fullmatch(r"[a-z0-9-]{1,64}", x) for x in ids), "an id the app would refuse"

    # Neighbours: maps whose areas overlap. Geofabrik draws each area a little
    # past the border, so two countries side by side overlap in a strip about
    # a kilometre wide, and a road there is in both maps.
    shapes = [shapely.make_valid(shape(regions[i]["geometry"])) for i in picked]
    tree = STRtree(shapes)
    for k, r in enumerate(rows):
        near = tree.query(shapes[k], predicate="intersects")
        r["neighbours"] = sorted(
            rows[j]["id"] for j in near if j != k and shapes[k].intersection(shapes[j]).area > 1e-7
        )
    outlines = {r["id"]: regions[i]["geometry"] for r, i in zip(rows, picked)}
    with open("outlines.json", "w") as f:
        json.dump(outlines, f, separators=(",", ":"))

    rows.sort(key=lambda r: r["name"])
    json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
    print()


main()
