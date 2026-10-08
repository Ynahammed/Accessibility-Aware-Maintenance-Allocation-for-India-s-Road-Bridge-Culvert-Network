"""Download the open datasets used by the road-resilience project.

Run on your own machine (needs internet):

    pip install imdlib osmnx geopandas pyarrow
    python scripts/download_data.py --district "YOUR DISTRICT, YOUR STATE, India" \
        --start-year 1990 --end-year 2024 --out data/raw

What this fetches automatically:
  1. IMD gridded daily rainfall (0.25 degree) via imdlib, year by year.
  2. An OpenStreetMap drivable road network for one district via osmnx.
  3. US National Bridge Inventory yearly delimited files (FHWA), which are the real
     labelled histories used to validate the deterioration models (E1/E2).

What it cannot fetch (it prints the pages instead):
  - PMGSY rural connectivity layers (roads, habitations, facilities)
  - IBMS / state PWD condition records (needs a data request)

Reachability note: in a sandboxed run, imdpune.gov.in and geosadak-pmgsy.nic.in may be
unreachable while download.geofabrik.de, overpass-api.de and fhwa.dot.gov work. The NBI
leg is therefore the one most likely to succeed anywhere.
"""
import argparse
import sys
from pathlib import Path

# 2-letter state codes -> FIPS state code used inside the NBI files
NBI_DEFAULT_STATES = ["AL", "CA", "TX", "NY", "IL", "OH"]

# Overpass mirrors, tried in order. Individual mirrors 500/timeout unpredictably, so the
# downloader falls through this list per request.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _candidate_mirrors(primary):
    out = ([primary] if primary else []) + [m for m in OVERPASS_MIRRORS if m != primary]
    return out


def download_imd(start_year, end_year, out_dir):
    import imdlib as imd

    target = out_dir / "imd_rain"
    target.mkdir(parents=True, exist_ok=True)
    # imdlib downloads one binary .grd file per year from IMD Pune.
    imd.get_data("rain", start_year, end_year, fn_format="yearwise", file_dir=str(target))
    print(f"IMD rainfall {start_year}-{end_year} saved under {target}")


def _safe_to_parquet(gdf, path):
    """Write a GeoDataFrame to Parquet, stringifying mixed-type object columns.

    OSM edge columns like ``osmid`` mix scalars and lists, which Arrow rejects; casting
    them to strings loses nothing for our purposes.
    """
    out = gdf.copy()
    geom = getattr(out, "geometry", None)
    geom_name = geom.name if geom is not None else None
    for col in out.columns:
        if col != geom_name and out[col].dtype == object:
            out[col] = out[col].astype(str)
    out.to_parquet(path)


def download_osm(district, out_dir, overpass_url=None, timeout=600):
    import osmnx as ox

    if overpass_url:
        ox.settings.overpass_url = overpass_url
    ox.settings.requests_timeout = timeout
    ox.settings.http_user_agent = "rra-research/0.1 (road resilience allocation)"

    target = out_dir / "osm"
    target.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_place(district, network_type="drive", simplify=True)
    ox.save_graphml(graph, target / "roads.graphml")
    nodes, edges = ox.graph_to_gdfs(graph)
    _safe_to_parquet(nodes, target / "nodes.parquet")
    _safe_to_parquet(edges.reset_index(), target / "edges.parquet")
    print(f"OSM roads for '{district}': {len(nodes)} nodes, {len(edges)} edges -> {target}")


def download_osm_bbox(bbox, out_dir, overpass_url=None, timeout=600):
    """Fallback for large districts: fetch by (north, south, east, west) bbox."""
    import osmnx as ox

    if overpass_url:
        ox.settings.overpass_url = overpass_url
    ox.settings.requests_timeout = timeout
    ox.settings.http_user_agent = "rra-research/0.1 (road resilience allocation)"
    north, south, east, west = bbox
    target = out_dir / "osm"
    target.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_bbox(
        bbox=(west, south, east, north), network_type="drive", simplify=True
    )
    ox.save_graphml(graph, target / "roads.graphml")
    nodes, edges = ox.graph_to_gdfs(graph)
    _safe_to_parquet(nodes, target / "nodes.parquet")
    _safe_to_parquet(edges.reset_index(), target / "edges.parquet")
    print(f"OSM roads for bbox {bbox}: {len(nodes)} nodes, {len(edges)} edges -> {target}")


def download_nbi(states, years, out_dir):
    """Fetch FHWA NBI delimited files: data/raw/nbi/<year>/<ST><YY>.txt."""
    import urllib.request

    base = "https://www.fhwa.dot.gov/bridge/nbi"
    ok, failed = 0, []
    for year in years:
        y2 = str(year)[-2:]
        target = out_dir / "nbi" / str(year)
        target.mkdir(parents=True, exist_ok=True)
        for st in states:
            url = f"{base}/{year}/delimited/{st}{y2}.txt"
            dest = target / f"{st}{y2}.txt"
            if dest.exists() and dest.stat().st_size > 0:
                ok += 1
                continue
            try:
                urllib.request.urlretrieve(url, dest)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed.append((year, st, str(exc)))
                print(f"  ! {st}{y2}: {exc}")
    print(f"NBI: {ok} files under {out_dir / 'nbi'}"
          + (f", {len(failed)} failed" if failed else ""))


