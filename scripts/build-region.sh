#!/bin/bash
# Builds one routing map inside the Valhalla image (the same Valhalla version
# the app runs): /work/<id>.osm.pbf in, /work/<id>.tar out.
#
#   admins     the country and state of every road, for "avoid borders", the
#              border crossings the app reports, and each country's own
#              rules on where bikes may go
#   elevation  heights from the free public terrain tiles, for the hills a
#              bike route weighs and the app's climb profile
set -euo pipefail
id="$1"
cd /work
valhalla_build_config \
  --mjolnir-tile-dir /work/tiles \
  --mjolnir-tile-extract "/work/$id.tar" \
  --mjolnir-admin /work/admins.sqlite \
  --mjolnir-concurrency "$(nproc)" \
  --additional-data-elevation /work/elevation \
  > /work/valhalla.json
valhalla_build_admins -c /work/valhalla.json "/work/$id.osm.pbf"
# The road graph first, then the heights for the area it covers, then the rest
# of the build, which reads them.
valhalla_build_tiles -c /work/valhalla.json -e build "/work/$id.osm.pbf"
valhalla_build_elevation --from-tiles -c /work/valhalla.json -v
valhalla_build_tiles -c /work/valhalla.json -s enhance "/work/$id.osm.pbf"
valhalla_build_extract -c /work/valhalla.json -v
ls -la "/work/$id.tar"
