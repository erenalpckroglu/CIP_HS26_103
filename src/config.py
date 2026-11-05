"""Paths and constants for the CIP HS26 Group 103 rent project."""
from pathlib import Path

# Paths (all scripts run from the repo root, but paths do not depend on it)
ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DATA_RAW = ROOT / "data" / "raw"
DATA_EXTERNAL = DATA_RAW / "external"
DATA_HTML = DATA_RAW / "html"
DATA_RECON = DATA_RAW / "recon"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_PROCESSED = ROOT / "data" / "processed"
FIGURES_DIR = ROOT / "figures"
TABLES_DIR = ROOT / "tables"
CLEANING_LOG = TABLES_DIR / "cleaning_log.csv"

# Scraping
RATE_LIMIT_SECONDS = 1.0
USER_AGENT = "CIP-HS26-student-project"
REQUEST_TIMEOUT = 30  # seconds

# Bounding boxes as (lon_min, lon_max, lat_min, lat_max)
CH_BBOX = (5.95, 10.50, 45.80, 47.81)
TEST_BBOX = (8.25, 8.36, 47.02, 47.08)  # city of Lucerne

# Analysis
DISTANCE_BANDS_KM = [0.5, 1, 2]
DISTANCE_LABELS = ["<0.5 km", "0.5-1 km", "1-2 km", ">2 km"]
MIN_LISTINGS_PER_MUNICIPALITY = 5

# Valid value ranges (min, max)
RANGES = {
    "rent_gross": (300, 15000),  # CHF per month
    "area_m2": (15, 400),
    "rooms": (1, 10),
    "price_m2": (5, 100),  # CHF per m2 per month
}
FLOOR_RANGE = (-5, 50)  # outside: set to missing, row kept (99 is used as a placeholder)

# Canton number (BFS) -> abbreviation
CANTONS = {1: "ZH", 2: "BE", 3: "LU", 4: "UR", 5: "SZ", 6: "OW", 7: "NW", 8: "GL", 9: "ZG", 10: "FR", 11: "SO",
           12: "BS", 13: "BL", 14: "SH", 15: "AR", 16: "AI", 17: "SG", 18: "GR", 19: "AG", 20: "TG", 21: "TI",
           22: "VD", 23: "VS", 24: "NE", 25: "GE", 26: "JU"}

# Coordinate reference systems
CRS_METRIC = "EPSG:2056"
CRS_WGS84 = "EPSG:4326"

# Modelling
RANDOM_STATE = 42
TEST_SIZE = 0.2
