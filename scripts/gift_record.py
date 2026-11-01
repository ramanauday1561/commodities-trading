"""Record GIFT Nifty (and the USD/INR future) on every run, so a GIFT-era history builds up for a fair test later.

Usage: python scripts/gift_record.py <store_dir> [data_dir]
Why (29 Oct 2026): gift_study.py found SGX Nifty explained 78% of NIFTY's opening gap and lifted the from-open signal's
trades in 2018-2023, but no free GIFT Nifty history exists after SGX Nifty moved to GIFT City (July 2023), so it cannot
be tested where it matters. NSE India's site shows a live GIFT Nifty quote (its getGiftNifty API, read after loading
the home page for cookies); this saves one row per run to <store_dir>/gift/<YYYY-MM>.csv. Information only: nothing
uses it until a few months exist and it has passed a test.
The gap GIFT points to (fixed 29 Oct 2026): GIFT Nifty's own "change" is against its own previous close, and it trades
at a premium to NIFTY that moves around. On 29 Oct it showed -0.27% at 08:55 (22,690), but NIFTY opened at 22,690.65,
only -0.04% from its 22,698.85 close: the -0.27% was mostly the premium. So each GIFT row also stores NIFTY's previous
close (from today-nifty.json), the premium at that close (the last GIFT row from 15:15-15:45 IST on that session, minus
NIFTY's close) and the gap after removing it. Without a recorded premium the gap is left empty, not guessed.
<data_dir>/gift-nifty.json keeps the latest GIFT row for the page and the 08:57 alert.
"""
import csv
import glob
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
HOME, API = "https://www.nseindia.com/", "https://www.nseindia.com/api/NextApi/apiClient?functionName=getGiftNifty"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
COLS = ["fetched", "kind", "quote_time", "price", "change", "change_pct", "contracts", "expiry",
        "nifty_prev_close", "premium", "gap_pct"]
CLOSE_FROM, CLOSE_TO = "15:15", "15:45"         # GIFT rows near NSE's 15:30 close give the premium


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


def premium_at_close(store_dir, day, nifty_close):
    """GIFT Nifty minus NIFTY at NSE's close on `day` (YYYY-MM-DD), from the recorded rows; None if not recorded."""
    best = None
    for f in sorted(glob.glob(os.path.join(store_dir, "gift", f"{day[:7]}.csv"))):
        for r in csv.DictReader(open(f)):
            t = r["fetched"]
            if r["kind"] == "gift_nifty" and t[:10] == day and CLOSE_FROM <= t[11:16] <= CLOSE_TO and r["price"]:
                best = float(r["price"])
    return round(best - nifty_close, 2) if best is not None and nifty_close else None


def last_close_day(store_dir, before):
    """The latest day before `before` (YYYY-MM-DD) with a GIFT row in NSE's closing window: the session the premium is
    measured at. (Rows fetched on weekends or holidays are not sessions; 31 Oct 2026, a Saturday, was taken as one.)"""
    days = {r["fetched"][:10] for f in glob.glob(os.path.join(store_dir, "gift", "*.csv")) for r in csv.DictReader(open(f))
            if r["kind"] == "gift_nifty" and r["fetched"][:10] < before and CLOSE_FROM <= r["fetched"][11:16] <= CLOSE_TO}
    return max(days) if days else None


def with_gap(row, store_dir, today, last=None):
    """Adds NIFTY's previous close, the premium at that close and the gap GIFT points to (or leaves them empty).
    last: (date, close) of NIFTY's last session from nifty.json, used when today's file has no previous close (weekends,
    holidays and before the pre-open run; on 31 Oct 2026 the gap was left empty for that reason)."""
    pre = (today or {}).get("preopen") or {}
    pc = pre.get("prev_close")
    prev_day = last_close_day(store_dir, row["fetched"][:10])
    if not pc and last and prev_day and last[0] == prev_day:
        pc = last[1]
    row.update({"nifty_prev_close": pc, "premium": None, "gap_pct": None})
    if not pc:
        return row
    prem = premium_at_close(store_dir, prev_day, pc) if prev_day else None
    if prem is not None:
        row["premium"] = prem
        row["gap_pct"] = round(((row["price"] - prem) / pc - 1) * 100, 3)
    return row


def _upgrade(path):
    """Rewrites a month file written before the gap columns existed, so new rows line up."""
    rows = list(csv.DictReader(open(path)))
    if rows and set(COLS) - set(rows[0].keys()):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows({k: r.get(k) for k in COLS} for r in rows)


def record(store_dir, now=None, get=fetch, data_dir=None):
    now = now or datetime.now(IST)
    try:
        new = rows(get(), now.isoformat(timespec="minutes"))
    except Exception as e:                                  # never stops the run
        print(f"gift: unavailable ({type(e).__name__})", flush=True)
        return []
    if not new:
        print("gift: no quote in the answer", flush=True)
        return []
    today = None
    if data_dir and os.path.exists(os.path.join(data_dir, "today-nifty.json")):
        today = json.load(open(os.path.join(data_dir, "today-nifty.json")))
        if today.get("date") != now.date().isoformat():
            today = None
    last = None
    if data_dir and os.path.exists(os.path.join(data_dir, "nifty.json")):
        n = json.load(open(os.path.join(data_dir, "nifty.json")))
        last = (n.get("last_date"), n.get("last_close")) if n.get("last_close") else None
    for r in new:
        if r["kind"] == "gift_nifty":
            with_gap(r, store_dir, today, last)
    path = os.path.join(store_dir, "gift", f"{now:%Y-%m}.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        _upgrade(path)
    first = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if first:
            w.writeheader()
        w.writerows(new)
    if data_dir:
        g = next((r for r in new if r["kind"] == "gift_nifty"), None)
        if g:
            json.dump(g, open(os.path.join(data_dir, "gift-nifty.json"), "w"), separators=(",", ":"))
    print("gift: " + ", ".join(f"{r['kind']} {r['price']} ({r['quote_time']})"
                               + (f", gap vs NIFTY {r['gap_pct']:+.2f}% (premium {r['premium']})" if r.get("gap_pct") is not None else "")
                               for r in new), flush=True)
    return new


if __name__ == "__main__":
    record(sys.argv[1], data_dir=sys.argv[2] if len(sys.argv) > 2 else None)
