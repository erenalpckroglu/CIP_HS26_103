"""Download and prepare the open reference data (stations, municipalities, income).

Run from the repo root: python src/01_external_data.py
Downloads are cached in data/raw/external/; outputs go to data/processed/.
"""
import re
import zipfile
from urllib.parse import urljoin

import geopandas as gpd
import pandas as pd

from config import CRS_METRIC, DATA_EXTERNAL, DATA_PROCESSED
from utils import get_logger, log_step, polite_session

log = get_logger("external")

STATIONS_PAGE = "https://data.opentransportdata.swiss/dataset/service-point-v2"
STATIONS_FILE = "actual-date-swiss-service-point.csv"
BOUNDARIES_PAGE = "https://www.swisstopo.admin.ch/en/landscape-model-swissboundaries3d"
BOUNDARIES_STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissboundaries3d/items?limit=100"
INCOME_PAGE = "https://www.estv.admin.ch/de/statistiken-natuerliche-personen-gemeinden-1983-bis-heute"
INCOME_FILE = "statistik-dbst-np-gden-2022-normalfall.xlsx"
INCOME_RANGE = (40_000, 150_000)  # plausible mean taxable income per taxpayer, CHF


def link_on_page(session, page_url, filename):
    """Find the download link for `filename` on a dataset page."""
    html = session.get(page_url).text
    hrefs = re.findall(r'href="([^"]*' + re.escape(filename) + r')"', html)
    if not hrefs:
        raise ValueError(f"no link to {filename} found on {page_url}")
    return urljoin(page_url, hrefs[0])


def latest_boundaries_url(session):
    """Return the GeoPackage zip URL of the newest swissBOUNDARIES3D release (STAC API)."""
    items = session.get(BOUNDARIES_STAC).json()["features"]
    latest = max(items, key=lambda item: item["id"])
    return next(a["href"] for name, a in latest["assets"].items() if name.endswith(".gpkg.zip"))


def download(session, url, target):
    """Stream `url` to `target` unless the file already exists."""
    if target.exists():
        log.info("cached: %s", target.name)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    log.info("downloading %s", url)
    with session.get(url, stream=True) as response:
        response.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in response.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(target)


def fetch_sources(session):
    """Download the three files; on failure print the page URL and file name for a manual download."""
    paths = {}
    zips = sorted(DATA_EXTERNAL.glob("swissboundaries3d_*.gpkg.zip"))
    jobs = {
        "stations": (STATIONS_PAGE, DATA_EXTERNAL / STATIONS_FILE, lambda: link_on_page(session, STATIONS_PAGE, STATIONS_FILE)),
        "boundaries": (BOUNDARIES_PAGE, zips[-1] if zips else None, lambda: latest_boundaries_url(session)),
        "income": (INCOME_PAGE, DATA_EXTERNAL / INCOME_FILE, lambda: link_on_page(session, INCOME_PAGE, INCOME_FILE)),
    }
    for name, (page, target, resolve) in jobs.items():
        try:
            if target is None:
                url = resolve()
                target = DATA_EXTERNAL / url.rsplit("/", 1)[-1]
                download(session, url, target)
            elif not target.exists():
                download(session, resolve(), target)
            else:
                log.info("cached: %s", target.name)
            paths[name] = target
        except Exception as err:  # keep going with the other sources
            log.error("%s failed (%s). Download by hand from %s and save into %s", name, err, page, DATA_EXTERNAL)
            if target is not None:
                log.error("expected file name: %s", target.name)
    return paths


def inspect(title, df):
    """Print shape, columns with dtypes and the first 5 rows."""
    print(f"\n=== {title}: {df.shape[0]} rows x {df.shape[1]} columns")
    print(df.dtypes.to_string())
    head = df.drop(columns="geometry", errors="ignore").head()
    print(head.T.to_string(max_colwidth=30) if head.shape[1] > 12 else head.to_string(max_colwidth=30))


def build_stations(csv_path):
    """Railway stations with WGS84 coordinates -> data/processed/stations.parquet."""
    raw = pd.read_csv(csv_path, sep=";", low_memory=False)
    inspect("service points (raw)", raw)
    train = raw[raw["meansOfTransport"].fillna("").str.contains("TRAIN")]
    stations = train.rename(columns={"designationOfficial": "name", "wgs84North": "lat", "wgs84East": "lon"})
    stations = stations[["name", "lat", "lon"]].dropna().drop_duplicates().reset_index(drop=True)
    log_step("ext_stations", len(raw), len(stations),
             "kept service points with means of transport TRAIN and coordinates, deduplicated by name and coordinates")
    stations.to_parquet(DATA_PROCESSED / "stations.parquet", index=False)
    return stations


