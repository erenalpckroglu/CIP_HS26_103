"""The six cleaning steps for data/interim/listings_parsed.csv.

Run from the repo root: python src/04_clean.py
Output: data/processed/listings_clean.parquet, tables/missing_values.csv, tables/cleaning_log.csv

Steps: 1 missing data, 2 data types, 3 value ranges, 4 outliers, 5 format,
6 enrichment. They run in the order 1, 2, 5, 6, 3, 4: first the target population is selected (5), then price_m2
exists (6) and can be range-checked (3) and flagged (4). Every step calls log_step (rows before / after).
"""
import pandas as pd

from config import CH_BBOX, CLEANING_LOG, DATA_INTERIM, DATA_PROCESSED, FLOOR_RANGE, RANGES, TABLES_DIR
from utils import get_logger, log_step

log = get_logger("clean")

# regular apartment types found in the data; excluded: SINGLE_ROOM, FURNISHED_FLAT, ATTIC (unclear, 3 rows)
KEEP_TYPES = ["APARTMENT", "DUPLEX", "ATTIC_FLAT", "LOFT", "ROOF_FLAT", "TERRACE_FLAT", "STUDIO", "BACHELOR_FLAT"]
DUPLICATE_KEY = ["street", "zip", "rooms", "area_m2", "rent_gross"]
YEAR_BUILT_MAX_MISSING = 0.40


def step1_missing(df):
    """Step 1, missing data: report shares, treat 0 as missing, fill gross rent, drop rows without rent."""
    report = pd.DataFrame({"n_missing": df.isna().sum(), "share_missing": df.isna().mean().round(4)})
    report.to_csv(TABLES_DIR / "missing_values.csv", index_label="column")

    n = len(df)
    zeros = {col: int((df[col] == 0).sum()) for col in ("rent_gross", "rent_net", "area_m2")}
    for col in zeros:
        df.loc[df[col] == 0, col] = float("nan")
    log_step("clean_1a_zero_placeholders", n, n,
             f"0 treated as missing (placeholder, not a value): {zeros}")

    fill = df["rent_gross"].isna() & df["rent_net"].notna() & df["rent_charges"].notna()
    df.loc[fill, "rent_gross"] = df.loc[fill, "rent_net"] + df.loc[fill, "rent_charges"]
    log_step("clean_1b_fill_gross_rent", n, n, f"rent_gross = rent_net + rent_charges for {int(fill.sum())} rows")

    before = len(df)
    df = df[df["rent_gross"].notna()].copy()
    log_step("clean_1c_drop_no_rent", before, len(df), "no gross rent (net rent without charges, or no rent at all)")

    df["has_area"] = df["area_m2"].notna()
    year_missing = df["year_built"].isna().mean()
    log_step("clean_1d_has_area", len(df), len(df),
             f"{int((~df['has_area']).sum())} rows without area kept with has_area=False (no price_m2); "
             f"year_built {year_missing:.0%} missing -> " + ("not used in models" if year_missing > YEAR_BUILT_MAX_MISSING else "usable"))
    return df


