# Reply workbook format

Copy this directory to `data/raw/pwd/<reply-name>/`, rename nothing, and paste the reply's
numbers into the CSVs. XLSX works too: point a manifest entry at the file and give a sheet
(`"closures": {"file": "reply.xlsx", "sheet": "Closures"}`).

Then run:

```
python scripts/ingest_pwd_reply.py data/raw/pwd/<reply-name> --write-docs
```

The tool refuses to proceed if the manifest has no `office`, `application_ref` or
`reply_date`, because a value with no provenance may not override an assumption.

---

## `manifest.json`

| Key | Meaning |
|---|---|
| `office` | The public authority that replied, as written on the reply |
| `application_ref` | The RTI application/receipt number — this is what makes a value citable |
| `reply_date` | `YYYY-MM-DD` |
| `tables` | Which file (or `{file, sheet}`) holds each table; omit a table you did not ask for |

## Tables

Column headers are matched loosely: case, spaces and punctuation are ignored, and common
alternatives are accepted (for example `structure type`, `type` or `class`; `date of
closure`, `closure date` or `date of failure`). Extra columns are ignored. A missing
*required* column stops the run and names both the field and the headers it would accept.

### `structures.csv`

| Column | Required | Notes |
|---|---|---|
| `structure_id` | yes | Any stable identifier; used to join the other tables |
| `structure_type` | yes | `culvert`, `box culvert`, `minor bridge`, `major bridge`. Anything else (`causeway`, `RCC bridge`, `vent`) is reported as unmapped and excluded, never guessed into a class |
| `span_m`, `year_built`, `road`, `page` | no | Coverage only; no register parameter reads them yet |

### `inspections.csv`

| Column | Required | Notes |
|---|---|---|
| `structure_id` | yes | |
| `inspection_date` | yes | ISO (`2021-06-10`) preferred; other formats fall back to day-first |
| `rating` | yes | Text (`Good`, `Fair`, `Poor`, `Severe`) or a number |
| `rating_scheme` | **required for numeric ratings** | `1-4` (1 = best) or `0-3` (0 = best). An unstated numeric scale is refused, because a wrong guess would invert every condition in the reply |
| `page` | no | Reply page number, recorded in the provenance trail |

Two or more inspections per structure are what make a repair effect measurable: the tool
takes the last rating before a work's completion date and the first one after it.

**The gap is corrected for deterioration.** Those two inspections can be a year apart, so
their difference is repair *minus* ordinary deterioration. The tool measures each
structure's own condition trend from inspections that precede its first recorded work
(median steps per year), multiplies that by each pair's inspection gap, and adds it back —
a repair followed by a one-step drop over a year on a structure that loses a step a year is
flat, not a contradiction. `coverage.json → repair_pairs` reports the rate, its sample, the
median and maximum gap, and three counts: `worsened` (worse than the no-repair
counterfactual — a real contradiction), `worsened_unadjusted` (raw worse readings, usually
just a long gap) and `unadjudicated` (worse readings with no pre-work history to judge them
against, so no contradiction is claimed). Contradictory pairs are dropped from the median,
not treated as fatal to the type: the override still applies whenever at least `MIN_SAMPLE`
(5) usable adjusted pairs remain afterwards. A type becomes unusable only when dropping them
leaves fewer than 5, and the skip reason is then `insufficient_or_contradictory` with the
contradiction count.

**The adjusted recovery is capped at the pre-work condition.** A structure at Fair (2) can
recover at most two steps, because Good (0) is the floor of the scale. Without that cap,
adding a year of deterioration to a post-repair reading already at Good implies a condition
below the floor and can push a minor effect past the 3-step axis. A pair that hits the cap
uses the structure's pre-work condition instead of the larger adjusted value; the count is
reported as `coverage.json → repair_pairs.capped`, each affected pair is listed in
`capped_pairs` (structure, work type, pre-work condition, uncapped value, value used), and
the override's provenance detail names how many pairs were capped.

**The correction is not a full fix.** It is a single median rate applied to every pair, not
a per-structure forecast, and the history must predate the first work (a structure inspected
only after repair contributes no rate). The residual bias therefore runs both ways:

- a repaired structure that deteriorates **faster** than its pre-repair record leaves some
deterioration in the estimate, so the effect is **understated**;
- one that deteriorates **more slowly** (or not at all) has deterioration added that did not
  occur, so the effect is **overstated**.

The provenance detail records which of these applied to each override, so the direction of
the remaining bias is visible next to the value.

### `closures.csv`

