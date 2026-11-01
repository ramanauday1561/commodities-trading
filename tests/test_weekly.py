"""The Saturday summary and each day on real option prices (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import option_record  # noqa: E402
import weekly  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def data_dir():
    d = tempfile.mkdtemp()
    candles = [{"time": t, "close": c} for t, c in (("2026-10-23", 22600.0), ("2026-10-28", 22698.85), ("2026-10-30", 23053.1))]
    json.dump({"candles": candles, "us_events": {"upcoming": [{"date": "2026-11-06", "kind": "jobs"}]}}, open(os.path.join(d, "nifty.json"), "w"))
    json.dump({"record": {"recent": [{"d": "2026-10-30", "gap_hit": False, "close_hit": False, "from_open_trade": True,
                                      "from_open_dir": "up", "with_stop_pct": 0.42},
                                     {"d": "2026-10-29", "gap_hit": True, "close_hit": False, "from_open_trade": False}]}},
              open(os.path.join(d, "today-nifty.json"), "w"))
    json.dump({"days": [{"d": "2026-10-29", "call": {"rs": 10033}, "put": {"rs": -8986}},
                        {"d": "2026-10-30", "call": {"rs": 1745}, "put": {"rs": -3221}, "app": {"side": "CALL", "rs": 1745}}]},
              open(os.path.join(d, "options-nifty.json"), "w"))
    json.dump({"price": 23242.5, "gap_pct": 0.677, "premium": 33.9}, open(os.path.join(d, "gift-nifty.json"), "w"))
    return d


def weekdays_after(d, n, name):
    out, x = [], d
    while len(out) < n:
        x = x + pd.Timedelta(days=1)
        if x.weekday() < 5:
            out.append(x)
    return out


class Weekly(unittest.TestCase):
    def test_the_message(self):
        with mock.patch("live.track_record", return_value=None), \
                mock.patch("weekly.next_sessions", side_effect=weekdays_after):
            text = weekly.body(data_dir(), tempfile.mkdtemp(), date(2026, 10, 31), [{"date": "2026-10-30", "name": "Reliance"}])
        self.assertIn("NIFTY 50 23,053.10 (+2.00%)", text)
        self.assertIn("gap right 1 of 2, close right 0 of 2; 1 trade(s): 10-30 CALL +0.42%", text)
        self.assertIn("a CALL every day +Rs11,778, a PUT -Rs12,207; our trades +Rs1,745", text.replace("an at-the-money ", "a "))
        self.assertIn("Monday open +0.68%", text)
        self.assertIn("stands aside on Mon 02 Nov, Mon 09 Nov", text)

    def test_once_a_week_on_the_weekend_with_a_channel(self):
        store = tempfile.mkdtemp()
        with mock.patch("status.channels", return_value=[("telegram", None)]), \
                mock.patch("status.notify", return_value={"telegram": "sent"}) as n, \
                mock.patch("weekly.body", return_value="text"):
            self.assertIsNone(weekly.main("d", store, datetime(2026, 10, 30, 9, tzinfo=IST), results=[]))   # Friday
            self.assertEqual(weekly.main("d", store, datetime(2026, 10, 31, 7, tzinfo=IST), results=[]), "text")
            self.assertIsNone(weekly.main("d", store, datetime(2026, 11, 1, 7, tzinfo=IST), results=[]))    # Sunday: sent
            self.assertEqual(n.call_count, 1)


class OptionRecord(unittest.TestCase):
    def test_days_on_real_prices(self):
        d = date(2026, 10, 30)
        rows = [{"d": d, "expiry": date(2026, 11, 3), "strike": k, "type": t, "open": 100.0, "close": c, "settle": 0, "oi": 1,
                 "volume": 1, "fut": 23000} for k in (22900.0, 22950.0, 23000.0) for t, c in (("CE", 130.0), ("PE", 70.0))]
        calls = [{"d": "2026-10-30", "result": {"open": 22964.5}, "from_open": {"trade": True, "direction": "up"}},
                 {"d": "2026-10-29", "result": {"open": 22690.65}, "from_open": {"trade": False}}]
        out = option_record.build(pd.DataFrame(rows), calls)
        self.assertEqual(len(out), 1)                                                    # no prices for 29 Oct here
        self.assertEqual(out[0]["call"]["strike"], 22950.0)
        self.assertEqual(out[0]["call"]["rs"], round((30 - 1.85) * 65))
        self.assertEqual(out[0]["app"]["side"], "CALL")


if __name__ == "__main__":
    unittest.main()
