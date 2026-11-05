# Flatfox: site structure and data collection notes

Observed on 2026-11-03 with headless Chrome through Selenium (generic User-Agent `CIP-HS26-student-project`, cookies rejected, at least 1.5 s between page loads). Raw test pages were stored in `data/raw/recon/` (git-ignored, 10 files). No secrets (API keys, tokens) and no personal data are recorded here.

## 1. robots.txt
Copy: `docs/robots_flatfox.txt` (HTTP 200, 2026-11-03). `User-agent: *`, `Allow: /`. Disallowed: `/admin/`, `/*/publi/goal/`, `/*/partner/`, `/*/temp/`, `/*/lang/`, `/*/change-language/`, `/*/sprache-aendern/`, `/*/cockpit/`. `/en/search/`, `/en/flat/...` and `/api/` are not disallowed.

## 2. Cookie banner (OneTrust)
- Appears on the first visit. Buttons: `#onetrust-accept-btn-handler` ("I Accept"), `#onetrust-pc-btn-handler` ("Show Purposes").
- Reject optional cookies: click `#onetrust-pc-btn-handler`, then `.ot-pc-refuse-all-handler` ("No consent"). Afterwards `#onetrust-banner-sdk` and `#onetrust-pc-sdk` are no longer displayed.

## 3. Search page `https://flatfox.ch/en/search/`
- Default URL after load: `?east=10.492340&north=48.894602&south=44.667133&take=48&west=5.956080` (map box of Switzerland; `take` = number of cards loaded).
- **Location search field:** `input.mapboxgl-ctrl-geocoder--input` (aria-label "Region, place or street"), a Mapbox geocoder. Suggestions: `ul.suggestions li` (`div.mapboxgl-ctrl-geocoder--suggestion`). "Luzern" returns only streets ("Luzernerstrasse"); "Lucerne" or "Kriens" returns the place as first suggestion (title equals the query). Clicking it sets `place_name`, `place_type=place`, `query` and a new map box.
- **Filter control:** button with text `Listing type` (class `css-10i1n87` is hashed and unstable, so find it by text). It opens a multi-select dropdown that stays open after a click; clicking an active option again switches it off. Options: `button.dropdown-choice[value="RENT"]` ("For rent"), `[value="SALE"]`, `[value="APARTMENT"]`, `HOUSE`, and others. Close the dropdown with Escape (a click on the page body hits a listing card and navigates away).
- Filters applied through the UI (RENT, then APARTMENT) give: `?east=..&north=..&object_category=APARTMENT&offer_type=RENT&south=..&take=48&west=..`. Other controls (Rooms, Price, Favorites, Sort by, More, Subscriptions) are not needed.
- **Result cards:** `div.search-result > div.listing-thumb` inside `.flat-search__content__results`. Each card has two links to the same listing: `a.listing-thumb__image` (image, price in `.attributes .price`, badges such as "Priority", "Temporary", "Furnished") and `a.listing-thumb-title` (`h2` = object title like "3 1/2 rooms apartment" plus `span.listing-thumb-title__location` = "6006 Luzern"). The street appears only in the `title` attribute of `header.listing-thumb-header`. Listing id = last path segment of the href. Use `a[href*="/flat/"]` and deduplicate ids (96 links for 48 cards).
- **Show more:** `//button[.//span[normalize-space()='Show more']]` (class `css-i6h46n` is hashed). Each click adds 48 cards and writes `take` into the URL (48 -> 96 -> ...). The button disappears when all listings of the box are loaded.
- **400 notice:** `div.flat-search-max-items-warn`, text "Only showing 400 listings. Zoom in or filter to narrow your search". Visible for the whole-Switzerland box with the filters, not for the Lucerne box.
- **Visible result count:** none on the page (only "We'll let you know as soon as there are new search results.").
- **Test, Lucerne box lon 8.25-8.36, lat 47.02-47.08, RENT + APARTMENT:** 48, 96, 144, 192, 240, 284 cards after 5 clicks of "Show more", then no button.
- The app widens the map box to the aspect ratio of the window (north 47.08 -> 47.101, south 47.02 -> 46.999 in the URL), so tiles overlap slightly and ids must be deduplicated.
- The category `APARTMENT` still contains furnished and temporary flats, studios, duplexes and single rooms (see section 8), so the cleaning step has to filter them.

