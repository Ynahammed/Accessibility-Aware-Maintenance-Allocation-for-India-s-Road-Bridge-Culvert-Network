# Assumptions register

Auto-generated from `src/rra/assumptions.py` — do not edit by hand.
Every entry is an **assumed** or **fitted** quantity that is *varied*, not claimed.

| Parameter | Unit | Range | Default | Source | Why needed | How varied |
|---|---|---|---|---|---|---|
| `fragility_beta0` | logit | -6–-1 | -3 | assumed | Baseline failure log-odds; no Indian failure labels exist. | Swept across the range; reported as a sensitivity axis. |
| `fragility_beta1` | logit per condition step | 0.3–3 | 1.2 | assumed | Condition drives failure probability. | Swept slope; threshold behaviour tested. |
| `fragility_beta2` | logit per log rain ratio | 0.5–4 | 2 | assumed | Rainfall loading above the local reference level. | Swept slope. |
| `fragility_rain_ref_level` | return period (years) | 2–10 | 5 | assumed | Reference rainfall event defining R=1. | Swept; stress scenarios use fixed return levels. |
| `deterioration_acceleration` | multiplier | 1–3 | 1.5 | assumed | Indian climate/load/maintenance differ from NBI conditions. | Multiplier on hazard rates; reported as a sensitivity axis. |
| `repair_effect_minor` | condition-step reset | 0–1 | 0.5 | assumed | Minor repair effect on condition. | Range per intervention type; regret reported. |
| `repair_effect_major` | condition-step reset | 1–3 | 2 | assumed | Major repair effect on condition. | Range per intervention type; regret reported. |
| `repair_effect_replace` | condition-step reset | 3–4 | 4 | assumed | Replacement resets to Good. | Effectively full reset. |
| `outage_mean_days_culvert` | days | 3–30 | 10 | assumed | Outage duration after failure (no repair-time records). | Swept mean by structure type. |
| `outage_mean_days_minor_bridge` | days | 7–90 | 30 | assumed | Outage duration after failure. | Swept mean by structure type. |
| `outage_mean_days_major_bridge` | days | 30–365 | 120 | assumed | Outage duration after failure. | Swept mean by structure type. |
| `emergency_premium` | multiplier | 1–3 | 1.8 | assumed | Restoring a failed asset costs more than a planned repair. | Swept multiplier. |
| `facility_weight_health` | weight | 0.5–3 | 1 | assumed | Relative importance of access to health services. | Grid over weights; rank-stability tests. |
| `facility_weight_school` | weight | 0.5–3 | 1 | assumed | Relative importance of access to schools. | Grid over weights; rank-stability tests. |
| `travel_time_cap_health` | minutes | 30–120 | 60 | assumed | Acceptable travel time to a health facility. | Grid over caps; rank-stability tests. |
| `travel_time_cap_school` | minutes | 20–90 | 45 | assumed | Acceptable travel time to a school. | Grid over caps; rank-stability tests. |
| `snap_tolerance_m` | metres | 10–50 | 25 | assumed | Distance within which an asset attaches to the nearest network node. | Fixed near 25 m; logged overshoots. |
| `speed_rural_kph` | km/h | 20–40 | 30 | assumed | Free-flow speed on rural (PMGSY) roads. | Fixed; sensitivity checked. |
| `speed_state_kph` | km/h | 40–60 | 50 | assumed | Free-flow speed on state highways. | Fixed; sensitivity checked. |
| `speed_national_kph` | km/h | 60–90 | 70 | assumed | Free-flow speed on national highways. | Fixed; sensitivity checked. |
| `speed_connector_kph` | km/h | 3–15 | 5 | assumed | Last-mile (walking) speed on the connector from an asset to the road node. | Fixed; sensitivity checked. |
