# Alappuzha modelled flood exposure — KSDMA return-period depth

India-only overlay of the official KSDMA/CIMA return-period flood-depth rasters on the
PMGSY DRRP road network, the district OSM road clip, mapped facilities and habitat points.

**These are modelled hazard overlap numbers.** A road edge inside a deep cell is exposed in
the model; it is not evidence that the road closed, that a structure failed, or that any
repair is justified. No observed flood damage or maintenance cost enters this analysis.

## Hazard source

- Product: KSDMA *Flood Hazard Probability of Kerala* — historical and RCP8.5 return periods
  (UNEP/UN-GRID/CIMA Italy 2020 modelling, distributed by KSDMA).
- Cell values: modelled flood depth in centimetres. Cell size 92.1 m.
- Twelve layers: 10/25/50/100/200/500 years, historical and RCP8.5.
- One layer is stored as integer centimetres, the rest as float32; each file is decoded
  using its own declared sample format.

## Modelled district footprint

| Layer | Cells with any depth | Median flooded depth (cm) | p95 flooded (cm) | ≥30 cm cells |
|---|---|---|---|---|
| historical_10yr | 35.5% | 206 | 353 | 35.1% |
| historical_25yr | 37.2% | 223 | 388 | 35.8% |
| historical_50yr | 38.4% | 244 | 407 | 37.0% |
| historical_100yr | 40.4% | 271 | 432 | 39.0% |
| historical_200yr | 42.1% | 307 | 468 | 40.6% |
| historical_500yr | 43.9% | 337 | 501 | 42.6% |
| rcp85_10yr | 42.9% | 291 | 466 | 41.7% |
| rcp85_25yr | 42.9% | 323 | 518 | 41.9% |
| rcp85_50yr | 48.3% | 369 | 615 | 46.9% |
| rcp85_100yr | 50.2% | 395 | 632 | 48.8% |
| rcp85_200yr | 51.0% | 415 | 657 | 49.5% |
| rcp85_500yr | 53.3% | 435 | 711 | 51.8% |

Unit check. The rasters carry no value metadata, so the centimetre reading was tested
against KSDMA's own district maps for Alappuzha: their legend classes the same surface as
`Flood Water Level (m)` at <4, 4-8, 8-12 and >12 m. Those breaks are 400/800/1200 in the
raster's own units, and the district values (0 to about 1,300) reproduce exactly those
classes under a centimetre reading. The scaling is corroborated; the datum is not documented
in the raster package, and the taluk-level PDFs are labelled reference purpose only.

### What the footprint means

The modelled floodplain is broad: the 10-year historical layer already covers more than a
third of the district at a median modelled depth above 2 m. Splitting the district by
longitude (not equal-area bands) shows where that comes from:

| Layer | West (<76.40E, kayal) | Central | East (>=76.52E, upland) |
|---|---|---|---|
| historical_10yr | 20.6% / 202 cm | 62.7% / 212 cm | 19.5% / 173 cm |
| historical_25yr | 21.4% / 218 cm | 64.9% / 231 cm | 21.9% / 170 cm |
| historical_50yr | 22.3% / 251 cm | 66.2% / 250 cm | 23.5% / 179 cm |
| historical_100yr | 23.9% / 284 cm | 68.4% / 278 cm | 25.5% / 189 cm |
| historical_200yr | 25.2% / 321 cm | 70.7% / 319 cm | 26.9% / 197 cm |
| historical_500yr | 27.2% / 348 cm | 72.0% / 353 cm | 29.3% / 208 cm |
| rcp85_10yr | 23.5% / 300 cm | 70.9% / 289 cm | 32.6% / 287 cm |
| rcp85_25yr | 23.5% / 333 cm | 70.9% / 321 cm | 32.6% / 319 cm |
| rcp85_50yr | 26.3% / 376 cm | 77.6% / 364 cm | 40.0% / 399 cm |
| rcp85_100yr | 29.4% / 382 cm | 78.4% / 393 cm | 41.5% / 435 cm |
| rcp85_200yr | 30.6% / 391 cm | 78.7% / 416 cm | 42.4% / 459 cm |
| rcp85_500yr | 32.1% / 408 cm | 79.7% / 436 cm | 47.7% / 479 cm |

The concentration is in the central kayal/paddy belt (62.7% of cells at
the 10-year historical layer), against 20.6% in the western coastal band and
19.5% in the eastern midland. That ordering matches the low-lying
paddy and backwater zone, but the eastern share is high for upland terrain, and the median
modelled depth in every band is metres at a 10-year event. A state-wide hydraulic model that
does not resolve polders, field drainage and pumping keeps water standing on land that is
normally drained, so the absolute shares overstate expected inundation.

