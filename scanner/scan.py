#!/usr/bin/env python3
import json,re,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote,urljoin
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"data/results.json"
KEYWORDS=json.loads((ROOT/"keywords.json").read_text())
UA="SMSearcher/1.0 (+https://github.com/Dranawor/SMSearcher)"
def fetch(url):
 r=Request(url,headers={"User-Agent":UA,"Accept-Language":"en-US,en;q=0.8"})
 with urlopen(r,timeout=25) as x:return x.read().decode("utf-8","replace")
def clean(s):return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",s or "")).strip()
def search(k):
 u="https://steamcommunity.com/workshop/browse/?searchtext="+quote(k)+"&browsesort=trend&section=readytouseitems"
 html=fetch(u); out=[]; seen=set()
 pat=r'href=["\']([^"\']*sharedfiles/filedetails/\?id=\d+[^"\']*)["\'][^>]*>(.*?)</a>'
 for href,inner in re.findall(pat,html,re.I|re.S):
  url=urljoin("https://steamcommunity.com/",href.replace("&amp;","&")); m=re.search(r"[?&]id=(\d+)",url)
  if not m or m.group(1) in seen:continue
  seen.add(m.group(1)); title=clean(inner)
  if title:out.append({"id":m.group(1),"url":url,"title":title,"keywords":[k]})
 return out
def main():
 old={}
 if OUT.exists():
  try:old={str(x["id"]):x for x in json.loads(OUT.read_text()).get("items",[])}
  except:pass
 merged={};errors=[]
 for k in KEYWORDS:
  try:
   for x in search(k):
    i=x["id"]
    if i in merged:merged[i]["keywords"]=sorted(set(merged[i]["keywords"]+[k]))
    else:x["is_new"]=i not in old;x["found_at"]=datetime.now(timezone.utc).strftime("%Y-%m-%d");merged[i]=x
   time.sleep(1.5)
  except Exception as e:errors.append({"keyword":k,"error":str(e)})
 items=sorted(merged.values(),key=lambda x:(not x.get("is_new",False),x.get("title","").lower()))
 OUT.write_text(json.dumps({"scan":{"completed_at":datetime.now(timezone.utc).isoformat(),"errors":errors},"keywords":KEYWORDS,"items":items},indent=2,ensure_ascii=False))
 print(f"Tracked {len(items)} listings; {len(errors)} keyword errors.")
if __name__=="__main__":main()
