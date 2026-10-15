"""Temporary: which official calendar sources answer from a GitHub runner?"""
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
URLS = [
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "https://www.federalreserve.gov/monetarypolicy/fomchistorical2019.htm",
    "https://www.bls.gov/schedule/news_release/cpi.htm",
    "https://www.bls.gov/schedule/news_release/empsit.htm",
    "https://www.bls.gov/bls/news-release/cpi.htm",
    "https://www.bls.gov/bls/news-release/empsit.htm",
    "https://alfred.stlouisfed.org/series/downloaddata?seid=CPIAUCSL",
    "https://fred.stlouisfed.org/releases/dates?rid=10",
    "https://www.bls.gov/schedule/2023/home.htm",
]
for u in URLS:
    try:
        req = urllib.request.Request(u, headers=UA)
        body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text)
        dates = re.findall(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}", text)
        print(f"PROBE OK {u} len={len(body)} dates={len(dates)} sample={dates[:6]}")
        i = text.find("2024")
        print("   text:", text[max(0, i - 300):i + 500][:800])
    except Exception as e:
        print(f"PROBE FAIL {u} {e!r}")