| Column | Required | Notes |
|---|---|---|
| `structure_id` | yes | |
| `closed_date`, `reopened_date` | yes | Duration is computed from these; a structure still closed at the time of reply is kept for coverage but excluded from the median |
| `structure_type` | no | Taken from `structures.csv` when absent |
| `cause`, `page` | no | `cause` is recorded but not yet used |

Negative durations and unparseable dates are counted in `coverage.json` and dropped — never
clipped to zero.

### `expenditure.csv`

| Column | Required | Notes |
|---|---|---|
| `structure_id` | yes | |
| `work_type` | yes | `minor repair`, `major repair`, `rehabilitation`, `reconstruction`, `replacement`, `emergency restoration`. **Routine maintenance is deliberately excluded**: it is not a condition reset, and mixing it in biases the repair effect downwards |
| `completed_date` | yes | The date the work finished, used to bracket the before/after inspections |
| `sanctioned_crore`, `spent_crore` | no | Used with `estimate_crore` for the emergency premium; these amounts do not set the Schedule-of-Rates base cost |
| `estimate_crore` | no | With `spent_crore`, gives the emergency premium (spend ÷ departmental estimate) |
| `crew_days` | no | Read as reply coverage, but **not currently used for a crew-days override** |

### `sor.csv`

| Column | Required | Notes |
|---|---|---|
| `structure_type` | yes | Same vocabulary as above |
| `intervention` | yes | `minor`, `major`, `replace`, or the work-type wording above |
| `rate_crore` | yes | **₹ crore**, not lakh or rupees — the whole project uses one unit |
| `item`, `crew_days`, `page` | no | `item` is kept in provenance detail; SoR `crew_days` is the source used for labour overrides (expenditure `crew_days` is not) |

The register's base cost is a *minor*-repair cost, scaled by `COST_MULTIPLIER`
(1 / 4 / 12 for minor / major / replace). If the reply only has major or replace rates, the
base is backed out by dividing by that multiplier and the method is recorded.

**Units are guarded.** `rate_crore` must be ₹ crore. A rate that implies a base cost more
than 25× away from the register's placeholder (in either direction) is refused as an
implausible magnitude — the usual cause is a bare `Rate` column holding ₹ lakh — and listed
under `coverage.json → schedule_of_rates.rejected_implausible` with the median, the ratio and
a unit hint. The placeholder then stays in force, so the plan remains fundable instead of
being priced out of its budget.

`crew_days` is derived the same way and from the **same intervention** as the base cost:
median crew days of those items, divided by `LABOUR_MULTIPLIER` (1 / 2.5 / 6). Mixing
interventions would otherwise scale a major item's crew days twice — a type whose reply
only quotes major items would charge a major repair its crew days *and* the major
multiplier. The divisor and the source intervention are recorded in the provenance detail.

---

## What the tool will not do

- **It will not impute.** A row with an unusable date or an unstated rating scale is
  dropped and counted, never repaired.
- **It will not fit a median to a handful of rows.** A group needs at least 5 usable
  observations (`MIN_SAMPLE`); otherwise the assumption stays and the reason is logged.
- **It will not absorb a contradiction.** A worse first-after rating is not treated as a
  contradiction on its own: the rating expected at that inspection with no repair at all
  (the pre-work rating plus observed deterioration over the gap) is computed first, and only
  a reading worse than that counterfactual is counted. With no pre-work history there is no
  counterfactual, so a worse reading is reported as `unadjudicated` and left out of the
  median instead of being called a contradiction. A contradiction removes that pair, not
  the whole type: with at least `MIN_SAMPLE` (5) usable adjusted pairs left, the override is
  fitted to the remaining ones and the contradiction count is still reported in
  `coverage.json`. Only when fewer than 5 usable pairs remain does the type stay assumed,
  logged as `insufficient_or_contradictory`.
- **It will not call a computed number `real`.** Anything the tool calculates is `fitted`.
  Only a value the reply states directly is `real`.
- **It will not touch `deterioration_acceleration`.** Condition transitions are exported to
  `condition_transitions.csv` for later fitting; converting an observed rate into the
  simulator's multiplier is a modelling decision, not an ingestion step.

## Outputs

| File | Contents |
|---|---|
| `register_overrides.json` | Every override with office, application reference, reply date, table, page, statistic and sample size — plus every parameter left alone and why |
| `coverage.json` | Rows read, rows usable, unmapped structure/work types, bad dates, still-closed records |
| `condition_transitions.csv` | Inspection-to-inspection condition change per structure-year |
| `docs/assumptions_measured.md` | With `--write-docs`: the applied overrides, for citation next to `docs/assumptions.md` |