## 4. Listing URLs
Pattern: `https://flatfox.ch/en/flat/<slug>/<id>/`. Slug is `<street-number-zip-city>`, `<zip-city>` without street, or `auf-anfrage-<zip-city>` ("on request").

## 5. Fetching listing pages: plain requests is blocked (HTTP 403)
- `requests` with the generic User-Agent got 200 for robots.txt but **HTTP 403 for a listing page**. The collection stops on 403 or 429 by design; there was no retry and no change of headers.
- Selenium (normal headless Chrome, cookies rejected) loads all listing pages. The 10 test pages were fetched this way (3 s wait + 1.5 s limiter, about 4.5 s per page). **Estimate for all listings: 15,000 pages x 4.5 s = about 19 hours.**
- `driver.page_source` is the rendered DOM (about 0.7 MB per page, mostly inline CSS/JS); the fields below are in the server-rendered part.

## 6. Listing page field map (HTML, 10 pages: 8 apartments/studio/duplex, 2 furnished flats, 5 with street)
Detail tables: `table.table--rows` rows `<tr><td>label:</td><td>value</td></tr>`, under the headings `h2 "Rent"` and `h2 "Details"`. Counts are out of 10 pages.

| Field | Where | Example / notes |
|---|---|---|
| gross rent | row `Gross rent (incl. utilities):` | `CHF 1’030 per month` (thousands separator is U+2019), present 9/10 |
| net rent | row `Net rent (excl. utilities):` | `CHF 980 per month`, present 5/10 (one page has only net, one only gross) |
| charges | row `Utilities:` | `CHF 50 per month`, present 4/10 |
| rooms | row `Number of rooms:` | `2 ½` (the character ½ must be parsed), 10/10; ad JSON `number_of_rooms` is clean (`"2.5"`) |
| living area | row `Livingspace:` | `76 m²`, present 7/10 |
| floor | row `Floor:` | `3rd floor`, `21st floor`, present 8/10; ground floor / basement wording not seen in the sample |
| object type | `h1` "Rent a <rooms> <type> in <city>" | seen: apartment, studio, duplex, furnished flat. The ad JSON `object_category` is always `APARTMENT` |
| features | row `Facilities:` (comma-separated labels) and ad JSON `attributes` (machine keys) | `Parking space, Lift, Balcony/Garden, Dishwasher, Garage, Fire place, View`; keys `parkingspace`, `lift`, `balconygarden`, `garage`, ... present 7/10 |
| street, zip, city | `h2` right under the `h1`: `<street no>, <zip> <city> - CHF ... per month`; zip, city also in ad JSON | `Auf Anfrage, 6010 Kriens` when the street is hidden; `6003 Luzern - ...` when there is none; one page had no such header |
| latitude, longitude | **not in the HTML** (see section 7) | |
| furnished, temporary | row `Particulars:` = `Temporary, Furnished` / `Furnished`; also `h1` contains "furnished flat" | present 2/10 pages (the 2 furnished flats; the other 8 pages have no such row) |
| year built | row `Year of construction:` (also `Year of renovation:`) | present 3/10; ad JSON `year_built` |
| canton | ad JSON `state` | `"LU"`, but null on one of 10 pages |

`data-ad-slot-keywords` (a JSON attribute on an ad `div`) holds offer_type, price_display, attributes, zipcode, city, state, space_display, number_of_rooms, year_built. It is not used for rent or area: `price_display` equals neither the gross nor the net rent on several pages (for example 2680 vs gross 2920), and `space_display` differed from `Livingspace:` on 3 of 7 pages (131 vs 113, 46 vs 54, 84 vs 77). The advertiser block, the description and the website field contain personal data and are never parsed.

