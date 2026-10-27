"""The 5-minute candle history: session candles only, stored days never change, unfinished days wait (no network)."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import intraday_data as idata  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def day(d, base=100.0, start="09:10", end="15:35"):
    t = pd.date_range(f"{d} {start}", f"{d} {end}", freq="5min")
    return pd.DataFrame({"datetime": t, "open": base, "high": base + 1, "low": base - 1, "close": base})


class History(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_only_session_candles_one_file_a_month(self):
        self.assertEqual(idata.add(self.d, "nifty", pd.concat([day("2026-05-29"), day("2026-06-01")])), 2)
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "nifty"))), ["2026-05.csv", "2026-06.csv"])
        days = idata.load(self.d)
        self.assertEqual(len(days), 2)
        g = days[pd.Timestamp("2026-06-01").date()]
        self.assertEqual((len(g), str(g.index[0].time()), str(g.index[-1].time())), (75, "09:15:00", "15:25:00"))

    def test_stored_days_are_not_changed(self):
        idata.add(self.d, "nifty", day("2026-06-01", 100.0))
        self.assertEqual(idata.add(self.d, "nifty", pd.concat([day("2026-06-01", 200.0), day("2026-06-02", 200.0)])), 1)
        days = idata.load(self.d)
        self.assertEqual(days[pd.Timestamp("2026-06-01").date()]["Close"].iloc[0], 100.0)

    def test_today_waits_for_the_close_and_kaggle_loads_once(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("NIFTY 50_5minute.csv", day("2015-01-09").rename(columns={"datetime": "date"})
                       .assign(volume=0).to_csv(index=False))
        calls = []
        y = lambda s: pd.concat([day("2026-10-26"), day("2026-10-27")])
        out = idata.update(self.d, datetime(2026, 10, 27, 14, 0, tzinfo=IST), y,
                           get_kaggle=lambda: calls.append(1) or buf.getvalue())
        self.assertEqual((out["kaggle"], out["nifty"]), ({"nifty": 1}, 1))     # 26 Oct only; 27 Oct still open
        out = idata.update(self.d, datetime(2026, 10, 27, 15, 50, tzinfo=IST), y, get_kaggle=lambda: calls.append(1))
        self.assertEqual((out["nifty"], len(calls)), (1, 1))
        self.assertIn("3 (2015-01-09 to 2026-10-27)", out["nifty_days"])


if __name__ == "__main__":
    unittest.main()
