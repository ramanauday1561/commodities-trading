"""Experiment mode "kagglesearch" (28 Oct 2026): public Kaggle datasets with years of intraday (hourly or finer) prices
for the 09:15 signal's overnight inputs: US index futures (ES / NQ), Nikkei, KOSPI, Hang Seng, the Indian ADRs (HDB,
IBN, INFY) and USD/INR. Searches Kaggle's public API without a key and lists what it finds; nothing is downloaded.
"""
import json

import requests

QUERIES = ["ES futures 1 minute", "S&P 500 futures intraday", "Nasdaq futures 1 minute", "E-mini S&P hourly",
           "SPX intraday 1 minute", "Nikkei 225 intraday", "Nikkei 1 minute", "Hang Seng intraday", "KOSPI intraday",
           "Asian indices hourly", "USDINR intraday", "forex 1 minute data", "HDFC Bank ADR", "Infosys stock minute",
           "us stocks 1 minute", "index futures hourly"]
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; commodities-trading/1.0)"}


def main():
    seen = set()
    for q in QUERIES:
        try:
            r = requests.get("https://www.kaggle.com/api/v1/datasets/list", params={"search": q, "sortBy": "relevance",
                             "page": 1}, headers=HEAD, timeout=40)
            if r.status_code != 200:
                print(f"KSEARCH {q}: HTTP {r.status_code} {r.text[:120]}", flush=True)
                continue
            rows = []
            for d in r.json()[:8]:
                ref = d.get("ref") or d.get("url", "")
                if ref in seen:
                    continue
                seen.add(ref)
                rows.append({"ref": ref, "title": d.get("title"), "mb": round((d.get("totalBytes") or 0) / 1e6, 1),
                             "updated": str(d.get("lastUpdated"))[:10], "licence": d.get("licenseName"),
                             "downloads": d.get("downloadCount")})
            print("KSEARCH " + json.dumps({q: rows}), flush=True)
        except Exception as e:
            print(f"KSEARCH {q}: {type(e).__name__} {e}", flush=True)
