"""Live NIFTY option prices from Kite (no network)."""
import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import kite  # noqa: E402
import options_live as ol  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 4, 11, 5, tzinfo=IST)            # Wednesday; NIFTY weekly expiry on Tuesdays


def instruments():
    rows = []
    for exp in ("2026-11-04", "2026-11-10", "2026-11-17", "2026-11-24"):
        for k in range(23500, 24101, 50):
            for t in ("CE", "PE"):
                rows.append({"instrument_token": str(len(rows) + 1), "tradingsymbol": f"NIFTY{exp}{k}{t}", "name": "NIFTY",
                             "segment": "NFO-OPT", "expiry": exp, "strike": str(k), "instrument_type": t, "lot_size": "65"})
    rows.append({"instrument_token": "999", "tradingsymbol": "BANKNIFTYX", "name": "BANKNIFTY", "segment": "NFO-OPT",
                 "expiry": "2026-11-10", "strike": "50000", "instrument_type": "CE", "lot_size": "30"})
    return rows


def quote(syms):
    out = {}
    for s in syms:
        if s == "NSE:NIFTY 50":
            out[s] = {"last_price": 23786.0, "ohlc": {"open": 23842.6}}
        else:
            ce = s.endswith("CE")
            out[s] = {"last_price": 90.0 if ce else 140.0, "ohlc": {"open": 120.0 if ce else 110.0, "high": 1, "low": 1, "close": 1},
                      "volume": 10, "oi": 5, "depth": {"buy": [{"price": 89.5}], "sell": [{"price": 90.5}]}}
    return out


class Snap(unittest.TestCase):

    def test_snapshot_and_page_file(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as data, \
                mock.patch.object(kite, "session", return_value=("k", "t")):
            today = {"date": "2026-11-04", "preopen": {"recorded": {"from_open": {"trade": True, "direction": "down"}}}}
            out = ol.snap(d, data, now=NOW, quote=quote, fetch=instruments, today_json=today)
            self.assertEqual(out["expiry"], "2026-11-10")                 # not the expiring contract (as option_record)
            self.assertEqual(out["call"]["strike"], 23850)                # the strike at NIFTY's open
            self.assertEqual(out["call"]["rs"], round((90 - 120 - ol.COST) * 65))
            self.assertEqual(out["put"]["rs"], round((140 - 110 - ol.COST) * 65))
            self.assertEqual(out["app"]["side"], "PUT")
            self.assertEqual(out["atm_now"]["strike"], 23800)
            rows = list(csv.DictReader(open(os.path.join(d, "snapshots", "2026-11-04.csv"))))
            self.assertEqual(len(rows), 13 * 2 * 2)                       # 21 strikes wanted, 13 listed; CE and PE; 2 expiries
            self.assertEqual({r["expiry"] for r in rows}, {"2026-11-04", "2026-11-10"})     # expiry day: today's and the next
            self.assertEqual(json.load(open(os.path.join(data, "options-live.json")))["call"]["open"], 120.0)
            ol.snap(d, data, now=NOW.replace(minute=15), quote=quote, fetch=instruments)
            self.assertEqual(len(list(csv.DictReader(open(os.path.join(d, "snapshots", "2026-11-04.csv"))))), 104)

    def test_nothing_without_login_or_outside_the_session(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(kite, "session", return_value=None):
                self.assertIsNone(ol.snap(d, d, now=NOW, quote=quote, fetch=instruments))
            with mock.patch.object(kite, "session", return_value=("k", "t")):
                self.assertIsNone(ol.snap(d, d, now=NOW.replace(hour=8, minute=55), quote=quote, fetch=instruments))

    def test_close_candles(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as data, \
                mock.patch.object(kite, "session", return_value=("k", "t")):
            ol.snap(d, data, now=NOW, quote=quote, fetch=instruments)
            hist = lambda tok: [(NOW.replace(hour=9, minute=15), 1, 2, 0.5, 1.5, 100)]
            out = ol.close(d, now=NOW.replace(hour=15, minute=50), history=hist)
            self.assertEqual(len(out), 52)
            self.assertTrue(os.path.exists(os.path.join(d, "candles", "2026-11-04.csv")))


class ChainAndPaper(unittest.TestCase):
    """5 Nov 2026: the wider chain's open interest summary, and the paper straddle (short_option_study variant C)."""

    def test_oi_summary(self):
        rows = [{"expiry": "E", "strike": 100.0, "type": "CE", "oi": 50}, {"expiry": "E", "strike": 110.0, "type": "CE", "oi": 150},
                {"expiry": "E", "strike": 90.0, "type": "PE", "oi": 300}, {"expiry": "E", "strike": 100.0, "type": "PE", "oi": 100},
                {"expiry": "F", "strike": 100.0, "type": "CE", "oi": 999}]
        first = [{"at": "09:16", "expiry": "E", "strike": 100.0, "type": "CE", "oi": "100"},
                 {"at": "09:16", "expiry": "E", "strike": 100.0, "type": "PE", "oi": "100"}]
        out = ol.oi_summary(rows, "E", first)
        self.assertEqual((out["pcr"], out["call_wall"], out["put_wall"]), (2.0, 110.0, 90.0))
        self.assertEqual((out["call_oi_change"], out["put_oi_change"], out["since"]), (100, 300, "09:16"))
        self.assertIsNone(ol.oi_summary([], "E"))

    def test_paper_straddle(self):
        with tempfile.TemporaryDirectory() as d:
            q = {(23850, "CE"): {"last_price": 90.0, "ohlc": {"open": 120.0, "high": 130.0}},
                 (23850, "PE"): {"last_price": 140.0, "ohlc": {"open": 110.0, "high": 170.0}}}      # the PUT hit +50% (165)
            row, rec = ol.paper(d, NOW, q, 23850, "2026-11-04", final=False)
            self.assertEqual(row["legs"]["CE"], {"sold": 120.0, "now": 90.0, "stopped": False, "pts": 30.0})
            self.assertTrue(row["legs"]["PE"]["stopped"])
            self.assertEqual(row["pts"], round(30.0 - 57.0 - 2 * ol.COST, 2))
            self.assertEqual(rec["days"], 0)                                   # not final yet
            row, rec = ol.paper(d, NOW.replace(hour=15, minute=25), q, 23850, "2026-11-04", final=True)
            self.assertEqual((rec["days"], rec["total_rs"]), (1, row["rs"]))
            self.assertEqual(len(json.load(open(os.path.join(d, "paper", "straddle.json")))), 1)     # one row a day

    def test_snap_writes_chain_and_paper(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as data, \
                mock.patch.object(kite, "session", return_value=("k", "t")):
            ol.snap(d, data, now=NOW, quote=quote, fetch=instruments)
            out = ol.snap(d, data, now=NOW.replace(minute=15), quote=quote, fetch=instruments)
            self.assertEqual(out["chain"]["expiry"], "2026-11-10")
            self.assertEqual(out["chain"]["pcr"], 1.0)
            self.assertEqual(out["chain"]["since"], "11:05")
            self.assertEqual(out["paper"]["today"]["expiry"], "2026-11-04")    # nearest: the expiring one on expiry day
            self.assertEqual(out["paper"]["today"]["strike"], 23850)


if __name__ == "__main__":
    unittest.main()
