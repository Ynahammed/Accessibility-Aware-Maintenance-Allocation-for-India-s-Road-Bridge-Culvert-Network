# Legacy town-area network QA

This report describes the older town-area extract under `data/raw/osm/` only. It is not
Alappuzha district-wide QA. Current district-wide roads, settlements/population, facilities,
and provisional crossing candidates are documented in
[`alappuzha_network_join/README.md`](alappuzha_network_join/README.md).

- Nodes: 1,972
- Edges: 2,361
- Connected components: 1
- Share in largest component: 1.000

## Structures

- Edges tagged bridge/culvert: 74 (74 bridge, 0 culvert)
- This selected town-area directory has no water layer, so this report did not run crossing inference.
  That does not mean the district water layer is unavailable.

## Habitations and facilities

- OSM place habitation points in this selected directory: 0
- Health facilities: 0; schools: 0
- This selected town-area directory lacks these layers; district-wide OSM and PMGSY/Census evidence is maintained separately.

The district-wide OSM data are volunteered mapping, not an authoritative PWD asset or facility
register. Road/water intersection candidates are screening records, not verified structures.
PWD condition ratings and maintenance costs remain unavailable, so no validated real-district
allocation loss or recommendation is reported.