Use this layer for *relative* exposure: which PMGSY links, facilities and habitations sit in
the lowest modelled terrain, and how that set grows between return periods and climate
scenarios. Do not read a district-wide share as the area expected to flood in a given year.
Converting this to expected closures would need a district drainage/irrigation record and
observed closure or damage data, neither of which is available.

### Is the depth on water, or on dry land?

Distance from each modelled-depth cell to the nearest mapped OSM water feature:

| Layer | On/touching water | ≤100 m | 100-250 m | >250 m | Median depth beyond 250 m |
|---|---|---|---|---|---|
| historical_10yr | 2.9% | 48.0% | 34.4% | 14.7% | 194 cm |
| rcp85_100yr | 3.0% | 46.0% | 35.2% | 15.8% | 407 cm |

OSM water mapping is volunteered and incomplete, so 'far from mapped water' includes
unmapped canals and paddy drains. Read the split as an indication of whether the
footprint behaves like a floodplain delineation or like standing water on dry fields.

### External validation: attempted, not achieved

No open vector extent of an observed Kerala flood was reachable for Alappuzha: the NRSC
NDEM rapid-mapping sheet for 21 August 2018 is marked *for official use* and carries no
district area table, and HDX returns no Kerala 2018 flood-extent dataset. **The decoding
and units are validated here; the model's accuracy is not.**

Kerala's own post-2018 modelling report (CWC/KSDMA, December 2018) states that its 2D
model inundation appears larger than the satellite extent because imagery existed only
for 21 August 2018, after the peak. That is an official acknowledgement of the direction
of the bias documented above, and it is why the exposure tables are labelled relative
rather than absolute.

## PMGSY DRRP roads

Length-weighted overlap of 1,839 District Rural Roads Plan links with modelled depth. Lengths
are recomputed in UTM 43N; the service's own `st_length(shape)` is in Web Mercator and
overstates ground distance.

| Layer | Any depth (km) | Share | ≥30 cm (km) | Share |
|---|---|---|---|---|
| historical_10yr | 468 | 20.4% | 461 | 20.1% |
| historical_25yr | 512 | 22.3% | 470 | 20.5% |
| historical_50yr | 544 | 23.7% | 501 | 21.8% |
| historical_100yr | 589 | 25.7% | 549 | 23.9% |
| historical_200yr | 638 | 27.8% | 593 | 25.8% |
| historical_500yr | 686 | 29.9% | 643 | 28.0% |
| rcp85_10yr | 694 | 30.2% | 657 | 28.6% |
| rcp85_25yr | 694 | 30.2% | 662 | 28.8% |
| rcp85_50yr | 864 | 37.6% | 821 | 35.7% |
| rcp85_100yr | 900 | 39.2% | 856 | 37.3% |
| rcp85_200yr | 919 | 40.0% | 874 | 38.1% |
| rcp85_500yr | 994 | 43.3% | 943 | 41.1% |

## OSM district roads

| Layer | Any depth (km) | Share | ≥30 cm (km) | Share |
|---|---|---|---|---|
| historical_10yr | 1,652 | 20.7% | 1,624 | 20.4% |
| historical_25yr | 1,800 | 22.6% | 1,672 | 21.0% |
| historical_50yr | 1,905 | 23.9% | 1,779 | 22.3% |
| historical_100yr | 2,072 | 26.0% | 1,943 | 24.4% |
| historical_200yr | 2,233 | 28.0% | 2,094 | 26.3% |
| historical_500yr | 2,383 | 29.9% | 2,248 | 28.2% |
| rcp85_10yr | 2,339 | 29.3% | 2,213 | 27.8% |
| rcp85_25yr | 2,339 | 29.3% | 2,231 | 28.0% |
| rcp85_50yr | 2,903 | 36.4% | 2,742 | 34.4% |
| rcp85_100yr | 3,056 | 38.3% | 2,891 | 36.3% |
| rcp85_200yr | 3,136 | 39.3% | 2,962 | 37.2% |
| rcp85_500yr | 3,345 | 41.9% | 3,174 | 39.8% |

## Facilities and settlements

Shown for four representative layers (10-year and 100-year historical, 100-year and
500-year RCP8.5); all twelve are in `summary.json` and the per-layer CSVs.

