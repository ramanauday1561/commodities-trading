"""NIFTY futures history from Kite (no network)."""
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
        rows = [{"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "instrument_token": "1"},
                {"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-12-29", "instrument_token": "2"},
                {"name": "NIFTY", "segment": "NFO-OPT", "expiry": "2026-11-09", "instrument_token": "3"},
                {"name": "BANKNIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "instrument_token": "4"}]
        self.assertEqual(fd.near_future(rows, datetime(2026, 11, 5).date()), 1)

    def test_update_then_only_new_days(self):
        calls = []

        def hist(a, b):
            calls.append((a.date(), b.date()))
            out, t = [], datetime.combine(max(a.date(), datetime(2026, 11, 3).date()), datetime.min.time())
            while t.date() <= b.date():
                for k in range(-1, 76):                      # one candle before the open, one after, are dropped
                    tt = t + timedelta(hours=9, minutes=15 + 5 * k)
                    out.append((tt.replace(tzinfo=IST), 100.0, 101.0, 99.0, 100.5, 10.0, 5.0))
                t += timedelta(days=1)
            return out
        inst = lambda: [{"name": "NIFTY", "segment": "NFO-FUT", "expiry": "2026-11-24", "instrument_token": "9"}]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(kite, "session", return_value=("k", "t")):
            n = fd.update(d, now=datetime(2026, 11, 4, 16, 0, tzinfo=IST), history=hist, instruments=inst)
            self.assertEqual(n, 2)                                # 3 and 4 Nov (finished after 15:35)
            df = pd.read_csv(os.path.join(d, "nifty", "2026-11.csv"))
            self.assertEqual(len(df), 2 * 75)
            self.assertEqual(list(df.columns), fd.COLS)
            calls.clear()
            fd.update(d, now=datetime(2026, 11, 5, 16, 0, tzinfo=IST), history=hist, instruments=inst)
            self.assertEqual(calls, [(datetime(2026, 11, 5).date(), datetime(2026, 11, 5).date())])


if __name__ == "__main__":
    unittest.main()
