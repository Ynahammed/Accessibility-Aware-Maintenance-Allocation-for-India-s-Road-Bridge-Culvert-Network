"""US National Bridge Inventory ingestion (plan section 3, 'Bridge condition histories').

Reads the FHWA delimited files, collapses the four component condition ratings into the
project's four states, and builds a cross-year panel keyed by (state code, structure
number) so consecutive inspection years can be joined into (features at t -> state at t+1)
pairs. This is the real labelled data the deterioration models are validated on (E1/E2).

Condition-state rule (documented assumption — the plan says to check the coding guide):
    overall = min of the *applicable* component ratings
              (deck 58, superstructure 59, substructure 60, culvert 62; 'N' = not applicable)
    Good  >= 7        Fair 5-6        Poor 3-4        Severe <= 2
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

STATES = ("Good", "Fair", "Poor", "Severe")
CONDITION_COLUMNS = (
    "DECK_COND_058",
    "SUPERSTRUCTURE_COND_059",
    "SUBSTRUCTURE_COND_060",
    "CULVERT_COND_062",
)
FEATURE_COLUMNS = [
    "state4",
    "age",
    "years_since_rehab",
    "material",
    "design_load",
    "spans",
    "max_span_m",
    "struct_len_m",
    "deck_width_m",
    "adt",
    "truck_pct",
]


def _num(value) -> float:
    """Coerce an NBI token to float; blank / 'N' / other codes become NaN."""
    if value is None:
        return np.nan
    s = str(value).strip()
    if s == "" or s.upper() in {"N", "NA", "N/A"}:
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def overall_to_state(rating: float) -> int:
    """Collapse an overall 0-9 rating to 0 Good .. 3 Severe (-1 if missing)."""
    if rating is None or np.isnan(rating):
        return -1
    if rating >= 7:
        return 0
    if rating >= 5:
        return 1
    if rating >= 3:
        return 2
    return 3


def _condition_state(deck, super_, sub, culvert) -> int:
    vals = [v for v in (deck, super_, sub, culvert) if not np.isnan(v)]
    if not vals:
        return -1
    return overall_to_state(min(vals))


NEEDED_COLUMNS = frozenset(
    {
        "STATE_CODE_001",
        "STRUCTURE_NUMBER_008",
        "YEAR_BUILT_027",
        "YEAR_RECONSTRUCTED_106",
        "STRUCTURE_KIND_043A",
        "DESIGN_LOAD_031",
        "MAIN_UNIT_SPANS_045",
        "MAX_SPAN_LEN_MT_048",
        "STRUCTURE_LEN_MT_049",
        "DECK_WIDTH_MT_052",
        "ADT_029",
        "PERCENT_ADT_TRUCK_109",
        *CONDITION_COLUMNS,
    }
)


def sheet_to_frame(path: str | Path, year: int) -> pd.DataFrame:
    """Parse one NBI delimited file into a tidy frame for a single inspection year."""
    df = pd.read_csv(
        path,
        dtype=str,
        low_memory=False,
        encoding_errors="replace",
        usecols=lambda c: c in NEEDED_COLUMNS,  # 123 fields -> the ~16 we use
    )

    def col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name]
        return pd.Series([np.nan] * len(df), index=df.index)

    out = pd.DataFrame(index=df.index)
    out["state_code"] = df["STATE_CODE_001"].astype(str).str.strip()
    out["structure_id"] = df["STRUCTURE_NUMBER_008"].astype(str).str.strip()
    out["key"] = out["state_code"] + "|" + out["structure_id"]
    out["year"] = int(year)
    out["year_built"] = col("YEAR_BUILT_027").map(_num)
    out["year_rehab"] = col("YEAR_RECONSTRUCTED_106").map(_num)
    out["material"] = col("STRUCTURE_KIND_043A").map(_num)
    out["design_load"] = col("DESIGN_LOAD_031").map(_num)
    out["spans"] = col("MAIN_UNIT_SPANS_045").map(_num)
    out["max_span_m"] = col("MAX_SPAN_LEN_MT_048").map(_num)
    out["struct_len_m"] = col("STRUCTURE_LEN_MT_049").map(_num)
    out["deck_width_m"] = col("DECK_WIDTH_MT_052").map(_num)
    out["adt"] = col("ADT_029").map(_num)
    out["truck_pct"] = col("PERCENT_ADT_TRUCK_109").map(_num)

    deck = col("DECK_COND_058").map(_num)
    super_ = col("SUPERSTRUCTURE_COND_059").map(_num)
    sub = col("SUBSTRUCTURE_COND_060").map(_num)
    culvert = col("CULVERT_COND_062").map(_num)
    out["rating"] = [
        _condition_state(d, s, u, c) for d, s, u, c in zip(deck, super_, sub, culvert)
    ]
    out["state4"] = out["rating"]

    out["age"] = int(year) - out["year_built"]
    out.loc[out["age"] < 0, "age"] = np.nan
    out["years_since_rehab"] = np.where(
        out["year_rehab"] > 0, int(year) - out["year_rehab"], np.nan
    )
    return out[out["state4"] >= 0].reset_index(drop=True)


def load_nbi_folder(folder: str | Path) -> pd.DataFrame:
    """Load every ``*.txt`` under ``folder`` (searched recursively) into one panel."""
    folder = Path(folder)
    frames = []
    for path in sorted(folder.rglob("*.txt")):
        stem = path.stem  # e.g. AL23
        try:
            year = 2000 + int(stem[-2:])
        except ValueError:
            continue
        frames.append(sheet_to_frame(path, year))
    if not frames:
        raise FileNotFoundError(f"no NBI *.txt files under {folder}")
    return pd.concat(frames, ignore_index=True)


def next_year_pairs(panel: pd.DataFrame) -> pd.DataFrame:
    """Pair each structure-year with the *next* year's state (features at t -> y_next)."""
    nxt = panel[["key", "year", "state4"]].copy()
    nxt["year"] = nxt["year"] - 1
    nxt = nxt.rename(columns={"state4": "y_next"})
    pairs = panel.merge(nxt, on=["key", "year"], how="inner")
    return pairs


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the model feature columns with NaNs filled by column medians."""
    X = frame[FEATURE_COLUMNS].copy()
    return X.fillna(X.median(numeric_only=True)).fillna(0.0)


def split_by_year(panel: pd.DataFrame, train_max: int, test_min: int):
    """Walk-forward split: train on early years, test on the latest (plan 5.4)."""
    train = panel[panel["year"] <= train_max]
    test = panel[panel["year"] >= test_min]
    if train.empty or test.empty:
        raise ValueError("empty split; check train_max/test_min against the years present")
    return train, test
