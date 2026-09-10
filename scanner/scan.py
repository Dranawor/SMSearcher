#!/usr/bin/env python3
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/results.json"
KEYWORDS = json.loads((ROOT / "keywords.json").read_text(encoding="utf-8"))

UA = "SMSearcher/1.0 (+https://github.com/Dranawor/SMSearcher)"
PAGES_PER_KEYWORD = 5
DELAY_SECONDS = 1.5

def fetch(url):
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.8",
    })
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", "replace")

def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()

def search(keyword):
    results, seen = [], set()

    for page in range(PAGES_PER_KEYWORD):
        url = (
            "https://steamcommunity.com/workshop/browse/"
            "?searchtext=" + quote(keyword)
            + "&browsesort=mostrecent"
            + "&section=readytouseitems"
            + "&numperpage=30"
            + "&p=" + str(page + 1)
            + "&actualsort=mostrecent"
        )

        html = fetch(url)
        pattern = (
            r'href=["\']([^"\']*sharedfiles/filedetails/\?id=\d+[^"\']*)'
            r'["\'][^>]*>(.*?)</a>'
        )
        found = 0

        for href, inner in re.findall(pattern, html, re.I | re.S):
            full_url = urljoin("https://steamcommunity.com/", href.replace("&amp;", "&"))
            match = re.search(r"[?&]id=(\d+)", full_url)
            if not match:
                continue

            listing_id = match.group(1)
            if listing_id in seen:
                continue

            title = clean(inner)
            if not title:
                continue

            seen.add(listing_id)
            results.append({
                "id": listing_id,
                "url": full_url,
                "title": title,
                "keywords": [keyword],
            })
            found += 1

        if found == 0:
            break
        time.sleep(DELAY_SECONDS)

    return results

def main():
    old = {}
    initialized = False

    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            initialized = bool(previous.get("scan", {}).get("initialized"))
            old = {
                str(x["id"]): x
                for x in previous.get("items", [])
                if "id" in x
            }
        except Exception:
            pass

    merged, errors = {}, []
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    for keyword in KEYWORDS:
        try:
            for item in search(keyword):
                listing_id = item["id"]

                if listing_id in merged:
                    merged[listing_id]["keywords"] = sorted(
                        set(merged[listing_id]["keywords"] + [keyword])
                    )
                    continue

                previous = old.get(listing_id, {})
                merged[listing_id] = {
                    "id": listing_id,
                    "url": item["url"],
                    "title": item["title"],
                    "keywords": sorted(set(previous.get("keywords", []) + [keyword])),
                    # First scan = baseline, so existing results aren't "new".
                    "is_new": initialized and listing_id not in old,
                    "found_at": previous.get("found_at", today),
                }
        except Exception as exc:
            errors.append({"keyword": keyword, "error": str(exc)})
        time.sleep(DELAY_SECONDS)

    output = {
        "scan": {
            "completed_at": now.isoformat(),
            "initialized": True,
            "errors": errors,
            "pages_per_keyword": PAGES_PER_KEYWORD,
            "sort": "mostrecent",
        },
        "keywords": KEYWORDS,
        "items": sorted(
            merged.values(),
            key=lambda x: (not x.get("is_new", False), x.get("title", "").lower())
        ),
    }

    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Tracked {len(merged)} listings; "
          f"{sum(x.get('is_new', False) for x in merged.values())} new; "
          f"{len(errors)} keyword errors.")

if __name__ == "__main__":
    main()
