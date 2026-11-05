"""Collect Flatfox rental apartment listings with Selenium (reads the JSON that the search page loads).

Run from the repo root: python src/02_collect_listings.py --test   (Lucerne box)
                        python src/02_collect_listings.py          (whole of Switzerland)

1. UI demonstration (search field, filter dropdown, "Show more"), logged to docs/selenium_interaction.log.
2. Tiling: load the search URL for a map box; if the box holds 400 or more listings (cap notice), split it into 4.
3. In every final tile click "Show more" until the cards stop growing, and collect id and URL from the cards.
While doing so the JSON that the browser itself loads (pin and public-listing) is read from the Chrome network log
and only whitelisted fields are stored (no agency, description, names or phone numbers).
Results are saved after every tile, so an interrupted run resumes where it stopped.
"""
import argparse
import csv
import json
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from config import CH_BBOX, DATA_INTERIM, DOCS_DIR, RATE_LIMIT_SECONDS, TEST_BBOX, USER_AGENT
from utils import RateLimiter, get_logger

log = get_logger("collect")

SEARCH_URL = "https://flatfox.ch/en/search/"
FILTERS = {"offer_type": "RENT", "object_category": "APARTMENT"}
PAGE_SIZE = 48  # cards per "Show more" click
CAP = 400  # the map shows at most 400 listings per box
MAX_CLICKS = 30
MAX_DEPTH = 12
SHOW_MORE = "//button[.//span[normalize-space()='Show more']]"
INTERACTION_LOG = DOCS_DIR / "selenium_interaction.log"
KEEP_FIELDS = ["pk", "slug", "object_type", "object_category", "offer_type", "rent_gross", "rent_net", "rent_charges",
               "space_display", "number_of_rooms", "floor", "year_built", "is_furnished", "is_temporary", "street",
               "zipcode", "city", "state", "latitude", "longitude"]


def make_driver():
    """Headless Chrome with a generic User-Agent, images off, network log on."""
    options = Options()
    for arg in ("--headless=new", "--window-size=1400,1000", f"--user-agent={USER_AGENT}",
                "--blink-settings=imagesEnabled=false"):
        options.add_argument(arg)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)


