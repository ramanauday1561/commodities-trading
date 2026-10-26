"""Experiment mode "pcrprobe" (26 Oct 2026): can a GitHub runner download NSE's daily F&O bhavcopy, the free official
file with every contract's open interest, and compute NIFTY's put-call ratio (open interest of NIFTY index puts over
calls) from it? If so, years of end-of-day PCR can be rebuilt for a backtest.
Two formats: the old one up to 5 Jul 2024 (fo<DDMONYYYY>bhav.csv.zip) and the UDiFF one from 8 Jul 2024.
"""
import io
import json
import time
import zipfile
from datetime import date

import pandas as pd
import requests

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "*/*", "Referer": "https://www.nseindia.com/"}


def url(d):
    if d >= date(2024, 7, 8):
        return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    mon = f"{d:%b}".upper()
    return f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d:%Y}/{mon}/fo{d:%d}{mon}{d:%Y}bhav.csv.zip"


def pcr(d, s):
    r = s.get(url(d), headers=HEAD, timeout=30)
    if r.status_code != 200:
        return {"status": r.status_code}
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]))
    df.columns = [c.strip() for c in df.columns]
    if "TckrSymb" in df.columns:                          # UDiFF
        m = (df["TckrSymb"] == "NIFTY") & (df["FinInstrmTp"] == "IDO")
        oi, typ = df.loc[m, "OpnIntrst"], df.loc[m, "OptnTp"]
    else:
        m = (df["SYMBOL"].str.strip() == "NIFTY") & (df["INSTRUMENT"].str.strip() == "OPTIDX")
        oi, typ = df.loc[m, "OPEN_INT"], df.loc[m, "OPTION_TYP"].str.strip()
    puts, calls = float(oi[typ == "PE"].sum()), float(oi[typ == "CE"].sum())
    return {"status": 200, "rows": int(m.sum()), "pcr": round(puts / calls, 3) if calls else None}


def main():
    days = [date(2016, 3, 1), date(2019, 6, 3), date(2022, 1, 3), date(2024, 7, 5), date(2024, 7, 8),
            date(2025, 6, 2), date(2026, 10, 22), date(2026, 10, 23)]
    out = {}
    with requests.Session() as s:
        try:
            s.get("https://www.nseindia.com/", headers=HEAD, timeout=20)      # cookies, in case the archive wants them
        except Exception as e:
            out["home"] = repr(e)
        for d in days:
            try:
                out[str(d)] = pcr(d, s)
            except Exception as e:
                out[str(d)] = {"error": repr(e)[:200]}
            time.sleep(1)
    print("STUDY pcrprobe " + json.dumps(out), flush=True)
