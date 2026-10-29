"""Experiment mode "giftprobe" (29 Oct 2026): where can years of GIFT Nifty (SGX Nifty before July 2023) prices come
from? GIFT Nifty trades on NSE IX in Gandhinagar almost round the clock (06:30-15:40 and 16:35-02:45 IST), so it
prices the overnight markets before NIFTY opens; the 11-year test (long_signal_study.py) suggests that is why the
from-open signal's edge faded after 2021. Checks Kaggle, Dukascopy, NSE IX and SGX's public historical files; prints
what each has. Nothing is saved.
"""
import io
import json
import lzma
import re
import struct
import time
import zipfile

import requests

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "*/*"}


def kaggle():
    for q in ("GIFT Nifty", "SGX Nifty", "Nifty futures intraday", "Nifty futures 1 minute", "NSE IX"):
        try:
            r = requests.get("https://www.kaggle.com/api/v1/datasets/list", params={"search": q}, headers=HEAD, timeout=40)
            rows = [{"ref": d.get("ref"), "title": d.get("title"), "mb": round((d.get("totalBytes") or 0) / 1e6, 1),
                     "updated": str(d.get("lastUpdated"))[:10], "licence": d.get("licenseName")} for d in r.json()[:8]]
            print("GIFT kaggle " + json.dumps({q: rows}), flush=True)
        except Exception as e:
            print(f"GIFT kaggle {q}: {type(e).__name__}", flush=True)


def dukascopy():
    for sym in ("INDIDXUSD", "INDIDXINR", "IND50IDXUSD", "NIFTYIDXUSD", "INDIAIDXUSD"):
        row = {}
        for y in (2018, 2022, 2026):
            url = f"https://datafeed.dukascopy.com/datafeed/{sym}/{y}/02/BID_candles_hour_1.bi5"
            st = "?"
            for k in range(4):
                try:
                    r = requests.get(url, headers=HEAD, timeout=60)
                    st = r.status_code
                    if st == 200 and r.content:
                        raw = lzma.decompress(r.content)
                        st = f"{len(raw) // 24} hours, close {struct.unpack('>5if', raw[:24])[2]}"
                    if st != 503:
                        break
                except Exception as e:
                    st = type(e).__name__
                time.sleep(8 * (k + 1))
            row[y] = st
        print("GIFT dukascopy " + json.dumps({sym: row}), flush=True)


def nseix():
    s = requests.Session()
    for url in ("https://www.nseix.com/", "https://www.nseix.com/markets/derivatives/historical-data",
                "https://www.nseix.com/markets/reports", "https://www.nseix.com/market-data/historical-data"):
        try:
            r = s.get(url, headers=HEAD, timeout=40)
            links = sorted(set(re.findall(r'href="([^"]*(?:bhav|histor|report|download|csv|zip)[^"]*)"', r.text, re.I)))[:25]
            print("GIFT nseix " + json.dumps({url: {"status": r.status_code, "bytes": len(r.text), "links": links}}), flush=True)
        except Exception as e:
            print(f"GIFT nseix {url}: {type(e).__name__}", flush=True)


def sgx():
    """SGX's public derivatives tick files (one zip a trading day, numbered); SGX Nifty traded there until July 2023."""
    for i in (2000, 3500, 5000, 5300, 5600):
        url = f"https://links.sgx.com/1.0.0/derivatives-historical/{i}/WEBPXTICK_DT.zip"
        try:
            r = requests.get(url, headers=HEAD, timeout=60)
            info = {"status": r.status_code, "bytes": len(r.content)}
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                name = z.namelist()[0]
                lines = z.open(name).read().decode("utf-8", "replace").splitlines()
                info.update({"file": name, "rows": len(lines), "header": lines[0][:200],
                             "nifty_rows": sum(1 for x in lines if ",IN," in x or ",IN " in x or "NIFTY" in x.upper())})
                sample = [x for x in lines if ",IN," in x][:2]
                info["sample"] = sample
            print("GIFT sgx " + json.dumps({i: info}), flush=True)
        except Exception as e:
            print(f"GIFT sgx {i}: {type(e).__name__}", flush=True)


def main():
    for f in (kaggle, nseix, sgx, dukascopy):
        try:
            f()
        except Exception as e:
            print(f"GIFT {f.__name__} failed: {e!r}", flush=True)
