"""Ingest a PWD/RTI reply into measured overrides for the assumptions register.

The register (`rra.assumptions`) is the project's single source of truth for quantities
that are *assumed*. When a public authority answers an RTI request, some of those
quantities stop being assumptions. This module is the only path by which a parameter may
change from ``assumed`` to ``real``/``fitted``, and it enforces four rules so that the
change is defensible:

1. **Provenance is mandatory.** Every override carries the office, the application
   reference, the reply date, the table and (if known) the page it came from. A reply
   without a reference number or date is refused outright.
2. **``real`` means transcribed.** A value the reply states directly (a rate in the
   Schedule of Rates, a single closure duration tied to one structure) is ``real``.
   Anything this module *computes* — a median, a ratio, an aggregate — is ``fitted``.
3. **Samples must be adequate.** A group (for example culvert closures) needs at least
   ``MIN_SAMPLE`` usable observations. Below that the assumption is left alone and the
   reason is recorded, because a median of two numbers is not a measurement.
4. **Contradictions are reported, not absorbed.** If the record implies a repair makes
   condition worse, the parameter is not overridden; the direction conflict is logged.

Nothing is imputed: rows with unusable dates or an unstated rating scheme are dropped and
counted in ``coverage`` rather than guessed at.

Typical use
-----------
    python scripts/ingest_pwd_reply.py data/raw/pwd/rti_2026_11 --write-docs

The reply directory is described by ``manifest.json`` (see
``docs/rti/reply_template/README.md``); tables may be CSV or XLSX.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from rra.assumptions import AssumptionRegister

# A group needs this many usable observations before a median may replace an assumption.
MIN_SAMPLE = 5

# A derived base cost may differ from the register's placeholder by at most this factor.
# A unit error is systematic and large: reading "Rate" values in Rs lakh as Rs crore inflates
# every rate 100x, which silently empties every plan because nothing fits the budget. The band
# refuses such a rate and reports it, instead of applying it and calling it measured.
MAX_COST_RATIO = 25.0

SourceTag = Literal["real", "fitted"]

# --- column aliases -----------------------------------------------------------------
# Real replies do not use our column names. Each logical field lists the headers we
# accept, compared case- and punctuation-insensitively.

_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "structures": {
        "structure_id": ("structure id", "structure code", "asset id", "sl no", "sl. no", "id"),
        "structure_type": ("structure type", "type", "class", "structure class"),
        "span_m": ("span m", "span", "length m", "total length m", "span length m"),
        "year_built": ("year built", "year of construction", "construction year"),
        "road": ("road", "road name", "road no", "chainage road"),
        "page": ("page", "page no", "page number", "reply page"),
    },
    "inspections": {
        "structure_id": ("structure id", "structure code", "asset id", "sl no", "sl. no", "id"),
        "inspection_date": ("inspection date", "date of inspection", "inspected on", "date"),
        "rating": ("rating", "condition", "condition rating", "grade", "condition grade"),
        "rating_scheme": ("rating scheme", "rating scale", "scale", "condition scale"),
        "page": ("page", "page no", "page number", "reply page"),
    },
    "closures": {
        "structure_id": ("structure id", "structure code", "asset id", "sl no", "sl. no", "id"),
        "structure_type": ("structure type", "type", "class", "structure class"),
        "closed_date": ("closed date", "date of closure", "closure date", "date closed",
                        "date of failure", "failure date"),
        "reopened_date": ("reopened date", "date reopened", "reopening date", "restoration date",
                          "date of reopening", "date restored"),
        "cause": ("cause", "reason", "apparent cause", "nature of damage"),
        "page": ("page", "page no", "page number", "reply page"),
    },
    "expenditure": {
        "structure_id": ("structure id", "structure code", "asset id", "sl no", "sl. no", "id"),
        "work_type": ("work type", "nature of work", "type of work", "intervention"),
        "completed_date": ("completed date", "date of completion", "completion date",
                           "date completed"),
        "sanctioned_crore": ("sanctioned crore", "sanctioned amount crore", "sanctioned",
                             "sanctioned amount"),
        "spent_crore": ("spent crore", "amount spent crore", "actual expenditure crore",
                        "expenditure crore", "amount spent"),
        "estimate_crore": ("estimate crore", "estimated cost crore", "estimate"),
        "crew_days": ("crew days", "man days", "labour days", "crew-days"),
        "page": ("page", "page no", "page number", "reply page"),
    },
    "sor": {
        "item": ("item", "item description", "description"),
        "structure_type": ("structure type", "type", "class", "structure class"),
        "intervention": ("intervention", "work type", "nature of work", "repair class"),
        "rate_crore": ("rate crore", "rate", "unit rate crore", "amount crore"),
        "crew_days": ("crew days", "man days", "labour days", "crew-days"),
        "page": ("page", "page no", "page number", "reply page"),
    },
}


class ReplyError(ValueError):
    """The reply cannot be used as supplied (bad manifest, missing columns, no provenance)."""


# --- small helpers ------------------------------------------------------------------


def _norm(value: Any) -> str:
    """Lower-case, collapse whitespace and punctuation for alias matching."""
    s = str(value).strip().lower()
    for ch in "._-/():":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _resolve(frame: pd.DataFrame, table: str, required: tuple[str, ...]) -> pd.DataFrame:
    """Rename the reply's columns to logical names, or explain exactly what is missing."""
    lookup = {}
    for col in frame.columns:
        lookup.setdefault(_norm(col), col)
    renames, missing = {}, []
    for logical in _ALIASES[table]:
        for alias in _ALIASES[table][logical]:
            if alias in lookup:
                renames[lookup[alias]] = logical
                break
    out = frame.rename(columns=renames)
    for logical in required:
        if logical not in out.columns:
            missing.append(f"{logical} (accepts: {', '.join(_ALIASES[table][logical])})")
    if missing:
        raise ReplyError(f"table '{table}' is missing required column(s): " + "; ".join(missing))
    return out


