from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
CACHE_DATA_DIR = DATA_DIR / "cache"
SAMPLES_DATA_DIR = DATA_DIR / "samples"

DB_DIR = PROJECT_ROOT / "db"
DUCKDB_PATH = DB_DIR / "quant.duckdb"
SQLITE_PATH = DB_DIR / "quant.sqlite3"


def ensure_data_dirs() -> None:
    for path in [
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        CACHE_DATA_DIR,
        SAMPLES_DATA_DIR,
        DB_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
