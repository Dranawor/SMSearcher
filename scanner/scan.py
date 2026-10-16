import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_FILE = DATA_DIR / "results.json"
KEYWORDS_FILE = ROOT / "keywords.json"
APP_ID = "286160"
WINDOW_DAYS = 7
LATE_INDEX_HOURS = 48
RESULTS_PER_PAGE = 50
MAX_PAGES = 5
SEARCH_DELAY = 1.0
API_BATCH_SIZE = 100
API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SMSearcher/2.0)", "Accept-Language": "en-US,en;q=0.9"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def load():
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    keywords = raw if isinstance(raw, list) else raw.get("keywords", [])
    keywords = list(dict.fromkeys(str(k).strip() for k in keywords if str(k).strip()))
    if not keywords:
        raise RuntimeError("keywords.json contains no keywords")
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"scan": {}, "items": []}
    if not isinstance(data.get("items"), list):
        raise RuntimeError("results.json items must be a list")
    return keywords, data


def request(method, url, **kwargs):
    last_error = None
    for attempt in range(4):
        try:
            response = SESSION.request(method, url, timeout=35, **kwargs)
            if response.status_code == 200:
                return response
            last_error = f"HTTP {response.status_code} for {url}"
            if response.status_code not in (429, 500, 502, 503, 504):
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt < 3:
            time.sleep(min(30, 3 * (2 ** attempt)))
    raise RuntimeError(last_error or f"Failed to fetch {url}")


def search_ids(keyword, since, until):
    found = set()
    page_count = 0
    for page in range(1, MAX_PAGES + 1):
        params = {
            "appid": APP_ID,
            "searchtext": keyword,
            "section": "readytouseitems",
            "browsesort": "mostrecent",
            "actualsort": "mostrecent",
            "num_per_page": RESULTS_PER_PAGE,
            "p": page,
            "days": WINDOW_DAYS,
            "created_date_range_filter_start": int(since.timestamp()),
            "created_date_range_filter_end": int(until.timestamp()),
            "updated_date_range_filter_start": 0,
            "updated_date_range_filter_end": 0,
        }
        response = request("GET", "https://steamcommunity.com/workshop/browse/", params=params)
        matches = re.findall(
            r'''href=["']([^"']*steamcommunity\.com/sharedfiles/filedetails/\?[^"']+)["']''',
            response.text,
            flags=re.I,
        )
        ids = set()
        for match in matches:
            url = html.unescape(match)
            try:
                parsed = urlparse(url)
                vals = parse_qs(parsed.query).get("id", [])
                if vals and vals[0].isdigit():
                    ids.add(vals[0])
            except ValueError:
                continue
        print(f"{keyword} page {page}: {len(ids)} IDs", flush=True)
        found.update(ids)
        page_count += 1
        if len(ids) < RESULTS_PER_PAGE:
            break
        if page < MAX_PAGES:
            time.sleep(SEARCH_DELAY)
    return found, page_count


def get_details(ids):
    result = {}
    ids = sorted(ids)
    for offset in range(0, len(ids), API_BATCH_SIZE):
        batch = ids[offset:offset + API_BATCH_SIZE]
        form = {"itemcount": str(len(batch))}
        form.update({f"publishedfileids[{i}]": value for i, value in enumerate(batch)})
        response = request("POST", API_URL, data=form)
        payload = response.json()
        details = payload.get("response", {}).get("publishedfiledetails")
        if not isinstance(details, list) or len(details) != len(batch):
            raise RuntimeError("Steam details API returned an incomplete batch; database not changed")
        for detail in details:
            listing_id = str(detail.get("publishedfileid", ""))
            if listing_id in batch:
                result[listing_id] = detail
        if any(value not in result for value in batch):
            raise RuntimeError("Steam details API omitted an ID; database not changed")
        if offset + API_BATCH_SIZE < len(ids):
            time.sleep(1)
    return result


