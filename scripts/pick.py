#!/usr/bin/env python3
"""The maps one run builds, as a GitHub Actions matrix. The argument is a
comma-separated list of map ids, or "N/M" for the Nth of M equal shares of
build-list.json (a run builds at most 256 maps)."""

import json
import re
import sys

rows = json.load(open("build-list.json"))
arg = sys.argv[1].strip()
m = re.fullmatch(r"(\d+)/(\d+)", arg)
if m:
    n, total = int(m.group(1)), int(m.group(2))
    picked = rows[n - 1 :: total]
else:
    wanted = {x.strip() for x in arg.split(",") if x.strip()}
    picked = [r for r in rows if r["id"] in wanted]
    missing = wanted - {r["id"] for r in picked}
    if missing:
        sys.exit("not in build-list.json: " + ", ".join(sorted(missing)))
if not picked or len(picked) > 256:
    sys.exit(f"{len(picked)} maps picked; a run builds 1 to 256")
# Biggest first, so the longest builds are not left for last.
picked.sort(key=lambda r: -r["pbf_bytes"])
print("matrix=" + json.dumps([{"id": r["id"], "pbf": r["pbf"]} for r in picked]))