def wait_for(condition, timeout=20, step=0.5):
    """Poll `condition` until it is true or the timeout (seconds) has passed."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(step)
    return False


def url_box(url):
    """(west, south, east, north) from the query string of a search or pin URL."""
    query = parse_qs(urlparse(url).query)
    return tuple(float(query[k][0]) for k in ("west", "south", "east", "north"))


def harvest(driver, state):
    """Read new network-log entries; keep pin and listing JSON. Stops the run on HTTP 403/429."""
    for entry in driver.get_log("performance"):
        message = json.loads(entry["message"])["message"]
        if message["method"] != "Network.responseReceived":
            continue
        response = message["params"]["response"]
        url = response["url"]
        if "flatfox.ch" in url and response["status"] in (403, 429):
            raise RuntimeError(f"HTTP {response['status']} from {url}: stopping the run (politeness rule)")
        kind = "pin" if "/api/v1/pin/" in url else "listing" if "/api/v1/public-listing/" in url else None
        if kind is None:
            continue
        try:
            body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": message["params"]["requestId"]})["body"]
            data = json.loads(body)
        except Exception:  # body no longer available
            state["lost"] += 1
            continue
        rows = data.get("results", []) if isinstance(data, dict) else data
        if kind == "pin":
            state["pins"].append((url_box(url), rows))
        else:
            state["items"].update({row["pk"]: row for row in rows})


def card_links(driver):
    """{listing id: URL} of all result cards currently shown."""
    hrefs = driver.execute_script("return [...document.querySelectorAll('a.listing-thumb-title')].map(a => a.href)")
    return {href.rstrip("/").rsplit("/", 1)[-1]: href for href in hrefs}


def cap_notice(driver):
    """True if the '400 listings' notice is visible."""
    return any(e.is_displayed() for e in driver.find_elements(By.CSS_SELECTOR, ".flat-search-max-items-warn"))


def click(driver, element):
    """Scroll to an element and click it (JS click if something covers it)."""
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", element)
    time.sleep(0.5)
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click()", element)


def reject_cookies(driver, note):
    """Choose 'No consent' in the cookie banner (Show Purposes, then No consent)."""
    if wait_for(lambda: driver.find_elements(By.ID, "onetrust-pc-btn-handler"), timeout=10):
        driver.find_element(By.ID, "onetrust-pc-btn-handler").click()
        time.sleep(1.5)
        driver.find_element(By.CSS_SELECTOR, ".ot-pc-refuse-all-handler").click()
        time.sleep(1.5)
        note("cookie banner: clicked #onetrust-pc-btn-handler, then .ot-pc-refuse-all-handler (No consent)")
    else:
        note("cookie banner: not shown")


def ui_demo(driver, limiter):
    """Use the dynamic elements like a visitor: search field, filter dropdown, Show more. Writes the interaction log."""
    lines = []

    def note(text):
        lines.append(f"{datetime.now().isoformat(timespec='seconds')} | {text}")
        log.info(text)

    limiter.wait()
    driver.get(SEARCH_URL)
    time.sleep(3)
    note(f"opened {SEARCH_URL}")
    reject_cookies(driver, note)

    box = driver.find_element(By.CSS_SELECTOR, "input.mapboxgl-ctrl-geocoder--input")
    box.click()
    box.send_keys("Lucerne")
    wait_for(lambda: driver.find_elements(By.CSS_SELECTOR, "ul.suggestions li"), timeout=10)
    note("search field input.mapboxgl-ctrl-geocoder--input: typed 'Lucerne'")
    suggestion = next(li for li in driver.find_elements(By.CSS_SELECTOR, "ul.suggestions li")
                      if li.text.split("\n")[0].strip() == "Lucerne")
    limiter.wait()
    suggestion.click()
    time.sleep(3)
    note(f"search field: clicked suggestion 'Lucerne', URL now {driver.current_url}")

    limiter.wait()
    driver.find_element(By.XPATH, "//button[normalize-space()='Listing type']").click()
    time.sleep(1.5)
    note("filter: opened dropdown button 'Listing type'")
    for value in ("RENT", "APARTMENT"):
        limiter.wait()
        driver.find_element(By.CSS_SELECTOR, f'button.dropdown-choice[value="{value}"]').click()
        time.sleep(2.5)
        note(f"filter: clicked button.dropdown-choice[value={value}], URL now {driver.current_url}")
    webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    time.sleep(2)

    before = len(card_links(driver))
    limiter.wait()
    click(driver, driver.find_element(By.XPATH, SHOW_MORE))
    wait_for(lambda: len(card_links(driver)) > before, timeout=10)
    note(f"list scroll: clicked 'Show more' once, cards {before} -> {len(card_links(driver))}")
    INTERACTION_LOG.write_text("UI demonstration of the Selenium run (cookie banner, search field, filter, Show more)\n"
                               + "\n".join(lines) + "\n", encoding="utf-8")
    driver.get_log("performance")  # discard the network log of the demonstration


def scrape_tile(driver, limiter, tile):
    """Load one map box. Returns n_pins, capped, cards, items and the box the page really showed."""
    west, south, east, north = tile
    url = SEARCH_URL + "?" + urlencode({**FILTERS, "east": f"{east:.6f}", "west": f"{west:.6f}",
                                        "north": f"{north:.6f}", "south": f"{south:.6f}", "take": PAGE_SIZE})
    state = {"pins": [], "items": {}, "lost": 0}
    driver.get_log("performance")
    limiter.wait()
    driver.get(url)
    wait_for(lambda: harvest(driver, state) or state["pins"], timeout=25)
    time.sleep(2)  # the app widens the box to the window shape and reloads the pins
    harvest(driver, state)
    shown = url_box(driver.current_url)
    pins = next((rows for box, rows in reversed(state["pins"]) if all(abs(a - b) < 1e-5 for a, b in zip(box, shown))),
                state["pins"][-1][1] if state["pins"] else [])
    capped = len(pins) >= CAP or cap_notice(driver)
    expected = min(PAGE_SIZE, len(pins))
    wait_for(lambda: harvest(driver, state) or len(card_links(driver)) >= expected, timeout=15)
    return {"state": state, "pins": pins, "capped": capped, "shown": shown}


def load_all(driver, limiter, state, expected):
    """Click 'Show more' until the cards stop growing or all `expected` (pins) are shown (max MAX_CLICKS)."""
    failures = 0
    for _ in range(MAX_CLICKS):
        before = len(card_links(driver))
        if before >= expected:
            break
        buttons = driver.find_elements(By.XPATH, SHOW_MORE)
        if not buttons:  # the button is briefly missing while a batch renders
            if wait_for(lambda: driver.find_elements(By.XPATH, SHOW_MORE), timeout=5):
                continue
            break
        limiter.wait()
        click(driver, buttons[0])
        if wait_for(lambda: harvest(driver, state) or len(card_links(driver)) > before, timeout=10):
            failures = 0
        else:
            failures += 1
            if failures >= 3:
                break
    time.sleep(1)
    harvest(driver, state)
    return card_links(driver)


def append_csv(path, header, rows):
    """Append rows to a CSV file, writing the header first if the file is new."""
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(header)
        writer.writerows(rows)


def save_tile(paths, key, depth, status, pins, cards, items, scraped_at):
    """Append one finished tile to the three interim files (data first, tile log last)."""
    key_text = ",".join(f"{v:.5f}" for v in key)
    append_csv(paths["urls"], ["id", "url", "tile"], [(i, u, key_text) for i, u in cards.items()])
    with open(paths["json"], "a", encoding="utf-8") as f:
        for item in items.values():
            row = {k: item.get(k) for k in KEEP_FIELDS}
            row["attributes"] = [a["name"] for a in item.get("attributes", [])]
            row["scraped_at"] = scraped_at
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    pin_ids = {str(p["pk"]) for p in pins}
    append_csv(paths["tiles"], ["tile", "depth", "status", "n_pins", "n_cards", "n_json", "pins_without_card",
                                "pins_without_json", "scraped_at"],
               [(key_text, depth, status, len(pins), len(cards), len(items), len(pin_ids - set(cards)),
                 len(pin_ids - {str(k) for k in items}), scraped_at)])


def process(driver, limiter, paths, done, tile, depth):
    """Scrape a tile; split it into 4 and recurse while it hits the 400-listings cap."""
    key_text = ",".join(f"{v:.5f}" for v in tile)
    if done.get(key_text) in ("final", "capped"):
        return
    if done.get(key_text) != "split":
        result = scrape_tile(driver, limiter, tile)
        pins, state = result["pins"], result["state"]
        scraped_at = datetime.now().isoformat(timespec="seconds")
        if result["capped"] and depth < MAX_DEPTH:
            log.info("depth %d tile %s: %d pins, cap reached -> split", depth, key_text, len(pins))
            save_tile(paths, tile, depth, "split", pins, {}, {}, scraped_at)
            done[key_text] = "split"
        else:
            cards = load_all(driver, limiter, state, len(pins))
            status = "capped" if result["capped"] else "final"
            log.info("depth %d tile %s: %d pins, %d cards, %d json -> %s", depth, key_text, len(pins), len(cards),
                     len(state["items"]), status)
            save_tile(paths, tile, depth, status, pins, cards, state["items"], scraped_at)
            done[key_text] = "final"
            return
    west, south, east, north = tile
    mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
    for sub in ((west, south, mid_lon, mid_lat), (mid_lon, south, east, mid_lat),
                (west, mid_lat, mid_lon, north), (mid_lon, mid_lat, east, north)):
        process(driver, limiter, paths, done, sub, depth + 1)


def finalize(paths):
    """Deduplicate by id and print the summary of the run."""
    urls = pd.read_csv(paths["urls"], dtype=str)
    unique = urls.drop_duplicates("id")
    unique.to_csv(paths["urls"], index=False)
    with open(paths["json"], encoding="utf-8") as f:
        lines = [line for line in f if line.strip()]
    first_per_pk = {json.loads(line)["pk"]: line for line in reversed(lines)}  # keeps the first line of each pk
    unique_lines = [line for line in lines if first_per_pk[json.loads(line)["pk"]] is line]
    with open(paths["json"], "w", encoding="utf-8") as f:
        f.writelines(unique_lines)
    tiles = pd.read_csv(paths["tiles"]).drop_duplicates("tile", keep="last")
    final = tiles[tiles["status"].isin(["final", "capped"])]
    print("\n=== Summary")
    print(f"tiles loaded: {len(tiles)} (split: {(tiles['status'] == 'split').sum()}, final: {len(final)})")
    print(f"tiles that still hit the cap: {(tiles['status'] == 'capped').sum()}")
    print(f"listing links: {len(urls)} rows, unique ids: {len(unique)}")
    json_ids = {str(json.loads(line)["pk"]) for line in unique_lines}
    print(f"listing JSON records: {len(lines)} rows, unique: {len(unique_lines)}; ids without JSON: "
          f"{len(set(unique['id']) - json_ids)}")
    print(f"pins without card in final tiles: {int(final['pins_without_card'].sum())}, "
          f"pins without JSON: {int(final['pins_without_json'].sum())}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--test", action="store_true", help="only the Lucerne test box (separate *_test files)")
    args = parser.parse_args()
    lon_min, lon_max, lat_min, lat_max = TEST_BBOX if args.test else CH_BBOX
    suffix = "_test" if args.test else ""
    DATA_INTERIM.mkdir(parents=True, exist_ok=True)
    paths = {"urls": DATA_INTERIM / f"listing_urls{suffix}.csv", "tiles": DATA_INTERIM / f"tiles_done{suffix}.csv",
             "json": DATA_INTERIM / f"listings_json{suffix}.jsonl"}
    done = {}
    if paths["tiles"].exists():
        done = dict(pd.read_csv(paths["tiles"], dtype=str)[["tile", "status"]].itertuples(index=False))
        log.info("resuming: %d tiles already done", len(done))
    limiter = RateLimiter(RATE_LIMIT_SECONDS)
    driver = make_driver()
    try:
        ui_demo(driver, limiter)
        process(driver, limiter, paths, done, (lon_min, lat_min, lon_max, lat_max), 0)
    finally:
        driver.quit()
    finalize(paths)


if __name__ == "__main__":
    main()
