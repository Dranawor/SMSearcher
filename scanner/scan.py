import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_FILE = DATA_DIR / "results.json"
KEYWORDS_FILE = DATA_DIR / "keywords.json"

APP_ID = "286160"

WINDOW_DAYS = 7
RESULTS_PER_PAGE = 50
MAX_RECENT_PAGES = 5

SEARCH_DELAY_SECONDS = 1.5
DETAIL_DELAY_SECONDS = 1.5

MAX_RETRIES = 2
MAX_429_WAIT = 30

MAX_DETAIL_ENRICHMENTS = 100

DEFAULT_KEYWORDS = [
    "Stonemaier",
    "Viticulture",
    "Euphoria",
    "Between Two Cities",
    "Scythe",
    "Charterstone",
    "My Little Scythe",
    "Between Two Castles",
    "Wingspan",
    "Tapestry",
    "Pendulum",
    "Red Rising",
    "Rolling Realms",
    "Libertalia",
    "Smitten",
    "Expeditions",
    "Apiary",
    "Wyrmspan",
    "Stamp Swap",
    "Finspan",
    "Vantage",
    "Origin Story",
    "Wingspan Pocket",
    "Duel of Meloch",
    "Tokaido",
    "Namiji",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SMSearcher/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}


def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def unix_timestamp(dt):
    return int(dt.timestamp())


def load_keywords():
    if not KEYWORDS_FILE.exists():
        return DEFAULT_KEYWORDS[:]

    try:
        with open(KEYWORDS_FILE, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]

        if isinstance(data, dict):
            keywords = data.get("keywords")

            if isinstance(keywords, list):
                return [str(x).strip() for x in keywords if str(x).strip()]

    except Exception as e:
        print(f"Could not read keywords.json: {e}")

    return DEFAULT_KEYWORDS[:]


def load_results():
    if not RESULTS_FILE.exists():
        return {}, {}

    try:
        with open(RESULTS_FILE, encoding="utf-8") as f:
            data = json.load(f)

        items = data.get("items", [])
        previous = {}

        for item in items:
            item_id = str(item.get("id", "")).strip()

            if item_id:
                previous[item_id] = item

        return previous, data

    except Exception as e:
        raise RuntimeError(
            f"Could not read existing results.json: {e}"
        )


def save_results(
    items,
    keywords,
    previous_data,
    started_at,
    completed_at,
    pages_checked,
    errors,
):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    scan_data = dict(previous_data.get("scan", {}))

    scan_data.update(
        {
            "started_at": started_at,
            "completed_at": completed_at,
            "window_days": WINDOW_DAYS,
            "created_after": unix_timestamp(
                now_utc() - timedelta(days=WINDOW_DAYS)
            ),
            "created_before": unix_timestamp(now_utc()),
            "keywords_scanned": len(keywords),
            "pages_checked": pages_checked,
            "results_per_page": RESULTS_PER_PAGE,
            "errors": errors,
        }
    )

    data = dict(previous_data)

    data["scan"] = scan_data
    data["keywords"] = keywords
    data["items"] = sorted(
        items,
        key=lambda x: (
            bool(x.get("is_new")),
            x.get("found_at", ""),
        ),
        reverse=True,
    )

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def fetch(url):
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30,
            )

            if response.status_code == 200:
                return response.text

            if response.status_code == 429:
                wait = min(
                    MAX_429_WAIT,
                    10 * (attempt + 1),
                )

                print(
                    f"Steam returned HTTP 429. "
                    f"Waiting {wait} seconds before retry."
                )

                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                    continue

            print(
                f"HTTP {response.status_code} while fetching {url}"
            )

        except requests.RequestException as e:
            print(f"Request error: {e}")

            if attempt < MAX_RETRIES:
                time.sleep(5)
                continue

        break

    return None


def search_url(
    keyword,
    page,
    start_timestamp,
    end_timestamp,
):
    params = (
        f"appid={APP_ID}"
        f"&searchtext={quote(keyword)}"
        f"&section=readytouseitems"
        f"&browsesort=mostrecent"
        f"&actualsort=mostrecent"
        f"&num_per_page={RESULTS_PER_PAGE}"
        f"&p={page}"
        f"&days={WINDOW_DAYS}"
        f"&created_date_range_filter_start={start_timestamp}"
        f"&created_date_range_filter_end={end_timestamp}"
        f"&updated_date_range_filter_start=0"
        f"&updated_date_range_filter_end=0"
    )

    return (
        "https://steamcommunity.com/workshop/browse/?"
        + params
    )


