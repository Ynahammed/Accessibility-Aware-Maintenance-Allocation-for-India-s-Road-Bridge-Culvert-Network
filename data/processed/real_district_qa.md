# Real district network QA

- nodes: 1972
- edges: 2361
- connected components: 1
- share in largest component: 1.000

## Structures
- edges tagged bridge/culvert: 74 (74 bridge, 0 culvert)
- water layer: **missing** -> crossing inference skipped (Overpass feature fetch blocked here; retry on a network with access)

## Habitations and facilities
- habitation points (OSM place): 0
- health facilities: 0, schools: 0
- **accessibility loss cannot be computed yet**: needs both habitation and health-facility layers (PMGSY is blocked here; OSM feature fetch also failed)

This is the plan's week-1 exit test in progress: one command that reconstructs a district's network from raw data. The road graph reproduces; the structure and habitation layers depend on the blocked sources.
