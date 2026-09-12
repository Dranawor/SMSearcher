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

KEYWORDS = json.loads(
    (ROOT / "keywords.json").read_text(encoding="utf-8")
)

APP_ID = 286160
BASE = "https://steamcommunity.com"

USER_AGENT = "SMSearcher/1.4 (+https://github.com/Dranawor/SMSearcher)"

FIRST_SCAN_PAGES = 3
REGULAR_SCAN_PAGES = 1

# Delay between Workshop search requests.
# There are no longer any individual detail-page requests.
DELAY_SECONDS = 2.0

MAX_RETRIES = 3


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

            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", "replace")

        except HTTPError as exc:
            last = exc

            if exc.code != 429 or attempt >= MAX_RETRIES:
                raise

            retry_after = exc.headers.get("Retry-After")

            if retry_after:
                try:
                    wait = max(10, int(retry_after))
                except ValueError:
                    wait = 15 * (attempt + 1)
            else:
                wait = 15 * (attempt + 1)

            print(f"Steam returned HTTP 429; waiting {wait}s...")
            time.sleep(wait)

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


def extract_results(html, keyword):
    results = []
    seen = set()

    # Find Workshop item links directly from the search results page.
    href_re = re.compile(
        r'''href\s*=\s*["']([^"']*sharedfiles/filedetails/\?id=(\d+)[^"']*)["']''',
        re.I,
    )

    for match in href_re.finditer(html):
        href = match.group(1)
        listing_id = match.group(2)

        if listing_id in seen:
            continue

        # Look around the link for the title that Steam includes
        # in the search-results HTML.
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

        # Some Steam pages use different markup. Try a couple
        # additional lightweight patterns before falling back.
        if not title:
            title_match = re.search(
                r'<div[^>]+class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</div>',
                nearby,
                re.I | re.S,
            )

            if title_match:
                title = clean_html(title_match.group(1))

        url = urljoin(
            BASE + "/",
            unescape(href).replace("&amp;", "&"),
        )

        seen.add(listing_id)

        results.append(
            {
                "id": listing_id,
                "url": url,
                "title": title or f"Workshop item {listing_id}",
                "keywords": [keyword],
            }
        )

    return results


def search(keyword, pages):
    found = []
    seen = set()

    for page in range(1, pages + 1):
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

        html = fetch(url)
        page_results = extract_results(html, keyword)

        print(
            f"Searching {keyword!r}, "
            f"page {page}: {len(page_results)} links"
        )

        for item in page_results:
            if item["id"] not in seen:
                seen.add(item["id"])
                found.append(item)

        if not page_results:
            break

        if page < pages:
            time.sleep(DELAY_SECONDS)

    return found


def load_previous():
    if not OUT.exists():
        return {}, set()

    try:
        data = json.loads(
            OUT.read_text(encoding="utf-8")
        )
    except Exception:
        return {}, set()

    previous_items = {
        str(item["id"]): item
        for item in data.get("items", [])
        if item.get("id")
    }

    baseline_keywords = set(
        data.get("scan", {}).get("baseline_keywords", [])
    )

    return previous_items, baseline_keywords


def main():
    old, baseline = load_previous()

    first_scan = not bool(old)

    pages = (
        FIRST_SCAN_PAGES
        if first_scan
        else REGULAR_SCAN_PAGES
    )

    # Preserve previously discovered listings, but clear the
    # transient is_new flag before this scan.
    merged = {
        listing_id: {
            **item,
            "is_new": False,
        }
        for listing_id, item in old.items()
    }

    errors = []
    successful = 0

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    for keyword in KEYWORDS:
        try:
            found = search(keyword, pages)
            successful += 1

            for item in found:
                listing_id = item["id"]

                if listing_id in merged:
                    existing = merged[listing_id]

                    # Add any newly discovered keyword.
                    existing["keywords"] = sorted(
                        set(
                            existing.get("keywords", [])
                            + [keyword]
                        )
                    )

                    # Keep the URL current.
                    existing["url"] = item["url"]

                    # Search results normally provide a title.
                    # Replace the placeholder if we have a real one.
                    new_title = item.get("title", "")

                    if (
                        new_title
                        and not new_title.startswith("Workshop item ")
                    ):
                        existing["title"] = new_title

                else:
                    merged[listing_id] = {
                        **item,
                        "keywords": [keyword],
                        "is_new": (
                            bool(old)
                            and keyword not in baseline
                        ),
                        "found_at": today,
                    }

        except Exception as exc:
            print(
                f"ERROR for {keyword!r}: {exc}"
            )

            errors.append(
                {
                    "keyword": keyword,
                    "error": str(exc),
                }
            )

        time.sleep(DELAY_SECONDS)

    if not successful:
        raise RuntimeError(
            "Every Steam keyword search failed."
        )

    # The scan itself no longer visits individual Workshop pages.
    # Detailed Workshop information is loaded by the dashboard
    # only when a reviewer hovers over a listing.
    baseline.update(KEYWORDS)

    output = {
        "scan": {
            "completed_at": now.isoformat(),
            "initialized": True,
            "baseline_keywords": sorted(baseline),
            "errors": errors,
            "pages_checked": pages,
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
        f"Scan complete: {len(merged)} total listings."
    )


if __name__ == "__main__":
    main()
