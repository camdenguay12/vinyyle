#!/usr/bin/env python3
"""Refresh VINYYLE difficulty from observed ListenBrainz album popularity.
Run: python scripts/refresh_popularity.py
No API key required. MusicBrainz lookups are throttled to ~1 request/sec.
"""
import json, math, os, pathlib, time, urllib.parse, urllib.request, datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "albums.json"
HEADERS = {"User-Agent": "VINYYLE/1.0 (https://github.com/camdenguay12/vinyyle)", "Accept": "application/json"}
def get(url, retries=4):
    for n in range(retries):
        try:
            req=urllib.request.Request(url,headers=HEADERS)
            with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
        except Exception as ex:
            print("GET retry",n+1,str(ex)[:130],flush=True)
            time.sleep(min(45,2**n*3))
    return None
def post(url,payload,retries=4):
    for n in range(retries):
        try:
            req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={**HEADERS,"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=40) as response:return json.load(response)
        except Exception as ex:
            print("POST retry",n+1,str(ex)[:130],flush=True)
            time.sleep(min(45,2**n*3))
    return None
def normalize(s):
    import unicodedata,re
    return re.sub(r"[^a-z0-9]+","",unicodedata.normalize("NFKD",s.lower()).encode("ascii","ignore").decode())
data=json.loads(PATH.read_text())
albums=data["albums"]
missing=[a for a in albums if not a.get("mbid")]
print("Resolving MusicBrainz release-group IDs:",len(missing),flush=True)
for idx,a in enumerate(missing):
    q='releasegroup:"%s" AND artist:"%s"'%(a["title"].replace('"',''),a["artist"].replace('"',''))
    url="https://musicbrainz.org/ws/2/release-group/?"+urllib.parse.urlencode({"query":q,"fmt":"json","limit":5})
    results=get(url)
    if results:
        matches=[x for x in results.get("release-groups",[]) if normalize(x.get("title",""))==normalize(a["title"]) and any(normalize(c.get("name",""))==normalize(a["artist"]) for c in x.get("artist-credit",[]) if isinstance(c,dict))]
        if matches:
            best=max(matches,key=lambda x:(int(x.get("score",0)),x.get("primary-type")=="Album"))
            if best.get("primary-type")=="Album" and int(best.get("score",0))>=75:a["mbid"]=best["id"]
    if idx%100==0:print("MusicBrainz processed",idx+1,"/",len(missing),flush=True)
    time.sleep(1.1)
byid={a["mbid"]:a for a in albums if a.get("mbid")}
ids=list(byid)
print("Querying ListenBrainz popularity for",len(ids),"albums",flush=True)
matched=0
for i in range(0,len(ids),100):
    result=post("https://api.listenbrainz.org/1/popularity/release-group",{"release_group_mbids":ids[i:i+100]})
    if not isinstance(result,list):continue
    for entry in result:
        a=byid.get(entry.get("release_group_mbid"))
        if a is None:continue
        listeners=entry.get("total_user_count")
        listens=entry.get("total_listen_count")
        if isinstance(listeners,int) and listeners>=0 and isinstance(listens,int) and listens>=0:
            a["popularity"]={"source":"ListenBrainz","unique_listeners":listeners,"total_listens":listens,"retrieved_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
            matched+=1
print("Measured albums:",matched,flush=True)
if matched==0:
    print("No live popularity measurements; leaving existing ranking unchanged.")
    raise SystemExit(0)
# Use real observed listeners and listens as primary ranking signals.
# Albums without measurements remain explicitly unmeasured, not assigned fabricated counts.
# Keep unmeasured albums in the lower-confidence segment until more coverage is available.
def rank(a):
    p=a.get("popularity") or {}
    listeners=p.get("unique_listeners")
    listens=p.get("total_listens")
    if not isinstance(listeners,int) or not isinstance(listens,int):return (0,0,0,a.get("recognizability_score",0))
    return (1,math.log1p(listeners),math.log1p(listens),a.get("recognizability_score",0))
ordered=sorted(albums,key=rank,reverse=True)
for i,a in enumerate(ordered):
    a["recognizability_score"]=round(100*(1-i/(len(albums)-1)),2)
    a["difficulty"]="easy" if i<500 else "hard"
    a["recognizability_method"]="ListenBrainz measured popularity" if a.get("popularity") else "unmeasured; provisional placement"
data["recognizability_scoring"]={"version":2,"source":"ListenBrainz public popularity API","method":"Rank by observed unique listeners, then total listens; unmeasured albums sorted after measured albums using prior provisional order. Percentile scores are relative to this 1500-album catalog, not an absolute popularity measure.","measured_albums":sum(bool(a.get("popularity")) for a in albums),"easy_count":500,"hard_count":1000,"updated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
print("Saved",data["recognizability_scoring"]["measured_albums"],"measured albums.",flush=True)
