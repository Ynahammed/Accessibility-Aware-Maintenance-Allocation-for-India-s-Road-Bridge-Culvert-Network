# Alappuzha network access baseline

India-only descriptive analysis using Census 2011, PMGSY GeoSadak, the district OSM clip, and its road graph.

- Network: 297,492 nodes and 306,881 edges.
- Attached OSM destinations: 309 hospital; 425 health_any; 1,000 school.
- Access is estimated as nearest network travel time using OSM highway-class speeds and 5 km/h snap connectors.
- Coverage bands: 15, 30, and 60 minutes; summaries are population-weighted and shown separately for each source.

## PMGSY habitation population field

- Origin records: 1,981; source population total: 2,169,418.
- Located origins: 1,981 (2,169,418); missing coordinates: 0 (0).
- Network-attached origins: 1,978 (2,165,691); coordinate-bearing origins outside the 500 m snap limit: 3 (3,727).

### Nearest mapped hospital (amenity=hospital)

- Attached origins with no route to a mapped destination: 25 (14,508).
- Median among routed origins: 2.8 min.
- Within 15 min: 99.0% of all source population.
- Within 15 min: 99.0% of population with locations.
- Within 15 min: 99.2% of population attached to network.
- Within 30 min: 99.2% of all source population.
- Within 30 min: 99.2% of population with locations.
- Within 30 min: 99.3% of population attached to network.
- Within 60 min: 99.2% of all source population.
- Within 60 min: 99.2% of population with locations.
- Within 60 min: 99.3% of population attached to network.

### Nearest mapped health point (hospital, clinic or doctors' office)

- Attached origins with no route to a mapped destination: 25 (14,508).
- Median among routed origins: 2.4 min.
- Within 15 min: 99.0% of all source population.
- Within 15 min: 99.0% of population with locations.
- Within 15 min: 99.2% of population attached to network.
- Within 30 min: 99.2% of all source population.
- Within 30 min: 99.2% of population with locations.
- Within 30 min: 99.3% of population attached to network.
- Within 60 min: 99.2% of all source population.
- Within 60 min: 99.2% of population with locations.
- Within 60 min: 99.3% of population attached to network.

### Nearest mapped school (school, college, kindergarten)

- Attached origins with no route to a mapped destination: 19 (12,171).
- Median among routed origins: 1.8 min.
- Within 15 min: 99.1% of all source population.
- Within 15 min: 99.1% of population with locations.
- Within 15 min: 99.3% of population attached to network.
- Within 30 min: 99.3% of all source population.
- Within 30 min: 99.3% of population with locations.
- Within 30 min: 99.4% of population attached to network.
- Within 60 min: 99.3% of all source population.
- Within 60 min: 99.3% of population with locations.
- Within 60 min: 99.4% of population attached to network.

## Census 2011 village population

- Origin records: 52; source population total: 979,643.
- Located origins: 22 (437,682); missing coordinates: 30 (541,961).
- Network-attached origins: 22 (437,682); coordinate-bearing origins outside the 500 m snap limit: 0 (0).

### Nearest mapped hospital (amenity=hospital)

- Attached origins with no route to a mapped destination: 0 (0).
- Median among routed origins: 2.3 min.
- Within 15 min: 44.7% of all source population.
- Within 15 min: 100.0% of population with locations.
- Within 15 min: 100.0% of population attached to network.
- Within 30 min: 44.7% of all source population.
- Within 30 min: 100.0% of population with locations.
- Within 30 min: 100.0% of population attached to network.
- Within 60 min: 44.7% of all source population.
- Within 60 min: 100.0% of population with locations.
- Within 60 min: 100.0% of population attached to network.

### Nearest mapped health point (hospital, clinic or doctors' office)

- Attached origins with no route to a mapped destination: 0 (0).
- Median among routed origins: 2.1 min.
- Within 15 min: 44.7% of all source population.
- Within 15 min: 100.0% of population with locations.
- Within 15 min: 100.0% of population attached to network.
- Within 30 min: 44.7% of all source population.
- Within 30 min: 100.0% of population with locations.
- Within 30 min: 100.0% of population attached to network.
- Within 60 min: 44.7% of all source population.
- Within 60 min: 100.0% of population with locations.
- Within 60 min: 100.0% of population attached to network.

### Nearest mapped school (school, college, kindergarten)

- Attached origins with no route to a mapped destination: 0 (0).
- Median among routed origins: 2.0 min.
- Within 15 min: 44.7% of all source population.
- Within 15 min: 100.0% of population with locations.
- Within 15 min: 100.0% of population attached to network.
- Within 30 min: 44.7% of all source population.
- Within 30 min: 100.0% of population with locations.
- Within 30 min: 100.0% of population attached to network.
- Within 60 min: 44.7% of all source population.
- Within 60 min: 100.0% of population with locations.
- Within 60 min: 100.0% of population attached to network.

## Interpretation limits

PMGSY population-field totals and Census 2011 totals are separate sources; do not sum them. The Census locations are approximate weighted centroids and 30 unmatched villages have null coordinates. OSM health/school mapping is volunteered and incomplete. Travel times use free-flow class-speed assumptions and do not include congestion, flood closure, road condition, or facility capacity. This is not a maintenance recommendation.

Detailed per-origin results are in `origin_access.csv`; machine-readable summaries are in `summary.json`.
