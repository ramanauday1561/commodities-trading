"""NIFTY futures from Kite (no network)."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import futures_data as fd  # noqa: E402
import kite  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


class Futures(unittest.TestCase):
    def test_near_future(self):
        rows = [{"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "instrument_token": "1", "tradingsymbol": "NIFTY26NOVFUT"},
                {"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-12-29", "instrument_token": "2", "tradingsymbol": "NIFTY26DECFUT"},
                {"name": "NIFTY", "segment": "NFO-OPT", "expiry": "2026-11-09", "instrument_token": "3", "tradingsymbol": "x"},
                {"name": "BANKNIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "instrument_token": "4", "tradingsymbol": "y"}]
        self.assertEqual(fd.near_future(rows, datetime(2026, 11, 5).date()), (1, "NIFTY26NOVFUT"))

    def test_update(self):
        calls = []

        def hist(tok, interval, a, b, cont):
            calls.append((interval, cont))
            if interval == "day":                               # continuous daily candles
                return [(datetime(2026, 11, k, tzinfo=IST), 100.0 + k, 101.0, 99.0, 100.5, 10.0, 5.0) for k in (2, 3, 4)]
            t0 = datetime(2026, 11, 4, 9, 10, tzinfo=IST)
            return [(t0 + timedelta(minutes=5 * k), 1.0, 2.0, 0.5, 1.5, 3.0, 4.0) for k in range(78)]
        inst = lambda: [{"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "instrument_token": "9", "tradingsymbol": "NIFTY26NOVFUT"}]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(kite, "session", return_value=("k", "t")):
            out = fd.update(d, now=datetime(2026, 11, 4, 16, 0, tzinfo=IST), history=hist, instruments=inst)
            self.assertEqual(calls, [("day", True), ("5minute", False)])
            self.assertEqual(out["daily"], "3 days, 2026-11-02 to 2026-11-04")
            daily = fd.load_daily(d)
            self.assertEqual(float(daily.loc[pd.Timestamp("2026-11-03"), "open"]), 103.0)
            intra = pd.read_csv(os.path.join(d, "nifty-5m", "2026-11.csv"))
            self.assertEqual(len(intra), 75)                     # 09:15 ... 15:25 only
            self.assertEqual(set(intra["contract"]), {"NIFTY26NOVFUT"})


if __name__ == "__main__":
    unittest.main()
