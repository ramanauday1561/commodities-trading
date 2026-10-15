"""Temporary: which official calendar sources answer from a GitHub runner? (second try)"""
import re
import urllib.request

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9",
     "Referer": "https://www.bls.gov/", "Connection": "keep-alive"}
URLS = [
    ("https://www.bls.gov/schedule/news_release/bls.ics", H),
    ("https://www.bls.gov/schedule/news_release/cpi.htm", H),
    ("https://www.bls.gov/cpi/", H),
    ("https://api.stlouisfed.org/fred/series/vintagedates?series_id=CPIAUCSL&file_type=json", {"User-Agent": "Mozilla/5.0"}),
    ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL", {"User-Agent": "Mozilla/5.0"}),
    ("https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=CPIAUCSL", {"User-Agent": "Mozilla/5.0"}),
    ("https://www.federalreserve.gov/releases/h15/", {"User-Agent": "Mozilla/5.0"}),
]
for u, h in URLS:
    try:
        body = urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=60).read().decode("utf-8", "ignore")
        print(f"PROBE OK {u} len={len(body)}")
        print("   head:", re.sub(r"\s+", " ", body[:700]))
    except Exception as e:
        print(f"PROBE FAIL {u} {e!r} {getattr(e, 'read', lambda: b'')()[:200]!r}")
