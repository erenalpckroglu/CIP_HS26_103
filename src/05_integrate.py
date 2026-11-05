"""Integrate listings with municipality, nearest railway station and income.

Run from the repo root: python src/05_integrate.py
Input:  data/processed/listings_clean.parquet, municipalities.gpkg, stations.parquet, income.parquet
Output: data/processed/analysis.parquet, municipality_summary.parquet, municipality_summary.csv
Every merge is logged with log_step (rows before / rows with a match).
"""
import csv

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from config import (CANTONS, CH_BBOX, CLEANING_LOG, CRS_METRIC, CRS_WGS84, DATA_INTERIM, DATA_PROCESSED,
                    DISTANCE_BANDS_KM, DISTANCE_LABELS, MIN_LISTINGS_PER_MUNICIPALITY, RATE_LIMIT_SECONDS)
from utils import RateLimiter, get_logger, log_step, polite_session

log = get_logger("integrate")

GEOCODE_URL = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
GEOCODE_CACHE = DATA_INTERIM / "geocode_cache.csv"
EARTH_RADIUS_KM = 6371.0088
NEAREST_MAX_M = 500  # listings just outside a municipality polygon (lake shore, imprecise point) -> nearest one


def geocode_missing(df):
    """Geocode only listings without valid coordinates (geo.admin.ch SearchServer, cached, 1 request/s)."""
    df["exact_location"] = df["lat"].notna() & df["lon"].notna() & df["street"].notna()
    missing = df["lat"].isna() | df["lon"].isna()
    cache = {}
    if GEOCODE_CACHE.exists():
        cache = {row["query"]: (row["lat"], row["lon"]) for row in pd.read_csv(GEOCODE_CACHE).to_dict("records")}
    queries = (df["street"].fillna("") + " " + df["zip"].astype(str) + " " + df["city"].fillna("")).str.strip()
    todo = sorted(set(queries[missing]) - set(cache))
    if todo:
        session, limiter = polite_session(), RateLimiter(RATE_LIMIT_SECONDS)
        new = []
        for text in todo:
            limiter.wait()
            results = session.get(GEOCODE_URL, params={"searchText": text, "type": "locations", "limit": 1}).json()["results"]
            attrs = results[0]["attrs"] if results else {}
            new.append({"query": text, "lat": attrs.get("lat", np.nan), "lon": attrs.get("lon", np.nan)})
            cache[text] = (new[-1]["lat"], new[-1]["lon"])
        is_new = not GEOCODE_CACHE.exists()
        with open(GEOCODE_CACHE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["query", "lat", "lon"])
            if is_new:
                writer.writeheader()
            writer.writerows(new)
    lon_min, lon_max, lat_min, lat_max = CH_BBOX
    for i in df.index[missing]:
        lat, lon = cache.get(queries[i], (np.nan, np.nan))
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            df.loc[i, ["lat", "lon"]] = [lat, lon]
    found = int(missing.sum() - (df["lat"].isna() | df["lon"].isna()).sum())
    log_step("integrate_1_geocode", int(missing.sum()), found,
             f"listings without coordinates that got coordinates from geo.admin.ch (rows removed = not found); "
             f"exact_location = own coordinates and street ({int(df['exact_location'].sum())} listings)")
    return df


def join_municipality(df):
    """Spatial join (points in EPSG:2056) with the municipality polygons -> bfs_nr, municipality, canton, density."""
    muni = gpd.read_file(DATA_PROCESSED / "municipalities.gpkg")[["bfs_nr", "name", "canton_nr", "density", "geometry"]]
    has_xy = df["lat"].notna() & df["lon"].notna()
    points = gpd.GeoDataFrame(df[has_xy], geometry=gpd.points_from_xy(df.loc[has_xy, "lon"], df.loc[has_xy, "lat"]),
                              crs=CRS_WGS84).to_crs(CRS_METRIC)
    inside = gpd.sjoin(points, muni, how="left", predicate="within").drop(columns="index_right")
    inside = inside[~inside.index.duplicated()]
    log_step("integrate_2a_municipality_within", len(df), int(inside["bfs_nr"].notna().sum()),
             "listings inside a municipality polygon (the others: no coordinates, lake, border or foreign territory)")
    outside = inside[inside["bfs_nr"].isna()].drop(columns=["bfs_nr", "name", "canton_nr", "density"])
    if len(outside):
        near = gpd.sjoin_nearest(outside, muni, how="left", max_distance=NEAREST_MAX_M).drop(columns="index_right")
        near = near[~near.index.duplicated()]
        inside.loc[near.index, ["bfs_nr", "name", "canton_nr", "density"]] = near[["bfs_nr", "name", "canton_nr", "density"]]
    log_step("integrate_2b_municipality_nearest", int(len(outside)), int(len(outside) - inside["bfs_nr"].isna().sum()),
             f"listings outside all polygons that got the nearest municipality within {NEAREST_MAX_M} m")
    df = df.join(pd.DataFrame(inside[["bfs_nr", "name", "canton_nr", "density"]]).rename(columns={"name": "municipality"}))
    df["bfs_nr"] = df["bfs_nr"].astype("Int64")
    df["canton_nr"] = df["canton_nr"].astype("Int64")
    df["canton"] = df["canton_nr"].map(CANTONS)
    log_step("integrate_2c_municipality_final", len(df), int(df["bfs_nr"].notna().sum()), "listings with a municipality (bfs_nr) after both steps")
    return df


