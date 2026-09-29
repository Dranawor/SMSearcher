#!/usr/bin/env python3

import json
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "results.json"
KEYWORDS = json.loads((ROOT / "keywords.json").read_text(encoding="utf-8"))

APP_ID = 286160
BASE = "https://steamcommunity.com"
USER_AGENT = "SMSearcher/1.3 (+https://github.com/Dranawor/SMSearcher)"

FIRST_SCAN_PAGES = 5
RECENT_SCAN_PAGES = 5
HISTORICAL_START_PAGE = 6
HISTORICAL_PAGES_PER_RUN = 1

DELAY_SECONDS = 2.0
DETAIL_DELAY_SECONDS = 1.5

MAX_RETRIES = 2
MAX_DETAIL_ENRICHMENTS = 80
MAX_429_WAIT = 30


class SteamRateLimit(Exception):
    pass


def fetch(url):
    last = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

            with urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")

        except HTTPError as exc:
            last = exc

            if exc.code == 429:
                if attempt >= MAX_RETRIES:
                    raise SteamRateLimit(
                        f"Steam returned HTTP 429 after {MAX_RETRIES} retries"
                    )

                retry_after = exc.headers.get("Retry-After")

                if retry_after:
                    try:
                        wait = min(MAX_429_WAIT, max(10, int(retry_after)))
                    except ValueError:
                        wait = min(MAX_429_WAIT, 10 * (attempt + 1))
                else:
                    wait = min(MAX_429_WAIT, 10 * (attempt + 1))

                print(f"Steam returned HTTP 429; waiting {wait}s...")
                time.sleep(wait)
                continue

            raise

        except URLError as exc:
            last = exc

            if attempt >= MAX_RETRIES:
                raise

            wait = 5 * (attempt + 1)
            print(f"Network error; waiting {wait}s...")
            time.sleep(wait)

    raise last


