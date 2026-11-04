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


class Frozen(unittest.TestCase):
    """2 Nov 2026: Yahoo's bars stop moving before the close (15:15 and 15:20 at the previous close), then 15:25 jumps."""

    def test_paused_bars_after_15_00_are_left_out_when_read(self):
        t = pd.date_range("2026-11-02 14:55", periods=7, freq="5min")
        c = [23300.0, 23313.25, 23330.25, 23331.1, 23331.1, 23331.1, 23440.8]
        g = pd.DataFrame({"Open": [23290.0] + c[:-1], "High": [x + 5 for x in c[:3]] + [23331.1, 23331.1, 23331.1, 23440.8],
                          "Low": [x - 5 for x in c[:3]] + [23330.35, 23331.1, 23331.1, 23331.1], "Close": c}, index=t)
        m = idata.frozen(g)
        self.assertEqual(list(g.index[m].strftime("%H:%M")), ["15:10", "15:15", "15:20"])   # 15:10 here: 0.85 pt
        self.assertEqual(list(idata.drop_frozen(g).index.strftime("%H:%M")), ["14:55", "15:00", "15:05", "15:25"])

    def test_a_quiet_bar_before_15_00_and_a_real_one_are_kept(self):
        t = pd.date_range("2026-11-02 14:50", periods=3, freq="5min")
        g = pd.DataFrame({"Open": [100.0, 100.0, 100.0], "High": [100.0, 100.0, 100.5], "Low": [100.0, 100.0, 99.5],
                          "Close": [100.0, 100.0, 100.2]}, index=t)
        self.assertFalse(idata.frozen(g).any())


if __name__ == "__main__":
    unittest.main()


class KiteRepair(unittest.TestCase):
    """4 Nov 2026: Kite's candles replace Yahoo days (frozen before the close) and fill gaps; Kaggle days stay."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def frozen_day(self, d):
        g = day(d, start="09:15", end="15:25")
        late = g["datetime"].dt.time >= pd.Timestamp("15:05").time()
        g.loc[late, ["open", "high", "low", "close"]] = 100.0                    # no range at the previous close
        return g

    def test_replace_yahoo_fill_gap_keep_kaggle(self):
        idata.add(self.d, "nifty", day("2026-05-15", start="09:15", end="15:25"))          # a Kaggle day
        idata.add(self.d, "nifty", self.frozen_day("2026-08-12"))                           # a Yahoo day
        self.assertEqual(idata.sources(self.d, "nifty"), {"2026-05-15": "kaggle", "2026-08-12": "yahoo"})
        self.assertEqual(len(idata.load(self.d)[datetime(2026, 8, 12).date()]), 70)         # frozen bars left out
        kite = pd.concat([day(x, base=200.0, start="09:15", end="15:25") for x in ("2026-05-15", "2026-06-10", "2026-08-12")])
        added, replaced, gone = idata.replace(self.d, "nifty", kite)
        self.assertEqual((added, replaced), (1, 1))
        self.assertGreater(gone, 0)
        src = idata.sources(self.d, "nifty")
        self.assertEqual(src, {"2026-05-15": "kaggle", "2026-06-10": "kite", "2026-08-12": "kite"})
        got = idata.load(self.d)
        self.assertEqual(float(got[datetime(2026, 5, 15).date()]["Close"].iloc[0]), 100.0)  # Kaggle kept
        self.assertEqual(float(got[datetime(2026, 8, 12).date()]["Close"].iloc[0]), 200.0)  # Kite in
        self.assertEqual(len(got[datetime(2026, 8, 12).date()]), 75)
        self.assertEqual(idata.replace(self.d, "nifty", kite), (0, 0, 0))                   # Kite days are final

    def test_quiet_kite_bars_are_kept(self):
        g = self.frozen_day("2026-09-01")
        idata.replace(self.d, "nifty", g)
        self.assertEqual(len(idata.load(self.d)[datetime(2026, 9, 1).date()]), 75)

    def test_update_prefers_kite_and_repair(self):
        now = datetime(2026, 11, 4, 16, 0, tzinfo=IST)
        idata.add(self.d, "nifty", self.frozen_day("2026-11-02"))
        open(os.path.join(self.d, "kaggle-loaded.txt"), "w").write("done")
        kite = lambda sym, a, b: pd.concat([day(x, base=300.0, start="09:15", end="15:25") for x in ("2026-11-02", "2026-11-03", "2026-11-04")])
        out = idata.update(self.d, now, get_yahoo=lambda s: (_ for _ in ()).throw(AssertionError("Yahoo not needed")), get_kite=kite)
        self.assertEqual(out["nifty"]["kite_added"], 2)
        self.assertEqual(out["nifty"]["kite_replaced"], 1)
        out = idata.update(self.d, now, get_yahoo=lambda s: day("2026-11-04", start="09:15", end="15:25"), get_kite=lambda *a: None)
        self.assertEqual(idata.sources(self.d, "nifty")["2026-11-04"], "kite")
        r = idata.repair(self.d, "2026-11-01", now=now, get=lambda *a: None)
        self.assertEqual(r["nifty"], "no Kite login today")
