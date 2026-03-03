"""
Build baseline reference data for infrastructure stress index.

Reads arcgis_exports CSVs, merges on nta2020, computes heat/nonheat counts
and densities per km². Outputs data_processed/baseline_features.csv.
"""

import pandas as pd
from pathlib import Path


def get_project_root() -> Path:
    """Project root is parent of src/."""
    return Path(__file__).resolve().parent.parent


def main():
    root = get_project_root()
    arcgis = root / "arcgis_exports"
    out_dir = root / "data_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read CSVs
    area = pd.read_csv(arcgis / "nta_area.csv")
    heat = pd.read_csv(arcgis / "nta_311_heat.csv")
    nonheat = pd.read_csv(arcgis / "nta_311_nonheat.csv")

    # Rename Join_Count before merge to avoid column conflicts
    heat = heat.rename(columns={"Join_Count": "heat_count"})
    nonheat = nonheat.rename(columns={"Join_Count": "nonheat_count"})

    # Merge on nta2020
    df = area.merge(heat[["nta2020", "heat_count"]], on="nta2020", how="left")
    df = df.merge(nonheat[["nta2020", "nonheat_count"]], on="nta2020", how="left")

    # Fill missing counts with 0
    df["heat_count"] = df["heat_count"].fillna(0).astype(int)
    df["nonheat_count"] = df["nonheat_count"].fillna(0).astype(int)

    # Compute densities per km²
    df["heat_per_km2"] = df["heat_count"] / df["area_km2"]
    df["nonheat_per_km2"] = df["nonheat_count"] / df["area_km2"]

    out_path = out_dir / "baseline_features.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {out_path} ({len(df)} NTAs)")


if __name__ == "__main__":
    main()
