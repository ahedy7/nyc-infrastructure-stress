"""
Compute the infrastructure stress index from baseline features.

Loads baseline_features.csv, z-scores each index feature across NTAs, and sets
stress_score to the mean of those z-scores (equal weights).
Outputs data_processed/baseline_index.csv.
"""

import pandas as pd
from pathlib import Path

from config import INDEX_FEATURES


def get_project_root() -> Path:
    """Project root is parent of src/."""
    return Path(__file__).resolve().parent.parent


def main():
    root = get_project_root()
    in_path = root / "data_processed" / "baseline_features.csv"
    out_dir = root / "data_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(in_path)

    missing = [f for f in INDEX_FEATURES if f not in df.columns]
    if missing:
        raise KeyError(
            "baseline_features.csv is missing index feature column(s): "
            + ", ".join(missing)
        )

    z_cols: list[str] = []
    for feat in INDEX_FEATURES:
        col = pd.to_numeric(df[feat], errors="coerce")
        zname = f"z_{feat}"
        z = (col - col.mean()) / col.std()
        df[zname] = z.fillna(0)
        z_cols.append(zname)

    df["stress_score"] = df[z_cols].mean(axis=1)

    out_path = out_dir / "baseline_index.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {out_path} ({len(df)} NTAs); index = mean of {len(INDEX_FEATURES)} z-scores")


if __name__ == "__main__":
    main()