def step2_types(df):
    """Step 2, data types: numeric prices/area/rooms, integer floor, string zip, booleans, 0/1 feature columns."""
    n = len(df)
    for col in ("rent_gross", "rent_net", "rent_charges", "rooms", "area_m2", "lat", "lon"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    for col in ("floor", "year_built"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round().astype("Int64")  # ground floor = 0
    df["id"] = df["id"].astype(str)
    df["zip"] = df["zip"].astype("string")
    for col in ("is_furnished", "is_temporary"):
        df[col] = df[col].astype(bool)
    features = df["features"].fillna("").str.split("|")
    for name, keys in {"has_balcony": ["balconygarden"], "has_lift": ["lift"],
                       "has_parking": ["parkingspace", "garage"], "has_minergie": ["minergie"]}.items():
        df[name] = features.apply(lambda f: int(any(k in f for k in keys)))
    df = df.drop(columns="features")
    log_step("clean_2_data_types", n, n,
             "rooms/prices/area/lat/lon float, floor/year_built Int64 (ground floor 0), id and zip string, "
             "is_furnished/is_temporary bool, features -> has_balcony/has_lift/has_parking/has_minergie (0/1)")
    return df


def steclean_format(df):
    """Step 5, format: regular apartments only, no furnished/temporary, no duplicates."""
    before = len(df)
    removed = df.loc[~df["object_type"].isin(KEEP_TYPES), "object_type"].value_counts().to_dict()
    df = df[df["object_type"].isin(KEEP_TYPES)]
    log_step("clean_5a_object_types", before, len(df), f"kept {KEEP_TYPES}; removed {removed}")

    before = len(df)
    furnished, temporary = int(df["is_furnished"].sum()), int(df["is_temporary"].sum())
    df = df[~(df["is_furnished"] | df["is_temporary"])]
    log_step("clean_5b_furnished_temporary", before, len(df), f"removed furnished ({furnished}) and temporary ({temporary}) listings")

    before = len(df)
    df = df.drop_duplicates("id")
    log_step("clean_5c_duplicate_ids", before, len(df), "duplicate listing ids")

    before = len(df)
    complete = df[DUPLICATE_KEY].notna().all(axis=1)  # rows with a missing key part cannot be judged
    df = df[~(complete & df.duplicated(DUPLICATE_KEY))]
    log_step("clean_5d_duplicate_flats", before, len(df), f"same {DUPLICATE_KEY} (first kept; only rows with all five values)")
    return df.copy()


def step6_enrichment(df):
    """Step 6, enrichment: price_m2 = rent_gross / area_m2 (CHF per m2 per month)."""
    df["price_m2"] = df["rent_gross"] / df["area_m2"]
    log_step("clean_6_price_m2", len(df), len(df), f"new column price_m2 = rent_gross / area_m2 for {int(df['price_m2'].notna().sum())} rows with area")
    return df


def step3_ranges(df):
    """Step 3, value ranges: drop rows outside the ranges of config.RANGES; fix floor and coordinates."""
    for col, (low, high) in RANGES.items():
        before = len(df)
        df = df[~(df[col].notna() & ~df[col].between(low, high))]
        log_step(f"clean_3_range_{col}", before, len(df), f"{col} outside {low} to {high}")
    low, high = FLOOR_RANGE
    bad_floor = df["floor"].notna() & ~df["floor"].between(low, high)
    df.loc[bad_floor, "floor"] = pd.NA
    log_step("clean_3_range_floor", len(df), len(df), f"floor outside {low} to {high} set to missing for {int(bad_floor.sum())} rows (rows kept)")
    lon_min, lon_max, lat_min, lat_max = CH_BBOX
    bad_xy = ~(df["lon"].between(lon_min, lon_max) & df["lat"].between(lat_min, lat_max))
    df.loc[bad_xy, ["lat", "lon"]] = float("nan")
    log_step("clean_3_range_coordinates", len(df), len(df), f"coordinates outside CH_BBOX set to missing (geocoded in 05_integrate.py) for {int(bad_xy.sum())} rows")
    return df.copy()


def step4_outliers(df):
    """Step 4, outliers: flag price_m2 outside 1.5 x IQR (global); rows are kept."""
    q1, q3 = df["price_m2"].quantile([0.25, 0.75])
    low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    df["is_outlier"] = (df["price_m2"] < low) | (df["price_m2"] > high)
    log_step("clean_4_outliers", len(df), len(df),
             f"{int(df['is_outlier'].sum())} rows flagged is_outlier: price_m2 outside {low:.1f} to {high:.1f} CHF/m2 (1.5 x IQR, global); flag only, rows kept")
    return df


def main():
    df = pd.read_csv(DATA_INTERIM / "listings_parsed.csv", dtype={"zip": str})
    log_step("clean_0_input", len(df), len(df), "rows read from data/interim/listings_parsed.csv")
    df = step1_missing(df)
    df = step2_types(df)
    df = steclean_format(df)
    df = step6_enrichment(df)
    df = step3_ranges(df)
    df = step4_outliers(df)
    columns = ["id", "url", "object_type", "rent_gross", "rent_net", "rent_charges", "rooms", "area_m2", "has_area",
               "price_m2", "floor", "year_built", "street", "zip", "city", "lat", "lon", "is_furnished", "is_temporary",
               "has_balcony", "has_lift", "has_parking", "has_minergie", "is_outlier", "scraped_at"]
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    df[columns].reset_index(drop=True).to_parquet(DATA_PROCESSED / "listings_clean.parquet", index=False)

    steps = pd.read_csv(CLEANING_LOG)
    steps = steps[steps["step"].str.startswith("clean_")].drop(columns="timestamp")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 110)
    print("\n=== Cleaning log")
    print(steps.to_string(index=False))
    print(f"\nclean listings: {len(df)} | with price_m2: {int(df['price_m2'].notna().sum())} | outliers flagged: {int(df['is_outlier'].sum())}")


if __name__ == "__main__":
    main()
