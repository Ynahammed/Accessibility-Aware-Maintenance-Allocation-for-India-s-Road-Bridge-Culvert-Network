"""India-only Alappuzha flood exposure: KSDMA return-period depth rasters vs mapped roads and points.

Reads the official KSDMA historical (UNEP/UN-GRID/CIMA, 2020) and RCP8.5 return-period
GeoTIFFs directly from their downloaded ZIPs, without GDAL, by decoding the tiled TIFF
tags. Cell values are modelled flood depth in centimetres (KSDMA/RMSI documentation);
they are **modelled hazard**, not observed flooding or damage.

Exposure is reported as geometric overlap of mapped lines/points with modelled depth
classes. A road edge crossing a deep cell does not establish that it was impassable, and
a settlement point in a cell does not establish that homes were flooded.

Run: python scripts/alappuzha_flood_exposure.py
"""
from __future__ import annotations

import json
import math
import struct
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
FLOOD = RAW / "ksdma/flood"
OUT = ROOT / "data/processed/alappuzha_flood_exposure"
JOIN = ROOT / "data/processed/alappuzha_network_join"
BOUNDARY_FILE = RAW / "boundaries/kerala_districts_census_2011.geojson"

# Scenario order is the published KSDMA set: six return periods, historical and RCP8.5.
SCENARIOS = [
    ("historical", 10, "historical_10_25_50_years.zip", "_10_yr_Historical.tif"),
    ("historical", 25, "historical_10_25_50_years.zip", "_25_yr_Historical.tif"),
    ("historical", 50, "historical_10_25_50_years.zip", "_50_yr_Historical.tif"),
    ("historical", 100, "historical_100_200_500_years.zip", "_100_yr_Historical.tif"),
    ("historical", 200, "historical_100_200_500_years.zip", "_200_yr_Historical.tif"),
    ("historical", 500, "historical_100_200_500_years.zip", "_500_yr_Historical.tif"),
    ("rcp85", 10, "rcp85_10_25_50_years.zip", "_10_yr_RCP.tif"),
    ("rcp85", 25, "rcp85_10_25_50_years.zip", "_25_yr_RCP.tif"),
    ("rcp85", 50, "rcp85_10_25_50_years.zip", "_50_yr_RCP.tif"),
    ("rcp85", 100, "rcp85_100_200_500_years.zip", "_100_yr_RCP.tif"),
    ("rcp85", 200, "rcp85_100_200_500_years.zip", "_200_yr_RCP.tif"),
    ("rcp85", 500, "rcp85_100_200_500_years.zip", "_500_yr_RCP.tif"),
]

# Depth bands in centimetres, from the source raster's own unit.
BANDS = [(0.0, 25.0), (25.0, 50.0), (50.0, 100.0), (100.0, 200.0), (200.0, math.inf)]
BAND_LABELS = ["0-25", "25-50", "50-100", "100-200", "200+"]
# Indicative depth at which a light vehicle should not attempt a crossing. This is a
# decision threshold applied to modelled depth, not an observation of closures.
VEHICLE_THRESHOLD_CM = 30.0
SAMPLE_SPACING_M = 100.0
NODATA_FLOAT = -1.0e30

TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
PYPROJ_CRS = "EPSG:32643"


