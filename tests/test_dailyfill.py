import os
import sys
import unittest
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from dailyfill import append_day, daily_from_intraday  # noqa: E402


def bars(start, end, tz, freq="15min"):
    idx = pd.date_range(start, end, freq=freq, tz=tz, inclusive="left")
    c = 100 + np.arange(len(idx), dtype=float)
    return pd.DataFrame({"open": c - 0.5, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0}, index=idx)


class DailyFill(unittest.TestCase):
    def test_nifty_session_is_rebuilt(self):
        b = pd.concat([bars("2026-10-12 09:15", "2026-10-12 15:30", "Asia/Kolkata"),
                       bars("2026-10-13 09:15", "2026-10-13 15:30", "Asia/Kolkata")])
        day = b.loc["2026-10-13"]
        row = daily_from_intraday(b, date(2026, 10, 13), "Asia/Kolkata", 15, 30)
        self.assertEqual(row["open"], day["open"].iloc[0])
        self.assertEqual(row["close"], day["close"].iloc[-1])
        self.assertEqual(row["high"], day["high"].max())
        self.assertEqual(row["low"], day["low"].min())
        self.assertEqual(row["volume"], len(day))

    def test_utc_bars_are_converted(self):
        b = bars("2026-10-13 09:15", "2026-10-13 15:30", "Asia/Kolkata")
        b.index = b.index.tz_convert("UTC").tz_localize(None)
        row = daily_from_intraday(b, date(2026, 10, 13), "Asia/Kolkata", 15, 30)
        self.assertEqual(row["close"], b["close"].iloc[-1])

    def test_unfinished_session_is_not_used(self):
        b = bars("2026-10-13 09:15", "2026-10-13 13:00", "Asia/Kolkata")
        self.assertIsNone(daily_from_intraday(b, date(2026, 10, 13), "Asia/Kolkata", 15, 30))
        self.assertIsNone(daily_from_intraday(b.iloc[:0], date(2026, 10, 13), "Asia/Kolkata", 15, 30))

    def test_futures_session_starts_the_evening_before(self):
        b = bars("2026-10-12 18:00", "2026-10-13 17:00", "America/New_York")
        row = daily_from_intraday(b, date(2026, 10, 13), "America/New_York", 17, 0)
        self.assertEqual(row["open"], b["open"].iloc[0])           # 18:00 on the 12th belongs to the 13th
        self.assertEqual(row["close"], b["close"].iloc[-1])

    def test_append_day(self):
        full = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [0.0]},
                            index=pd.DatetimeIndex(["2026-10-12"]))
        out = append_day(full, date(2026, 10, 13), {"open": 1.5, "high": 3, "low": 1, "close": 2, "volume": 5})
        self.assertEqual(list(out.index.strftime("%Y-%m-%d")), ["2026-10-12", "2026-10-13"])
        self.assertEqual(out["close"].iloc[-1], 2)
        self.assertEqual(list(out.columns), list(full.columns))


if __name__ == "__main__":
    unittest.main()
