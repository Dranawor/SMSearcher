#!/usr/bin/env python3
import json, re, time
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
FIRST_SCAN_PAGES, REGULAR_SCAN_PAGES = 3, 1
DELAY_SECONDS, DETAIL_DELAY_SECONDS = 2.0, 1.5
MAX_RETRIES, MAX_DETAIL_ENRICHMENTS = 3, 40

def fetch(url):
    last = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"})
            with urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except HTTPError as exc:
            last = exc
            if exc.code != 429 or attempt >= MAX_RETRIES: raise
            wait = max(10, int(exc.headers.get("Retry-After"))) if exc.headers.get("Retry-After") else 15 * (attempt + 1)
            print(f"Steam returned HTTP 429; waiting {wait}s...")
            time.sleep(wait)
        except URLError as exc:
            last = exc
            if attempt >= MAX_RETRIES: raise
            time.sleep(5 * (attempt + 1))
    raise last

def clean_html(value):
    value = unescape(value or "")
    value = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", value, flags=re.I|re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def meta(html, prop):
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']{re.escape(prop)}["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I|re.S)
        if m: return clean_html(m.group(1))
    return ""

def extract_detail(html):
    title, image, description = meta(html, "og:title"), meta(html, "og:image"), meta(html, "og:description")
    if not title:
        m = re.search(r'<div[^>]+class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</div>', html, re.I|re.S)
        if m: title = clean_html(m.group(1))
    creator = ""
    for pattern in [
        r'<a[^>]+class=["\'][^"\']*(?:friendBlockLinkOverlay|workshop_author_link)[^"\']*["\'][^>]*>(.*?)</a>',
        r'<div[^>]+class=["\'][^"\']*workshopItemAuthor[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>',
    ]:
        m = re.search(pattern, html, re.I|re.S)
        if m and clean_html(m.group(1)):
            creator = clean_html(m.group(1)); break
    return {"title": title, "creator": creator, "thumbnail": image, "description": description}

def extract_results(html, keyword):
    results, seen = [], set()
    href_re = re.compile(r'''href\s*=\s*["']([^"']*sharedfiles/filedetails/\?id=(\d+)[^"']*)["']''', re.I)
    for m in href_re.finditer(html):
        href, listing_id = m.group(1), m.group(2)
        if listing_id in seen: continue
        nearby = html[max(0,m.start()-1200):min(len(html),m.end()+1800)]
        title = ""
        tm = re.search(r'class=["\'][^"\']*workshopItemTitle[^"\']*["\'][^>]*>(.*?)</', nearby, re.I|re.S)
        if tm: title = clean_html(tm.group(1))
        seen.add(listing_id)
        results.append({"id": listing_id, "url": urljoin(BASE+"/", unescape(href).replace("&amp;","&")), "title": title or f"Workshop item {listing_id}", "keywords":[keyword]})
    return results

def search(keyword, pages):
    found, seen = [], set()
    for page in range(1, pages+1):
        url = f"{BASE}/workshop/browse/?appid={APP_ID}&searchtext={quote(keyword)}&section=readytouseitems&browsesort=mostrecent&actualsort=mostrecent&numperpage=30&p={page}"
        page_results = extract_results(fetch(url), keyword)
        print(f"Searching {keyword!r}, page {page}: {len(page_results)} links")
        for item in page_results:
            if item["id"] not in seen:
                seen.add(item["id"]); found.append(item)
        if not page_results: break
        if page < pages: time.sleep(DELAY_SECONDS)
    return found

def load_previous():
    if not OUT.exists(): return {}, set()
    try: data = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception: return {}, set()
    return ({str(x["id"]): x for x in data.get("items",[]) if x.get("id")},
            set(data.get("scan",{}).get("baseline_keywords",[])))

def enrich_items(merged):
    candidates = [x for x in merged.values() if not x.get("title") or str(x.get("title","")).startswith("Workshop item ") or not x.get("thumbnail") or not x.get("creator") or not x.get("description")]
    candidates.sort(key=lambda x:(not x.get("is_new",False),x.get("found_at","")))
    candidates = candidates[:MAX_DETAIL_ENRICHMENTS]
    print(f"Enriching {len(candidates)} listing previews/details...")
    for i, item in enumerate(candidates,1):
        try:
            detail = extract_detail(fetch(f"{BASE}/sharedfiles/filedetails/?id={item['id']}"))
            for key in ("title","creator","thumbnail","description"):
                if detail.get(key): item[key] = detail[key]
            print(f"  {i}/{len(candidates)} {item['id']}: {item.get('title','Untitled')}")
        except Exception as exc: print(f"  detail error for {item['id']}: {exc}")
        if i < len(candidates): time.sleep(DETAIL_DELAY_SECONDS)

def main():
    old, baseline = load_previous()
    first = not bool(old); pages = FIRST_SCAN_PAGES if first else REGULAR_SCAN_PAGES
    merged = {k:{**v,"is_new":False} for k,v in old.items()}
    errors=[]; successful=0; now=datetime.now(timezone.utc); today=now.strftime("%Y-%m-%d")
    for keyword in KEYWORDS:
        try:
            found=search(keyword,pages); successful+=1
            for item in found:
                lid=item["id"]
                if lid in merged:
                    merged[lid]["keywords"]=sorted(set(merged[lid].get("keywords",[])+[keyword]))
                    merged[lid]["url"]=item["url"]
                    if str(merged[lid].get("title","")).startswith("Workshop item "): merged[lid]["title"]=item["title"]
                else:
                    merged[lid]={**item,"keywords":[keyword],"is_new":bool(old) and keyword not in baseline,"found_at":today}
        except Exception as exc:
            print(f"ERROR for {keyword!r}: {exc}"); errors.append({"keyword":keyword,"error":str(exc)})
        time.sleep(DELAY_SECONDS)
    if not successful: raise RuntimeError("Every Steam keyword search failed.")
    enrich_items(merged); baseline.update(KEYWORDS)
    output={"scan":{"completed_at":now.isoformat(),"initialized":True,"baseline_keywords":sorted(baseline),"errors":errors,"pages_checked":pages,"sort":"mostrecent"},"keywords":KEYWORDS,"items":sorted(merged.values(),key=lambda x:(not x.get("is_new",False),x.get("found_at",""),x.get("title","").lower()))}
    OUT.write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding="utf-8")

if __name__ == "__main__": main()
