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

APP_ID = 286160  # Tabletop Simulator
BASE = "https://steamcommunity.com"
USER_AGENT = "SMSearcher/1.2 (+https://github.com/Dranawor/SMSearcher)"

FIRST_SCAN_PAGES = 3
REGULAR_SCAN_PAGES = 1
DELAY_SECONDS = 2.0
MAX_RETRIES = 3


def fetch(url):
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code != 429 or attempt >= MAX_RETRIES:
                raise
            retry_after = exc.headers.get("Retry-After")
            try:
                wait = max(10, int(retry_after)) if retry_after else 15 * (attempt + 1)
            except (TypeError, ValueError):
                wait = 15 * (attempt + 1)
            print(f"Steam returned HTTP 429; waiting {wait}s...")
            time.sleep(wait)
        except URLError as exc:
            last_error = exc
            if attempt >= MAX_RETRIES:
                raise
            wait = 5 * (attempt + 1)
            print(f"Steam connection error; waiting {wait}s...")
            time.sleep(wait)
    raise last_error


def clean_html(value):
    value = unescape(value or "")
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_results(html, keyword):
    results = []
    seen = set()

    href_re = re.compile(
        r'''href\s*=\s*["']([^"']*sharedfiles/filedetails/\?id=(\d+)[^"']*)["']''',
        re.I,
    )

    for match in href_re.finditer(html):
        href, listing_id = match.group(1), match.group(2)
        if listing_id in seen:
            continue

        full_url = urljoin(BASE + "/", unescape(href).replace("&amp;", "&"))

        start = max(0, match.start() - 1200)
        end = min(len(html), match.end() + 1800)
        nearby = html[start:end]

        title = ""
        patterns = [
            r'class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</',
            r'class=["\'][^"\']*workshopItem[^"\']*["\'][^>]*>.*?class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</',
        ]
        for pattern in patterns:
            m = re.search(pattern, nearby, re.I | re.S)
            if m:
                title = clean_html(m.group(1))
                if title:
                    break

        if not title:
            anchor = re.search(
                r"<a\b[^>]*href\s*=\s*["']"
                + re.escape(href)
                + r"["'][^>]*>(.*?)</a>",
                nearby,
                re.I | re.S,
            )
            if anchor:
                title = clean_html(anchor.group(1))

        seen.add(listing_id)
        results.append(
            {
                "id": listing_id,
                "url": full_url,
                "title": title or f"Workshop item {listing_id}",
                "keywords": [keyword],
            }
        )

    return results


def search(keyword, pages):
    all_results = []
    seen = set()

    for page in range(1, pages + 1):
        url = (
            f"{BASE}/workshop/browse/"
            f"?appid={APP_ID}"
            f"&searchtext={quote(keyword)}"
            "&section=readytouseitems"
            "&browsesort=mostrecent"
            "&actualsort=mostrecent"
            "&numperpage=30"
            f"&p={page}"
        )

        print(f"Searching {keyword!r}, page {page}...")
        html = fetch(url)
        page_results = extract_results(html, keyword)
        print(f"  found {len(page_results)} Workshop links")

        for item in page_results:
            if item["id"] not in seen:
                seen.add(item["id"])
                all_results.append(item)

        if not page_results:
            break
        if page < pages:
            time.sleep(DELAY_SECONDS)

    return all_results


def load_previous():
    if not OUT.exists():
        return {}, set()

    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}, set()

    old = {
        str(item["id"]): item
        for item in data.get("items", [])
        if item.get("id")
    }
    baseline_keywords = set(data.get("scan", {}).get("baseline_keywords", []))
    return old, baseline_keywords


def main():
    old, baseline_keywords = load_previous()
    first_scan = not bool(old)
    pages = FIRST_SCAN_PAGES if first_scan else REGULAR_SCAN_PAGES

    merged = dict(old)
    errors = []
    successful_keywords = 0
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    print(
        f"Starting {'baseline' if first_scan else 'regular'} scan: "
        f"{len(KEYWORDS)} keywords, {pages} page(s) per keyword."
    )

    for keyword in KEYWORDS:
        try:
            found = search(keyword, pages)
            successful_keywords += 1
            keyword_is_new = keyword not in baseline_keywords

            for item in found:
                listing_id = item["id"]

                if listing_id in merged:
                    merged[listing_id]["keywords"] = sorted(
                        set(merged[listing_id].get("keywords", []) + [keyword])
                    )
                    merged[listing_id]["url"] = item["url"]
                    if not merged[listing_id].get("title"):
                        merged[listing_id]["title"] = item["title"]
                else:
                    merged[listing_id] = {
                        "id": listing_id,
                        "url": item["url"],
                        "title": item["title"],
                        "keywords": [keyword],
                        "is_new": bool(old) and not keyword_is_new,
                        "found_at": today,
                    }

        except Exception as exc:
            print(f"  ERROR for {keyword!r}: {exc}")
            errors.append({"keyword": keyword, "error": str(exc)})

        time.sleep(DELAY_SECONDS)

    if successful_keywords == 0:
        raise RuntimeError(
            "Every Steam keyword search failed. Existing results were preserved."
        )

    baseline_keywords.update(KEYWORDS)

    output = {
        "scan": {
            "completed_at": now.isoformat(),
            "initialized": True,
            "baseline_keywords": sorted(baseline_keywords),
            "errors": errors,
            "pages_checked": pages,
            "sort": "mostrecent",
        },
        "keywords": KEYWORDS,
        "items": sorted(
            merged.values(),
            key=lambda x: (
                not x.get("is_new", False),
                x.get("found_at", ""),
                x.get("title", "").lower(),
            ),
        ),
    }

    OUT.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    new_count = sum(1 for item in merged.values() if item.get("is_new"))
    print(
        f"Completed: {len(merged)} tracked listings; "
        f"{new_count} new; {len(errors)} keyword errors."
    )


if __name__ == "__main__":
    main()