def extract_search_results(page_html):
    results = []

    pattern = re.compile(
        r'<a[^>]+href="(https://steamcommunity\.com/sharedfiles/'
        r'filedetails/\?id=(\d+))"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    seen = set()

    for match in pattern.finditer(page_html):
        url = html.unescape(match.group(1))
        item_id = match.group(2)
        content = match.group(3)

        if item_id in seen:
            continue

        seen.add(item_id)

        text = re.sub(
            r"<[^>]+>",
            " ",
            content,
        )

        text = html.unescape(text)
        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        results.append(
            {
                "id": item_id,
                "url": url,
                "title": text or "Untitled",
            }
        )

    return results


def extract_detail(item, detail_html):
    title = item.get("title") or ""
    creator = ""
    description = ""
    preview = ""

    title_match = re.search(
        r'<div[^>]+class="[^"]*workshopItemTitle[^"]*"'
        r'[^>]*>(.*?)</div>',
        detail_html,
        re.IGNORECASE | re.DOTALL,
    )

    if title_match:
        value = re.sub(
            r"<[^>]+>",
            " ",
            title_match.group(1),
        )

        value = html.unescape(value)
        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        if value:
            title = value

    creator_match = re.search(
        r'<a[^>]+href="https://steamcommunity\.com/profiles/'
        r'[^"]+"[^>]*>(.*?)</a>',
        detail_html,
        re.IGNORECASE | re.DOTALL,
    )

    if creator_match:
        value = re.sub(
            r"<[^>]+>",
            " ",
            creator_match.group(1),
        )

        value = html.unescape(value)
        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        if value:
            creator = value

    description_match = re.search(
        r'<div[^>]+class="[^"]*workshopItemDescription[^"]*"'
        r'[^>]*>(.*?)</div>',
        detail_html,
        re.IGNORECASE | re.DOTALL,
    )

    if description_match:
        value = re.sub(
            r"<[^>]+>",
            " ",
            description_match.group(1),
        )

        value = html.unescape(value)
        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        if value:
            description = value

    preview_patterns = [
        r'<img[^>]+class="[^"]*workshopItemPreviewImage[^"]*"'
        r'[^>]+src="([^"]+)"',
        r'<img[^>]+src="([^"]+)"'
        r'[^>]+class="[^"]*workshopItemPreviewImage[^"]*"',
        r'<img[^>]+src="(https://steamuserimages[^"]+)"',
    ]

    for pattern in preview_patterns:
        preview_match = re.search(
            pattern,
            detail_html,
            re.IGNORECASE,
        )

        if preview_match:
            preview = html.unescape(
                preview_match.group(1)
            )
            break

    item["title"] = title
    item["creator"] = creator
    item["description"] = description
    item["preview"] = preview

    return item


def search_keyword(
    keyword,
    start_timestamp,
    end_timestamp,
):
    found = {}
    pages_checked = 0

    for page in range(
        1,
        MAX_RECENT_PAGES + 1,
    ):
        url = search_url(
            keyword,
            page,
            start_timestamp,
            end_timestamp,
        )

        print(
            f"Searching '{keyword}' "
            f"page {page}/{MAX_RECENT_PAGES}"
        )

        page_html = fetch(url)

        if page_html is None:
            raise RuntimeError(
                f"Could not retrieve Steam results for "
                f"keyword '{keyword}' page {page}"
            )

        pages_checked += 1

        page_results = extract_search_results(
            page_html
        )

        print(
            f"  Found {len(page_results)} listings "
            f"on page {page}"
        )

        for item in page_results:
            item_id = str(item["id"])

            if item_id not in found:
                found[item_id] = {
                    "id": item_id,
                    "url": item["url"],
                    "title": item.get(
                        "title",
                        "Untitled",
                    ),
                    "creator": "",
                    "description": "",
                    "preview": "",
                    "keywords": [keyword],
                }

            elif keyword not in found[item_id]["keywords"]:
                found[item_id]["keywords"].append(
                    keyword
                )

        if len(page_results) < RESULTS_PER_PAGE:
            break

        time.sleep(SEARCH_DELAY_SECONDS)

    return found, pages_checked


def merge_results(
    found_items,
    previous,
):
    now = iso_now()
    merged = {}

    for item_id, item in found_items.items():
        old = previous.get(item_id)

        if old:
            item["found_at"] = old.get(
                "found_at",
                now,
            )

            item["is_new"] = old.get(
                "is_new",
                False,
            )

            if old.get("creator"):
                item["creator"] = old["creator"]

            if old.get("description"):
                item["description"] = old[
                    "description"
                ]

            if old.get("preview"):
                item["preview"] = old["preview"]

            old_keywords = old.get(
                "keywords",
                [],
            )

            item["keywords"] = sorted(
                set(
                    old_keywords
                    + item.get("keywords", [])
                )
            )

        else:
            item["found_at"] = now
            item["is_new"] = True

        merged[item_id] = item

    for item_id, old in previous.items():
        if item_id not in merged:
            merged[item_id] = old

    return merged


def enrich_items(items):
    candidates = [
        item
        for item in items
        if item.get("is_new")
        and (
            not item.get("creator")
            or not item.get("description")
            or not item.get("preview")
        )
    ]

    candidates.sort(
        key=lambda item: item.get(
            "found_at",
            "",
        ),
        reverse=True,
    )

    candidates = candidates[
        :MAX_DETAIL_ENRICHMENTS
    ]

    print(
        f"Enriching {len(candidates)} "
        f"new listing previews/details..."
    )

    for index, item in enumerate(
        candidates,
        1,
    ):
        print(
            f"  Enriching {index}/{len(candidates)}: "
            f"{item.get('title', 'Untitled')}"
        )

        detail_html = fetch(
            item["url"]
        )

        if detail_html:
            try:
                extract_detail(
                    item,
                    detail_html,
                )
            except Exception as e:
                print(
                    f"  Could not parse detail page "
                    f"for {item['id']}: {e}"
                )

        if index < len(candidates):
            time.sleep(
                DETAIL_DELAY_SECONDS
            )


def main():
    started_at = iso_now()

    keywords = load_keywords()

    if not keywords:
        raise RuntimeError(
            "No keywords were found."
        )

    previous, previous_data = load_results()

    current_time = now_utc()

    start_time = (
        current_time
        - timedelta(days=WINDOW_DAYS)
    )

    start_timestamp = unix_timestamp(
        start_time
    )

    end_timestamp = unix_timestamp(
        current_time
    )

    print(
        f"Scanning Workshop listings created "
        f"between {start_time.isoformat()} "
        f"and {current_time.isoformat()}"
    )

    print(
        f"Existing listings in database: "
        f"{len(previous)}"
    )

    print(
        f"Keywords: {len(keywords)}"
    )

    print(
        f"Maximum pages per keyword: "
        f"{MAX_RECENT_PAGES}"
    )

    print(
        f"Results per page: "
        f"{RESULTS_PER_PAGE}"
    )

    all_found = {}
    successful_keywords = []
    failed_keywords = []
    total_pages = 0
    errors = []

    for keyword in keywords:
        try:
            results, pages = search_keyword(
                keyword,
                start_timestamp,
                end_timestamp,
            )

            total_pages += pages
            successful_keywords.append(
                keyword
            )

            for item_id, item in results.items():
                if item_id not in all_found:
                    all_found[item_id] = item

                else:
                    existing = all_found[
                        item_id
                    ]

                    for item_keyword in item.get(
                        "keywords",
                        [],
                    ):
                        if item_keyword not in existing[
                            "keywords"
                        ]:
                            existing[
                                "keywords"
                            ].append(
                                item_keyword
                            )

            print(
                f"  Total unique recent matches: "
                f"{len(all_found)}"
            )

        except Exception as e:
            message = (
                f"{keyword}: {e}"
            )

            print(
                f"ERROR: {message}"
            )

            failed_keywords.append(
                keyword
            )

            errors.append(
                message
            )

    if not successful_keywords:
        raise RuntimeError(
            "Every Steam Workshop keyword search "
            "failed. Existing results were not changed."
        )

    merged = merge_results(
        all_found,
        previous,
    )

    items = list(
        merged.values()
    )

    enrich_items(items)

    completed_at = iso_now()

    save_results(
        items,
        keywords,
        previous_data,
        started_at,
        completed_at,
        total_pages,
        errors,
    )

    new_count = sum(
        1
        for item in items
        if item.get("is_new")
        and item.get("id") in all_found
        and item.get("found_at") == completed_at
    )

    actual_new_count = sum(
        1
        for item in all_found.values()
        if item.get("is_new")
    )

    print()
    print("Scan complete.")
    print(
        f"Keywords successfully scanned: "
        f"{len(successful_keywords)}"
    )
    print(
        f"Keywords failed: "
        f"{len(failed_keywords)}"
    )
    print(
        f"Existing listings preserved: "
        f"{len(previous)}"
    )
    print(
        f"Recent listings found: "
        f"{len(all_found)}"
    )
    print(
        f"New listings added: "
        f"{actual_new_count}"
    )
    print(
        f"Total listings in database: "
        f"{len(items)}"
    )
    print(
        f"Pages checked: "
        f"{total_pages}"
    )


if __name__ == "__main__":
    main()