def build_municipalities(zip_path):
    """Swiss municipality polygons with population and density -> data/processed/municipalities.gpkg."""
    folder = zip_path.with_name(zip_path.name.removesuffix(".gpkg.zip"))
    if not list(folder.glob("*.gpkg")):
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(folder)
    gpkg = next(folder.glob("*.gpkg"))
    raw = gpd.read_file(gpkg, layer="tlm_hoheitsgebiet")
    inspect(f"swissBOUNDARIES3D tlm_hoheitsgebiet ({gpkg.name})", raw)
    # Gemeindegebiet = municipality; exclude lakes (Kantonsgebiet), Kommunanz and foreign enclaves (LI, DE, IT)
    muni = raw[(raw["objektart"] == "Gemeindegebiet") & (raw["icc"] == "CH")]
    muni = muni.rename(columns={"bfs_nummer": "bfs_nr", "kantonsnummer": "canton_nr",
                                "einwohnerzahl": "population", "gem_flaeche": "area_ha"})
    muni = muni[["bfs_nr", "name", "canton_nr", "population", "area_ha", "geometry"]].copy()
    muni["canton_nr"] = muni["canton_nr"].astype(int)
    muni["area_km2"] = muni["area_ha"] / 100
    muni["density"] = muni["population"] / muni["area_km2"]
    muni = muni.to_crs(CRS_METRIC)
    muni["geometry"] = muni.geometry.force_2d()
    log_step("ext_municipalities", len(raw), len(muni),
             "kept Gemeindegebiet in CH; dropped lakes, Kommunanz and enclaves of LI/DE/IT")
    out = DATA_PROCESSED / "municipalities.gpkg"
    out.unlink(missing_ok=True)
    muni.reset_index(drop=True).to_file(out, driver="GPKG", layer="municipalities")
    return muni.reset_index(drop=True)


def build_income(xlsx_path):
    """Mean taxable income per taxpayer and municipality (ESTV 2022) -> data/processed/income.parquet."""
    def read_total(sheet, column):
        df = pd.read_excel(xlsx_path, sheet_name=sheet, header=2)  # two title rows above the header
        inspect(f"ESTV sheet {sheet} ({column})", df)
        df = df.rename(columns={"Gemeinde ID": "bfs_nr", "Gemeinde / Commune": "name", "Total / Totale": column})
        df[column] = pd.to_numeric(df[column], errors="coerce")  # suppressed cells are "-"
        return df[["bfs_nr", "name", column]]

    taxpayers = read_total("521", "n_taxpayers")  # number of taxpayers, by class of taxable income
    income = read_total("523", "income_total")  # taxable income in CHF, same classes
    national = income.iloc[-1, 2] / taxpayers.iloc[-1, 2]  # last row = Switzerland total
    print(f"\nUnit check: Swiss total {income.iloc[-1, 2]:,.0f} CHF / {taxpayers.iloc[-1, 2]:,.0f} taxpayers "
          f"= {national:,.0f} CHF per taxpayer (so the sheet is in CHF, not 1,000 CHF)")
    # Rows with Gemeinde ID 10000 are canton/country totals
    both = taxpayers.merge(income[["bfs_nr", "income_total"]], on="bfs_nr")
    both = both[both["bfs_nr"].between(1, 9999)].copy()
    both["bfs_nr"] = both["bfs_nr"].astype(int)
    both["income_mean"] = both["income_total"] / both["n_taxpayers"]
    log_step("ext_income", len(taxpayers), len(both), "dropped canton and country total rows of the ESTV sheets")
    outside = both[~both["income_mean"].between(*INCOME_RANGE)]
    print(f"income_mean outside {INCOME_RANGE[0]:,}-{INCOME_RANGE[1]:,} CHF: {len(outside)} municipalities")
    if len(outside):
        print(outside.sort_values("income_mean").to_string(index=False))
    both.to_parquet(DATA_PROCESSED / "income.parquet", index=False)
    return both


def match_check(income, muni):
    """Share of ESTV 2022 municipalities that exist in the 2026 boundaries (and vice versa)."""
    found = income["bfs_nr"].isin(muni["bfs_nr"])
    log_step("ext_income_in_boundaries", len(income), int(found.sum()),
             "ESTV 2022 BFS numbers not found in 2026 boundaries (municipality mergers 2022-2026)")
    covered = muni["bfs_nr"].isin(income["bfs_nr"])
    log_step("ext_boundaries_with_income", len(muni), int(covered.sum()),
             "2026 municipalities without ESTV 2022 income (merged since 2022 or values suppressed)")
    print(f"\nMatch rate: {found.mean():.1%} of {len(income)} ESTV municipalities are in the 2026 boundaries "
          f"({(~found).sum()} unmatched); {covered.mean():.1%} of {len(muni)} boundary municipalities have income")
    print("Unmatched ESTV examples:", income.loc[~found, ["bfs_nr", "name"]].head(8).to_dict("records"))


def main():
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    paths = fetch_sources(polite_session())
    stations = build_stations(paths["stations"]) if "stations" in paths else None
    muni = build_municipalities(paths["boundaries"]) if "boundaries" in paths else None
    income = build_income(paths["income"]) if "income" in paths else None
    if muni is not None and income is not None:
        match_check(income, muni)
    print("\n=== Summary")
    if stations is not None:
        print(f"stations: {len(stations)} rows, missing coordinates: {stations[['lat', 'lon']].isna().any(axis=1).sum()}")
    if muni is not None:
        print(f"municipalities: {len(muni)} rows, missing density: {muni['density'].isna().sum()}, CRS {muni.crs.to_string()}")
    if income is not None:
        print(f"income: {len(income)} rows, income_mean {income['income_mean'].min():,.0f} to "
              f"{income['income_mean'].max():,.0f} CHF (median {income['income_mean'].median():,.0f})")


if __name__ == "__main__":
    main()