def add_station_distance(df):
    """Nearest railway station by haversine distance (BallTree) -> station_name, station_km, station_band."""
    stations = pd.read_parquet(DATA_PROCESSED / "stations.parquet")
    tree = BallTree(np.radians(stations[["lat", "lon"]].to_numpy()), metric="haversine")
    has_xy = df["lat"].notna() & df["lon"].notna()
    dist, idx = tree.query(np.radians(df.loc[has_xy, ["lat", "lon"]].to_numpy()), k=1)
    df.loc[has_xy, "station_km"] = dist[:, 0] * EARTH_RADIUS_KM
    df.loc[has_xy, "station_name"] = stations["name"].to_numpy()[idx[:, 0]]
    df["station_band"] = pd.cut(df["station_km"], [0, *DISTANCE_BANDS_KM, np.inf], labels=DISTANCE_LABELS, right=False)
    log_step("integrate_3_station_distance", len(df), int(df["station_km"].notna().sum()),
             f"listings with nearest railway station among {len(stations)} stations (straight-line distance)")
    return df


def merge_income(df):
    """Mean taxable income per taxpayer (ESTV 2022) by bfs_nr -> income_mean."""
    income = pd.read_parquet(DATA_PROCESSED / "income.parquet")[["bfs_nr", "income_mean"]]
    df = df.merge(income, on="bfs_nr", how="left")
    log_step("integrate_4_income_merge", len(df), int(df["income_mean"].notna().sum()),
             "listings with income_mean; unmatched = municipalities merged after 2022 (no ESTV 2022 value) or no municipality")
    return df


def flag_outliers_per_canton(df):
    """Final outlier flag: price_m2 outside 1.5 x IQR within its canton (replaces the global flag of the cleaning step)."""
    def outside(prices):
        q1, q3 = prices.quantile([0.25, 0.75])
        return (prices < q1 - 1.5 * (q3 - q1)) | (prices > q3 + 1.5 * (q3 - q1))

    df["is_outlier"] = df.groupby("canton_nr")["price_m2"].transform(outside).fillna(False).astype(bool)
    log_step("integrate_5_outliers_per_canton", len(df), len(df),
             f"{int(df['is_outlier'].sum())} rows flagged is_outlier (price_m2 outside 1.5 x IQR per canton); flag only, rows kept")
    return df


def municipality_summary(df):
    """One row per municipality with listings: counts, medians, density, income."""
    grouped = df.dropna(subset=["bfs_nr"]).groupby("bfs_nr")
    summary = grouped.agg(municipality=("municipality", "first"), canton=("canton", "first"),
                          n_listings=("id", "count"), n_price_m2=("price_m2", "count"),
                          median_price_m2=("price_m2", "median"), median_rent=("rent_gross", "median"),
                          density=("density", "first"), income_mean=("income_mean", "first")).reset_index()
    summary["enough_data"] = summary["n_price_m2"] >= MIN_LISTINGS_PER_MUNICIPALITY
    summary = summary.round({"median_price_m2": 2, "median_rent": 0, "density": 1, "income_mean": 0})
    log_step("integrate_6_municipality_summary", int(df["bfs_nr"].notna().sum()), len(summary),
             f"listings with municipality -> {len(summary)} municipalities with listings; "
             f"{int(summary['enough_data'].sum())} with at least {MIN_LISTINGS_PER_MUNICIPALITY} listings that have price_m2")
    return summary


def main():
    df = pd.read_parquet(DATA_PROCESSED / "listings_clean.parquet")
    df = geocode_missing(df)
    df = join_municipality(df)
    df = add_station_distance(df)
    df = merge_income(df)
    df = flag_outliers_per_canton(df)
    summary = municipality_summary(df)
    df.to_parquet(DATA_PROCESSED / "analysis.parquet", index=False)
    summary.to_parquet(DATA_PROCESSED / "municipality_summary.parquet", index=False)
    summary.to_csv(DATA_PROCESSED / "municipality_summary.csv", index=False)

    log_table = pd.read_csv(CLEANING_LOG)
    log_table = log_table[log_table["step"].str.startswith("integrate_")].drop(columns="timestamp")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 120)
    print("\n=== Integration log")
    print(log_table.to_string(index=False))
    print(f"\nanalysis: {len(df)} listings | municipality summary: {len(summary)} rows")


if __name__ == "__main__":
    main()