def _dates(series: pd.Series) -> pd.Series:
    """Parse dates, preferring ISO and only then falling back to day-first.

    ``dayfirst=True`` applied blindly reads an ISO string like ``2021-06-10`` as 6 October,
    silently swapping month and day. So ISO is parsed first, and the day-first rule is used
    only for the entries ISO could not read. Genuinely ambiguous ``dd/mm`` vs ``mm/dd``
    values in a non-ISO reply are read day-first, which is the Indian convention.
    """
    parsed = pd.to_datetime(series, errors="coerce", format="ISO8601")
    missing = parsed.isna()
    if bool(missing.any()):
        fallback = pd.to_datetime(series[missing], errors="coerce", dayfirst=True)
        parsed = parsed.copy()
        parsed.loc[missing] = fallback
    return parsed


def _page_of(row: pd.Series) -> str | None:
    page = row.get("page")
    if page is None or (isinstance(page, float) and math.isnan(page)) or str(page).strip() == "":
        return None
    return str(page).strip()


# --- structure / work vocabularies ---------------------------------------------------

_TYPE_MAP = {
    "culvert": "culvert",
    "box culvert": "culvert",
    "pipe culvert": "culvert",
    "slab culvert": "culvert",
    "minor bridge": "minor_bridge",
    "minor br": "minor_bridge",
    "major bridge": "major_bridge",
    "major br": "major_bridge",
}

# Work types that reset condition, mapped to the intervention they correspond to.
# Routine maintenance is deliberately excluded: it is not a condition reset, so mixing it
# in would bias the repair effect downwards.
_WORK_MAP = {
    "minor": "minor",
    "minor repair": "minor",
    "major": "major",
    "major repair": "major",
    "rehabilitation": "major",
    "reconstruction": "replace",
    "replacement": "replace",
    "emergency": "emergency",
    "emergency restoration": "emergency",
    "restoration": "emergency",
}

_EFFECT_PARAM = {
    "minor": "repair_effect_minor",
    "major": "repair_effect_major",
    "replace": "repair_effect_replace",
}


def _structure_type(value: Any) -> str | None:
    """Map a reply's structure type to the register's vocabulary, or None if unknown."""
    key = _norm(value)
    if key in _TYPE_MAP:
        return _TYPE_MAP[key]
    # accept "minor bridge (RCC)" style suffixes only when the prefix is unambiguous
    for prefix, mapped in _TYPE_MAP.items():
        if key.startswith(prefix + " "):
            return mapped
    return None


def _work_type(value: Any) -> str | None:
    return _WORK_MAP.get(_norm(value))


