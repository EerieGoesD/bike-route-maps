#!/usr/bin/env python3
"""Writes regions.json, the list of maps the app offers, from what is in the
"maps" release right now: every <id>.tar there, with its size and checksum
as GitHub reports them, its border file when there is one, and its name,
box, rough outline and neighbours from build-list.json. Built again from scratch each
time, so runs that finish together cannot undo each other."""

import json
import subprocess
import sys

repo = sys.argv[1]
rows = {r["id"]: r for r in json.load(open("build-list.json"))}
release = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/releases/tags/maps"]))
pages = subprocess.check_output(
    ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases/{release['id']}/assets?per_page=100"]
)
assets = [a for page in json.loads(pages) for a in page]
borders = {
    a["name"][: -len(".borders.json")]: a["browser_download_url"]
    for a in assets
    if a["name"].endswith(".borders.json") and a.get("state") == "uploaded"
}

regions = []
for a in assets:
    if not a["name"].endswith(".tar") or a.get("state") != "uploaded":
        continue
    rid = a["name"][: -len(".tar")]
    row = rows.get(rid)
    if not row or not (a.get("digest") or "").startswith("sha256:"):
        continue
    regions.append(
        {
            "id": rid,
            "name": row["name"],
            "bbox": row["bbox"],
            "url": a["browser_download_url"],
            "bytes": a["size"],
            "sha256": a["digest"][len("sha256:") :],
            "built": a["updated_at"][:10],
            "borders": borders.get(rid),
            "neighbours": row.get("neighbours", []),
            "area": row.get("area"),
        }
    )
regions.sort(key=lambda r: r["name"])
json.dump({"regions": regions}, sys.stdout, ensure_ascii=False, separators=(",", ":"))
print()
print(f"{len(regions)} maps", file=sys.stderr)
