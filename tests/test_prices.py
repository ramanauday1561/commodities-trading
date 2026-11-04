"""prices.download: Kite first, Yahoo as the backup, and the checks (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import kite  # noqa: E402
import prices  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 4, 11, 7, tzinfo=IST)          # a Wednesday, in the session


def kite_5m(path, key, token):
    """Fake Kite: 5-minute candles 09:15 .. 11:00 on 3 and 4 Nov."""
    rows = []
    for day in ("2026-11-03", "2026-11-04"):
        t = datetime.fromisoformat(day + "T09:15:00+05:30")
        while t.time() <= datetime(2026, 1, 1, 11, 0).time():
            rows.append([t.strftime("%Y-%m-%dT%H:%M:%S+0530"), 100, 101, 99, 100.5, 0])
            t += timedelta(minutes=5)
    return {"data": {"candles": rows}}


def kite_day(path, key, token):
    return {"data": {"candles": [[f"2026-11-0{d}T00:00:00+0530", 1, 2, 0.5, 1.5 + d, 0] for d in (2, 3, 4)]}}


def yahoo_frame(last, freq="5min", n=20, daily=False):
    idx = pd.date_range(end=last, periods=n, freq=freq)
    df = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.2, "Adj Close": 1.2, "Volume": 0}, index=idx)
    return df


class Download(unittest.TestCase):

    def setUp(self):
        prices.HEALTH.clear()

    def yahoo(self, frame):
        calls = []

        def y(symbol, period, interval, **kw):
            calls.append((symbol, period, interval))
            return frame.copy()
        return y, calls

    def test_other_symbols_go_to_yahoo(self):
        y, calls = self.yahoo(yahoo_frame("2026-11-04 10:00"))
        with mock.patch.object(kite, "session", return_value=("k", "t")):
            prices.download("ES=F", "5d", "1h", now=NOW, yahoo=y)
        self.assertEqual(calls, [("ES=F", "5d", "1h")])

    def test_no_login_uses_yahoo(self):
        y, calls = self.yahoo(yahoo_frame(pd.Timestamp("2026-11-04 11:00", tz=IST)))
        with mock.patch.object(kite, "session", return_value=None):
            df = prices.download("^NSEI", "1d", "5m", now=NOW, yahoo=y)
        self.assertEqual((prices.source_of(df), len(calls)), ("yahoo", 1))
        self.assertIsNone(prices.HEALTH[-1]["issue"])            # no login is not an error

    def test_kite_intraday_like_yfinance(self):
        y, calls = self.yahoo(yahoo_frame("2026-11-04 10:00"))
        with mock.patch.object(kite, "session", return_value=("k", "t")):
            df = prices.download("^NSEI", "1d", "5m", now=NOW, get=kite_5m, yahoo=y)
        self.assertEqual(prices.source_of(df), "kite")
        self.assertEqual(calls, [])
        self.assertEqual(set(df.index.date), {datetime(2026, 11, 4).date()})          # period 1d: the last session
        self.assertEqual(str(df.index.tz), "Asia/Kolkata")
        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Adj Close", "Volume"])
        self.assertEqual(df.index[0].strftime("%H:%M"), "09:15")

    def test_stale_kite_tries_yahoo(self):
        late = NOW + timedelta(hours=2)                                                  # 13:07: Kite stops at 11:00
        fresh = yahoo_frame(pd.Timestamp("2026-11-04 13:00", tz=IST))
        y, calls = self.yahoo(fresh)
        with mock.patch.object(kite, "session", return_value=("k", "t")):
            df = prices.download("^NSEI", "1d", "5m", now=late, get=kite_5m, yahoo=y)
        self.assertEqual(prices.source_of(df), "yahoo")
        self.assertIn("Kite candles stale", prices.HEALTH[-1]["issue"])

    def test_kite_error_falls_back(self):
        def down(*a, **k):
            raise kite.KiteError("HTTP 403 TokenException: expired")
        y, calls = self.yahoo(yahoo_frame(pd.Timestamp("2026-11-04 11:05", tz=IST)))
        with mock.patch.object(kite, "session", return_value=("k", "t")):
            df = prices.download("^NSEI", "1d", "5m", now=NOW, get=down, yahoo=y)
        self.assertEqual(prices.source_of(df), "yahoo")
        self.assertIn("TokenException", prices.HEALTH[-1]["issue"])

    def test_daily_kite_and_long_history_merged(self):
        old = yahoo_frame("2026-11-03", freq="D", n=400)
        old.loc[pd.Timestamp("2026-11-03"), "Close"] = 999.0                             # Yahoo's version of 3 Nov
        y, calls = self.yahoo(old)
        with mock.patch.object(kite, "session", return_value=("k", "t")):
            short = prices.download("^NSEI", "5d", "1d", now=NOW, get=kite_day, yahoo=y)
            long = prices.download("^NSEI", "max", "1d", now=NOW, get=kite_day, yahoo=y)
        self.assertEqual((prices.source_of(short), short.index.tz), ("kite", None))
        self.assertEqual(prices.source_of(long), "kite+yahoo")
        self.assertEqual(long.loc[pd.Timestamp("2026-11-03"), "Close"], 4.5)            # Kite's official close wins
        self.assertEqual(long.index[-1], pd.Timestamp("2026-11-04"))
        self.assertGreater(len(long), 390)

    def test_missing_session(self):
        df = yahoo_frame("2026-10-30", freq="D", n=5)
        self.assertEqual(prices.missing_session(df, datetime(2026, 11, 3, 2, 9, tzinfo=IST)), "2026-11-02")
        self.assertIsNone(prices.missing_session(yahoo_frame("2026-11-02", freq="D", n=5), datetime(2026, 11, 3, 2, 9, tzinfo=IST)))

    def test_health_file(self):
        y, _ = self.yahoo(yahoo_frame(pd.Timestamp("2026-11-04 11:05", tz=IST)))
        with mock.patch.object(kite, "session", return_value=None):
            prices.download("^NSEI", "1d", "5m", now=NOW, yahoo=y)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "data-health.json")
            with mock.patch.object(kite, "session", return_value=None):
                out = prices.save_health(p)
            self.assertEqual(json.load(open(p))["series"]["NIFTY 50 5m"]["source"], "yahoo")
            self.assertFalse(out["kite"])


if __name__ == "__main__":
    unittest.main()