## 7. Coordinates: are they in the HTML? No
- No latitude/longitude pair anywhere in the listing HTML (searched for numeric patterns and for lat/lng keys). The only numbers of that kind are the `north/east/south/west` of "save search" links; they are the same for listings in the same ZIP area, i.e. a ZIP-area box and not the listing position.
- **Coordinates are available in the JSON that the search page loads itself** (visible in the browser's own network traffic; `/api/v1/` is not disallowed by robots.txt). They are read passively from the Selenium session (Chrome DevTools network log), without extra requests:
  - `GET /api/v1/pin/?east=..&west=..&north=..&south=..&max_count=400&offer_type=RENT&object_category=APARTMENT` returns one object per listing in the map box with `pk`, `latitude`, `longitude`, `price_display` (and like/priority flags). 284 pins for the 284 cards of the Lucerne test.
  - `GET /api/v1/public-listing/?expand=cover_image&limit=0&pk=<id>&pk=<id>...` (48 ids per call, triggered by "Show more") returns the full listing objects. Stored fields: `pk, object_type, object_category, offer_type, rent_gross, rent_net, rent_charges, space_display (=livingspace), number_of_rooms, floor, year_built, attributes, is_furnished, is_temporary, street, zipcode, city, state, latitude, longitude, slug`. Personal or free-text keys exist too (`agency`, `description`, `pitch_title`, ...) and are never stored.
  - Pin coordinates equal the listing JSON coordinates in 284 of 284 cases; none are missing. Of the 55 listings without street, 49 have coordinates of their own (6 share identical coordinates with another listing); of the 229 with street, 74 share coordinates with another listing in the same building. Whether coordinates without a street are exact or only approximate is unknown, so `exact_location` is defined as "own coordinates and street present".

## 8. Facts from the Lucerne test (n = 284 listings, RENT + APARTMENT, JSON)
- `object_type`: APARTMENT 224, FURNISHED_FLAT 39, SINGLE_ROOM 7, ATTIC_FLAT 6, DUPLEX 5, STUDIO 2, ROOF_FLAT 1 (`object_category` is APARTMENT for all).
- `is_furnished` True 86 (30%), `is_temporary` True 56 (20%), `is_swap` 0.
- Missing: living area 18%, rent_gross 17%, rent_net 54%, rent_charges 48%, floor 17% (null; value 0 = ground floor, negative = basement, e.g. -3), year_built 59%, street 19%, canton `state` 70%, rooms 0%, latitude 0%.
- `price_unit` always `monthly`; `status` always `act`.
- Attribute vocabulary (machine keys): `lift, balconygarden, parkingspace, garage, minergie, petsallowed, cable, view, dishwasher, parquetflooring, tumbler, washingmachine, broadbandinternet, stonefloor, accessiblewithwheelchair, fireplace, ramp, raisedgroundfloor, partofcooperative`. So `has_balcony = balconygarden`, `has_lift = lift`, `has_parking = parkingspace or garage`, `has_minergie = minergie`.

## 9. Design decision: read the JSON of the search page
1. Plain `requests` gets 403 on listing pages. Selenium page loads work but would cost about 19 hours for the full download.
2. The HTML has no coordinates, so every listing would need geocoding (about 15,000 requests at 1 per second, about 4 hours, and less exact).
3. The JSON that the search page loads itself contains all required fields plus exact coordinates, and arrives as a by-product of the Selenium work that is needed anyway (tiling and "Show more": 48 listings per click, about 320 clicks for 15,000 listings).
4. Therefore `src/02_collect_listings.py` keeps the UI demonstration (search field, filter, Show more), tiles the map, and collects the `pin` and `public-listing` JSON from the browser's network log while doing so. Only whitelisted fields are stored (never `agency`, descriptions, names, phones). `src/03_parse_listings.py` is a small parser over the stored JSON fields, BeautifulSoup is used to cross-check the values against saved listing pages (section 10), and geocoding via geo.admin.ch remains only as a fallback.

## 10. Cross-check: JSON values vs detail-page values (data-quality limitation)
`src/03_parse_listings.py` compares the parsed JSON with the 10 saved test pages using BeautifulSoup (`tables/parse_crosscheck.csv`):
- Identical in all pairs: floor (8/8), year built (3/3), balcony, lift, parking (10/10 each).
- Different: gross rent (differs in 7 of 9 pairs), net rent (3/5), charges (2/4), living area (5/7), rooms (3/10). In every differing rent pair the detail page shows the higher value (+2% to +16%); rooms differ by 0.5, area by 1 to 6 m².
- Re-loading three of the pages a few hours later showed the same page values, and the live JSON equalled the stored JSON, so this is not a collection artefact. The website itself shows two versions of the same listing: the search cards and the JSON (`rent_title`, `price_display`) on one side, the detail-page tables on the other.
- The JSON is internally consistent (gross = net + charges in 6,850 of 6,974 records, 98.2%); the detail pages are not always (for example net 945 + utilities 90 is not gross 1,010).
- Which version is the "true" advertised rent cannot be decided from outside. The analysis uses the JSON values (the same numbers as the search cards). The limitation, and the small sample (10 pages) it is based on, is stated in the report.
