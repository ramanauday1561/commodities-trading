"""Futures contract rolls in Yahoo's continuous series (CL=F, GC=F, SI=F).

Probe (experiment mode "rollprobe"): which dated contract Yahoo's continuous daily close follows on each day, so the
roll days and the price gap between the old and the new contract can be measured.
"""
import json

import numpy as np
import pandas as pd
import yfinance as yf

CODES = "FGHJKMNQUVXZ"
ROOTS = {"CL=F": ("CL", "NYM", CODES), "GC=F": ("GC", "CMX", "GJMQVZ"), "SI=F": ("SI", "CMX", "HKNUZ")}


def _daily(symbol, period="max"):
    raw = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
    if raw is None or not len(raw):
        return None
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.rename(columns=str.lower)[["open", "high", "low", "close"]]


def contracts(root, ex, months, start_year, end_year):
    return [f"{root}{m}{y % 100:02d}.{ex}" for y in range(start_year, end_year + 1) for m in months]


def probe():
    out = {}
    for cont, (root, ex, months) in ROOTS.items():
        c = _daily(cont)
        r = {"rows": len(c), "first": str(c.index[0].date())}
        gap = (c["open"] / c["close"].shift(1) - 1).dropna()
        g3 = gap[gap.index >= "2023-01-01"]
        r["gap_abs_pct"] = {q: round(float(g3.abs().quantile(q) * 100), 3) for q in (0.5, 0.9, 0.99)}
        r["top_gaps_since_2023"] = {str(k.date()): round(float(v * 100), 2)
                                    for k, v in g3.abs().sort_values().tail(30).items()}
        dated, avail = {}, {}
        for t in contracts(root, ex, months, 2023, 2027):
            try:
                d = _daily(t, period="5y")
            except Exception as e:
                d = None
            if d is not None and len(d):
                dated[t] = d["close"]
                avail[t] = [str(d.index[0].date()), str(d.index[-1].date()), len(d)]
        r["dated_available"] = avail
        # which dated contract matches the continuous close each day (within 0.05%)
        follow = {}
        for day, px in c["close"][c.index >= "2023-01-01"].items():
            hits = [t for t, s in dated.items() if day in s.index and abs(s.loc[day] / px - 1) < 5e-4]
            follow[day] = hits[0] if len(hits) == 1 else ("?" if not hits else "|".join(hits))
        f = pd.Series(follow)
        switches = []
        prev = None
        for day, t in f.items():
            if t != prev:
                row = {"d": str(day.date()), "to": t}
                if prev and prev in dated and t in dated:
                    i = c.index.get_loc(day)
                    d0 = c.index[i - 1]
                    o, n = dated[prev], dated[t]
                    if d0 in o.index and d0 in n.index:
                        row["ratio_new_over_old_pct"] = round(float((n.loc[d0] / o.loc[d0] - 1) * 100), 3)
                    row["gap_pct"] = round(float(gap.get(day, np.nan) * 100), 3)
                switches.append(row)
                prev = t
        r["switches"] = switches[-60:]
        r["unmatched_days"] = int((f == "?").sum())
        out[cont] = r
    # hourly: is Yahoo's hourly continuous series re-based to the current contract?
    try:
        h = yf.download("CL=F", period="60d", interval="1h", auto_adjust=False, progress=False)
        h.columns = [c[0] if isinstance(c, tuple) else c for c in h.columns]
        h = h["Close"].dropna()
        jumps = (h / h.shift(1) - 1).abs()
        out["cl_hourly_60d_jumps_gt2pct"] = {str(k): round(float(v * 100), 2) for k, v in jumps[jumps > 0.02].items()}
        for t in ("CLX26.NYM", "CLZ26.NYM", "CLV26.NYM"):
            d = yf.download(t, period="60d", interval="1h", auto_adjust=False, progress=False)
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
            s = d["Close"].dropna() if len(d) else pd.Series(dtype=float)
            j = h.index.intersection(s.index)
            same = (np.abs(h.loc[j] / s.loc[j] - 1) < 5e-4) if len(j) else pd.Series(dtype=bool)
            out[f"cl_hourly_matches_{t}"] = {"overlap": len(j), "first_match": str(same[same].index[0]) if same.any() else None,
                                             "last_match": str(same[same].index[-1]) if same.any() else None,
                                             "share": round(float(same.mean()), 3) if len(j) else None}
    except Exception as e:
        out["hourly_error"] = repr(e)
    print("STUDY rollprobe " + json.dumps(out), flush=True)