def clean_html(value):
    value = unescape(value or "")
    value = re.sub(
        r"<script\b.*?</script>|<style\b.*?</style>",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def meta(html, prop):
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']{re.escape(prop)}["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)

        if match:
            return clean_html(match.group(1))

    return ""


def extract_detail(html):
    title = meta(html, "og:title")
    image = meta(html, "og:image")
    description = meta(html, "og:description")

    if not title:
        match = re.search(
            r'<div[^>]+class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</div>',
            html,
            re.I | re.S,
        )

        if match:
            title = clean_html(match.group(1))

    creator = ""

    for pattern in [
        r'<a[^>]+class=["\'][^"\']*(?:friendBlockLinkOverlay|workshop_author_link)[^"\']*["\'][^>]*>(.*?)</a>',
        r'<div[^>]+class=["\'][^"\']*workshopItemAuthor[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>',
    ]:
        match = re.search(pattern, html, re.I | re.S)

        if match and clean_html(match.group(1)):
            creator = clean_html(match.group(1))
            break

    return {
        "title": title,
        "creator": creator,
        "thumbnail": image,
        "description": description,
    }


def extract_results(html, keyword):
    results = []
    seen = set()

    href_re = re.compile(
        r'''href\s*=\s*["']([^"']*sharedfiles/filedetails/\?id=(\d+)[^"']*)["']''',
        re.I,
    )

    for match in href_re.finditer(html):
        href = match.group(1)
        listing_id = match.group(2)

        if listing_id in seen:
            continue

        nearby = html[
            max(0, match.start() - 1200):
            min(len(html), match.end() + 1800)
        ]

        title = ""

        title_match = re.search(
            r'class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</',
            nearby,
            re.I | re.S,
        )

        if title_match:
            title = clean_html(title_match.group(1))

        seen.add(listing_id)

        results.append(
            {
                "id": listing_id,
                "url": urljoin(
                    BASE + "/",
                    unescape(href).replace("&amp;", "&"),
                ),
                "title": title or f"Workshop item {listing_id}",
                "keywords": [keyword],
            }
        )

    return results


def search(keyword, pages, start_page=1):
    found = []
    seen = set()

    for offset in range(pages):
        page = start_page + offset

        url = (
            f"{BASE}/workshop/browse/"
            f"?appid={APP_ID}"
            f"&searchtext={quote(keyword)}"
            f"&section=readytouseitems"
            f"&browsesort=mostrecent"
            f"&actualsort=mostrecent"
            f"&numperpage=30"
            f"&p={page}"
        )

        page_results = extract_results(fetch(url), keyword)

        print(
            f"Searching {keyword!r}, page {page}: "
            f"{len(page_results)} links"
        )

        for item in page_results:
            if item["id"] not in seen:
                seen.add(item["id"])
                found.append(item)

        if not page_results:
            break

        if offset < pages - 1:
            time.sleep(DELAY_SECONDS)

    return found


def load_previous():
    if not OUT.exists():
        return {}, set(), {}

    try:
        data = json.loads(
            OUT.read_text(encoding="utf-8")
        )
    except Exception:
        return {}, set(), {}

    old = {
        str(x["id"]): x
        for x in data.get("items", [])
        if x.get("id")
    }

    baseline = set(
        data.get("scan", {}).get("baseline_keywords", [])
    )

    historical_pages = data.get("scan", {}).get(
        "historical_pages", {}
    )

    if not isinstance(historical_pages, dict):
        historical_pages = {}

    return old, baseline, historical_pages


def merge_items(merged, found, keyword, mark_new):
    for item in found:
        listing_id = item["id"]

        if listing_id in merged:
            merged[listing_id]["keywords"] = sorted(
                set(
                    merged[listing_id].get("keywords", [])
                    + [keyword]
                )
            )

            merged[listing_id]["url"] = item["url"]

            existing_title = str(
                merged[listing_id].get("title", "")
            )

            if existing_title.startswith("Workshop item "):
                merged[listing_id]["title"] = item["title"]

        else:
            merged[listing_id] = {
                **item,
                "keywords": [keyword],
                "is_new": mark_new,
                "found_at": datetime.now(
                    timezone.utc
                ).strftime("%Y-%m-%d"),
            }


def enrich_items(merged):
    candidates = [
        item
        for item in merged.values()
        if (
            not item.get("title")
            or str(item.get("title", "")).startswith(
                "Workshop item "
            )
            or not item.get("thumbnail")
            or not item.get("creator")
            or not item.get("description")
        )
    ]

    candidates.sort(
        key=lambda item: (
            not item.get("is_new", False),
            item.get("found_at", ""),
            str(item.get("id", "")),
        )
    )

    candidates = candidates[:MAX_DETAIL_ENRICHMENTS]

    new_count = sum(
        1 for item in candidates
        if item.get("is_new", False)
    )

    existing_count = len(candidates) - new_count

    print(
        f"Enriching {len(candidates)} listing previews/details "
        f"({new_count} new, {existing_count} existing)..."
    )

    for index, item in enumerate(candidates, 1):
        try:
            detail_url = (
                f"{BASE}/sharedfiles/filedetails/"
                f"?id={item['id']}"
            )

            detail = extract_detail(
                fetch(detail_url)
            )

            for key in (
                "title",
                "creator",
                "thumbnail",
                "description",
            ):
                if detail.get(key):
                    item[key] = detail[key]

            label = (
                "NEW"
                if item.get("is_new")
                else "existing"
            )

            print(
                f"  {index}/{len(candidates)} "
                f"[{label}] {item['id']}: "
                f"{item.get('title', 'Untitled')}"
            )

        except Exception as exc:
            print(
                f"  detail error for {item['id']}: {exc}"
            )

        if index < len(candidates):
            time.sleep(DETAIL_DELAY_SECONDS)


def main():
    old, baseline, historical_pages = load_previous()

    first_scan = not bool(old)

    recent_pages = (
        FIRST_SCAN_PAGES
        if first_scan
        else RECENT_SCAN_PAGES
    )

    merged = {
        listing_id: {
            **item,
            "is_new": False,
        }
        for listing_id, item in old.items()
    }

    errors = []
    successful_recent = 0
    successful_historical = 0

    now = datetime.now(timezone.utc)

    for keyword in KEYWORDS:
        try:
            recent = search(
                keyword,
                recent_pages,
                1,
            )

            successful_recent += 1

            merge_items(
                merged,
                recent,
                keyword,
                not first_scan,
            )

        except Exception as exc:
            print(
                f"ERROR during recent scan for "
                f"{keyword!r}: {exc}"
            )

            errors.append(
                {
                    "keyword": keyword,
                    "stage": "recent",
                    "error": str(exc),
                }
            )

        time.sleep(DELAY_SECONDS)

    for keyword in KEYWORDS:
        current_page = int(
            historical_pages.get(
                keyword,
                HISTORICAL_START_PAGE,
            )
        )

        try:
            historical = search(
                keyword,
                HISTORICAL_PAGES_PER_RUN,
                current_page,
            )

            successful_historical += 1

            merge_items(
                merged,
                historical,
                keyword,
                False,
            )

            if historical:
                historical_pages[keyword] = (
                    current_page
                    + HISTORICAL_PAGES_PER_RUN
                )
            else:
                historical_pages[keyword] = (
                    HISTORICAL_START_PAGE
                )

        except Exception as exc:
            print(
                f"ERROR during historical scan for "
                f"{keyword!r}, page {current_page}: {exc}"
            )

            errors.append(
                {
                    "keyword": keyword,
                    "stage": "historical",
                    "page": current_page,
                    "error": str(exc),
                }
            )

        time.sleep(DELAY_SECONDS)

    if not successful_recent:
        raise RuntimeError(
            "Every Steam recent search failed."
        )

    enrich_items(merged)

    baseline.update(KEYWORDS)

    output = {
        "scan": {
            "completed_at": now.isoformat(),
            "initialized": True,
            "baseline_keywords": sorted(baseline),
            "errors": errors,
            "pages_checked": recent_pages,
            "historical_pages": historical_pages,
            "historical_pages_checked": HISTORICAL_PAGES_PER_RUN,
            "sort": "mostrecent",
        },
        "keywords": KEYWORDS,
        "items": sorted(
            merged.values(),
            key=lambda item: (
                not item.get("is_new", False),
                item.get("found_at", ""),
                item.get("title", "").lower(),
            ),
        ),
    }

    OUT.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        f"Scan complete. "
        f"Recent searches: {successful_recent}/"
        f"{len(KEYWORDS)}. "
        f"Historical searches: {successful_historical}/"
        f"{len(KEYWORDS)}. "
        f"Listings: {len(merged)}."
    )


if __name__ == "__main__":
    main()
