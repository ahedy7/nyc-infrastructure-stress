"""
ETL: FEMA flood hazard zones -> NTA flood share (static feature).

Goal: Compute FEMA Special Flood Hazard Area (SFHA) share per 2020 NTA.

Flood zones:
- SFHA zones include any FEMA zone starting with "A" or "V" (e.g., A, AE, AO,
  AH, A99, V, VE).

Data sources:
- Prefer a local FEMA flood hazard zone layer in data_raw/fema_flood/ (shapefile,
  GeoJSON, GeoPackage).
- Otherwise fetch from FEMA NFHL ArcGIS REST service (layer 28: Flood Hazard
  Zones). This is the upstream source the NY Open Data listing references.

Output: data_processed/nta_flood_zones.csv with columns:
  NTACode, NTAName, area_km2, flood_area_km2, clim_flood_share
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

NTA_CRS_AREA = "EPSG:2263"  # NAD83 / New York Long Island (ftUS) — best for NYC areas

DEFAULT_NYC_BBOX_WGS84 = (-74.2591, 40.4774, -73.7004, 40.9176)  # NYC approx

# FEMA NFHL ArcGIS REST (public) — Flood Hazard Zones layer id is 28.
NFHL_FLOOD_HAZARD_ZONES_QUERY_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)

# If hazards.fema.gov is unreachable in some environments, fall back to Esri's
# Living Atlas "USA Flood Hazard Areas (Reduced Set)" derived from NFHL
# (includes FLD_ZONE and SFHA_TF).
LIVING_ATLAS_FLOOD_HAZARD_ZONES_QUERY_URL = (
    "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
    "USA_Flood_Hazard_Reduced_Set_gdb/FeatureServer/0/query"
)


@dataclass(frozen=True)
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def as_envelope_json(self) -> dict:
        return {
            "xmin": self.xmin,
            "ymin": self.ymin,
            "xmax": self.xmax,
            "ymax": self.ymax,
            "spatialReference": {"wkid": 4326},
        }


def _is_sfha_zone(val: object) -> bool:
    if val is None:
        return False
    s = str(val).strip().upper()
    return bool(s) and (s.startswith("A") or s.startswith("V"))


def _find_first_vector_file(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    candidates: list[Path] = []
    candidates += sorted(directory.glob("*.shp"))
    candidates += sorted(directory.glob("*.geojson"))
    candidates += sorted(directory.glob("*.json"))
    candidates += sorted(directory.glob("*.gpkg"))
    return candidates[0] if candidates else None


def load_nta_layer(nta_path: Path) -> gpd.GeoDataFrame:
    nta = gpd.read_file(nta_path)
    if nta.empty:
        raise RuntimeError(f"NTA layer is empty: {nta_path}")
    if nta.crs is None:
        raise RuntimeError(f"NTA layer has unknown CRS: {nta_path}")
    required = {"nta2020", "ntaname"}
    missing = required - set(map(str.lower, nta.columns))
    if missing:
        # Be permissive: try to locate likely columns.
        cols = {c.lower(): c for c in nta.columns}
        if "nta2020" in cols and "ntaname" in cols:
            nta = nta.rename(columns={cols["nta2020"]: "nta2020", cols["ntaname"]: "ntaname"})
        else:
            raise RuntimeError(
                "NTA layer missing required columns (expected nta2020, ntaname). "
                f"Have: {nta.columns.tolist()}"
            )
    return nta


def load_fema_flood_zones_local(path_or_dir: Path) -> gpd.GeoDataFrame | None:
    if path_or_dir.is_file():
        path = path_or_dir
    else:
        path = _find_first_vector_file(path_or_dir)
        if path is None:
            return None

    gdf = gpd.read_file(path)
    if gdf.empty:
        raise RuntimeError(f"FEMA flood hazard layer is empty: {path}")
    if gdf.crs is None:
        raise RuntimeError(f"FEMA flood hazard layer has unknown CRS: {path}")

    # Try common field names for flood zone code.
    zone_col = None
    for c in gdf.columns:
        if str(c).strip().upper() in {"FLD_ZONE", "FLOODZONE", "ZONE", "FLDZON", "FLDZONE"}:
            zone_col = c
            break
    if zone_col is None:
        raise RuntimeError(
            "Could not find a flood zone field in local FEMA layer. "
            f"Columns: {gdf.columns.tolist()}"
        )

    gdf = gdf[gdf[zone_col].map(_is_sfha_zone)].copy()
    gdf = gdf.rename(columns={zone_col: "FLD_ZONE"})
    gdf = gdf[gdf.geometry.notna()]
    return gdf[["FLD_ZONE", "geometry"]]


def _arcgis_query_geojson(
    *,
    url: str,
    bbox: BBox,
    session: requests.Session,
    out_fields: str,
    page_size: int,
) -> list[dict]:
    """Query an ArcGIS Feature/MapServer layer endpoint returning GeoJSON features."""
    features: list[dict] = []
    offset = 0

    while True:
        r = session.get(
            url,
            params={
                "where": "1=1",
                "geometry": json.dumps(bbox.as_envelope_json()),
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": out_fields,
                "returnGeometry": "true",
                "outSR": 4326,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "geojson",
            },
            timeout=300,
        )
        r.raise_for_status()
        payload = r.json()
        page = payload.get("features") or []
        if not page:
            break
        features.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    return features


def fetch_fema_flood_zones_remote(bbox: BBox, session: requests.Session) -> gpd.GeoDataFrame:
    """
    Fetch FEMA NFHL Flood Hazard Zones intersecting bbox from ArcGIS REST.

    Uses resultOffset pagination (maxRecordCount=2000).
    Returns GeoDataFrame in EPSG:4326 with columns FLD_ZONE, geometry.
    """
    try:
        all_features = _arcgis_query_geojson(
            url=NFHL_FLOOD_HAZARD_ZONES_QUERY_URL,
            bbox=bbox,
            session=session,
            out_fields="FLD_ZONE",
            page_size=2000,
        )
    except requests.RequestException as e:
        print(
            f"Warning: NFHL endpoint failed ({type(e).__name__}); falling back to Living Atlas.",
            file=sys.stderr,
        )
        all_features = _arcgis_query_geojson(
            url=LIVING_ATLAS_FLOOD_HAZARD_ZONES_QUERY_URL,
            bbox=bbox,
            session=session,
            out_fields="FLD_ZONE,SFHA_TF",
            page_size=250,  # service maxRecordCount
        )

    if not all_features:
        return gpd.GeoDataFrame({"FLD_ZONE": []}, geometry=[], crs="EPSG:4326")

    records: list[dict] = []
    geoms = []
    for f in all_features:
        props = f.get("properties") or {}
        zone = props.get("FLD_ZONE")
        if not _is_sfha_zone(zone):
            continue
        geom = f.get("geometry")
        if geom is None:
            continue
        geoms.append(shape(geom))
        records.append({"FLD_ZONE": str(zone).strip().upper()})

    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
    return gdf


def compute_flood_share_by_nta(
    nta: gpd.GeoDataFrame,
    flood: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Compute flood area intersection share per NTA in EPSG:2263.

    Implementation note: we unary_union all flood polygons (SFHA-only), then
    intersect once per NTA geometry to avoid an expensive full overlay.
    """
    nta_2263 = nta.to_crs(NTA_CRS_AREA).copy()
    flood_2263 = flood.to_crs(NTA_CRS_AREA).copy()

    nta_2263 = nta_2263[nta_2263.geometry.notna()].copy()
    flood_2263 = flood_2263[flood_2263.geometry.notna()].copy()

    # Clean invalid geometries where possible (buffer(0) trick).
    nta_2263["geometry"] = nta_2263.geometry.buffer(0)
    flood_2263["geometry"] = flood_2263.geometry.buffer(0)

    # geopandas/shapely are transitioning away from unary_union
    flood_union = (
        flood_2263.geometry.union_all()
        if hasattr(flood_2263.geometry, "union_all")
        else flood_2263.geometry.unary_union
    )

    nta_area_m2 = nta_2263.geometry.area
    flood_area_m2 = nta_2263.geometry.apply(lambda g: g.intersection(flood_union).area)

    out = pd.DataFrame(
        {
            "NTACode": nta_2263["nta2020"].astype(str).values,
            "NTAName": nta_2263["ntaname"].astype(str).values,
            "area_km2": (nta_area_m2 / 1_000_000.0).astype(float).values,
            "flood_area_km2": (flood_area_m2 / 1_000_000.0).astype(float).values,
        }
    )
    out["clim_flood_share"] = out["flood_area_km2"] / out["area_km2"].replace(0, float("nan"))
    out["clim_flood_share"] = out["clim_flood_share"].fillna(0.0).clip(lower=0.0, upper=1.0)
    return out


