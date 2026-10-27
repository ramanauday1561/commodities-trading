"""Experiment mode "kaggleprobe" (27 Oct 2026): can a GitHub runner download the Kaggle dataset
debashis74017/nifty-50-minute-data (NIFTY 50 1-minute candles, years of them) without a Kaggle key? Yahoo keeps only
~60 days of 5-minute candles, too few to test intraday rules. Tries Kaggle's public download link and kagglehub, both
without credentials, then prints the files, the licence and a sample of the NIFTY 50 file. Nothing is saved.
"""
import glob
import io
import json
import os
import tempfile
import zipfile

import pandas as pd
import requests

REF = "debashis74017/nifty-50-minute-data"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; commodities-trading/1.0)"}


def show(path):
    """The files, and the NIFTY 50 one's columns, first / last rows, size and the session times it covers."""
    files = sorted(f for f in glob.glob(os.path.join(path, "**", "*"), recursive=True) if os.path.isfile(f))
    print("KAGGLE files " + json.dumps({os.path.relpath(f, path): os.path.getsize(f) // 1024 for f in files}), flush=True)
    nifty = [f for f in files if "nifty 50" in os.path.basename(f).lower().replace("_", " ")
             or os.path.basename(f).lower() in ("nifty_50.csv", "nifty50.csv", "nifty 50_minute.csv")]
    for f in nifty[:2]:
        df = pd.read_csv(f)
        print(f"KAGGLE {os.path.basename(f)}: {len(df)} rows, columns {list(df.columns)}", flush=True)
        print("KAGGLE head\n" + df.head(3).to_string() + "\nKAGGLE tail\n" + df.tail(3).to_string(), flush=True)
        tcol = next((c for c in df.columns if "date" in c.lower() or "time" in c.lower()), df.columns[0])
        t = pd.to_datetime(df[tcol], errors="coerce").dropna()
        print("KAGGLE range " + json.dumps({"first": str(t.min()), "last": str(t.max()), "days": int(t.dt.date.nunique()),
                                            "earliest_time": str(t.dt.time.min()), "latest_time": str(t.dt.time.max())}),
              flush=True)
    return bool(files)


def licence():
    for url in (f"https://www.kaggle.com/api/v1/datasets/view/{REF}", f"https://www.kaggle.com/datasets/{REF}"):
        try:
            r = requests.get(url, headers=HEAD, timeout=30)
            txt = r.text
            lic = r.json().get("licenses") if "api/v1" in url and r.ok else None
            print(f"KAGGLE meta {url}: HTTP {r.status_code}, licences {lic}", flush=True)
            if lic is None:
                for k in ("CC0", "CC BY", "Attribution", "ODbL", "Apache", "GPL", "MIT", "Other", "Unknown"):
                    if k in txt:
                        print(f"KAGGLE page mentions licence word: {k}", flush=True)
        except Exception as e:
            print(f"KAGGLE meta {url}: {type(e).__name__}", flush=True)


def main():
    licence()
    url = f"https://www.kaggle.com/api/v1/datasets/download/{REF}"
    try:
        r = requests.get(url, headers=HEAD, timeout=600, allow_redirects=True)
        print(f"KAGGLE direct: HTTP {r.status_code}, {len(r.content) // 1024} KB, "
              f"type {r.headers.get('content-type')}", flush=True)
        if r.ok and r.content[:2] == b"PK":
            with tempfile.TemporaryDirectory() as d:
                zipfile.ZipFile(io.BytesIO(r.content)).extractall(d)
                if show(d):
                    print("KAGGLE result: the direct link works without a key", flush=True)
                    return
        else:
            print("KAGGLE direct body: " + r.text[:200].replace("\n", " "), flush=True)
    except Exception as e:
        print(f"KAGGLE direct: {type(e).__name__} {e}", flush=True)
    try:
        import kagglehub
        path = kagglehub.dataset_download(REF)
        if show(path):
            print("KAGGLE result: kagglehub works without a key", flush=True)
            return
    except Exception as e:
        print(f"KAGGLE kagglehub: {type(e).__name__} {str(e)[:300]}", flush=True)
    print("KAGGLE result: no download without a key", flush=True)
