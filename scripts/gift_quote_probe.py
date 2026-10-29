"""Experiment mode "giftquote" (29 Oct 2026): a free live GIFT Nifty quote a GitHub runner can read, so the app can
record one every morning (no free GIFT Nifty history exists after June 2023; see gift_study.py). Tries NSE India's
market-status API, NSE IX's site and a few public price feeds; prints status and any GIFT Nifty fields. Saves nothing.
"""
import json
import re

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEAD = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}


def show(name, r, keys=("gift", "GIFT", "Gift")):
    body = r.text
    hits = []
    for k in keys:
        for m in re.finditer(k, body):
            hits.append(body[max(0, m.start() - 80):m.start() + 220].replace("\n", " "))
            if len(hits) >= 3:
                break
    print("GQ " + json.dumps({name: {"status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(body),
                                      "gift": hits[:3]}}), flush=True)


def nse():
    s = requests.Session()
    s.headers.update(HEAD)
    try:
        h = s.get("https://www.nseindia.com/", timeout=30)
        print(f"GQ nse home: {h.status_code}, cookies {sorted(s.cookies.keys())}", flush=True)
        s.headers["Referer"] = "https://www.nseindia.com/"
        for path in ("/api/marketStatus", "/api/NextApi/apiClient?functionName=getGiftNifty", "/api/allIndices"):
            r = s.get("https://www.nseindia.com" + path, timeout=30)
            show("nse " + path, r)
            if path == "/api/marketStatus" and r.ok:
                try:
                    print("GQ nse giftnifty " + json.dumps(r.json().get("giftnifty")), flush=True)
                except ValueError:
                    pass
    except Exception as e:
        print(f"GQ nse: {type(e).__name__} {e}", flush=True)


def others():
    urls = {
        "nseix home": "https://www.nseix.com/",
        "nseix api guess 1": "https://www.nseix.com/api/market-data/gift-nifty",
        "nseix api guess 2": "https://www.nseix.com/markets/gift-nifty",
        "moneycontrol gift page": "https://www.moneycontrol.com/markets/global-indices/",
        "moneycontrol price api": "https://priceapi.moneycontrol.com/pricefeed/notapplicable/inidicesindia/in%3BGIFTNIFTY",
        "et markets": "https://economictimes.indiatimes.com/markets/gift-nifty",
        "groww gift": "https://groww.in/indices/global-indices/sgx-nifty",
        "yahoo search": "https://query1.finance.yahoo.com/v1/finance/search?q=GIFT%20Nifty",
    }
    for name, url in urls.items():
        try:
            r = requests.get(url, headers=HEAD, timeout=30)
            show(name, r)
            if name == "nseix home":
                apis = sorted(set(re.findall(r'["\'](/?(?:api|services|marketdata|market-data)[^"\' ]{3,80})["\']', r.text)))[:30]
                js = sorted(set(re.findall(r'src="([^"]+\.js)"', r.text)))[:10]
                print("GQ nseix paths " + json.dumps({"apis": apis, "js": js}), flush=True)
        except Exception as e:
            print(f"GQ {name}: {type(e).__name__}", flush=True)


def main():
    nse()
    others()