def _condition(value: Any, scheme: Any) -> int | None:
    """Map a stated rating to 0 Good .. 3 Severe. Refuses to guess a numeric scale."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = _norm(value)
    words = {
        "good": 0, "fair": 1, "poor": 2, "severe": 3, "very poor": 3,
        "satisfactory": 1, "distressed": 2, "critical": 3,
    }
    if text in words:
        return words[text]
    scale = _norm(scheme) if scheme is not None else ""
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if scale in {"0 3", "0 to 3", "0 3 severity", "severity 0 3"}:
        mapped = int(round(number))
    elif scale in {"1 4", "1 to 4", "1 4 grade", "grade 1 4"}:
        mapped = int(round(number)) - 1  # 1 = best
    else:
        return None  # an unstated numeric scale could be inverted; never guess
    return mapped if 0 <= mapped <= 3 else None


# --- provenance and results ----------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    office: str
    application_ref: str
    reply_date: str
    table: str
    statistic: str  # "stated" | "median" | "median-ratio"
    n: int
    page: str | None = None
    detail: str = ""


@dataclass
class Update:
    """One parameter (or rate) whose value came from a reply."""

    parameter: str
    value: float
    source: SourceTag
    provenance: Provenance
    previous: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "previous": self.previous,
            "provenance": asdict(self.provenance),
            "note": self.note,
        }


@dataclass
class Overrides:
    register: dict[str, Update] = field(default_factory=dict)
    rates: dict[str, Update] = field(default_factory=dict)  # Schedule of Rates base costs
    labour: dict[str, Update] = field(default_factory=dict)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)  # kept out of the JSON

    def skip(self, parameter: str, reason: str, **extra: Any) -> None:
        self.skipped.append({"parameter": parameter, "reason": reason, **extra})

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "manifest": self.manifest,
            "register": {k: v.as_dict() for k, v in self.register.items()},
            "schedule_of_rates": {k: v.as_dict() for k, v in self.rates.items()},
            "labour_days": {k: v.as_dict() for k, v in self.labour.items()},
            "skipped": self.skipped,
            "coverage": self.coverage,
        }


# --- reading the reply ---------------------------------------------------------------

_REQUIRED: dict[str, tuple[str, ...]] = {
    "structures": ("structure_id", "structure_type"),
    "inspections": ("structure_id", "inspection_date", "rating"),
    "closures": ("structure_id", "closed_date", "reopened_date"),
    "expenditure": ("structure_id", "work_type", "completed_date"),
    "sor": ("structure_type", "intervention", "rate_crore"),
}


def _read_spec(folder: Path, spec: Any) -> pd.DataFrame:
    """Read one table described by a manifest entry (path or {file, sheet})."""
    if isinstance(spec, str):
        path, sheet = folder / spec, 0
    elif isinstance(spec, dict):
        path, sheet = folder / spec["file"], spec.get("sheet", 0)
    else:
        raise ReplyError(f"unusable table spec: {spec!r}")
    if not path.exists():
        raise ReplyError(f"listed reply file does not exist: {path}")
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet, dtype=object)
    return pd.read_csv(path, dtype=object, encoding_errors="replace")


def load_reply(folder: str | Path) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """Read ``manifest.json`` and every table it lists.

    The manifest must carry the provenance that makes the data citable::

        {"office": "...", "application_ref": "...", "reply_date": "YYYY-MM-DD",
         "tables": {"closures": "closures.csv", ...}}
    """
    folder = Path(folder)
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise ReplyError(f"no manifest.json in {folder}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("office", "application_ref", "reply_date"):
        if not str(manifest.get(key, "")).strip():
            raise ReplyError(
                f"manifest is missing '{key}'; a reply without provenance cannot override "
                "an assumption"
            )
    try:
        date.fromisoformat(str(manifest["reply_date"]))
    except ValueError as exc:
        raise ReplyError(f"reply_date must be YYYY-MM-DD, got {manifest['reply_date']!r}") from exc

    tables = {}
    for name, spec in (manifest.get("tables") or {}).items():
        if name not in _REQUIRED:
            raise ReplyError(f"unknown table '{name}' in manifest")
        tables[name] = _resolve(_read_spec(folder, spec), name, _REQUIRED[name])
    return manifest, tables


# --- derivations ---------------------------------------------------------------------


def _median_update(
    parameter: str,
    values: list[float],
    provenance: Provenance,
    previous: dict[str, Any],
    *,
    allow_negative: bool = False,
) -> Update | None:
    """Median of ``values`` as a fitted override, or None when the sample is too small."""
    usable = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(usable) < MIN_SAMPLE:
        return None
    median = float(np.median(usable))
    if median < 0 and not allow_negative:
        return None
    prov = replace(provenance, n=len(usable), statistic="median")
    return Update(
        parameter=parameter,
        value=median,
        source="fitted",
        provenance=prov,
        previous=previous,
        note=f"median over {len(usable)} observations (min n={MIN_SAMPLE})",
    )


def _previous(register: AssumptionRegister, name: str) -> dict[str, Any]:
    p = register[name]
    return {"default": p.default, "low": p.low, "high": p.high, "source": p.source}


def _deterioration_rate(
    inspections: pd.DataFrame, work: pd.DataFrame
) -> tuple[float | None, int]:
    """Median condition steps per year from inspections that precede any recorded work.

    A repair effect is measured between the last inspection before a work and the first one
    after it, so the gap contains ordinary deterioration. This rate is what lets the
    estimator add that deterioration back instead of reading it as a weak repair.

    Only inspections *before* a structure's first recorded work are used: inspections after
    a repair show the repair, not the deterioration, and would bias the rate downwards.
    Returns ``(rate, n_observations)``; ``rate`` is None when the reply has no usable
    pre-work interval, in which case the estimate cannot be adjusted and says so.
    """
    first_work = work.groupby("structure_id")["_done"].min()
    slopes: list[float] = []
    for sid, group in inspections.sort_values("_date").groupby("structure_id"):
        cutoff = first_work.get(sid)
        g = group
        if cutoff is not None and not pd.isna(cutoff):
            g = g[g["_date"] < cutoff]
        g = g.sort_values("_date").reset_index(drop=True)
        for i in range(len(g) - 1):
            years = (g.loc[i + 1, "_date"] - g.loc[i, "_date"]).days / 365.25
            if years > 0:
                slopes.append((g.loc[i + 1, "_cond"] - g.loc[i, "_cond"]) / years)
    if not slopes:
        return None, 0
    # deterioration cannot be negative; a negative median means the history is dominated by
    # unrecorded improvements, so no adjustment is defensible.
    return max(float(np.median(slopes)), 0.0), len(slopes)


def derive(
    manifest: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    register: AssumptionRegister,
) -> Overrides:
    """Turn reply tables into register overrides, recording everything left alone."""
    out = Overrides(manifest=manifest)
    base = Provenance(
        office=str(manifest["office"]),
        application_ref=str(manifest["application_ref"]),
        reply_date=str(manifest["reply_date"]),
        table="",
        statistic="stated",
        n=0,
    )
    coverage: dict[str, Any] = {}

    # -- structures: coverage only, no register parameter reads the inventory directly
    if "structures" in tables:
        st = tables["structures"].copy()
        st["_type"] = st["structure_type"].map(_structure_type)
        coverage["structures"] = {
            "rows": int(len(st)),
            "mapped_type": int(st["_type"].notna().sum()),
            "unmapped_types": sorted(
                {str(v).strip() for v in st.loc[st["_type"].isna(), "structure_type"].dropna()}
            ),
            "by_type": {k: int(v) for k, v in st["_type"].value_counts().items()},
        }

    # -- closures -> outage days by structure type
    if "closures" in tables:
        cl = tables["closures"].copy()
        cl["_type"] = cl["structure_type"].map(_structure_type) if "structure_type" in cl else None
        if cl["_type"] is None or cl["_type"].isna().all():
            # fall back to the structures table so a closures sheet need not repeat type
            if "structures" in tables:
                types = tables["structures"].assign(
                    _type=lambda d: d["structure_type"].map(_structure_type)
                )[["structure_id", "_type"]]
                cl = cl.drop(columns=["_type"], errors="ignore").merge(
                    types, on="structure_id", how="left"
                )
            else:
                cl["_type"] = None
        cl["_closed"] = _dates(cl["closed_date"])
        cl["_reopened"] = _dates(cl["reopened_date"])
        cl["_days"] = (cl["_reopened"] - cl["_closed"]).dt.total_seconds() / 86400.0
        bad_dates = int(cl["_closed"].isna().sum())
        bad_days = int((cl["_days"] < 0).sum())
        cl.loc[cl["_days"] < 0, "_days"] = np.nan
        coverage["closures"] = {
            "rows": int(len(cl)),
            "unparseable_closed_date": bad_dates,
            "negative_duration": bad_days,
            "typed": int(cl["_type"].notna().sum()),
            "still_closed": int(cl["_reopened"].isna().sum()),
        }

        for stype, parameter in (
            ("culvert", "outage_mean_days_culvert"),
            ("minor_bridge", "outage_mean_days_minor_bridge"),
            ("major_bridge", "outage_mean_days_major_bridge"),
        ):
            subset = cl[cl["_type"] == stype]
            days = subset["_days"].dropna().tolist()
            pages = sorted({p for p in subset.apply(_page_of, axis=1) if p})
            update = _median_update(
                parameter,
                days,
                replace(base, table="closures", page=",".join(pages) or None,
                        detail=f"closure duration, {stype}"),
                _previous(register, parameter),
            )
            if update is None:
                out.skip(parameter, "fewer_than_min_n", n=len(days), required=MIN_SAMPLE)
            else:
                out.register[parameter] = update

    # -- inspections -> repair effects (needs expenditure for the work dates)
    inspections = None
    if "inspections" in tables:
        ins = tables["inspections"].copy()
        ins["_date"] = _dates(ins["inspection_date"])
        ins["_cond"] = [
            _condition(r.get("rating"), r.get("rating_scheme")) for _, r in ins.iterrows()
        ]
        refused = int(ins["_cond"].isna().sum())
        ins = ins[ins["_cond"].notna() & ins["_date"].notna()]
        coverage["inspections"] = {
            "rows": int(len(tables["inspections"])),
            "usable": int(len(ins)),
            "refused_unstated_scale_or_unparseable": refused,
        }
        inspections = ins

        # descriptive only: consecutive-inspection condition change, per year. This is an
        # export for later fitting, not an override — turning a rate into the simulator's
        # multiplier needs a modelling decision that a reply cannot make.
        if len(ins) > 1:
            rows = []
            for sid, group in ins.sort_values("_date").groupby("structure_id"):
                g = group.reset_index(drop=True)
                for i in range(len(g) - 1):
                    years = (g.loc[i + 1, "_date"] - g.loc[i, "_date"]).days / 365.25
                    if years > 0:
                        rows.append(
                            {
                                "structure_id": sid,
                                "from_state": int(g.loc[i, "_cond"]),
                                "to_state": int(g.loc[i + 1, "_cond"]),
                                "years": years,
                                "steps_per_year": (g.loc[i + 1, "_cond"] - g.loc[i, "_cond"]) / years,
                            }
                        )
            frame = pd.DataFrame(rows)
            out.frames["condition_transitions"] = frame
            coverage["condition_transitions"] = {"rows": int(len(frame))}

    if "expenditure" in tables:
        ex = tables["expenditure"].copy()
        ex["_work"] = ex["work_type"].map(_work_type)
        ex["_done"] = _dates(ex["completed_date"])
        coverage["expenditure"] = {
            "rows": int(len(ex)),
            "mapped_work_type": int(ex["_work"].notna().sum()),
            "unmapped_work_types": sorted(
                {str(v).strip() for v in ex.loc[ex["_work"].isna(), "work_type"].dropna()}
            ),
        }

        if inspections is not None:
            work = ex[ex["_work"].notna() & ex["_done"].notna()][
                ["structure_id", "_work", "_done"]
            ].copy()
            work["work_id"] = range(len(work))
            merged = work.merge(
                inspections[["structure_id", "_date", "_cond"]], on="structure_id", how="inner"
            )
            before = (
                merged[merged["_date"] < merged["_done"]]
                .sort_values("_date")
                .groupby("work_id")
                .last()[["_cond", "_date"]]
                .rename(columns={"_cond": "_before", "_date": "_before_date"})
            )
            after = (
                merged[merged["_date"] > merged["_done"]]
                .sort_values("_date")
                .groupby("work_id")
                .first()[["_cond", "_date"]]
                .rename(columns={"_cond": "_after", "_date": "_after_date"})
            )
            pairs = (
                work.set_index("work_id")
                .join(before)
                .join(after)
                .reset_index(drop=True)
                .dropna(subset=["_before", "_after"])
            )
            # the pair spans two inspection dates, and the condition change across that
            # whole interval is repair *minus* ordinary deterioration. Measure each
            # structure's own pre-work deterioration rate and add the deterioration
            # expected over the pair's gap back in, so a year-long gap is not read as a
            # weaker repair (or, when the sign flips, as a contradiction).
            pairs["_gap_years"] = pairs["_after_date"].sub(pairs["_before_date"]).dt.days / 365.25
            rate, rate_n = _deterioration_rate(inspections, work)
            pairs["_deterioration"] = (
                pairs["_gap_years"] * rate if rate is not None else np.nan
            )
            pairs["_recovered"] = pairs["_before"] - pairs["_after"]
            # Counterfactual: the condition the structure would have reached with no repair,
            # i.e. the rating before the work plus the deterioration expected over the gap.
            # Only a rating worse than that counterfactual contradicts a working repair. When
            # no rate could be measured there is no counterfactual, so a worse reading is
            # *unadjudicated*: it is reported, never counted as a contradiction.
            adjudicated = rate is not None
            uncapped = (
                pairs["_recovered"] + pairs["_deterioration"]
                if adjudicated
                else np.nan
            )
            pairs["_adjusted_uncapped"] = uncapped
            # A repair cannot recover more steps than the structure had before the work:
            # the condition scale runs 0 (Good) to 3 (Severe), and adding a year of
            # deterioration to a post-repair reading already at Good would imply a
            # condition below the floor and can push a minor effect past the axis.
            if adjudicated:
                pairs["_capped"] = uncapped > pairs["_before"]
                pairs["_adjusted"] = np.minimum(uncapped, pairs["_before"])
            else:
                pairs["_capped"] = False
                pairs["_adjusted"] = np.nan
            raw_worse = pairs["_recovered"] < 0
            genuine = int((pairs["_adjusted"] < 0).sum()) if adjudicated else 0
            coverage["repair_pairs"] = {
                "rows": int(len(pairs)),
                "by_intervention": {
                    k: int(v) for k, v in pairs["_work"].value_counts().items()
                },
                # a genuine contradiction: worse than the no-repair counterfactual
                "worsened": genuine,
                # a worse *raw* reading is usually just a long gap, not a contradiction
                "worsened_unadjusted": int(raw_worse.sum()),
                # worse, but no deterioration history to judge it against: not a contradiction
                "unadjudicated": int(raw_worse.sum()) if not adjudicated else 0,
                # adjusted recovery reduced to the pre-work condition (0 is the floor, so a
                # structure cannot recover more steps than it had before the repair)
                "capped": int(pairs["_capped"].sum()),
                "capped_pairs": [
                    {
                        "structure_id": str(row["structure_id"]),
                        "work": str(row["_work"]),
                        "before": int(row["_before"]),
                        "adjusted_uncapped": round(float(row["_adjusted_uncapped"]), 3),
                        "used": int(row["_adjusted"]),
                    }
                    for _, row in pairs[pairs["_capped"]].iterrows()
                ],
                "cap_rule": "adjusted recovery capped at the pre-work condition",
                "deterioration_steps_per_year": (
                    None if rate is None else round(rate, 4)
                ),
                "deterioration_observations": rate_n,
                "median_gap_years": round(float(pairs["_gap_years"].median()), 3),
                "max_gap_years": round(float(pairs["_gap_years"].max()), 3),
                "adjustment": (
                    "added back median pre-work deterioration x inspection gap"
                    if adjudicated
                    else "no pre-work inspection interval; worse readings left unadjudicated"
                ),
            }
            bias_note = (
                "net of observed pre-work deterioration over the inspection gap"
                if adjudicated
                else "no pre-work history to adjust for deterioration"
            )
            for work_kind, parameter in _EFFECT_PARAM.items():
                kind = pairs[pairs["_work"] == work_kind]
                # a worse-than-counterfactual pair is dropped; an unadjudicated worse pair is
                # also left out of the median, because it cannot be attributed either way
                usable = kind["_adjusted"] >= 0 if adjudicated else kind["_recovered"] >= 0
                values = kind.loc[usable, "_recovered" if not adjudicated else "_adjusted"]
                values = values.astype(float).tolist()
                kind_capped = int(kind["_capped"].sum()) if adjudicated else 0
                cap_note = (
                    f"; {kind_capped} pair(s) capped at the pre-work condition because the "
                    "deterioration add-back would have credited more recovery than the "
                    "structure had left to recover"
                    if kind_capped
                    else ""
                )
                if adjudicated:
                    detail = (
                        f"condition steps recovered after {work_kind} work, {bias_note}; "
                        "the rate is a single median, not a per-structure forecast, so bias "
                        "remains in both directions: a repaired structure deteriorating "
                        "faster than its pre-work record keeps some deterioration in the "
                        "estimate (effect understated), and one deteriorating more slowly "
                        "has deterioration added that did not occur (effect overstated)"
                        f"{cap_note}"
                    )
                else:
                    detail = (
                        f"condition steps recovered after {work_kind} work, {bias_note}; "
                        "where the inspection gap held ordinary deterioration the effect is "
                        "understated, and the reply gives no way to correct it"
                    )
                update = _median_update(
                    parameter,
                    values,
                    replace(base, table="inspections+expenditure", page=None, detail=detail),
                    _previous(register, parameter),
                )
                if update is None:
                    conflicts = int((kind["_adjusted"] < 0).sum()) if adjudicated else 0
                    unadjudicated = int((kind["_recovered"] < 0).sum()) if not adjudicated else 0
                    out.skip(
                        parameter,
                        "insufficient_or_contradictory" if conflicts else "fewer_than_min_n",
                        n=len(values),
                        contradictions=conflicts,
                        unadjudicated=unadjudicated,
                        required=MIN_SAMPLE,
                    )
                else:
                    out.register[parameter] = update

        # emergency premium: spend on an emergency restoration over the department's estimate
        if {"spent_crore", "estimate_crore"}.issubset(ex.columns):
            em = ex[ex["_work"] == "emergency"].copy()
            spent = pd.to_numeric(em.get("spent_crore"), errors="coerce")
            estimate = pd.to_numeric(em.get("estimate_crore"), errors="coerce")
            ratio = (spent / estimate).replace([np.inf, -np.inf], np.nan).dropna()
            update = _median_update(
                "emergency_premium",
                ratio.tolist(),
                replace(base, table="expenditure", statistic="median-ratio",
                        detail="emergency restoration spend / departmental estimate"),
                _previous(register, "emergency_premium"),
            )
            if update is None:
                out.skip("emergency_premium", "fewer_than_min_n", n=int(len(ratio)),
                         required=MIN_SAMPLE)
            else:
                out.register["emergency_premium"] = update

    # -- schedule of rates -> base cost per structure type (and crew days if given)
    if "sor" in tables:
        sor = tables["sor"].copy()
        sor["_type"] = sor["structure_type"].map(_structure_type)
        sor["_work"] = sor["intervention"].map(_work_type)
        sor["_rate"] = pd.to_numeric(sor["rate_crore"], errors="coerce")
        sor = sor[sor["_type"].notna() & sor["_work"].notna() & sor["_rate"].notna()]
        coverage["schedule_of_rates"] = {
            "usable_rows": int(len(sor)),
            "by_type": {k: int(v) for k, v in sor["_type"].value_counts().items()},
            # filled below: rates refused for an implausible magnitude, kept for review
            "rejected_implausible": [],
            "max_cost_ratio": MAX_COST_RATIO,
        }
        # The register stores a *minor*-repair base for both cost and crew-days:
        # COST_MULTIPLIER / LABOUR_MULTIPLIER scale them up per intervention. So both
        # must come from the same intervention, then be divided by its multiplier —
        # otherwise a type whose reply only quotes major items charges a major repair
        # twice over (its crew-days, then LABOUR_MULTIPLIER[major] again).
        from rra.cost.interventions import COST_MULTIPLIER, LABOUR_MULTIPLIER
        from rra.cost.sor import DEFAULT_BASE_COST_CRORE

        chosen_work: dict[str, str] = {}
        implausible: dict[str, dict] = {}
        rejected: list[dict] = []
        for stype in ("culvert", "minor_bridge", "major_bridge"):
            group = sor[sor["_type"] == stype]
            if group.empty:
                out.skip(f"base_cost::{stype}", "no_matching_sor_items")
                continue
            for work in ("minor", "major", "replace"):
                rates = group[group["_work"] == work]["_rate"]
                if len(rates) < MIN_SAMPLE:
                    continue
                median_rate = float(np.median(rates))
                base_cost = median_rate / COST_MULTIPLIER[work]
                placeholder = float(DEFAULT_BASE_COST_CRORE.get(stype, 0.0))
                ratio = base_cost / placeholder if placeholder > 0 else float("inf")
                if not (1.0 / MAX_COST_RATIO <= ratio <= MAX_COST_RATIO):
                    record = {
                        "structure_type": stype,
                        "intervention": work,
                        "median_rate_crore": round(median_rate, 4),
                        "base_cost_crore": round(base_cost, 4),
                        "placeholder_crore": placeholder,
                        "ratio_to_placeholder": round(ratio, 1),
                        "n": int(len(rates)),
                        "hint": (
                            "rates must be in Rs crore, not Rs lakh/rupees; "
                            "the rate was not applied"
                        ),
                    }
                    rejected.append(record)
                    implausible[stype] = record
                    continue
                chosen_work[stype] = work
                pages = sorted({p for p in group[group["_work"] == work].apply(_page_of, axis=1) if p})
                out.rates[stype] = Update(
                    parameter=f"base_cost::{stype}",
                    value=base_cost,
                    source="fitted",
                    provenance=replace(
                        base, table="sor", page=",".join(pages) or None,
                        statistic="median", n=int(len(rates)),
                        detail=f"{work} rate {median_rate:.4g} ₹cr / "
                               f"COST_MULTIPLIER[{work}]={COST_MULTIPLIER[work]:g}",
                    ),
                    previous={"source": "assumed (placeholder)"},
                    note=f"derived from {work} works; assumes COST_MULTIPLIER",
                )
                break
            else:
                if stype in implausible:
                    record = dict(implausible[stype])
                    out.skip(
                        f"base_cost::{stype}",
                        "implausible_magnitude",
                        **{k: v for k, v in record.items() if k != "structure_type"},
                    )
                else:
                    out.skip(f"base_cost::{stype}", "no_intervention_with_enough_rows",
                             n=int(len(group)))

        coverage["schedule_of_rates"]["rejected_implausible"] = rejected

        if "crew_days" in sor.columns:
            sor["_crew"] = pd.to_numeric(sor["crew_days"], errors="coerce")
            for stype in ("culvert", "minor_bridge", "major_bridge"):
                work = chosen_work.get(stype)
                if work is None:
                    # no base cost to pair it with: leave the placeholder alone rather
                    # than average crew days across interventions we did not price.
                    reason = (
                        "implausible_magnitude" if stype in implausible
                        else "no_base_cost_intervention"
                    )
                    out.skip(f"labour_days::{stype}", reason,
                             n=int((sor["_type"] == stype).sum()))
                    continue
                mask = (sor["_type"] == stype) & (sor["_work"] == work)
                multiplier = LABOUR_MULTIPLIER[work]
                crew = sor.loc[mask, "_crew"].dropna()
                detail = (
                    f"{work} crew days {float(np.median(crew)):.4g} / "
                    f"LABOUR_MULTIPLIER[{work}]={multiplier:g}"
                    if len(crew)
                    else f"crew days, {stype}"
                )
                update = _median_update(
                    f"labour_days::{stype}",
                    (crew / multiplier).tolist(),
                    replace(base, table="sor", detail=detail),
                    {"source": "assumed (placeholder)"},
                )
                if update is not None:
                    out.labour[stype] = Update(
                        parameter=update.parameter,
                        value=update.value,
                        source=update.source,
                        provenance=update.provenance,
                        previous=update.previous,
                        note=f"derived from {work} works; assumes LABOUR_MULTIPLIER",
                    )
                else:
                    out.skip(f"labour_days::{stype}", "fewer_than_min_n", n=int(len(crew)))

    out.coverage = {k: v for k, v in coverage.items() if not isinstance(v, pd.DataFrame)}
    return out


# --- applying the overrides ----------------------------------------------------------


def effective_register(register: AssumptionRegister, overrides: Overrides) -> AssumptionRegister:
    """A register whose defaults are the measured values, with ranges widened to fit.

    A measured value outside the pre-registered sweep range is *not* clipped: the range
    expands to include it, because the observation is the point.
    """
    params = dict(register.parameters)
    for name, update in overrides.register.items():
        if name not in params:
            raise ReplyError(f"reply maps to unknown parameter {name!r}")
        p = params[name]
        low, high = min(p.low, update.value), max(p.high, update.value)
        params[name] = replace(
            p,
            default=float(update.value),
            low=float(low),
            high=float(high),
            source=update.source,
            how=f"measured — {update.provenance.statistic} n={update.provenance.n}, "
                f"RTI {update.provenance.application_ref}",
        )
    return AssumptionRegister(params)


def measured_markdown(overrides: Overrides, register: AssumptionRegister) -> str:
    """Render the applied overrides with their provenance, for docs."""
    lines = [
        "# Assumptions register — measured overrides",
        "",
        "Generated by `scripts/ingest_pwd_reply.py` from a PWD/RTI reply. "
        "`docs/assumptions.md` remains the register of *assumed* values; this table records "
        "only entries that a reply has replaced. `real` means the reply states the value; "
        "`fitted` means this tool computed it from the reply's rows.",
        "",
        f"Office: {overrides.manifest.get('office', '')}  ",
        f"Application: {overrides.manifest.get('application_ref', '')}  ",
        f"Reply dated: {overrides.manifest.get('reply_date', '')}",
        "",
        "| Parameter | Was | Now | Source | n | Statistic | Table | Page |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, u in overrides.register.items():
        was = f"{u.previous.get('default', '')} ({u.previous.get('source', '')})"
        lines.append(
            f"| `{name}` | {was} | {u.value:g} | {u.source} | {u.provenance.n} | "
            f"{u.provenance.statistic} | {u.provenance.table} | {u.provenance.page or '—'} |"
        )
    if overrides.rates:
        lines += ["", "## Schedule of Rates (base minor-repair cost, ₹ crore)", "",
                  "| Structure | Base cost | Method | n | Application |", "|---|---|---|---|---|"]
        for stype, u in overrides.rates.items():
            lines.append(
                f"| {stype} | {u.value:.4f} | {u.provenance.detail} | {u.provenance.n} | "
                f"{u.provenance.application_ref} |"
            )
    if overrides.skipped:
        lines += ["", "## Left as assumptions", "",
                  "| Parameter | Reason | Detail |", "|---|---|---|"]
        for s in overrides.skipped:
            detail = ", ".join(f"{k}={v}" for k, v in s.items() if k not in {"parameter", "reason"})
            lines.append(f"| `{s['parameter']}` | {s['reason']} | {detail} |")
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    overrides: Overrides,
    register: AssumptionRegister,
    out_dir: str | Path,
    *,
    write_docs: bool = False,
    root: str | Path | None = None,
) -> dict[str, Path]:
    """Write the JSON record, the coverage tables and (optionally) the docs page."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    path = out / "register_overrides.json"
    path.write_text(
        json.dumps(overrides.as_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    written["overrides"] = path

    transitions = overrides.frames.get("condition_transitions")
    if isinstance(transitions, pd.DataFrame) and not transitions.empty:
        tpath = out / "condition_transitions.csv"
        transitions.to_csv(tpath, index=False)
        written["transitions"] = tpath

    cpath = out / "coverage.json"
    cpath.write_text(json.dumps(overrides.coverage, indent=2, default=str) + "\n", encoding="utf-8")
    written["coverage"] = cpath

    if write_docs and (overrides.register or overrides.rates):
        # Never render a docs page for a reply that changed nothing: an empty provenance
        # table on disk reads as if a reply had been applied.
        base = Path(root) if root else Path.cwd()
        dpath = base / "docs" / "assumptions_measured.md"
        dpath.parent.mkdir(parents=True, exist_ok=True)
        dpath.write_text(measured_markdown(overrides, register), encoding="utf-8")
        written["docs"] = dpath
    return written
