"""Tests for the news-tone forecast input (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import newsfeat  # noqa: E402

NIFTY = {"key": "nifty", "tz": "Asia/Kolkata", "close": "15:30", "news": {"query": "nifty"}}
GOLD = {"key": "gold", "tz": "America/New_York", "close": "17:00", "news": {"query": "gold"}}


def series(n, tone_effect, seed=0):
    """n sessions of tones and closes where each return = tone_effect * tone + noise."""
    rng = np.random.default_rng(seed)
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(n + 1)]
    tones = rng.normal(0, 0.3, n + 1)
    closes, c = {}, 100.0
    for i, d in enumerate(days):
        if i:
            c *= 1 + tone_effect * tones[i] + rng.normal(0, 0.01)
        closes[d.isoformat()] = c
    rows = [{"d": d.isoformat(), "tone": float(t), "stories": 5, "n": 5} for d, t in zip(days[1:], tones[1:])]
    return rows, closes


class Cutoff(unittest.TestCase):
    def test_cutoff_is_previous_close_and_skips_weekend(self):
        # Monday 13 Oct 2026 -> Friday 9 Oct 15:30 IST = 10:00 UTC
        self.assertEqual(newsfeat.cutoff(date(2026, 10, 13), NIFTY), datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(newsfeat.cutoff(date(2026, 10, 12), NIFTY), datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(newsfeat.cutoff(date(2026, 10, 13), GOLD), datetime(2026, 10, 12, 21, 0, tzinfo=timezone.utc))

    def test_only_headlines_inside_the_window_count(self):
        end = newsfeat.cutoff(date(2026, 10, 13), NIFTY)
        arts = [{"title": "Stocks surge", "url": "https://a.com/1", "domain": "a.com",
                 "seendate": (end - timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")},
                {"title": "Sensex crash after close", "url": "https://b.com/1", "domain": "b.com",     # after cutoff
                 "seendate": (end + timedelta(minutes=5)).strftime("%Y%m%dT%H%M%SZ")},
                {"title": "Old fall", "url": "https://c.com/1", "domain": "c.com",                    # too old
                 "seendate": (end - timedelta(hours=40)).strftime("%Y%m%dT%H%M%SZ")}]
        with mock.patch.object(newsfeat.news, "from_google", return_value=arts):
            r = newsfeat.session_row(NIFTY, date(2026, 10, 13))
        self.assertEqual((r["n"], r["tone"]), (1, 1.0))
        with mock.patch.object(newsfeat.news, "from_google", return_value=None):
            self.assertIsNone(newsfeat.session_row(NIFTY, date(2026, 10, 13)))

    def test_fill_skips_stored_and_future_sessions(self):
        now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
        rows = [{"d": "2026-10-09", "tone": 0, "stories": 0, "n": 0}]
        with mock.patch.object(newsfeat, "session_row", side_effect=lambda i, s: {"d": s.isoformat()}) as sr:
            new = newsfeat.fill(NIFTY, rows, [date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)], now)
        self.assertEqual([r["d"] for r in new], ["2026-10-12", "2026-10-13"])   # 14 Oct cutoff (13 Oct close) not reached
        self.assertEqual(sr.call_count, 2)


class Evaluate(unittest.TestCase):
    def test_real_signal_is_found_and_used(self):
        rows, closes = series(300, 0.02)
        st = newsfeat.evaluate(rows, closes)
        self.assertGreater(st["tested"], newsfeat.MIN_EVAL)
        self.assertGreater(st["shrink"], 0.3)
        self.assertLess(st["mse_ratio"], 1.0)
        self.assertGreater(newsfeat.adjustment(st, 0.5), 0)
        self.assertLess(newsfeat.adjustment(st, -0.5), 0)

    def test_noise_gets_little_or_no_weight(self):
        rows, closes = series(300, 0.0, seed=3)
        st = newsfeat.evaluate(rows, closes)
        self.assertLess(abs(newsfeat.adjustment(st, 1.0)), 0.002)

    def test_tiny_gain_is_not_enough(self):
        st = {"tested": 200, "shrink": 0.4, "slope": 0.01, "mean": 0.0, "sd": 0.2, "mse_ratio": 0.997}
        self.assertEqual(newsfeat.adjustment(st, 0.5), 0.0)
        self.assertNotEqual(newsfeat.adjustment({**st, "mse_ratio": 0.98}, 0.5), 0.0)

    def test_budget_restarts_for_a_late_news_step(self):
        newsfeat.news._start -= 10_000            # as if the module was imported long ago
        newsfeat.news._down.add("news.google.com")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")) as op, \
                mock.patch("time.sleep"):
            newsfeat.run(NIFTY, _Frame(), date(2026, 10, 13), tempfile.mkdtemp())
        self.assertTrue(op.called)               # requests were attempted, not skipped for lack of budget

    def test_too_little_history_has_no_effect(self):
        rows, closes = series(50, 0.02)
        st = newsfeat.evaluate(rows, closes)
        self.assertLess(st["tested"], newsfeat.MIN_EVAL)
        self.assertEqual(newsfeat.adjustment(st, 1.0), 0.0)

    def test_sessions_without_headlines_are_ignored(self):
        rows, closes = series(300, 0.02)
        for r in rows:
            r["n"] = 0
        self.assertEqual(newsfeat.evaluate(rows, closes)["sessions"], 0)


class _Frame:
    """Minimal stand-in for the price DataFrame used by newsfeat.run."""
    def __init__(self):
        import pandas as pd
        idx = pd.bdate_range("2026-09-28", "2026-10-12")
        self.index = idx
        self._close = pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)

    def __getitem__(self, k):
        return self._close


class ApplyAndMerge(unittest.TestCase):
    def test_apply_shifts_path_and_recomputes_probability(self):
        fc = [{"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "cal_p10": 99.0, "cal_p90": 103.0, "prob_up": 0.5},
              {"open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "cal_p10": 98.0, "cal_p90": 105.0, "prob_up": 0.5}]
        newsfeat.apply(fc, 0.01, 100.0, lambda ret, k: 0.5 + ret)
        self.assertEqual(fc[0]["open"], 100.0)            # today's open is the last close, not shifted
        self.assertEqual(fc[0]["close"], 102.01)
        self.assertEqual(fc[1]["open"], 102.01)
        self.assertAlmostEqual(fc[0]["prob_up"], 0.52)
        same = [dict(fc[0])]
        self.assertEqual(newsfeat.apply(same, 0.0, 100.0, None), same)

    def test_merge_saves_new_rows_from_forecast_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, store = os.path.join(tmp, "data"), os.path.join(tmp, "store")
            os.makedirs(os.path.join(store, "news-daily"))
            os.makedirs(data)
            json.dump([{"d": "2026-10-09", "tone": 0.1}], open(os.path.join(store, "news-daily", "nifty.json"), "w"))
            json.dump({"news_feature": {"rows_new": [{"d": "2026-10-12", "tone": -0.2}, {"d": "2026-10-09", "tone": 0.3}]}},
                      open(os.path.join(data, "nifty.json"), "w"))
            json.dump({"x": 1}, open(os.path.join(data, "news-nifty.json"), "w"))
            newsfeat.merge(data, store)
            rows = json.load(open(os.path.join(store, "news-daily", "nifty.json")))
            self.assertEqual([(r["d"], r["tone"]) for r in rows], [("2026-10-09", 0.3), ("2026-10-12", -0.2)])


if __name__ == "__main__":
    unittest.main()
