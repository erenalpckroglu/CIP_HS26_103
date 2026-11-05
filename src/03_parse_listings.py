"""Parse the collected listing JSON into data/interim/listings_parsed.csv.

Run from the repo root: python src/03_parse_listings.py --test   (first 50 listings -> listings_parsed_test.csv)
                        python src/03_parse_listings.py          (all listings -> listings_parsed.csv)

Input (from 02_collect_listings.py): data/interim/listings_json.jsonl (whitelisted fields only) and listing_urls.csv.
The values of the JSON are cross-checked against the visible detail tables of the saved recon pages
(data/raw/recon/*.html) with BeautifulSoup -> tables/parse_crosscheck.csv. Names, phone numbers, e-mail addresses
and description texts are never read.
"""
import argparse
import csv
import json
import re

import pandas as pd
from bs4 import BeautifulSoup

from config import DATA_INTERIM, DATA_RECON, TABLES_DIR
from utils import get_logger

log = get_logger("parse")

COLUMNS = ["id", "url", "object_type", "rent_gross", "rent_net", "rent_charges", "rooms", "area_m2", "floor",
           "year_built", "street", "zip", "city", "lat", "lon", "is_furnished", "is_temporary", "features", "scraped_at"]


def to_float(value):
    """Float of a number or numeric string, None if not possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_listing(record, url):
    """Map one listing JSON record to the columns of listings_parsed.csv."""
    return {
        "id": str(record["pk"]),
        "url": url,
        "object_type": record.get("object_type"),
        "rent_gross": to_float(record.get("rent_gross")),
        "rent_net": to_float(record.get("rent_net")),
        "rent_charges": to_float(record.get("rent_charges")),
        "rooms": to_float(record.get("number_of_rooms")),
        "area_m2": to_float(record.get("space_display")),
        "floor": to_float(record.get("floor")),
        "year_built": to_float(record.get("year_built")),
        "street": record.get("street") or None,
        "zip": None if record.get("zipcode") is None else str(record["zipcode"]),
        "city": record.get("city"),
        "lat": to_float(record.get("latitude")),
        "lon": to_float(record.get("longitude")),
        "is_furnished": record.get("is_furnished"),
        "is_temporary": record.get("is_temporary"),
        "features": "|".join(record.get("attributes") or []),
        "scraped_at": record.get("scraped_at"),
    }


def parse_all(limit=None):
    """Parse all stored listing records; returns (DataFrame, number of failed records)."""
    urls = pd.read_csv(DATA_INTERIM / "listing_urls.csv", dtype=str).set_index("id")["url"].to_dict()
    rows, failures = [], []
    with open(DATA_INTERIM / "listings_json.jsonl", encoding="utf-8") as f:
        for line in f:
            if limit and len(rows) >= limit:
                break
            try:
                record = json.loads(line)
                rows.append(parse_listing(record, urls[str(record["pk"])]))
            except (KeyError, ValueError, TypeError) as err:
                failures.append((line[:60].strip(), repr(err)))
    if failures:
        with open(DATA_INTERIM / "parse_failures.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["record", "error"])
            writer.writerows(failures)
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("floor", "year_built"):
        df[col] = df[col].astype("Int64")
    for col in ("is_furnished", "is_temporary"):
        df[col] = df[col].astype("boolean")
    return df, len(failures)


def html_fields(path):
    """Read the visible detail tables of a saved listing page with BeautifulSoup."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    table = {}
    for row in soup.select("table.table--rows tr"):
        cells = row.find_all("td")
        if len(cells) == 2:
            table[cells[0].get_text(" ", strip=True).rstrip(":")] = re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True))

    def number(label, pattern):
        match = re.search(pattern, table.get(label, ""))
        return float(re.sub(r"[’',]", "", match.group(1))) if match else None

    rooms = re.search(r"(\d+)(\s*½)?", table.get("Number of rooms", ""))
    floor = table.get("Floor", "")
    facilities = table.get("Facilities", "")
    return {
        "rent_gross": number("Gross rent (incl. utilities)", r"CHF\s*([\d’',.]+)"),
        "rent_net": number("Net rent (excl. utilities)", r"CHF\s*([\d’',.]+)"),
        "rent_charges": number("Utilities", r"CHF\s*([\d’',.]+)"),
        "rooms": int(rooms.group(1)) + (0.5 if rooms.group(2) else 0) if rooms else None,
        "area_m2": number("Livingspace", r"([\d.]+)\s*m²"),
        "floor": 0.0 if "ground" in floor.lower() else number("Floor", r"(-?\d+)"),
        "year_built": number("Year of construction", r"(\d{4})"),
        "has_balcony": "Balcony" in facilities,
        "has_lift": "Lift" in facilities,
        "has_parking": "Parking" in facilities or "Garage" in facilities,
    }


def cross_check(parsed):
    """Compare the parsed JSON values with the recon pages; returns a long table and prints the match rates."""
    rows = []
    by_id = parsed.set_index("id")
    for path in sorted(DATA_RECON.glob("*.html")):
        if path.stem not in by_id.index:
            continue
        record = by_id.loc[path.stem]
        features = set(str(record["features"]).split("|"))
        json_values = {"has_balcony": "balconygarden" in features, "has_lift": "lift" in features,
                       "has_parking": bool({"parkingspace", "garage"} & features)}
        for field, html_value in html_fields(path).items():
            json_value = json_values.get(field, record.get(field))
            json_value = None if pd.isna(json_value) else json_value
            both = html_value is not None and json_value is not None
            rows.append({"id": path.stem, "field": field, "html": html_value, "json": json_value,
                         "status": ("match" if html_value == json_value else "differs") if both
                         else "only html" if html_value is not None else "only json" if json_value is not None else "both missing"})
    table = pd.DataFrame(rows)
    if table.empty:
        log.warning("no recon pages found in %s, cross-check skipped", DATA_RECON)
        return table
    table.to_csv(TABLES_DIR / "parse_crosscheck.csv", index=False)
    both = table[table["status"].isin(["match", "differs"])]
    print(f"\n=== Cross-check JSON vs HTML ({table['id'].nunique()} recon pages, {len(both)} field pairs present in both)")
    print(both.groupby("field")["status"].apply(lambda s: f"{(s == 'match').sum()}/{len(s)} match").to_string())
    print(table["status"].value_counts().to_string())
    print(table[table["status"] == "differs"].to_string(index=False))
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--test", action="store_true", help="parse only the first 50 listings (listings_parsed_test.csv)")
    args = parser.parse_args()
    parsed, failed = parse_all(limit=50 if args.test else None)
    out = DATA_INTERIM / ("listings_parsed_test.csv" if args.test else "listings_parsed.csv")
    parsed.to_csv(out, index=False)
    collected = len(pd.read_csv(DATA_INTERIM / "listing_urls.csv", dtype=str))
    print(f"collected links: {collected}, parsed: {len(parsed)}, failed: {failed} -> {out.name}")
    if args.test:
        print("\n5 parsed rows (URL first, compare with the website):")
        print(parsed.head(5).drop(columns=["scraped_at", "features"]).to_string(index=False, max_colwidth=75))
    else:
        cross_check(parsed)


if __name__ == "__main__":
    main()