| Layer | Records | Any depth | ≥30 cm | Population in ≥30 cm |
|---|---|---|---|---|
| osm_health · historical_10yr | 425 | 45 (10.6%) | 42 (9.9%) | not applicable |
| osm_health · historical_100yr | 425 | 63 (14.8%) | 55 (12.9%) | not applicable |
| osm_health · rcp85_100yr | 425 | 139 (32.7%) | 121 (28.5%) | not applicable |
| osm_health · rcp85_500yr | 425 | 162 (38.1%) | 147 (34.6%) | not applicable |
| osm_school · historical_10yr | 1,000 | 104 (10.4%) | 97 (9.7%) | not applicable |
| osm_school · historical_100yr | 1,000 | 159 (15.9%) | 142 (14.2%) | not applicable |
| osm_school · rcp85_100yr | 1,000 | 299 (29.9%) | 274 (27.4%) | not applicable |
| osm_school · rcp85_500yr | 1,000 | 329 (32.9%) | 303 (30.3%) | not applicable |
| pmgsy_habitation · historical_10yr | 1,981 | 457 (23.1%) | 454 (22.9%) | 487,698 of 2,169,418 |
| pmgsy_habitation · historical_100yr | 1,981 | 575 (29.0%) | 535 (27.0%) | 573,052 of 2,169,418 |
| pmgsy_habitation · rcp85_100yr | 1,981 | 845 (42.7%) | 816 (41.2%) | 882,478 of 2,169,418 |
| pmgsy_habitation · rcp85_500yr | 1,981 | 916 (46.2%) | 882 (44.5%) | 943,417 of 2,169,418 |
| osm_place · historical_10yr | 168 | 27 (16.1%) | 26 (15.5%) | not applicable |
| osm_place · historical_100yr | 168 | 36 (21.4%) | 32 (19.0%) | not applicable |
| osm_place · rcp85_100yr | 168 | 63 (37.5%) | 58 (34.5%) | not applicable |
| osm_place · rcp85_500yr | 168 | 69 (41.1%) | 66 (39.3%) | not applicable |
| census_village_located · historical_10yr | 22 | 10 (45.5%) | 10 (45.5%) | 156,057 of 437,682 |
| census_village_located · historical_100yr | 22 | 11 (50.0%) | 10 (45.5%) | 156,057 of 437,682 |
| census_village_located · rcp85_100yr | 22 | 14 (63.6%) | 14 (63.6%) | 242,947 of 437,682 |
| census_village_located · rcp85_500yr | 22 | 14 (63.6%) | 14 (63.6%) | 242,947 of 437,682 |
| crossing_candidate · historical_10yr | 3,859 | 1,263 (32.7%) | 1,241 (32.2%) | not applicable |
| crossing_candidate · historical_100yr | 3,859 | 1,544 (40.0%) | 1,457 (37.8%) | not applicable |
| crossing_candidate · rcp85_100yr | 3,859 | 1,992 (51.6%) | 1,936 (50.2%) | not applicable |
| crossing_candidate · rcp85_500yr | 3,859 | 2,138 (55.4%) | 2,071 (53.7%) | not applicable |

## Interpretation limits

KSDMA depth is a modelled return-period hazard on a ~90 m grid, produced from hydrological
simulation of historical and RCP8.5 climate inputs. It is not an observed flood map: the
2018 and 2019 events are not this product. Sampling a road at 100 m intervals against a
90 m cell means exposure shares are approximate at the corridor scale, not asset-level.
The 30 cm band is an indicative depth at which a light vehicle should not cross; it is a
decision threshold applied to modelled depth, not recorded closures.

Crossing candidates are unverified geometric road/water intersections, so a candidate in a
flooded cell identifies a place to inspect, not a failing bridge or culvert. PMGSY population
fields and Census 2011 totals remain separate sources and are never summed. Census villages
without a defensible coordinate are excluded rather than placed arbitrarily.

The rasters are published as a state-wide hazard product, so they are not an asset survey.
KSDMA's own map sheets carry the note that external boundaries are not verified and are for
reference purpose only; this analysis inherits that limitation together with the district
boundary's 2011 vintage and the volunteered OSM road and facility mapping.

Per-road and per-point depth tables are in this directory; machine-readable aggregates are in
`summary.json`. Each point layer is its own CSV:
`osm_health_depth.csv`, `osm_school_depth.csv`, `pmgsy_habitation_depth.csv`,
`osm_place_depth.csv`, `census_village_located_depth.csv`, `crossing_candidate_depth.csv`.
