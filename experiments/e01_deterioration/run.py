"""E1 — do ML models beat agency-style deterioration models? (on real NBI data)

Fits M0 (age-class Markov) and M1 (gradient boosting) on real NBI inspection histories and
evaluates next-year condition state with a **walk-forward split by inspection year** (train
early, test latest; never a random split). Reports log-loss and ranked probability score.

    python experiments/e01_deterioration/run.py --data data/raw/nbi

Requires the NBI files (scripts/download_data.py, FHWA leg).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rra.deterioration.gbm import GradientBoostingDeterioration  # noqa: E402
from rra.deterioration import markov  # noqa: E402
from rra.evaluate import metrics  # noqa: E402
from rra.ingest import nbi  # noqa: E402

DEFAULTS = {
    "train_max": 2020,
    "validate_min": 2021,
    "test_min": 2022,
    "age_class_width": 10,
    "n_age_classes": 9,
    "seed": 0,
}


def markov_proba(pairs, matrices, class_width, age_median):
    """M0: next-year distribution from the age-class transition matrix."""
    p = np.zeros((len(pairs), markov.N_STATES))
    age = pairs["age"].fillna(age_median).to_numpy()
    cur = pairs["state4"].to_numpy(dtype=int)
    for i in range(len(pairs)):
        bucket = min(int(age[i]) // class_width, matrices.shape[0] - 1)
        p[i] = matrices[bucket, cur[i]]
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw/nbi")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    t0 = time.time()
    cfg = dict(DEFAULTS)
    panel = nbi.load_nbi_folder(ROOT / args.data if not Path(args.data).is_absolute() else args.data)
    pairs = nbi.next_year_pairs(panel)

    train = pairs[pairs["year"] <= cfg["train_max"]]
    test = pairs[pairs["year"] >= cfg["test_min"]]
    if train.empty or test.empty:
        raise SystemExit(
            f"empty split — years present: {sorted(pairs['year'].unique())}"
        )

    age_median = float(train["age"].median())
    y_test = test["y_next"].to_numpy(dtype=int)

    # --- M0: age-class Markov ---
    histories = list(
        zip(
            train["age"].fillna(age_median).to_numpy(dtype=int),
            train["state4"].to_numpy(dtype=int),
            train["y_next"].to_numpy(dtype=int),
        )
    )
    # build transition counts directly from the (age, state, next) triples
    counts = np.zeros((cfg["n_age_classes"], markov.N_STATES, markov.N_STATES))
    for a, s, n in histories:
        bucket = min(int(a) // cfg["age_class_width"], cfg["n_age_classes"] - 1)
        counts[bucket, int(s), int(n)] += 1.0
    matrices = np.stack([markov.fit_transition_matrix(counts[i]) for i in range(cfg["n_age_classes"])])
    p_m0 = markov_proba(test, matrices, cfg["age_class_width"], age_median)

    # --- M1: gradient boosting ---
    X_train = nbi.feature_matrix(train)
    X_test = nbi.feature_matrix(test)
    m1 = GradientBoostingDeterioration(n_estimators=150, max_depth=3, random_state=cfg["seed"])
    m1.fit(X_train.to_numpy(), train["y_next"].to_numpy(dtype=int))
    p_m1 = m1.predict_proba(X_test.to_numpy())

    rows = []
    for name, proba in (("M0_markov", p_m0), ("M1_gbm", p_m1)):
        rows.append(
            {
                "model": name,
                "log_loss": metrics.log_loss(y_test, proba),
                "rps": metrics.ranked_probability_score(y_test, proba),
                "accuracy": float((proba.argmax(axis=1) == y_test).mean()),
            }
        )

    # baseline: always predict the empirical next-state distribution
    base = np.bincount(train["y_next"].to_numpy(dtype=int), minlength=markov.N_STATES)
    p_base = np.tile(base / base.sum(), (len(y_test), 1))
    rows.append(
        {
            "model": "climatology",
            "log_loss": metrics.log_loss(y_test, p_base),
            "rps": metrics.ranked_probability_score(y_test, p_base),
            "accuracy": float((p_base.argmax(axis=1) == y_test).mean()),
        }
    )

    result = {
        "config": cfg,
        "n_panel_rows": int(len(panel)),
        "n_pairs": int(len(pairs)),
        "train_pairs": int(len(train)),
        "test_pairs": int(len(test)),
        "years": sorted(int(y) for y in panel["year"].unique()),
        "test_years": sorted(int(y) for y in test["year"].unique()),
        "state_distribution_train": {
            nbi.STATES[i]: int((train["state4"] == i).sum()) for i in range(markov.N_STATES)
        },
        "models": rows,
        "elapsed_seconds": time.time() - t0,
    }

    out_dir = Path(__file__).resolve().parent
    (out_dir / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / "results.md").write_text(_markdown(result), encoding="utf-8")
    print(_markdown(result))
    print(f"\n(wrote results.json / results.md in {result['elapsed_seconds']:.1f}s)")


def _markdown(result: dict) -> str:
    lines = [
        "# E1 — deterioration models on real NBI data",
        "",
        f"- panel rows: {result['n_panel_rows']}, structure-year pairs: {result['n_pairs']}",
        f"- train pairs (year <= {result['config']['train_max']}): {result['train_pairs']}",
        f"- test pairs  (year >= {result['config']['test_min']}): {result['test_pairs']}",
        f"- years loaded: {result['years']}",
        "",
        "| Model | Log-loss | RPS | Accuracy |",
        "|---|---|---|---|",
    ]
    for r in result["models"]:
        lines.append(
            f"| {r['model']} | {r['log_loss']:.4f} | {r['rps']:.4f} | {r['accuracy']:.3f} |"
        )
    lines += [
        "",
        "Lower log-loss / RPS is better. M0 is the agency-style baseline; M1 must beat it",
        "*and* the climatology baseline to support the plan's claim that ML models help.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
