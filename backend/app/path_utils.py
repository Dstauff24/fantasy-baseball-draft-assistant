from pathlib import Path
import os

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTIONS_CSV = BACKEND_ROOT / "Data" / "Baseball Ranks_2026 Pre-Season.csv"

def get_projections_csv_path() -> Path:
    env_path = os.getenv("FBA_PROJECTIONS_CSV") or os.getenv("PROJECTIONS_CSV_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_PROJECTIONS_CSV