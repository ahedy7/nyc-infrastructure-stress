"""
Configuration and path constants for the NYC Infrastructure Stress pipeline.

Stress index uses four features (equal-weight z-scores). DOT road-speed data is excluded
from the index by design; see PROJECT_BRIEF.md.
"""

from pathlib import Path


def get_project_root() -> Path:
    """Project root is parent of src/."""
    return Path(__file__).resolve().parent.parent


# Features z-scored and averaged with equal weights for the stress index
INDEX_FEATURES: tuple[str, ...] = (
    "svc_311_density",
    "mob_mta_delay_density",
    "util_outage_density",
    "clim_flood_share",
)


def main():
    """Placeholder main."""
    print("config loaded")


if __name__ == "__main__":
    main()
