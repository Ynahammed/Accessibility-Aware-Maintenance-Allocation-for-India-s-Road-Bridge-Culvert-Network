"""Real-district specifications shared by the layer scripts and the allocation module.

Every layer script used to hard-code Alappuzha: its Census district code, its raw and
processed directories, and its UTM zone. This module holds those facts once so a second
district can be built with ``--district <slug>`` instead of a copy of the scripts.

Nothing here is a data source of its own. A specification only names the Census 2011
district code used to select the boundary polygon and the directories a district's layers
live in; whether the layers exist is checked by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RealDistrict:
    """One district that has (or will have) the full measured-layer chain."""

    slug: str
    name: str
    census_code: int
    utm_epsg: int = 32643
    pmgsy_internal_id: int | None = None
    note: str = ""

    # --- raw inputs -----------------------------------------------------------------
    @property
    def raw_osm_dir(self) -> Path:
        return ROOT / "data" / "raw" / f"osm_{self.slug}_district"

    # --- processed layers -----------------------------------------------------------
    @property
    def join_dir(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_network_join"

    @property
    def resilience_dir(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_resilience"

    @property
    def allocation_dir(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_allocation"

    @property
    def access_dir(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_access_baseline"

    @property
    def census_join_csv(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_census2011_pmgsy_join.csv"

    @property
    def census_join_report(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_census2011_pmgsy_join.md"

    @property
    def pmgsy_crosswalk_csv(self) -> Path:
        return ROOT / "data" / "processed" / f"{self.slug}_pmgsy_habitations_census_crosswalk.csv"

    # --- shared state-level inputs --------------------------------------------------
    @property
    def boundary_file(self) -> Path:
        return ROOT / "data" / "raw" / "boundaries" / "kerala_districts_census_2011.geojson"

    @property
    def osm_pbf(self) -> Path:
        return ROOT / "data" / "raw" / "geofabrik" / "southern-zone-latest.osm.pbf"

    @property
    def pmgsy_habitation_zip(self) -> Path:
        return ROOT / "data" / "raw" / "pmgsy" / "Habitation_Kerala.zip"

    @property
    def census_workbook(self) -> Path:
        return ROOT / "data" / "raw" / "census" / "2011" / "DDW_PCA3211_2011_MDDS_with_UI.xlsx"


DISTRICTS: dict[str, RealDistrict] = {
    "alappuzha": RealDistrict(
        slug="alappuzha",
        name="Alappuzha",
        census_code=598,
        pmgsy_internal_id=8,
        note="First district; the kuttanad paddy belt with a dense canal network.",
    ),
    "pathanamthitta": RealDistrict(
        slug="pathanamthitta",
        name="Pathanamthitta",
        census_code=599,
        note="Second district; midland/rubber topography, no kayal paddy belt.",
    ),
    # Registered but not yet built: the three districts below cover road mixes absent from
    # the two kayal/midland districts (hill, forest plateau, coastal north). Each needs the
    # full layer chain before it can be cited; see docs/validation_and_limits.md.
    "idukki": RealDistrict(
        slug="idukki",
        name="Idukki",
        census_code=596,
        note="Candidate third district; hill terrain, sparse network, no coastal plain.",
    ),
    "wayanad": RealDistrict(
        slug="wayanad",
        name="Wayanad",
        census_code=590,
        note="Candidate third district; forest plateau, different road mix.",
    ),
    "kasaragod": RealDistrict(
        slug="kasaragod",
        name="Kasaragod",
        census_code=588,
        note="Candidate third district; coastal north, narrow district.",
    ),
}


def get_district(slug: str | None) -> RealDistrict:
    """Resolve a district slug, rejecting unknown names with the valid list."""
    key = (slug or "alappuzha").strip().lower()
    if key not in DISTRICTS:
        raise SystemExit(
            f"unknown district {slug!r}; choose one of: {', '.join(sorted(DISTRICTS))}"
        )
    return DISTRICTS[key]


def district_choices() -> list[str]:
    return sorted(DISTRICTS)


def boundary_feature(spec: RealDistrict) -> dict:
    """The GeoJSON feature whose Census 2011 district code matches the specification."""
    import json

    from shapely.geometry import shape

    data = json.loads(spec.boundary_file.read_text(encoding="utf-8"))
    feature = next(
        (
            f
            for f in data["features"]
            if f.get("properties", {}).get("censuscode") == spec.census_code
        ),
        None,
    )
    if feature is None:
        raise SystemExit(
            f"{spec.name} boundary with Census district code {spec.census_code} not found "
            f"in {spec.boundary_file}"
        )
    if feature["properties"].get("DISTRICT") not in (None, spec.name):
        raise SystemExit(
            f"Census code {spec.census_code} names "
            f"{feature['properties'].get('DISTRICT')!r}, expected {spec.name!r}"
        )
    return {"feature": feature, "geometry": shape(feature["geometry"])}