OSM_FEATURE_TAGS = {
    "water": {"waterway": True, "natural": "water", "water": True},
    "places": {"place": ["village", "hamlet", "town", "city"]},
    "facilities": {"amenity": ["hospital", "clinic", "doctors", "school", "college",
                                "kindergarten"]},
}


def download_osm_features(bbox, out_dir, overpass_url=None, timeout=600):
    """Fetch the point/line/polygon features the pipeline needs (plan 5.1).

    ``water`` supports the road-over-water crossing inference that recovers the structures
    OSM leaves untagged (0% culvert coverage in the test district). ``places`` become
    habitations and ``facilities`` health/school destinations.
    """
    import osmnx as ox
    import pandas as pd

    if overpass_url:
        ox.settings.overpass_url = overpass_url
    ox.settings.requests_timeout = timeout
    ox.settings.http_user_agent = "rra-research/0.1 (road resilience allocation)"

    north, south, east, west = bbox
    target = out_dir / "osm"
    target.mkdir(parents=True, exist_ok=True)
    written = []
    mirrors = _candidate_mirrors(overpass_url)
    for name, tags in OSM_FEATURE_TAGS.items():
        gdf = None
        for mirror in mirrors:
            ox.settings.overpass_url = mirror
            try:
                gdf = ox.features_from_bbox(bbox=(west, south, east, north), tags=tags)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  ! features '{name}' via {mirror}: {str(exc)[:90]}")
                gdf = None
        if gdf is None:
            print(f"  ! features '{name}': all mirrors failed")
            continue
        if len(gdf) == 0:
            print(f"  ! features '{name}': none found")
            continue
        path = target / f"{name}.parquet"
        gdf.reset_index().to_parquet(path)
        written.append((name, len(gdf)))
        print(f"  features '{name}': {len(gdf)} rows -> {path}")
    return written


def print_manual_steps(out_dir):
    print(
        f"""
Manual downloads (save into {out_dir}):

  PMGSY rural connectivity (roads, habitations, facilities; GODL licence)
    https://geosadak-pmgsy.nic.in/opendata/
    Save under {out_dir / 'pmgsy'}.

  US National Bridge Inventory (only if the automatic fetch above failed)
    https://www.fhwa.dot.gov/bridge/nbi/ascii.cfm
    Record format: https://www.fhwa.dot.gov/bridge/nbi/format.cfm

  Indian bridge/culvert condition (IBMS or state PWD)
    No public download found. Send a data request to the state PWD / MoRTH.
"""
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--district", default=None, help='e.g. "District, State, India"')
    parser.add_argument("--start-year", type=int, default=1990)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    parser.add_argument("--skip-imd", action="store_true")
    parser.add_argument("--skip-osm", action="store_true")
    parser.add_argument("--skip-nbi", action="store_true")
    parser.add_argument("--nbi-states", nargs="+", default=NBI_DEFAULT_STATES)
    parser.add_argument("--nbi-start", type=int, default=2016)
    parser.add_argument("--nbi-end", type=int, default=2023)
    parser.add_argument("--overpass-url", default=None,
                        help="Overpass mirror, e.g. https://overpass.kumi.systems/api/interpreter")
    parser.add_argument("--osm-timeout", type=int, default=900)
    parser.add_argument("--osm-bbox", nargs=4, type=float, default=None,
                        metavar=("N", "S", "E", "W"),
                        help="fallback: fetch by bounding box instead of place name")
    parser.add_argument("--osm-features", action="store_true",
                        help="also fetch water/places/facilities for the bbox")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.skip_imd:
        try:
            download_imd(args.start_year, args.end_year, args.out)
        except Exception as exc:  # noqa: BLE001
            print(f"IMD download failed (host may be unreachable): {exc}")
    if not args.skip_osm:
        try:
            if args.osm_bbox:
                download_osm_bbox(
                    tuple(args.osm_bbox), args.out, args.overpass_url, args.osm_timeout
                )
            elif args.district:
                download_osm(
                    args.district, args.out, args.overpass_url, args.osm_timeout
                )
            else:
                print("OSM skipped: pass --district or --osm-bbox.")
        except Exception as exc:  # noqa: BLE001
            print(f"OSM download failed: {exc}")
    if args.osm_features:
        bbox = tuple(args.osm_bbox) if args.osm_bbox else None
        if bbox is None:
            print("OSM features skipped: pass --osm-bbox")
        else:
            try:
                download_osm_features(bbox, args.out, args.overpass_url, args.osm_timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"OSM features failed: {exc}")
    if not args.skip_nbi:
        download_nbi(args.nbi_states, range(args.nbi_start, args.nbi_end + 1), args.out)
    print_manual_steps(args.out)


if __name__ == "__main__":
    sys.exit(main())
