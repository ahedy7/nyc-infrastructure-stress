"""
ETL: NYC 311 power outage complaints -> NTA-level complaint density.

Source dataset (NYC Open Data / Socrata):
  https://data.cityofnewyork.us/Social-Services/power-outage-complaints/br6j-yp22/about_data
API endpoint:
  https://data.cityofnewyork.us/resource/br6j-yp22.json

The dataset contains per-complaint latitude/longitude. We fetch all complaints
within a user-provided date window, spatially join points to 2020 NTA polygons,
then compute complaint_count and util_outage_density = complaint_count / area_km2.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

OUTAGES_URL = "https://data.cityofnewyork.us/resource/br6j-yp22.json"
PAGE_SIZE = 50_000


def ensure_nta_layer_path(nta_dir: Path) -> Path:
    """
    Return a usable local path to NTA boundaries (prefer .shp, otherwise .geojson).

    The repo often contains a GeoJSON at:
      data_raw/nta_2020/geo_export.geojson
    and a shapefile inside:
      data_raw/nta_2020/_extract/*.shp
    """

    preferred = nta_dir / "geo_export.shp"
    if preferred.exists():
        return preferred

    shps = sorted(nta_dir.glob("*.shp"))
    if shps:
        return shps[0]

    extract_dir = nta_dir / "_extract"
    if extract_dir.exists():
        shps = sorted(extract_dir.glob("*.shp"))
        if shps:
            return shps[0]

    preferred_geo = nta_dir / "geo_export.geojson"
    if preferred_geo.exists():
        return preferred_geo

    geos = sorted(nta_dir.glob("*.geojson"))
    if geos:
        return geos[0]

    raise FileNotFoundError(
        "Could not find NTA boundaries. Expected one of:\n"
        f"  - {nta_dir/'geo_export.shp'}\n"
        f"  - {nta_dir/'_extract/*.shp'}\n"
        f"  - {nta_dir/'geo_export.geojson'}"
    )


def _build_where(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """
    Build Socrata $where for created_date in [start, end] (inclusive by day).

    We implement this as:
      created_date >= startT00:00:00.000 AND created_date < (end+1day)T00:00:00.000
    to avoid time-of-day edge cases.
    """

    start = pd.Timestamp(start).normalize()
    end_exclusive = (pd.Timestamp(end).normalize() + pd.Timedelta(days=1))
    return (
        f"created_date >= '{start.strftime('%Y-%m-%dT00:00:00.000')}' "
        f"and created_date < '{end_exclusive.strftime('%Y-%m-%dT00:00:00.000')}'"
    )


def fetch_outage_complaints(
    session: requests.Session,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """Paginate complaint rows filtered by created_date window."""

    where = _build_where(start_date, end_date)
    offset = 0
    chunks: list[pd.DataFrame] = []

    while True:
        r = session.get(
            OUTAGES_URL,
            params={
                "$where": where,
                "$order": "created_date",
                "$limit": PAGE_SIZE,
                "$offset": offset,
                "$select": "unique_key,created_date,latitude,longitude,location",
            },
            timeout=120,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break

        chunks.append(pd.DataFrame(rows))
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not chunks:
        return pd.DataFrame(columns=["unique_key", "created_date", "latitude", "longitude"])

    out = pd.concat(chunks, ignore_index=True)
    if "created_date" in out.columns:
        out["created_date"] = pd.to_datetime(out["created_date"], errors="coerce", utc=True).dt.tz_convert(None)
    return out


def _coerce_lat_lon(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize coordinates to numeric `latitude`/`longitude`.

    Prefers explicit latitude/longitude fields; falls back to `location.coordinates`
    if needed.
    """

    df = df.copy()

    lat = pd.to_numeric(df.get("latitude"), errors="coerce")
    lon = pd.to_numeric(df.get("longitude"), errors="coerce")

    need = lat.isna() | lon.isna()
    if need.any() and "location" in df.columns:
        loc = df.loc[need, "location"]

        def _extract_lon_lat(v):
            if not isinstance(v, dict):
                return (None, None)
            coords = v.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                return (coords[0], coords[1])  # (lon, lat)
            return (v.get("longitude"), v.get("latitude"))

        extracted = loc.map(_extract_lon_lat)
        lon2 = pd.to_numeric(extracted.map(lambda t: t[0]), errors="coerce")
        lat2 = pd.to_numeric(extracted.map(lambda t: t[1]), errors="coerce")
        lon.loc[need] = lon2
        lat.loc[need] = lat2

    df["latitude"] = lat
    df["longitude"] = lon
    return df


def build_output_table(
    complaints: pd.DataFrame,
    nta: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, dict]:
    """Return output table and run stats."""

    complaints = _coerce_lat_lon(complaints)
    total_rows = int(len(complaints))
    valid_coords = complaints["latitude"].notna() & complaints["longitude"].notna()
    complaints = complaints[valid_coords].copy()

    pts = gpd.GeoDataFrame(
        complaints,
        geometry=gpd.points_from_xy(complaints["longitude"], complaints["latitude"]),
        crs="EPSG:4326",
    )

    nta = nta.copy()
    if nta.crs is None:
        nta.set_crs("EPSG:4326", inplace=True)
    else:
        nta = nta.to_crs("EPSG:4326")

    needed_cols = {"nta2020", "ntaname"}
    missing = needed_cols - set(nta.columns)
    if missing:
        raise RuntimeError(f"NTA layer missing required columns: {sorted(missing)}")

    nta_wgs = nta[["nta2020", "ntaname", "geometry"]].copy()
    joined = gpd.sjoin(
        pts,
        nta_wgs,
        how="left",
        predicate="intersects",
    )

    matched = joined["nta2020"].notna()
    matched_rows = int(matched.sum())
    unmatched_rows = int((~matched).sum())

    counts = (
        joined.loc[matched]
        .groupby("nta2020")["unique_key"]
        .size()
        .astype(int)
        .rename("complaint_count")
        .reset_index()
    )

    nta_out = nta_wgs.drop(columns=["geometry"]).copy()
    nta_area = nta_wgs.to_crs(32618)
    nta_out["area_km2"] = (nta_area.geometry.area / 1_000_000.0).astype(float)

    out = nta_out.merge(counts, on="nta2020", how="left")
    out["complaint_count"] = out["complaint_count"].fillna(0).astype(int)
    out["util_outage_density"] = out["complaint_count"] / out["area_km2"].replace(0, float("nan"))
    out["util_outage_density"] = out["util_outage_density"].fillna(0.0).astype(float)

    out = out.rename(columns={"nta2020": "NTACode", "ntaname": "NTAName"})[
        ["NTACode", "NTAName", "complaint_count", "area_km2", "util_outage_density"]
    ]

    stats = {
        "total_rows_fetched": total_rows,
        "rows_with_valid_coords": int(len(pts)),
        "rows_matched_to_nta": matched_rows,
        "rows_unmatched_to_nta": unmatched_rows,
        "nta_count": int(len(out)),
        "nta_with_complaints": int((out["complaint_count"] > 0).sum()),
    }
    return out, stats


def main(argv: list[str] | None = None) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    default_out = repo_root / "data_processed" / "nta_outages.csv"
    default_nta_dir = repo_root / "data_raw" / "nta_2020"

    parser = argparse.ArgumentParser(description="311 power outage complaints -> NTA CSV")
    parser.add_argument(
        "--output",
        type=Path,
        default=default_out,
        help=f"Output CSV path (default: {default_out})",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-02-15",
        help="Window start (YYYY-MM-DD). Inclusive by day.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-02-15",
        help="Window end (YYYY-MM-DD). Inclusive by day.",
    )
    parser.add_argument(
        "--nta-dir",
        type=Path,
        default=default_nta_dir,
        help="Directory with 2020 NTA boundaries (expects geo_export.shp or geo_export.geojson).",
    )
    args = parser.parse_args(argv)

    start = pd.Timestamp(args.start_date).normalize()
    end = pd.Timestamp(args.end_date).normalize()
    if end < start:
        raise ValueError("end-date must be >= start-date")

    session = requests.Session()
    complaints = fetch_outage_complaints(session, start, end)

    nta_path = ensure_nta_layer_path(args.nta_dir)
    nta = gpd.read_file(nta_path)

    out, stats = build_output_table(complaints, nta)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)

    top = out.sort_values("util_outage_density", ascending=False).head(5)
    print("Summary")
    print(f"  Window: {start.date()} to {end.date()} (inclusive)")
    print(f"  Total rows fetched: {stats['total_rows_fetched']}")
    print(f"  Rows with valid coords: {stats['rows_with_valid_coords']}")
    print(f"  Rows matched to NTA: {stats['rows_matched_to_nta']}")
    print(f"  Rows unmatched to NTA: {stats['rows_unmatched_to_nta']}")
    print(f"  NTAs total: {stats['nta_count']}")
    print(f"  NTAs with complaint_count > 0: {stats['nta_with_complaints']}")
    if len(top):
        print("  Top 5 NTAs by util_outage_density:")
        for _, row in top.iterrows():
            print(
                f"    {row['NTACode']} - {row['NTAName']}: "
                f"{int(row['complaint_count'])} complaints, "
                f"{float(row['util_outage_density']):.6g} per km^2"
            )
    print(f"  Wrote: {args.output}")


if __name__ == "__main__":
    main()
