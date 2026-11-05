"""Paper accounts on real option prices (paper_accounts.py; no network)."""
import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import paper_accounts as pa  # noqa: E402

DAY, EXP = "2026-11-05", "2026-11-09"
SNAP = ["at", "tradingsymbol", "expiry", "strike", "type", "ltp", "open", "high", "low", "prev_close", "volume", "oi", "bid", "ask", "spot"]
CANDLE = ["datetime", "tradingsymbol", "expiry", "strike", "type", "open", "high", "low", "close", "volume"]


def snaprow(at, k, t, ltp, spot, exp=EXP):
    return {"at": at, "tradingsymbol": f"NIFTY{k}{t}", "expiry": exp, "strike": f"{k}.0", "type": t, "ltp": ltp, "open": "",
            "high": "", "low": "", "prev_close": "", "volume": "", "oi": "", "bid": "", "ask": "", "spot": spot}


def write(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def chart_time(hm):
    """The Next 10 page's candle times: IST clock time written as UTC."""
    h, m = map(int, hm.split(":"))
    return int(datetime(2026, 11, 5, h, m, tzinfo=timezone.utc).timestamp())


class PaperAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d, self.data = os.path.join(self.tmp.name, "ol"), os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)
        # two runs with quotes: 09:35 (NIFTY 24,410 -> strike 24,400) and 09:46; an expiring-today chain is ignored
        write(os.path.join(self.d, "snapshots", f"{DAY}.csv"), SNAP, [
            snaprow("09:35", 24400, "CE", 100, 24410), snaprow("09:35", 24400, "PE", 90, 24410),
            snaprow("09:35", 24400, "CE", 5, 24410, exp=DAY),
            snaprow("09:46", 24400, "CE", 110, 24425), snaprow("09:46", 24400, "PE", 82, 24425)])
        # 5-minute candles for the 10:05 lean, which has no snapshot run (10:00-10:05 candle ends 10:05; 10:10-10:15 ends 10:15)
        write(os.path.join(self.d, "candles", f"{DAY}.csv"), CANDLE, [
            {"datetime": f"{DAY} {t}", "tradingsymbol": "X", "expiry": EXP, "strike": "24450.0", "type": "PE", "open": c, "high": c,
             "low": c, "close": c, "volume": 1} for t, c in (("10:00", 70), ("10:05", 72), ("10:10", 60))])
        json.dump([{"d": DAY, "rs": 4833, "final": True}], open(self._p("paper", "straddle.json"), "w"))
        leans = [{"made": "09:35", "at": "09:35", "lean": "up", "pts": 1.0, "confident": True, "size": 20, "typical": 23},
                 {"made": "09:33", "at": "09:35", "lean": "down", "pts": -1.0, "confident": False},
                 {"made": "10:06", "at": "10:05", "lean": "down", "pts": -0.5, "confident": False},
                 {"made": "11:00", "at": "11:00", "lean": "up", "pts": 0.2, "confident": False}]      # no prices: left out
        json.dump({"date": DAY, "leans": leans, "candles": [{"time": chart_time("09:55"), "close": 24440.0}]},
                  open(os.path.join(self.data, "next-nifty.json"), "w"))
        json.dump({"record": {"recent": [{"d": DAY, "from_open_dir": "down", "open": 24378.05}]}},
                  open(os.path.join(self.data, "today-nifty.json"), "w"))

    def tearDown(self):
        self.tmp.cleanup()

    def _p(self, *parts):
        p = os.path.join(self.d, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def test_prices_leans_on_quotes_then_candles(self):
        book = pa.update(self.d, self.data, now=datetime(2026, 11, 5, 15, 50))
        day = book["days"][0]
        by = {(x["at"], x["lean"]): x for x in day["leans"]}
        up = by[("09:35", "up")]
        self.assertEqual((up["strike"], up["type"], up["entry"], up["exit"], up["by"]), (24400.0, "CE", 100.0, 110.0, "quotes"))
        self.assertEqual(up["rs"], round((10 - pa.COST) * pa.LOT))
        self.assertEqual(by[("09:35", "down")]["rs"], round((-8 - pa.COST) * pa.LOT))
        c = by[("10:05", "down")]                                   # NIFTY 24,440 at 10:05 -> the 24,450 put, 70 -> 60
        self.assertEqual((c["strike"], c["entry"], c["exit"], c["by"]), (24450.0, 70.0, 60.0, "candles"))
        acc = day["accounts"]
        self.assertEqual((acc["leans"]["trades"], acc["leans"]["of"], acc["leans_star"]["trades"]), (3, 4, 1))
        self.assertEqual(acc["straddle"]["rs"], 4833)
        self.assertNotIn("signal_lean", acc)                        # no candles for the open's strike
        self.assertEqual(book["totals"]["leans"]["balance"], pa.CAPITAL + acc["leans"]["rs"])
        page = json.load(open(os.path.join(self.data, "paper-accounts.json")))
        self.assertEqual(page["totals"]["straddle"]["rs"], 4833)
        self.assertEqual(len(page["today_leans"]), 3)

    def test_rerun_replaces_the_day_and_keeps_earlier_days(self):
        pa.update(self.d, self.data)
        book = json.load(open(self._p("paper", "accounts.json")))
        book["days"].insert(0, {"d": "2026-11-04", "accounts": {"leans": {"rs": -100, "trades": 1, "won": 0}}, "leans": []})
        json.dump(book, open(self._p("paper", "accounts.json"), "w"))
        book = pa.update(self.d, self.data)
        self.assertEqual([x["d"] for x in book["days"]], ["2026-11-04", DAY])
        self.assertEqual(book["totals"]["leans"]["days"], 2)

    def test_signal_lean_open_to_close(self):
        write(os.path.join(self.d, "candles", "2026-11-06.csv"), CANDLE, [
            {"datetime": f"2026-11-06 {t}", "tradingsymbol": "X", "expiry": EXP, "strike": "24400.0", "type": "PE", "open": o,
             "high": o, "low": c, "close": c, "volume": 1} for t, o, c in (("09:15", 226, 220), ("15:25", 100, 98.6))])
        r = pa.signal_lean(os.path.join(self.d, "candles", "2026-11-06.csv"), "down", 24378.05, "2026-11-06")
        self.assertEqual((r["side"], r["strike"], r["entry"], r["exit"]), ("PE", 24400, 226.0, 98.6))
        self.assertIsNone(pa.signal_lean("missing.csv", "down", 24378.05, "2026-11-06"))


if __name__ == "__main__":
    unittest.main()
