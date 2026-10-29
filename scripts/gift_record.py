"""Record GIFT Nifty (and the USD/INR future) on every run, so a GIFT-era history builds up for a fair test later.

Usage: python scripts/gift_record.py <store_dir>
Why (29 Oct 2026): gift_study.py found SGX Nifty explained 78% of NIFTY's opening gap and lifted the from-open signal's
trades in 2018-2023, but no free GIFT Nifty history exists after SGX Nifty moved to GIFT City (July 2023), so it cannot
be tested where it matters. NSE India's site shows a live GIFT Nifty quote (its getGiftNifty API, read after loading
the home page for cookies); this saves one row per run to <store_dir>/gift/<YYYY-MM>.csv. Information only: nothing
uses it until a few months exist and it has passed a test.
"""
import csv
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
HOME, API = "https://www.nseindia.com/", "https://www.nseindia.com/api/NextApi/apiClient?functionName=getGiftNifty"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
COLS = ["fetched", "kind", "quote_time", "price", "change", "change_pct", "contracts", "expiry"]


def _find(obj, want):
    """Every dict under obj whose key matches `want` (case-insensitive), depth first."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == want and isinstance(v, dict):
                yield v
            yield from _find(v, want)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find(v, want)


def rows(payload, fetched):
    """The GIFT Nifty and USD/INR future rows in NSE's answer (either may be missing)."""
    out = []
    g = next(_find(payload, "giftnifty"), None)
    if g and g.get("lastprice") not in (None, "", "-"):
        out.append({"fetched": fetched, "kind": "gift_nifty", "quote_time": g.get("timestmp"),
                    "price": float(g["lastprice"]), "change": g.get("daychange"), "change_pct": g.get("perchange"),
                    "contracts": g.get("contractstraded"), "expiry": g.get("expirydate")})
    for v in _walk(payload):
        if v.get("instrument_type") == "FUTCUR" and v.get("ltp") not in (None, "", "-"):
            out.append({"fetched": fetched, "kind": "usdinr_future", "quote_time": v.get("timestamp") or v.get("timestmp"),
                         "price": float(v["ltp"]), "change": v.get("change"), "change_pct": v.get("pChange"),
                         "contracts": v.get("contracts"), "expiry": v.get("expiry_dt")})
            break
    return out


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def fetch():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"})
    s.get(HOME, timeout=20)
    s.headers["Referer"] = HOME
    r = s.get(API, timeout=20)
    r.raise_for_status()
    return r.json()


def record(store_dir, now=None, get=fetch):
    now = now or datetime.now(IST)
    try:
        new = rows(get(), now.isoformat(timespec="minutes"))
    except Exception as e:                                  # never stops the run
        print(f"gift: unavailable ({type(e).__name__})", flush=True)
        return []
    if not new:
        print("gift: no quote in the answer", flush=True)
        return []
    path = os.path.join(store_dir, "gift", f"{now:%Y-%m}.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    first = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if first:
            w.writeheader()
        w.writerows(new)
    print("gift: " + ", ".join(f"{r['kind']} {r['price']} ({r['quote_time']})" for r in new), flush=True)
    return new


if __name__ == "__main__":
    record(sys.argv[1])
