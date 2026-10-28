"""Experiment mode "dukaprobe" (28 Oct 2026): can a GitHub runner get years of free hourly history for the 09:15 signal's
overnight inputs? Yahoo keeps only 2 years of hourly candles, so the signal is tested on ~65 trades. Dukascopy's public
datafeed has 1-minute candles for index CFDs, currencies and commodities, one LZMA file per day; this checks which of
our inputs it has and how far back, on a few sample days. Nothing is saved.
"""
import json
import lzma
import struct
from datetime import date

import requests

BASE = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
CANDIDATES = {"es (S&P 500)": ["USA500IDXUSD"], "nq (Nasdaq 100)": ["USATECHIDXUSD"],
              "nikkei": ["JPNIDXJPY"], "hangseng": ["HKGIDXHKD"], "kospi": ["KORIDXKRW", "KOSPIIDXKRW", "KORIDXUSD"],
              "usdinr": ["USDINR"], "crude (WTI)": ["LIGHTCMDUSD"], "nifty (check)": ["INDIDXUSD", "IND50IDXUSD"]}
DAYS = [date(2015, 3, 17), date(2017, 6, 13), date(2020, 3, 17), date(2023, 10, 17), date(2026, 10, 27)]
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; commodities-trading/1.0)"}


def candles(sym, d):
    """[(seconds from 00:00 UTC, open, high, low, close)] in raw points, or an error string."""
    r = requests.get(BASE.format(sym=sym, y=d.year, m=d.month - 1, d=d.day), headers=HEAD, timeout=40)
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if not r.content:
        return "empty"
    raw = lzma.decompress(r.content)
    out = []
    for i in range(0, len(raw) - 23, 24):
        t, o, c, lo, hi, _ = struct.unpack(">5if", raw[i:i + 24])
        out.append((t, o, hi, lo, c))
    return out


def main():
    res = {}
    for name, syms in CANDIDATES.items():
        for sym in syms:
            row = {}
            for d in DAYS:
                try:
                    c = candles(sym, d)
                    row[str(d)] = c if isinstance(c, str) else f"{len(c)} min, {c[0][0] // 60:04d}-{c[-1][0] // 60:04d} UTC min, close {c[-1][4]}"
                except Exception as e:
                    row[str(d)] = f"{type(e).__name__}"
            res[f"{name} {sym}"] = row
            print("DUKA " + json.dumps({f"{name} {sym}": row}), flush=True)
    return res