def plain_text(raw):
    value = re.sub(r"<[^>]+>", " ", str(raw or ""))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def main():
    keywords, data = load()
    started = utcnow()
    scan = dict(data.get("scan") or {})
    baseline = timestamp(scan.get("baseline_at"))
    if baseline is None:
        raise RuntimeError("The queue baseline has not been initialized. Run Reset Workshop Queue first.")
    last_success = timestamp(scan.get("last_successful_scan"))
    rolling_start = started - timedelta(days=WINDOW_DAYS)
    since = max(rolling_start, baseline)
    if last_success is not None:
        since = max(since, last_success - timedelta(hours=LATE_INDEX_HOURS))
    previous = {}
    for item in data["items"]:
        listing_id = str(item.get("id", ""))
        if listing_id:
            previous[listing_id] = dict(item)
    discovered = {}
    total_pages = 0
    print(f"Verification window: {since.isoformat()} to {started.isoformat()}", flush=True)
    for keyword in keywords:
        found, pages = search_ids(keyword, since, started)
        total_pages += pages
        for listing_id in found:
            discovered.setdefault(listing_id, set()).add(keyword)
        print(f"Cumulative matching IDs: {len(discovered)}", flush=True)
    ignored_ids = set(str(value) for value in data.get("ignored_ids", []))
    candidates = set(discovered).difference(previous).difference(ignored_ids)
    print(f"Unseen IDs requiring publication-date verification: {len(candidates)}", flush=True)
    details = get_details(candidates) if candidates else {}
    items = {}
    for listing_id, existing in previous.items():
        existing["is_new"] = False
        if listing_id in discovered:
            existing["keywords"] = sorted(set(existing.get("keywords", [])) | discovered[listing_id])
        items[listing_id] = existing
    added = 0
    ignored_old = 0
    ignored_unavailable = 0
    for listing_id in sorted(candidates):
        detail = details[listing_id]
        if detail.get("result") != 1:
            ignored_unavailable += 1
            continue
        try:
            created = datetime.fromtimestamp(int(detail["time_created"]), tz=timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise RuntimeError(f"Steam did not provide a valid creation time for {listing_id}")
        if not since <= created <= started:
            ignored_ids.add(listing_id)
            ignored_old += 1
            continue
        app = str(detail.get("consumer_app_id", APP_ID))
        if app != APP_ID:
            ignored_unavailable += 1
            continue
        description = plain_text(detail.get("description", ""))
        thumbnail = str(detail.get("preview_url") or "")
        items[listing_id] = {
            "id": listing_id,
            "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={listing_id}",
            "title": plain_text(detail.get("title")) or "Untitled",
            "creator": "",
            "description": description,
            "thumbnail": thumbnail,
            "preview": thumbnail,
            "keywords": sorted(discovered[listing_id]),
            "created_at": created.isoformat(),
            "found_at": started.isoformat(),
            "is_new": True,
        }
        added += 1
    completed = utcnow()
    scan.update({
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "last_successful_scan": completed.isoformat(),
        "window_days": WINDOW_DAYS,
        "created_after": int(since.timestamp()),
        "created_before": int(started.timestamp()),
        "keywords_scanned": len(keywords),
        "pages_checked": total_pages,
        "results_per_page": RESULTS_PER_PAGE,
        "new_items_added": added,
        "older_unseen_items_rejected": ignored_old,
        "unavailable_items_rejected": ignored_unavailable,
        "errors": [],
    })
    data["scan"] = scan
    data["ignored_ids"] = sorted(ignored_ids)
    data["keywords"] = keywords
    data["items"] = sorted(items.values(), key=lambda item: (bool(item.get("is_new")), item.get("found_at") or ""), reverse=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = RESULTS_FILE.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    temp_file.replace(RESULTS_FILE)
    print(f"Previous listings retained: {len(previous)}")
    print(f"Newly created listings added: {added}")
    print(f"Older unseen listings rejected: {ignored_old}")
    print(f"Unlisted/deleted/mismatched listings rejected: {ignored_unavailable}")
    print(f"Total tracked listings: {len(items)}")


if __name__ == "__main__":
    main()
