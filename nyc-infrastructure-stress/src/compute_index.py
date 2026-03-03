"""
Compute the infrastructure stress index from baseline features.

Loads baseline_features.csv, z-scores heat/nonheat densities across NTAs,
computes service_strain = mean(z_heat, z_nonheat), stress_score = service_strain.
Outputs data_processed/baseline_index.csv.
"""

import pandas as pd
from pathlib import Path


def get_project_root() -> Path:
    """Project root is parent of src/."""
    return Path(__file__).resolve().parent.parent


def main():
    root = get_project_root()
    in_path = root / "data_processed" / "baseline_features.csv"
    out_dir = root / "data_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(in_path)

    # Z-score heat_per_km2 and nonheat_per_km2 across NTAs
    df["z_heat"] = (df["heat_per_km2"] - df["heat_per_km2"].mean()) / df["heat_per_km2"].std()
    df["z_nonheat"] = (df["nonheat_per_km2"] - df["nonheat_per_km2"].mean()) / df["nonheat_per_km2"].std()

    # Handle NaN from zero std (e.g. constant column)
    df["z_heat"] = df["z_heat"].fillna(0)
    df["z_nonheat"] = df["z_nonheat"].fillna(0)

    # service_strain = mean(z_heat, z_nonheat)
    df["service_strain"] = (df["z_heat"] + df["z_nonheat"]) / 2

    # For now: stress_score = service_strain
    df["stress_score"] = df["service_strain"]

    out_path = out_dir / "baseline_index.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {out_path} ({len(df)} NTAs)")


if __name__ == "__main__":
    main()