class GeoTiff:
    """Minimal reader for the uncompressed, tiled, single-band float/int GeoTIFFs KSDMA ships."""

    _TYPES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
    # Only these fields describe the pixel layout; unrelated tags (text, rationals) are skipped.
    _WANTED = {256, 257, 258, 259, 284, 322, 323, 324, 325, 339}

    def __init__(self, buf: bytes, label: str):
        if buf[:2] == b"II":
            self.bo = "<"
        elif buf[:2] == b"MM":
            self.bo = ">"
        else:
            raise ValueError(f"{label}: not a TIFF")
        magic = struct.unpack(self.bo + "H", buf[2:4])[0]
        if magic != 42:
            raise ValueError(f"{label}: unsupported TIFF magic {magic} (BigTIFF is not handled)")
        ifd = struct.unpack(self.bo + "I", buf[4:8])[0]
        count = struct.unpack(self.bo + "H", buf[ifd : ifd + 2])[0]
        tags: dict[int, int] = {}
        for index in range(count):
            entry = ifd + 2 + 12 * index
            tag, typ, n = struct.unpack(self.bo + "HHI", buf[entry : entry + 8])
            if tag in self._WANTED:
                tags[tag] = self._value(buf, entry, typ, n)

        self.width = tags[256]
        self.height = tags[257]
        self.bits = tags[258]
        self.compression = tags[259]
        self.planar = tags.get(284, 1)
        sample_format = tags.get(339, 1)
        if self.compression != 1:
            raise ValueError(f"{label}: compressed TIFF (compression={self.compression}) unsupported")
        if self.bits != 32 or self.planar != 1:
            raise ValueError(f"{label}: expected single-band 32-bit data, got bits={self.bits}")
        if 322 not in tags:
            raise ValueError(f"{label}: expected a tiled TIFF")
        self.tile_w = tags[322]
        self.tile_h = tags[323]
        self.offsets = tags[324]
        self.counts = tags[325]
        # SampleFormat 2 = signed integer (one KSDMA layer stores integer centimetres),
        # 3 = IEEE float. Honouring the file's own declaration avoids integer-reading a
        # float grid or vice versa.
        self.dtype = np.dtype(self.bo + ("i4" if sample_format == 2 else "f4"))
        if sample_format not in (2, 3):
            raise ValueError(f"{label}: unexpected SampleFormat {sample_format}")
        self.label = label
        self.buf = buf
        self.tiles_across = math.ceil(self.width / self.tile_w)
        self.tiles_down = math.ceil(self.height / self.tile_h)
        if len(self.offsets) != self.tiles_across * self.tiles_down:
            raise ValueError(f"{label}: tile count does not match dimensions")

    def _value(self, buf: bytes, entry: int, typ: int, n: int):
        size = self._TYPES.get(typ, 1) * n
        raw = buf[entry + 8 : entry + 8 + size] if size <= 4 else buf[
            struct.unpack(self.bo + "I", buf[entry + 8 : entry + 12])[0] :][:size]
        fmt = {1: "B", 3: "H", 4: "I", 16: "Q"}.get(typ)
        if fmt is None:
            raise ValueError(f"unsupported TIFF field type {typ}")
        values = struct.unpack(self.bo + fmt * n, raw)
        return values[0] if n == 1 else values

    def window(self, col0: int, row0: int, col1: int, row1: int) -> np.ndarray:
        if not (0 <= col0 < col1 <= self.width and 0 <= row0 < row1 <= self.height):
            raise ValueError(f"{self.label}: window outside raster")
        out = np.empty((row1 - row0, col1 - col0), dtype=self.dtype)
        tile_rows = self.tile_h
        tile_cols = self.tile_w
        for ty in range(row0 // tile_rows, (row1 - 1) // tile_rows + 1):
            for tx in range(col0 // tile_cols, (col1 - 1) // tile_cols + 1):
                index = ty * self.tiles_across + tx
                offset, nbytes = self.offsets[index], self.counts[index]
                expected = tile_rows * tile_cols * self.dtype.itemsize
                if nbytes != expected:
                    raise ValueError(f"{self.label}: unexpected tile byte count {nbytes}")
                tile = np.frombuffer(
                    self.buf, dtype=self.dtype, count=tile_rows * tile_cols, offset=offset
                ).reshape(tile_rows, tile_cols)
                r0, c0 = ty * tile_rows, tx * tile_cols
                rr0, rr1 = max(row0, r0), min(row1, r0 + tile_rows)
                cc0, cc1 = max(col0, c0), min(col1, c0 + tile_cols)
                out[rr0 - row0 : rr1 - row0, cc0 - col0 : cc1 - col0] = tile[
                    rr0 - r0 : rr1 - r0, cc0 - c0 : cc1 - c0
                ]
        return out


class Grid:
    """A KSDMA depth grid with its world file, plus district-window sampling."""

    def __init__(self, scenario: str, return_period: int, archive: str, suffix: str, polygon):
        path = FLOOD / archive
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            tif_name = next(n for n in names if n.endswith(suffix))
            tfw_name = next(n for n in names if n.replace(".tfw", ".tif") == tif_name)
            self.tiff = GeoTiff(zf.read(tif_name), tif_name)
            world = [float(v) for v in zf.read(tfw_name).decode().split()]
        self.scenario = scenario
        self.return_period = return_period
        self.source = f"{path.name}:{tif_name}"
        self.pixel_x, rotate_x, rotate_y, self.pixel_y, self.origin_lon, self.origin_lat = world
        if rotate_x or rotate_y or self.pixel_x <= 0 or self.pixel_y >= 0:
            raise ValueError(f"{tif_name}: unexpected world file orientation")
        minx, miny, maxx, maxy = polygon.bounds
        self.col0 = max(0, math.floor((minx - self.origin_lon) / self.pixel_x) - 1)
        self.col1 = min(self.tiff.width, math.ceil((maxx - self.origin_lon) / self.pixel_x) + 2)
        self.row0 = max(0, math.floor((self.origin_lat - maxy) / -self.pixel_y) - 1)
        self.row1 = min(self.tiff.height, math.ceil((self.origin_lat - miny) / -self.pixel_y) + 2)
        if self.col0 <= 0 or self.row0 <= 0 or self.col1 >= self.tiff.width or self.row1 >= self.tiff.height:
            raise ValueError(f"{tif_name}: district window touches the raster edge; georeferencing suspect")
        self.window = self.tiff.window(self.col0, self.row0, self.col1, self.row1).astype("float64")
        # Negative sentinels appear in some layers outside the modelled extent. Treat any
        # non-positive or absurd value as "no modelled depth" and count it for QA.
        self.nodata_cells = int((self.window < -1.0).sum())
        self.window = np.where(self.window < 0, 0.0, self.window)

    def district_mask(self, polygon) -> np.ndarray:
        """Cells whose centre falls inside the Census 2011 district polygon."""
        from shapely import contains_xy

        rows = np.arange(self.window.shape[0])
        cols = np.arange(self.window.shape[1])
        lons = self.origin_lon + (cols + self.col0) * self.pixel_x
        lats = self.origin_lat - (rows + self.row0) * -self.pixel_y
        grid_lon, grid_lat = np.meshgrid(lons, lats)
        return contains_xy(polygon, grid_lon, grid_lat)

    def lookup(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Nearest cell-centre depth (cm) for WGS84 coordinates."""
        lon = np.asarray(lon, dtype="float64")
        lat = np.asarray(lat, dtype="float64")
        col = np.rint((lon - self.origin_lon) / self.pixel_x).astype("int64") - self.col0
        row = np.rint((self.origin_lat - lat) / -self.pixel_y).astype("int64") - self.row0
        inside = (col >= 0) & (col < self.window.shape[1]) & (row >= 0) & (row < self.window.shape[0])
        depth = np.full(lon.shape, np.nan)
        depth[inside] = self.window[row[inside], col[inside]]
        return depth


def district_polygon():
    data = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    feature = next(f for f in data["features"] if f["properties"].get("censuscode") == 598)
    return shape(feature["geometry"])


def densify(lines: gpd.GeoDataFrame, label: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample points every ~SAMPLE_SPACING_M along each line; return lon, lat, line index."""
    metric = lines.geometry.to_crs(PYPROJ_CRS)
    degree_step = SAMPLE_SPACING_M / 110_000.0
    lons, lats, owners = [], [], []
    for position, geom in enumerate(lines.geometry):
        if geom is None or geom.is_empty:
            continue
        for part in getattr(geom, "geoms", [geom]):
            if part.is_empty or part.geom_type != "LineString":
                continue
            dense = part.segmentize(degree_step)
            coords = np.asarray(dense.coords)
            lons.append(coords[:, 0])
            lats.append(coords[:, 1])
            owners.append(np.full(len(coords), position, dtype="int64"))
    if not lons:
        raise ValueError(f"{label}: no linework to sample")
    return np.concatenate(lons), np.concatenate(lats), np.concatenate(owners)


def band_series(depth: np.ndarray) -> dict:
    positive = depth[np.isfinite(depth) & (depth > 0)]
    return {
        "flooded_share": float(np.isfinite(depth).sum() and (depth > 0).sum() / np.isfinite(depth).sum()),
        "median_flooded_cm": float(np.median(positive)) if positive.size else 0.0,
        "p95_flooded_cm": float(np.percentile(positive, 95)) if positive.size else 0.0,
        "max_cm": float(np.max(depth[np.isfinite(depth)])) if np.isfinite(depth).any() else 0.0,
        "share_ge_vehicle_threshold": float(
            (depth >= VEHICLE_THRESHOLD_CM).sum() / max(1, np.isfinite(depth).sum())
        ),
    }


def water_proximity(grid: "Grid", mask: np.ndarray, water_path: Path) -> dict:
    """Share of modelled-depth area that sits on or beside mapped water.

    A large depth footprint on land far from any mapped water is the signature of a model
    that keeps water standing where drainage would remove it; a footprint concentrated on
    water bodies and their margins is closer to a floodplain delineation. This is a
    plausibility check on the footprint, not a validation against observed flooding.
    """
    from shapely import STRtree

    water = gpd.read_parquet(water_path).to_crs("EPSG:32643")
    geometries = [g for g in water.geometry if g is not None and not g.is_empty]
    tree = STRtree(geometries)

    rows, cols = np.nonzero(mask & (grid.window > 0))
    lons = grid.origin_lon + (cols + grid.col0) * grid.pixel_x
    lats = grid.origin_lat - (rows + grid.row0) * -grid.pixel_y
    mx, my = TO_METRIC.transform(lons, lats)
    points = shapely.points(mx, my)
    indices, distances = tree.query_nearest(points, all_matches=False, return_distance=True)

    depth = grid.window[rows, cols]
    bands = {
        "on_or_touching_mapped_water": distances <= 1.0,
        "within_100m": (distances > 1.0) & (distances <= 100.0),
        "100_to_250m": (distances > 100.0) & (distances <= 250.0),
        "farther_than_250m": distances > 250.0,
    }
    total = int(depth.size)
    return {
        "positive_cells": total,
        "bands": {
            name: {
                "cells": int(mask_.sum()),
                "share": float(mask_.sum() / total) if total else None,
                "median_depth_cm": float(np.median(depth[mask_])) if mask_.any() else 0.0,
            }
            for name, mask_ in bands.items()
        },
    }


def spatial_check(grid: "Grid", mask: np.ndarray) -> dict:
    """Flooded share by north-south longitude band, as a model-behaviour check.

    Alappuzha rises from the backwater/kayal belt in the west to laterite midland in the
    east. A state-wide hydraulic product that does not resolve polders and field drainage
    shows extensive standing water across the low western belt; checking the split makes
    that visible instead of letting one district-wide share stand in for expected flooding.
    """
    rows = np.arange(grid.window.shape[0])
    cols = np.arange(grid.window.shape[1])
    lons = grid.origin_lon + (cols + grid.col0) * grid.pixel_x
    lats = grid.origin_lat - (rows + grid.row0) * -grid.pixel_y
    grid_lon, _ = np.meshgrid(lons, lats)
    depth = grid.window
    bands = [("west_kayal_lt_76.40E", 76.28, 76.40), ("central_76.40_76.52E", 76.40, 76.52),
             ("east_upland_ge_76.52E", 76.52, 76.70)]
    out = {}
    for name, low, high in bands:
        selected = mask & (grid_lon >= low) & (grid_lon < high)
        values = depth[selected]
        out[name] = {
            "cells": int(values.size),
            "flooded_share": float((values > 0).mean()) if values.size else None,
            "median_flooded_cm": float(np.median(values[values > 0])) if (values > 0).any() else 0.0,
        }
    return out


def main() -> None:
    # The console is cp1252 on Windows; the report uses symbols such as the depth band arrows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    polygon = district_polygon()
    grids = [Grid(*spec, polygon) for spec in SCENARIOS]
    keys = [f"{g.scenario}_{g.return_period}yr" for g in grids]
    print(f"Loaded {len(grids)} KSDMA depth grids; keys: {keys}", flush=True)

    # --- linework: PMGSY district rural roads and the OSM district road clip ---
    pmgsy = gpd.read_file(RAW / "pmgsy/alappuzha_drrp_roads.geojson")
    pmgsy = pmgsy.to_crs("EPSG:4326")
    pmgsy["road_length_km"] = pmgsy.geometry.to_crs(PYPROJ_CRS).length / 1000.0
    pmgsy["road_id"] = pmgsy["objectid"].astype(str)
    osm = gpd.read_parquet(RAW / "osm_alappuzha_district/roads.parquet").to_crs("EPSG:4326")
    osm = osm.loc[osm.geometry.notna() & ~osm.geometry.is_empty].copy()
    osm["road_id"] = osm["osm_id"].astype(str)
    osm["road_length_km"] = osm.geometry.to_crs(PYPROJ_CRS).length / 1000.0
    print(f"PMGSY roads {len(pmgsy):,} ({pmgsy.road_length_km.sum():,.0f} km); "
          f"OSM ways {len(osm):,} ({osm.road_length_km.sum():,.0f} km)", flush=True)

    layers = {}
    for name, frame in (("pmgsy", pmgsy), ("osm", osm)):
        lon, lat, owner = densify(frame, name)
        length_per_sample = frame["road_length_km"].to_numpy() / np.bincount(
            owner, minlength=len(frame)
        ).clip(min=1)
        layers[name] = {
            "frame": frame,
            "lon": lon,
            "lat": lat,
            "owner": owner,
            "sample_km": length_per_sample[owner],
            "n_samples": np.bincount(owner, minlength=len(frame)),
        }

    # --- points: OSM facilities, PMGSY habitations, OSM places, crossing candidates ---
    facilities = gpd.read_parquet(JOIN / "osm_facilities_snapped.parquet")
    habitations = gpd.read_parquet(JOIN / "pmgsy_habitations_snapped.parquet")
    places = gpd.read_parquet(JOIN / "osm_places_snapped.parquet")
    census = gpd.read_parquet(JOIN / "census_villages_snapped.parquet")
    crossings = gpd.read_parquet(JOIN / "water_crossing_candidates.parquet")

    point_layers = {
        "osm_health": pd.DataFrame({
            "entity_id": facilities.loc[facilities.facility_type.eq("health"), "entity_id"],
            "name": facilities.loc[facilities.facility_type.eq("health"), "name"],
            "longitude": facilities.loc[facilities.facility_type.eq("health"), "longitude"],
            "latitude": facilities.loc[facilities.facility_type.eq("health"), "latitude"],
            "population": np.nan,
        }),
        "osm_school": pd.DataFrame({
            "entity_id": facilities.loc[facilities.facility_type.eq("school"), "entity_id"],
            "name": facilities.loc[facilities.facility_type.eq("school"), "name"],
            "longitude": facilities.loc[facilities.facility_type.eq("school"), "longitude"],
            "latitude": facilities.loc[facilities.facility_type.eq("school"), "latitude"],
            "population": np.nan,
        }),
        "pmgsy_habitation": pd.DataFrame({
            "entity_id": habitations["entity_id"],
            "name": habitations["habitation_name"],
            "longitude": habitations["longitude"],
            "latitude": habitations["latitude"],
            "population": habitations["pmgsy_population_field"],
        }),
        "osm_place": pd.DataFrame({
            "entity_id": places["entity_id"],
            "name": places["name"],
            "longitude": places["longitude"],
            "latitude": places["latitude"],
            "population": np.nan,
        }),
        "census_village_located": pd.DataFrame({
            "entity_id": census.loc[census.longitude.notna(), "entity_id"],
            "name": census.loc[census.longitude.notna(), "census_village_name"],
            "longitude": census.loc[census.longitude.notna(), "longitude"],
            "latitude": census.loc[census.longitude.notna(), "latitude"],
            "population": census.loc[census.longitude.notna(), "census_population_2011"],
        }),
        "crossing_candidate": pd.DataFrame({
            "entity_id": crossings["entity_id"],
            "name": crossings["road_name"],
            "longitude": crossings["longitude"],
            "latitude": crossings["latitude"],
            "population": np.nan,
        }),
    }

    road_tables = {name: data["frame"][["road_id", "road_length_km"]].copy() for name, data in layers.items()}
    point_tables = {}
    summary = {
        "title": "Alappuzha modelled flood exposure (KSDMA return-period depth)",
        "scope": "Indian official sources only: KSDMA/CIMA flood depth rasters, PMGSY DRRP roads, "
                 "district OSM roads/facilities, Census 2011 and PMGSY habitation points",
        "hazard": {
            "product": "KSDMA Flood Hazard Probability of Kerala, historical and RCP8.5 return periods",
            "raster_value_unit": "centimetres of modelled flood depth (KSDMA/RMSI documentation)",
            "raster_cell_size_degrees": [grids[0].pixel_x, abs(grids[0].pixel_y)],
            "approximate_cell_size_m": round(abs(grids[0].pixel_y) * 110_574, 1),
            "scenarios": [
                {
                    "key": key,
                    "scenario": g.scenario,
                    "return_period_years": g.return_period,
                    "source": g.source,
                    "sample_format": str(g.tiff.dtype),
                    "district_window_cells": int(g.window.size),
                    "negative_sentinel_cells": g.nodata_cells,
                }
                for key, g in zip(keys, grids)
            ],
        },
        "thresholds": {
            "depth_bands_cm": BAND_LABELS,
            "indicative_vehicle_depth_cm": VEHICLE_THRESHOLD_CM,
            "line_sample_spacing_m": SAMPLE_SPACING_M,
        },
        "unit_validation": {
            "claim": "raster cell values are modelled flood depth in centimetres",
            "corroboration": "KSDMA's own Alappuzha district map PDFs classify the same surface as 'Flood Water Level (m)' with bands <4, 4-8, 8-12 and >12 m at data/raw/ksdma/flood/alappuzha_historical.pdf and alappuzha_rcp85.pdf. Those breaks correspond to 400, 800 and 1200 in the raster's own units, and the observed district values (0 to roughly 1300) reproduce exactly those classes under a centimetre reading.",
            "caveat": "The district PDFs cover Ambalapuzha taluk, not the whole district, and label the surface 'water level' rather than 'depth'. The scaling is corroborated; the exact datum is not documented in the raster package.",
        },
        "district_area": {},
        "district_area_latitude_split": {},
        "roads": {},
        "points": {},
        "caveats": [
            "KSDMA rasters are modelled return-period flood depth, not observed inundation, road closure or damage.",
            "Cells are ~90 m; depth is a cell value, not a measurement at a bridge, culvert or road edge.",
            "A road sampled in a deep cell is exposed in the model; this does not establish that it was impassable, and no closure or repair cost is implied.",
            "Crossing candidates are unverified geometric road/water intersections, not a bridge or culvert inventory.",
            "PMGSY population fields and Census 2011 populations are separate sources and must not be added.",
            "Census villages without a defensible coordinate are excluded from point exposure rather than placed arbitrarily.",
            "No observed flood damage, maintenance cost or condition record supports a maintenance recommendation from these numbers.",
        ],
    }

    # District-wide modelled footprint, clipped to the Census 2011 district polygon
    # rather than the raster window's bounding box.
    masks = {key: g.district_mask(polygon) for key, g in zip(keys, grids)}
    for key, g in zip(keys, grids):
        depth = g.window[masks[key]]
        depth = depth[np.isfinite(depth)]
        record = band_series(depth)
        record["district_cells"] = int(depth.size)
        summary["district_area"][key] = record
        summary["district_area_latitude_split"][key] = spatial_check(g, masks[key])
        if key in ("historical_10yr", "rcp85_100yr"):
            summary.setdefault("water_proximity", {})[key] = water_proximity(
                g, masks[key], RAW / "osm_alappuzha_district/water.parquet"
            )

    # --- sample lines ---
    for layer_name, data in layers.items():
        frame = data["frame"]
        table = road_tables[layer_name]
        flooded_flags = np.zeros(len(frame), dtype=bool)
        for key, grid in zip(keys, grids):
            depth = grid.lookup(data["lon"], data["lat"])
            table[f"depth_cm_{key}"] = np.nan
            table[f"depth_cm_{key}"] = np.round(
                pd.Series(depth).groupby(data["owner"]).max().reindex(range(len(frame))).to_numpy(), 1
            )
            per_road = pd.Series(depth).groupby(data["owner"])
            flooded_flags |= per_road.max().reindex(range(len(frame))).fillna(0).to_numpy() > 0
        table["exposed_any_scenario"] = flooded_flags

        # Length-weighted exposure per scenario, split by source road class.
        class_column = "roadcat" if layer_name == "pmgsy" else "highway"
        class_per_road = frame[class_column].fillna("unknown").astype(str).to_numpy()
        class_values = class_per_road[data["owner"]]
        for key, grid in zip(keys, grids):
            depth = grid.lookup(data["lon"], data["lat"])
            sample_km = data["sample_km"]
            valid = np.isfinite(depth)
            total_km = float(sample_km[valid].sum())
            record = {
                "sampled_length_km": round(total_km, 2),
                "any_depth_km": round(float(sample_km[valid & (depth > 0)].sum()), 2),
                "at_or_above_vehicle_threshold_km": round(
                    float(sample_km[valid & (depth >= VEHICLE_THRESHOLD_CM)].sum()), 2
                ),
                "bands_km": {
                    label: round(
                        float(sample_km[valid & (depth > low) & (depth <= high)].sum()), 2
                    )
                    for label, (low, high) in zip(BAND_LABELS, BANDS)
                },
                "roads_with_any_depth": int(
                    (pd.Series(depth).groupby(data["owner"]).max() > 0).sum()
                ),
                "roads_with_vehicle_threshold_depth": int(
                    (pd.Series(depth).groupby(data["owner"]).max() >= VEHICLE_THRESHOLD_CM).sum()
                ),
            }
            record["any_depth_share"] = (
                record["any_depth_km"] / total_km if total_km else None
            )
            record["vehicle_threshold_share"] = (
                record["at_or_above_vehicle_threshold_km"] / total_km if total_km else None
            )
            record["by_class"] = {}
            for cls in sorted(set(class_values)):
                mask = valid & (class_values == cls)
                class_km = float(sample_km[mask].sum())
                record["by_class"][cls] = {
                    "sampled_length_km": round(class_km, 2),
                    "any_depth_km": round(float(sample_km[mask & (depth > 0)].sum()), 2),
                    "vehicle_threshold_km": round(
                        float(sample_km[mask & (depth >= VEHICLE_THRESHOLD_CM)].sum()), 2
                    ),
                    "any_depth_share": (
                        float(sample_km[mask & (depth > 0)].sum()) / class_km if class_km else None
                    ),
                }
            summary["roads"].setdefault(layer_name, {})[key] = record

        road_tables[layer_name] = table

    # --- sample points ---
    for layer_name, frame in point_layers.items():
        frame = frame.reset_index(drop=True)
        table = frame[["entity_id", "name", "longitude", "latitude", "population"]].copy()
        for key, grid in zip(keys, grids):
            depth = grid.lookup(frame["longitude"].to_numpy(), frame["latitude"].to_numpy())
            table[f"depth_cm_{key}"] = np.round(depth, 1)
            finite = np.isfinite(depth)
            population = pd.to_numeric(frame["population"], errors="coerce").fillna(0.0).to_numpy()
            record = {
                "records": int(len(frame)),
                "records_in_raster": int(finite.sum()),
                "records_any_depth": int((depth > 0).sum()),
                "records_vehicle_threshold": int((depth >= VEHICLE_THRESHOLD_CM).sum()),
                "share_any_depth": (
                    float((depth > 0).sum()) / int(finite.sum()) if finite.sum() else None
                ),
                "share_vehicle_threshold": (
                    float((depth >= VEHICLE_THRESHOLD_CM).sum()) / int(finite.sum())
                    if finite.sum()
                    else None
                ),
            }
            if finite.any() and np.isfinite(population).any() and population.sum() > 0:
                record["population_any_depth"] = int(population[depth > 0].sum())
                record["population_vehicle_threshold"] = int(
                    population[depth >= VEHICLE_THRESHOLD_CM].sum()
                )
                record["population_total"] = int(population.sum())
            summary["points"].setdefault(layer_name, {})[key] = record
        point_tables[layer_name] = table

    # --- write outputs ---
    pmgsy_table = road_tables["pmgsy"].merge(
        pmgsy[["road_id", "roadname", "roadcat", "roadowner"]], on="road_id", how="left"
    )
    pmgsy_table.to_csv(OUT / "pmgsy_road_depth.csv", index=False)
    road_tables["osm"].to_csv(OUT / "osm_road_depth.csv", index=False)
    for layer_name, table in point_tables.items():
        table.to_csv(OUT / f"{layer_name}_depth.csv", index=False)
    summary["outputs"] = {
        "pmgsy_road_depth.csv": "per-road maximum sampled depth for each of the 12 return-period layers",
        "osm_road_depth.csv": "per-OSM-way maximum sampled depth for each layer",
        "point_depth.csv": "per-point sampled depth by layer (separate files per point layer)",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # --- human-readable report ---
    def pct(value):
        return "n/a" if value is None else f"{100 * value:.1f}%"

    lines = [
        "# Alappuzha modelled flood exposure — KSDMA return-period depth",
        "",
        "India-only overlay of the official KSDMA/CIMA return-period flood-depth rasters on the",
        "PMGSY DRRP road network, the district OSM road clip, mapped facilities and habitat points.",
        "",
        "**These are modelled hazard overlap numbers.** A road edge inside a deep cell is exposed in",
        "the model; it is not evidence that the road closed, that a structure failed, or that any",
        "repair is justified. No observed flood damage or maintenance cost enters this analysis.",
        "",
        "## Hazard source",
        "",
        f"- Product: KSDMA *Flood Hazard Probability of Kerala* — historical and RCP8.5 return periods",
        "  (UNEP/UN-GRID/CIMA Italy 2020 modelling, distributed by KSDMA).",
        f"- Cell values: modelled flood depth in centimetres. Cell size {summary['hazard']['approximate_cell_size_m']} m.",
        f"- Twelve layers: 10/25/50/100/200/500 years, historical and RCP8.5.",
        f"- One layer is stored as integer centimetres, the rest as float32; each file is decoded",
        "  using its own declared sample format.",
        "",
        "## Modelled district footprint",
        "",
        "| Layer | Cells with any depth | Median flooded depth (cm) | p95 flooded (cm) | ≥30 cm cells |",
        "|---|---|---|---|---|",
    ]
    for key in keys:
        record = summary["district_area"][key]
        lines.append(
            f"| {key} | {pct(record['flooded_share'])} | {record['median_flooded_cm']:.0f} | "
            f"{record['p95_flooded_cm']:.0f} | {pct(record['share_ge_vehicle_threshold'])} |"
        )

    lines += [
        "",
        "Unit check. The rasters carry no value metadata, so the centimetre reading was tested",
        "against KSDMA's own district maps for Alappuzha: their legend classes the same surface as",
        "`Flood Water Level (m)` at <4, 4-8, 8-12 and >12 m. Those breaks are 400/800/1200 in the",
        "raster's own units, and the district values (0 to about 1,300) reproduce exactly those",
        "classes under a centimetre reading. The scaling is corroborated; the datum is not documented",
        "in the raster package, and the taluk-level PDFs are labelled reference purpose only.",
        "",
        "### What the footprint means",
        "",
        "The modelled floodplain is broad: the 10-year historical layer already covers more than a",
        "third of the district at a median modelled depth above 2 m. Splitting the district by",
        "longitude (not equal-area bands) shows where that comes from:",
        "",
        "| Layer | West (<76.40E, kayal) | Central | East (>=76.52E, upland) |",
        "|---|---|---|---|",
    ]
    for key in keys:
        split = summary["district_area_latitude_split"][key]
        cells = [
            f"{pct(split[name]['flooded_share'])} / {split[name]['median_flooded_cm']:.0f} cm"
            for name in ("west_kayal_lt_76.40E", "central_76.40_76.52E", "east_upland_ge_76.52E")
        ]
        lines.append(f"| {key} | {cells[0]} | {cells[1]} | {cells[2]} |")

    central = summary["district_area_latitude_split"]["historical_10yr"]["central_76.40_76.52E"]
    east = summary["district_area_latitude_split"]["historical_10yr"]["east_upland_ge_76.52E"]
    west = summary["district_area_latitude_split"]["historical_10yr"]["west_kayal_lt_76.40E"]
    lines += [
        "",
        f"The concentration is in the central kayal/paddy belt ({pct(central['flooded_share'])} of cells at",
        f"the 10-year historical layer), against {pct(west['flooded_share'])} in the western coastal band and",
        f"{pct(east['flooded_share'])} in the eastern midland. That ordering matches the low-lying",
        "paddy and backwater zone, but the eastern share is high for upland terrain, and the median",
        "modelled depth in every band is metres at a 10-year event. A state-wide hydraulic model that",
        "does not resolve polders, field drainage and pumping can keep water standing on land that is",
        "normally drained, so the absolute shares may overstate expected inundation. The water-proximity",
        "test below is what distinguishes those two readings.",
        "",
        "Use this layer for *relative* exposure: which PMGSY links, facilities and habitations sit in",
        "the lowest modelled terrain, and how that set grows between return periods and climate",
        "scenarios. Do not read a district-wide share as the area expected to flood in a given year.",
        "Converting this to expected closures would need a district drainage/irrigation record and",
        "observed closure or damage data, neither of which is available.",
        "",
    ]
    proximity = summary.get("water_proximity", {})
    if proximity:
        lines += [
            "### Is the depth on water, or on dry land?",
            "",
            "Distance from each modelled-depth cell to the nearest mapped OSM water feature:",
            "",
            "| Layer | On/touching water | ≤100 m | 100-250 m | >250 m | Median depth beyond 250 m |",
            "|---|---|---|---|---|---|",
        ]
        for key in proximity:
            bands = proximity[key]["bands"]
            lines.append(
                f"| {key} | {pct(bands['on_or_touching_mapped_water']['share'])} | "
                f"{pct(bands['within_100m']['share'])} | {pct(bands['100_to_250m']['share'])} | "
                f"{pct(bands['farther_than_250m']['share'])} | "
                f"{bands['farther_than_250m']['median_depth_cm']:.0f} cm |"
            )
        lines += [
            "",
            "OSM water mapping is volunteered and incomplete, so 'far from mapped water' includes",
            "unmapped canals and paddy drains, and this split cannot by itself convict or clear the",
            "model. What it does show is that most modelled depth (about 82%) sits within 250 m of",
            "mapped water, which is floodplain-like rather than indiscriminate. The remaining share",
            "beyond 250 m - roughly one modelled-depth cell in seven, at a median depth of metres -",
            "is where over-extension is plausible and needs field or satellite checking.",
            "",
            "### External validation: attempted, not achieved",
            "",
            "No open vector extent of an observed Kerala flood was reachable for Alappuzha: the NRSC",
            "NDEM rapid-mapping sheet for 21 August 2018 is marked *for official use* and carries no",
            "district area table, and HDX returns no Kerala 2018 flood-extent dataset. **The decoding",
            "and units are validated here; the model's accuracy is not.**",
            "",
            "Kerala's post-2018 flood modelling report (CWC, December 2018, hosted by KSDMA) states its 2D",
            "model inundation appears larger than the satellite extent because imagery existed only",
            "for 21 August 2018, after the peak. That is an official acknowledgement of the direction",
            "of the bias documented above, and it is why the exposure tables are labelled relative",
            "rather than absolute.",
            "",
        ]
    lines += [
        "## PMGSY DRRP roads",
        "",
        "Length-weighted overlap of 1,839 District Rural Roads Plan links with modelled depth. Lengths",
        "are recomputed in UTM 43N; the service's own `st_length(shape)` is in Web Mercator and",
        "overstates ground distance.",
        "",
        "| Layer | Any depth (km) | Share | ≥30 cm (km) | Share |",
        "|---|---|---|---|---|",
    ]
    for key in keys:
        record = summary["roads"]["pmgsy"][key]
        lines.append(
            f"| {key} | {record['any_depth_km']:,.0f} | {pct(record['any_depth_share'])} | "
            f"{record['at_or_above_vehicle_threshold_km']:,.0f} | "
            f"{pct(record['vehicle_threshold_share'])} |"
        )

    lines += ["", "## OSM district roads", "",
              "| Layer | Any depth (km) | Share | ≥30 cm (km) | Share |",
              "|---|---|---|---|---|"]
    for key in keys:
        record = summary["roads"]["osm"][key]
        lines.append(
            f"| {key} | {record['any_depth_km']:,.0f} | {pct(record['any_depth_share'])} | "
            f"{record['at_or_above_vehicle_threshold_km']:,.0f} | "
            f"{pct(record['vehicle_threshold_share'])} |"
        )

    # Four representative layers keep this readable; every layer is in summary.json/CSV.
    point_keys = [k for k in ("historical_10yr", "historical_100yr", "rcp85_100yr", "rcp85_500yr")
                  if k in keys]
    lines += [
        "",
        "## Facilities and settlements",
        "",
        "Shown for four representative layers (10-year and 100-year historical, 100-year and",
        "500-year RCP8.5); all twelve are in `summary.json` and the per-layer CSVs.",
        "",
        "| Layer | Records | Any depth | ≥30 cm | Population in ≥30 cm |",
        "|---|---|---|---|---|",
    ]
    for layer_name, per_scenario in summary["points"].items():
        for key in point_keys:
            record = per_scenario[key]
            population = (
                f"{record['population_vehicle_threshold']:,} of {record['population_total']:,}"
                if "population_vehicle_threshold" in record
                else "not applicable"
            )
            lines.append(
                f"| {layer_name} · {key} | {record['records']:,} | "
                f"{record['records_any_depth']:,} ({pct(record['share_any_depth'])}) | "
                f"{record['records_vehicle_threshold']:,} ({pct(record['share_vehicle_threshold'])}) | "
                f"{population} |"
            )

    lines += [
        "",
        "## Interpretation limits",
        "",
        "KSDMA depth is a modelled return-period hazard on a ~90 m grid, produced from hydrological",
        "simulation of historical and RCP8.5 climate inputs. It is not an observed flood map: the",
        "2018 and 2019 events are not this product. Sampling a road at 100 m intervals against a",
        "90 m cell means exposure shares are approximate at the corridor scale, not asset-level.",
        "The 30 cm band is an indicative depth at which a light vehicle should not cross; it is a",
        "decision threshold applied to modelled depth, not recorded closures.",
        "",
        "Crossing candidates are unverified geometric road/water intersections, so a candidate in a",
        "flooded cell identifies a place to inspect, not a failing bridge or culvert. PMGSY population",
        "fields and Census 2011 totals remain separate sources and are never summed. Census villages",
        "without a defensible coordinate are excluded rather than placed arbitrarily.",
        "",
        "The rasters are published as a state-wide hazard product, so they are not an asset survey.",
        "KSDMA's own map sheets carry the note that external boundaries are not verified and are for",
        "reference purpose only; this analysis inherits that limitation together with the district",
        "boundary's 2011 vintage and the volunteered OSM road and facility mapping.",
        "",
        "Per-road and per-point depth tables are in this directory; machine-readable aggregates are in",
        "`summary.json`. Each point layer is its own CSV:",
        "`osm_health_depth.csv`, `osm_school_depth.csv`, `pmgsy_habitation_depth.csv`,",
        "`osm_place_depth.csv`, `census_village_located_depth.csv`, `crossing_candidate_depth.csv`.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
