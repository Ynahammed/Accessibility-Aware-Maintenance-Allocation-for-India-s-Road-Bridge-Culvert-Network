import pandas as pd
import pytest

from rra.ingest import nbi

HEADER = [
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
    "DECK_COND_058",
    "SUPERSTRUCTURE_COND_059",
    "SUBSTRUCTURE_COND_060",
    "CULVERT_COND_062",
]


def _row(state, sid, built, deck, sup, sub, culvert, kind="5", adt="100"):
    return [state, sid, built, "0", kind, "5", "1", "10.0", "11.0", "9.0", adt, "2",
            deck, sup, sub, culvert]


def _write(tmp_path, year, rows):
    p = tmp_path / f"XX{str(year)[-2:]}.txt"
    pd.DataFrame(rows, columns=HEADER).to_csv(p, index=False)
    return p


def test_overall_to_state_thresholds():
    assert nbi.overall_to_state(9) == 0  # Good
    assert nbi.overall_to_state(7) == 0
    assert nbi.overall_to_state(6) == 1  # Fair
    assert nbi.overall_to_state(5) == 1
    assert nbi.overall_to_state(4) == 2  # Poor
    assert nbi.overall_to_state(3) == 2
    assert nbi.overall_to_state(2) == 3  # Severe
    assert nbi.overall_to_state(0) == 3
    assert nbi.overall_to_state(float("nan")) == -1


def test_condition_uses_min_and_ignores_not_applicable(tmp_path):
    # bridge: deck 8, super 5, sub 9, culvert 'N' -> overall 5 -> Fair
    p = _write(tmp_path, 2020, [_row("01", "B1", "2000", "8", "5", "9", "N")])
    frame = nbi.sheet_to_frame(p, 2020)
    assert frame.iloc[0]["state4"] == 1
    assert frame.iloc[0]["age"] == 20


def test_rows_without_any_rating_are_dropped(tmp_path):
    rows = [
        _row("01", "B1", "2000", "8", "8", "8", "N"),
        _row("01", "B2", "2000", "N", "N", "N", "N"),  # no ratings -> dropped
    ]
    frame = nbi.sheet_to_frame(_write(tmp_path, 2020, rows), 2020)
    assert list(frame["structure_id"]) == ["B1"]


def test_load_folder_and_next_year_pairs(tmp_path):
    _write(tmp_path, 2019, [
        _row("01", "B1", "2000", "8", "8", "8", "N"),   # Good
        _row("01", "B2", "1990", "6", "6", "6", "N"),   # Fair
    ], )
    _write(tmp_path, 2020, [
        _row("01", "B1", "2000", "6", "6", "6", "N"),   # Good -> Fair next year
        _row("01", "B2", "1990", "4", "4", "4", "N"),   # Fair -> Poor next year
    ])
    panel = nbi.load_nbi_folder(tmp_path)
    assert sorted(panel["year"].unique()) == [2019, 2020]

    pairs = nbi.next_year_pairs(panel)
    b1 = pairs[pairs["structure_id"] == "B1"].iloc[0]
    assert b1["year"] == 2019
    assert b1["state4"] == 0 and b1["y_next"] == 1  # Good -> Fair


def test_feature_matrix_fills_nans(tmp_path):
    _write(tmp_path, 2020, [_row("01", "B1", "2000", "7", "7", "7", "N", adt="")])
    frame = nbi.sheet_to_frame(tmp_path / "XX20.txt", 2020)
    X = nbi.feature_matrix(frame)
    assert not X.isna().any().any()
    assert list(X.columns) == nbi.FEATURE_COLUMNS


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        nbi.load_nbi_folder(tmp_path / "nope")
