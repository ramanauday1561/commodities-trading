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
    """NIFTY 50, Bank NIFTY and India VIX 5-minute files: rows, first / last rows, days, session times, and NIFTY 50's
    daily close (its 15:25 candle) against Yahoo's official daily close."""
    files = sorted(f for f in glob.glob(os.path.join(path, "**", "*"), recursive=True) if os.path.isfile(f))
    print(f"KAGGLE {len(files)} files", flush=True)
    for name in ("NIFTY 50_5minute.csv", "NIFTY BANK_5minute.csv", "INDIA VIX_5minute.csv", "NIFTY 50_minute.csv"):
        f = next((x for x in files if os.path.basename(x) == name), None)
        if not f:
            print(f"KAGGLE {name}: missing", flush=True)
            continue
        df = pd.read_csv(f, parse_dates=["date"])
        sess = df[(df["date"].dt.time >= pd.Timestamp("09:15").time()) & (df["date"].dt.time <= pd.Timestamp("15:29").time())]
        days = sess["date"].dt.date
        per_day = sess.groupby(days).size()
        print(f"KAGGLE {name}: {len(df)} rows ({len(sess)} in 09:15-15:29), {days.nunique()} days, "
              f"{days.min()} to {days.max()}, bars per day median {int(per_day.median())}, "
              f"days with under 70 bars {int((per_day < 70).sum()) if '5minute' in name else '-'}", flush=True)
        if name == "NIFTY 50_5minute.csv":
            print("KAGGLE head\n" + df.head(3).to_string() + "\nKAGGLE tail\n" + sess.tail(3).to_string(), flush=True)
            import yfinance as yf
            y = yf.download("^NSEI", start="2015-11-01", interval="1d", auto_adjust=False, progress=False)
            y.columns = [c[0] if isinstance(c, tuple) else c for c in y.columns]
            yc = pd.Series(y["Close"].values, index=pd.to_datetime(y.index).date)
            kc = sess.groupby(days)["close"].last()
            both = kc.index.intersection(yc.index)
            diff = ((kc[both] / yc[both] - 1) * 100).abs()
            print("KAGGLE vs Yahoo close " + json.dumps({"days": len(both), "median_pct": round(float(diff.median()), 3),
                  "p95_pct": round(float(diff.quantile(0.95)), 3), "over_0.5pct": int((diff > 0.5).sum()),
                  "yahoo_days_missing_in_kaggle": int(len(set(yc.index[yc.index <= kc.index.max()]) - set(kc.index)))}),
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
