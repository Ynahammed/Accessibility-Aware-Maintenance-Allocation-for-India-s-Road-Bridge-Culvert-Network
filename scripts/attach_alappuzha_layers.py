"""Attach Alappuzha demand, facilities, and crossing candidates to district OSM.

Outputs are a separate processed spatial join and augmented graph. PMGSY-reported
point populations and Census village totals stay in separate layers; do not sum them.
Water intersections are screening candidates, not verified structures.

Run: python scripts/attach_alappuzha_layers.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Transformer, Geod
from scipy.spatial import cKDTree
from shapely.geometry import Point
from shapely.ops import transform
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from rra.ingest.osm import load_osm_graphml, tag_coverage  # noqa: E402
RAW=ROOT/'data/raw/osm_alappuzha_district'
PROCESSED=ROOT/'data/processed/alappuzha_network_join'
BOUNDARY_FILE=ROOT/'data/raw/boundaries/kerala_districts_census_2011.geojson'
PMGSY_CSV=ROOT/'data/processed/alappuzha_pmgsy_habitations_census_crosswalk.csv'
CENSUS_CSV=ROOT/'data/processed/alappuzha_census2011_pmgsy_join.csv'

# Alappuzha is in UTM zone 43N; this projected CRS gives metre distances.
TO_METRIC=Transformer.from_crs('EPSG:4326','EPSG:32643',always_xy=True)
FROM_METRIC=Transformer.from_crs('EPSG:32643','EPSG:4326',always_xy=True)
GEOD=Geod(ellps='WGS84')
WALKING_SPEED_KPH=5.0
ATTACH_LIMIT_M=500.0
NEAR_LIMIT_M=100.0
PLACE_TYPES={'city','town','village','hamlet','isolated_dwelling','suburb'}
HEALTH={'hospital','clinic','doctors'}
SCHOOLS={'school','college','kindergarten'}
HEALTHCARE={'hospital','clinic','doctor','health_post'}
TAG_RE=re.compile(r'"([^"]+)"\s*=>\s*"((?:[^"\\]|\\.)*)"')


def parse_tags(value):
    if value is None or pd.isna(value): return {}
    return {m.group(1):m.group(2).replace(r'\"','"').replace(r'\\','\\') for m in TAG_RE.finditer(str(value))}


def val(row,key,default=None):
    value=row.get(key,default)
    if value is None: return default
    try:
        if pd.isna(value): return default
    except (TypeError,ValueError): pass
    return value


def metric_xy(lon,lat):
    return TO_METRIC.transform(float(lon),float(lat))


def boundary_shape():
    data=json.loads(BOUNDARY_FILE.read_text(encoding='utf-8'))
    feature=next(f for f in data['features'] if f.get('properties',{}).get('censuscode')==598)
    from shapely.geometry import shape
    return shape(feature['geometry'])


def weighted_census_points(pmgsy: pd.DataFrame,census: pd.DataFrame):
    """One coordinate per matched Census village, weighted by PMGSY population field."""
    matched=pmgsy.loc[pmgsy.crosswalk_status.eq('exact_normalized_name_match')].copy()
    matched['census_village_code']=matched.census_village_code.astype('string')
    matched['mx'],matched['my']=zip(*matched.apply(lambda r:metric_xy(r.longitude,r.latitude),axis=1))
    result=[]
    for _,village in census.iterrows():
        code=str(village.census_village_code)
        group=matched.loc[matched.census_village_code.eq(code)]
        lon=lat=np.nan
        if not group.empty:
            weights=group.pmgsy_population_field.astype(float).clip(lower=0).to_numpy()
            if weights.sum()==0: weights=np.ones(len(group))
            mx=float(np.average(group.mx,weights=weights)); my=float(np.average(group.my,weights=weights))
            lon,lat=FROM_METRIC.transform(mx,my)
        result.append({
            'entity_id':f'census2011:{code}',
            'census_village_code':code,
            'census_village_name':village.census_village_name,
            'census_population_2011':int(village.census_population_2011),
            'matched_pmgsy_points':int(len(group)),
            'coordinate_method':'PMGSY-population-field-weighted centroid of exact-name matched points' if len(group) else 'unmatched: no defensible point coordinate',
            'longitude':lon,'latitude':lat,
        })
    return pd.DataFrame(result)


def snap_records(records:list[dict],node_ids:list,node_xy_metric:np.ndarray,tree:cKDTree):
    attached=[]
    for record in records:
        row=dict(record)
        lon=row.get('longitude'); lat=row.get('latitude')
        if lon is None or lat is None or pd.isna(lon) or pd.isna(lat):
            row.update(nearest_node_id=None,nearest_node_distance_m=np.nan,snap_status='no_coordinate',attached_to_network=False)
        else:
            mx,my=metric_xy(lon,lat)
            distance,index=tree.query([mx,my],k=1)
            distance=float(distance); nearest=node_ids[int(index)]
            status='near' if distance<=NEAR_LIMIT_M else 'acceptable' if distance<=ATTACH_LIMIT_M else 'distant'
            row.update(nearest_node_id=str(nearest),nearest_node_distance_m=distance,snap_status=status,attached_to_network=distance<=ATTACH_LIMIT_M)
        attached.append(row)
    return attached


def write_point_layer(records:list[dict],path:Path):
    frame=pd.DataFrame(records)
    # OSM IDs can be numeric in one feature type and text in another; Arrow requires
    # a stable physical type, so serialize object-valued source identifiers as text.
    for column in frame.columns:
        if pd.api.types.is_object_dtype(frame[column].dtype):
            frame[column]=frame[column].map(lambda value: None if value is None or (isinstance(value,float) and np.isnan(value)) else str(value))
    if 'longitude' in frame:
        frame['geometry']=[Point(x,y) if pd.notna(x) and pd.notna(y) else None for x,y in zip(frame.longitude,frame.latitude)]
        gdf=gpd.GeoDataFrame(frame,geometry='geometry',crs='EPSG:4326')
        gdf.to_parquet(path,index=False)
        return gdf
    frame.to_csv(path.with_suffix('.csv'),index=False)
    return frame


def linear_parts(geom):
    if geom is None or geom.is_empty: return
    if geom.geom_type=='LineString': yield geom
    elif geom.geom_type in ('MultiLineString','GeometryCollection'):
        for item in geom.geoms: yield from linear_parts(item)


def point_parts(geom):
    if geom is None or geom.is_empty: return
    if geom.geom_type=='Point': yield geom
    elif geom.geom_type in ('MultiPoint','GeometryCollection'):
        for item in geom.geoms: yield from point_parts(item)


def make_crossing_candidates(roads:gpd.GeoDataFrame,water:gpd.GeoDataFrame):
    """Intersect roads with mapped water; retain source IDs/tags and uncertainty class."""
    valid_water=[]
    for wi,row in water.iterrows():
        geom=row.geometry
        if geom is None or geom.is_empty: continue
        valid_water.append((wi,row,geom))
    tree=STRtree([item[2] for item in valid_water])
    records=[]
    for ri,road in roads.iterrows():
        road_geom=road.geometry
        if road_geom is None or road_geom.is_empty: continue
        road_tags=parse_tags(val(road,'other_tags'))
        bridge=road_tags.get('bridge','no')
        bridge_tagged=str(bridge).lower() not in {'','no','false','none','nan'}
        for candidate_index in tree.query(road_geom):
            wi,water_row,water_geom=valid_water[int(candidate_index)]
            water_class=str(val(water_row,'waterway',''))
            if water_geom.geom_type in ('LineString','MultiLineString'):
                intersection=road_geom.intersection(water_geom)
                method='road intersects mapped linear waterway'
            elif water_geom.geom_type in ('Polygon','MultiPolygon'):
                # Shoreline intersection avoids labeling roads wholly inside water polygons.
                intersection=road_geom.intersection(water_geom.boundary)
                method='road intersects mapped waterbody shoreline'
            else:
                continue
            if intersection.is_empty: continue
            points=list(point_parts(intersection))
            if not points and intersection.geom_type in ('LineString','MultiLineString'):
                points=[intersection.representative_point()]
            # keep candidate positions distinct along this road/water pair
            seen=set()
            for point in points:
                key=(round(point.x,7),round(point.y,7))
                if key in seen: continue
                seen.add(key)
                if water_class in ('river','stream','canal'):
                    priority='linear_waterway_screen'
                elif water_class in ('ditch','drain'):
                    priority='drainage_screen'
                else:
                    priority='waterbody_shoreline_screen'
                records.append({
                    'entity_id':f'crossing:{val(road,"osm_id",ri)}:{val(water_row,"osm_id",wi)}:{key[0]}:{key[1]}',
                    'road_osm_id':val(road,'osm_id',ri),
                    'road_name':val(road,'name'),
                    'road_highway':val(road,'highway'),
                    'road_bridge_tag':bridge,
                    'already_bridge_tagged':bridge_tagged,
                    'water_osm_id':val(water_row,'osm_id',wi),
                    'water_name':val(water_row,'name'),
                    'waterway_type':water_class,
                    'candidate_method':method,
                    'candidate_class':priority,
                    'verified_structure':False,
                    'longitude':point.x,'latitude':point.y,
                })
    return records


def main():
    PROCESSED.mkdir(parents=True,exist_ok=True)
    boundary=boundary_shape()
    graph=load_osm_graphml(RAW/'roads.graphml')
    node_ids=list(graph.nodes)
    node_xy=np.array([metric_xy(graph.nodes[n]['x'],graph.nodes[n]['y']) for n in node_ids],dtype=float)
    tree=cKDTree(node_xy)
    print(f'Road graph: {len(node_ids):,} nodes; snapping with EPSG:32643 KD-tree',flush=True)

    # PMGSY habitation points; point population is kept as a separate source field.
    pmgsy=pd.read_csv(PMGSY_CSV,dtype={'pmgsy_hab_id':'string','census_village_code':'string'})
    inside=pmgsy.apply(lambda r: boundary.contains(Point(float(r.longitude),float(r.latitude))),axis=1)
    excluded=int((~inside).sum()); pmgsy=pmgsy.loc[inside].copy()
    pm_records=[]
    for _,r in pmgsy.iterrows():
        pm_records.append({
            'entity_id':f'pmgsy:{r.pmgsy_hab_id}',
            'pmgsy_hab_id':str(r.pmgsy_hab_id),
            'habitation_name':r.pmgsy_habitation_name,
            'pmgsy_population_field':int(r.pmgsy_population_field),
            'population_source':'PMGSY TOT_POPULA field; reference year/definition retained from source metadata, not assumed to equal Census 2011',
            'census_village_code':str(r.census_village_code) if pd.notna(r.census_village_code) else None,
            'crosswalk_status':r.crosswalk_status,
            'longitude':float(r.longitude),'latitude':float(r.latitude),
        })
    pm_records=snap_records(pm_records,node_ids,node_xy,tree)
    pm_layer=write_point_layer(pm_records,PROCESSED/'pmgsy_habitations_snapped.parquet')

    # Census population once per village. Matched village coordinate is a weighted centroid;
    # unmatched villages are kept with null geometry, never assigned to an arbitrary point.
    census=pd.read_csv(CENSUS_CSV,dtype={'census_village_code':'string'})
    census['census_village_code']=census.census_village_code.str.strip()
    census_points=weighted_census_points(pmgsy,census)
    census_points=snap_records(census_points.to_dict(orient='records'),node_ids,node_xy,tree)
    census_layer=write_point_layer(census_points,PROCESSED/'census_villages_snapped.parquet')

    # OSM settlements; these add locations but have no observed population unless tagged.
    places=gpd.read_parquet(RAW/'places.parquet')
    place_records=[]
    for i,row in places.iterrows():
        p=row.geometry
        place_records.append({'entity_id':f'osm_place:{i}','osm_id':row.get('osm_id'),'name':row.get('name'),'place':row.get('place'),'osm_population':row.get('population'),'longitude':p.x,'latitude':p.y})
    place_records=snap_records(place_records,node_ids,node_xy,tree)
    place_layer=write_point_layer(place_records,PROCESSED/'osm_places_snapped.parquet')

    facilities=gpd.read_parquet(RAW/'facilities.parquet')
    facilities=facilities.loc[facilities.amenity.isin(HEALTH|SCHOOLS)].copy()
    facility_records=[]
    for i,row in facilities.iterrows():
        p=row.geometry
        facility_records.append({'entity_id':f'osm_facility:{i}','osm_id':row.get('osm_id'),'name':row.get('name'),'facility_type':'health' if row.amenity in HEALTH else 'school','amenity':row.amenity,'longitude':p.x,'latitude':p.y})
    facility_records=snap_records(facility_records,node_ids,node_xy,tree)
    facility_layer=write_point_layer(facility_records,PROCESSED/'osm_facilities_snapped.parquet')

    # OSM bridge/water intersections are candidates only. Retain bridge-tag info and method.
    roads=gpd.read_parquet(RAW/'roads.parquet'); water=gpd.read_parquet(RAW/'water.parquet')
    crossing_records=make_crossing_candidates(roads,water)
    crossing_records=snap_records(crossing_records,node_ids,node_xy,tree)
    crossing_layer=write_point_layer(crossing_records,PROCESSED/'water_crossing_candidates.parquet')

    # Add point nodes/connectors only if within 500 m. The joined graph is separate from raw graph.
    joined=graph.copy()
    layers=[('pmgsy',pm_records),('census2011',census_points),('osm_place',place_records),('osm_facility',facility_records),('crossing_candidate',crossing_records)]
    connector_count=0
    # Keep GraphML node IDs numeric: OSMnx's loader parses the entire node-ID
    # column as integers. Feature identity/type stay in attributes and Parquet.
    next_node_id=max(int(node) for node in joined.nodes)+1
    for layer_name,records in layers:
        for r in records:
            if not r.get('attached_to_network'): continue
            node=next_node_id
            next_node_id+=1
            x=float(r['longitude']); y=float(r['latitude']); dist=float(r['nearest_node_distance_m'])
            host=r['nearest_node_id']
            joined.add_node(node,x=x,y=y,kind=layer_name,source_id=str(r['entity_id']),snap_dist_m=dist)
            joined.add_edge(node,host,length_m=dist,highway='connector',speed_kph=WALKING_SPEED_KPH,
                            travel_time_min=(dist/1000)/WALKING_SPEED_KPH*60,is_bridge=False,is_culvert=False)
            connector_count+=1
    # GraphML values are serialized as strings for compatibility with OSMnx loader.
    for _,d in joined.nodes(data=True):
        for k,v in d.items(): d[k]=str(v)
    for _,_,d in joined.edges(data=True):
        for k,v in d.items(): d[k]=str(v)
    nx.write_graphml(joined,PROCESSED/'roads_with_snapped_features.graphml',encoding='utf-8')

    # QA summary preserves alternative demand sources and excluded/unmatched counts.
    def counts(records):
        statuses=pd.Series([r['snap_status'] for r in records]).value_counts().to_dict()
        return statuses
    crossing_classes=pd.Series([r['candidate_class'] for r in crossing_records]).value_counts().to_dict() if crossing_records else {}
    report=[
        '# Alappuzha network-linked public layers','',
        '- Raw roads and the original town-area graph are unchanged.',
        '- Snapping distances are computed in UTM zone 43N (EPSG:32643), then saved alongside WGS84 coordinates.',
        f'- Snap threshold: {ATTACH_LIMIT_M:.0f} m; near <= {NEAR_LIMIT_M:.0f} m; distances above threshold are retained but not connected in the augmented graph.',
        '- Connector edges are straight-line last-mile links at an assumed 5 km/h; this is a modelling assumption, not observed travel time.',
        '', '## Separate demand views (do not sum together)', '',
        f'- PMGSY habitation points retained inside boundary: {len(pm_records):,}; excluded by recheck: {excluded}; reported PMGSY population-field sum: {sum(r["pmgsy_population_field"] for r in pm_records):,} (source field, not relabelled as Census population).',
        f'- Census village records: {len(census_points)}; exact-name matched with coordinates: {sum(r["snap_status"]!="no_coordinate" for r in census_points)}; unmatched villages remain present with null coordinates.',
        '- Census 2011 village totals are stored once per village; matched coordinates are weighted centroids of exact-name PMGSY points, using PMGSY population field weights. This is an approximate spatial allocation, not an official village centroid.',
        '', '## Snap status', '',
        f'- PMGSY points: {counts(pm_records)}',
        f'- Census villages: {counts(census_points)}',
        f'- OSM places (no population imputed): {counts(place_records)}',
        f'- OSM facilities: {counts(facility_records)}',
        f'- Water-crossing candidates: {counts(crossing_records)}',
        f'- Attached nodes/connectors added to the separate augmented graph: {connector_count:,}',
        '', '## Water-crossing candidate limitations', '',
        f'- Candidate intersections: {len(crossing_records):,}; classes: {crossing_classes}.',
        '- A geometric road/water intersection does not establish that a bridge or culvert exists. These records require imagery or field/PWD verification and are not condition-rated assets.',
        '- Road bridge tags and waterway/waterbody feature tags are preserved for review; candidate layer includes `verified_structure=False`.',
        '', '## Outputs', '',
        '- `pmgsy_habitations_snapped.parquet`: PMGSY point counts/population field plus Census crosswalk and nearest road node.',
        '- `census_villages_snapped.parquet`: 52 village totals once each; only exact-match villages receive a derived coordinate.',
        '- `osm_places_snapped.parquet`: place locations, population not imputed.',
        '- `osm_facilities_snapped.parquet`: classified health/school points.',
        '- `water_crossing_candidates.parquet`: provisional intersection geometry and source tags.',
        '- `roads_with_snapped_features.graphml`: original network plus <=500 m feature connectors.',
        '',
    ]
    (PROCESSED/'README.md').write_text('\n'.join(report),encoding='utf-8')
    print('\n'.join(report),flush=True)


if __name__=='__main__': main()