def main(argv: list[str] | None = None) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    default_out = repo_root / "data_processed" / "nta_flood_zones.csv"
    default_nta_path = repo_root / "data_raw" / "nta_2020" / "geo_export.shp"
    default_fema_dir = repo_root / "data_raw" / "fema_flood"

    parser = argparse.ArgumentParser(description="Compute FEMA flood zone share per NTA.")
    parser.add_argument(
        "--nta-path",
        type=Path,
        default=default_nta_path,
        help=f"NTA shapefile/GeoJSON path (default: {default_nta_path})",
    )
    parser.add_argument(
        "--fema-path",
        type=Path,
        default=default_fema_dir,
        help=(
            "Local FEMA flood zone file or directory (default: data_raw/fema_flood). "
            "If missing/empty, the script fetches from FEMA NFHL service."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_out,
        help=f"Output CSV path (default: {default_out})",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=list(DEFAULT_NYC_BBOX_WGS84),
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        help="Fetch bbox in EPSG:4326 when using remote FEMA service (default: NYC approx).",
    )
    args = parser.parse_args(argv)

    # The project expects a shapefile, but some checkouts only have GeoJSON.
    if not args.nta_path.exists():
        fallback = None
        if args.nta_path.name.lower().endswith(".shp"):
            cand_geojson = args.nta_path.with_suffix(".geojson")
            if cand_geojson.exists():
                fallback = cand_geojson
            else:
                # Try any reasonable file in the same directory.
                same_dir = args.nta_path.parent
                for ext in (".shp", ".geojson", ".json", ".gpkg"):
                    matches = sorted(same_dir.glob(f"*{ext}"))
                    if matches:
                        fallback = matches[0]
                        break
        if fallback is None:
            raise FileNotFoundError(f"NTA layer not found: {args.nta_path}")
        print(f"Note: using fallback NTA layer: {fallback}", file=sys.stderr)
        args.nta_path = fallback

    nta = load_nta_layer(args.nta_path)

    flood = load_fema_flood_zones_local(args.fema_path)
    if flood is None:
        bbox = BBox(*map(float, args.bbox))
        session = requests.Session()
        flood = fetch_fema_flood_zones_remote(bbox, session)
        if flood.empty:
            raise RuntimeError(
                "Remote FEMA query returned 0 SFHA features. "
                "Try expanding --bbox or provide a local FEMA dataset under data_raw/fema_flood/."
            )

    out = compute_flood_share_by_nta(nta, flood)
    out = out.sort_values(["clim_flood_share", "NTACode"], ascending=[False, True]).reset_index(drop=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)

    n_positive = int((out["clim_flood_share"] > 0).sum())
    max_row = out.iloc[0] if len(out) else None
    max_share = float(max_row["clim_flood_share"]) if max_row is not None else float("nan")
    max_nta = (
        f"{max_row['NTACode']} ({max_row['NTAName']})" if max_row is not None else "—"
    )

    print("Summary")
    print(f"  NTAs with flood_share > 0: {n_positive}/{len(out)}")
    print(f"  Max flood_share NTA: {max_nta} = {max_share:.6g}")
    print(f"  Wrote: {args.output}")


if __name__ == "__main__":
    main()

