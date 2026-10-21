"""Today's call: tiers, walk-forward, live record (no network)."""
import os
import sys
import unittest
from datetime import date, datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import todaycall as tc  # noqa: E402


class Calls(unittest.TestCase):
    def test_tiers(self):
        past = np.linspace(0, 1, 101)
        self.assertEqual(tc.tier_of(0.95, past), "very_strong")
        self.assertEqual(tc.tier_of(0.85, past), "strong")
        self.assertEqual(tc.tier_of(0.60, past), "lean")
        self.assertEqual(tc.tier_of(0.10, past), "none")

    def test_walk_forward_learns_a_real_signal_and_never_uses_the_future(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(300, 3))
        y = 0.01 * X[:, 0] + rng.normal(0, 0.003, 300)
        p = tc.walk_forward(X, y)
        self.assertTrue(np.isnan(p[: tc.MIN_HIST]).all())
        ok = ~np.isnan(p)
        self.assertGreater((np.sign(p[ok]) == np.sign(y[ok])).mean(), 0.85)
        y2 = y.copy()
        y2[200:] = 99.0                                   # changing the future must not change earlier predictions
        self.assertTrue(np.allclose(tc.walk_forward(X, y2)[:201], p[:201], equal_nan=True))

    def test_call_block_reports_tier_accuracy(self):
        rng = np.random.default_rng(1)
        X = rng.normal(size=(300, 2))
        y = 0.01 * X[:, 0] + rng.normal(0, 0.004, 300)
        b = tc.call_block(X, y, np.array([2.5, 0.0]))
        self.assertEqual(b["direction"], "up")
        self.assertEqual(b["tier"], "very_strong")
        self.assertGreater(b["tiers"]["very_strong"]["accuracy"], b["tiers"]["all_days"]["accuracy"])

    def test_record_is_scored_only_after_the_close(self):
        nd = pd.DataFrame({"open": [100.0, 101.0], "close": [100.0, 99.0]},
                          index=pd.to_datetime(["2026-10-12", "2026-10-13"]))
        rec = [{"d": "2026-10-13", "gap": {"direction": "up", "tier": "strong"}, "close": {"direction": "up", "tier": "lean"}}]
        tc.resolve(rec, nd, date(2026, 10, 13), datetime(2026, 10, 13, 14, 0))
        self.assertNotIn("result", rec[0])
        tc.resolve(rec, nd, date(2026, 10, 13), datetime(2026, 10, 13, 16, 0))
        self.assertTrue(rec[0]["result"]["gap_hit"])
        self.assertFalse(rec[0]["result"]["close_hit"])
        s = tc.summarize_record(rec)
        self.assertEqual(s["gap"]["strong"], {"calls": 1, "hits": 1})
        self.assertEqual(s["close"]["lean"], {"calls": 1, "hits": 0})

    def test_from_open_signal_is_scored_from_the_open(self):
        nd = pd.DataFrame({"open": [100.0, 101.0, 100.0], "close": [100.0, 99.0, 101.0]},
                          index=pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-14"]))
        call = {"direction": "up", "tier": "none"}
        rec = [{"d": "2026-10-13", "gap": call, "close": call,
                "from_open": {"direction": "down", "tier": "strong", "pred_pct": -0.2, "trade": True}},
               {"d": "2026-10-14", "gap": call, "close": call,
                "from_open": {"direction": "up", "tier": "lean", "pred_pct": 0.05, "trade": False}}]
        tc.resolve(rec, nd, date(2026, 10, 14), datetime(2026, 10, 14, 16, 0))
        # sold at 101, closed at 99: +1.98% minus costs (not "right vs yesterday's close")
        self.assertAlmostEqual(rec[0]["result"]["from_open_pct"], round(-(99 / 101 - 1) * 100 - tc.TRADE_COST_PCT, 3))
        self.assertNotIn("from_open_pct", rec[1]["result"])          # no trade: nothing to score
        s = tc.summarize_record(rec)
        self.assertEqual((s["from_open"]["trades"], s["from_open"]["wins"], s["from_open"]["days"]), (1, 1, 2))

    def test_from_open_block_trades_only_top_days(self):
        rng = np.random.default_rng(2)
        X = rng.normal(size=(300, 2))
        y = 0.01 * X[:, 0] + rng.normal(0, 0.004, 300)
        self.assertTrue(tc.from_open_block(X, y, np.array([2.5, 0.0]))["trade"])
        self.assertFalse(tc.from_open_block(X, y, np.array([0.01, 0.0]))["trade"])
        self.assertIn("from_open", tc.from_open_block(X, y, np.array([0.0, 0.0]))["trade_stats"])

    def test_from_open_stands_aside_after_heavyweight_results(self):
        rng = np.random.default_rng(2)
        X = rng.normal(size=(300, 2))
        y = 0.01 * X[:, 0] + rng.normal(0, 0.004, 300)
        hist = np.zeros(300, bool)
        hist[::10] = True
        b = tc.from_open_block(X, y, np.array([2.5, 0.0]), hist, True)
        self.assertFalse(b["trade"])
        self.assertTrue(b["skipped_for_results"])
        self.assertTrue(tc.from_open_block(X, y, np.array([2.5, 0.0]), hist, False)["trade"])
        self.assertLess(b["trade_stats"]["days"], tc.from_open_block(X, y, np.array([2.5, 0.0]))["trade_stats"]["days"])

    def test_value_at_uses_only_finished_bars(self):
        s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-10-13 03:00", "2026-10-13 04:00"]).tz_localize("UTC"))
        self.assertEqual(tc.value_at(s, pd.Timestamp("2026-10-13 03:59", tz="UTC")), 1.0)
        self.assertTrue(np.isnan(tc.value_at(s, pd.Timestamp("2026-10-13 02:00", tz="UTC"))))

    def test_history_has_every_input_and_no_gaps(self):
        days = pd.bdate_range("2026-09-01", "2026-09-30")
        nd = pd.DataFrame({"open": np.linspace(100, 110, len(days)), "close": np.linspace(100.5, 110.5, len(days))},
                          index=days)
        hours = pd.date_range("2026-08-30", "2026-10-01", freq="h", tz="UTC")
        series = {k: pd.Series(np.linspace(1, 2, len(hours)), index=hours) for k in {**tc.OVERNIGHT, **tc.INDIA}}
        series["usdinr"] = pd.Series(dtype=float)                       # a missing input becomes 0, not NaN
        df = tc.history(nd, series)
        self.assertTrue(set(tc.GAP_FEATS) <= set(df.columns) and set(tc.FRESH_FEATS) <= set(df.columns))
        self.assertFalse(df[tc.GAP_FEATS + tc.FRESH_FEATS].isna().any().any())
        self.assertTrue((df["usdinr"] == 0).all())

    def test_us_futures_split_at_the_us_close(self):
        # Fri 16 Oct 2026: NIFTY closes 10:00 UTC, the US cash session closes 20:00 UTC (EDT); Monday's call at 03:40 UTC
        hours = pd.date_range("2026-10-16 00:00", "2026-10-19 04:00", freq="h", tz="UTC")
        es = pd.Series(100.0, index=hours)
        es[es.index >= "2026-10-16 15:00"] = 101.0                       # +1% during the US session
        es[es.index >= "2026-10-18 23:00"] = 99.99                       # -1% after it (the weekend reaction)
        f = tc.overnight_features({"es": es}, date(2026, 10, 16), date(2026, 10, 19),
                                  pd.Timestamp("2026-10-19 03:40", tz="UTC"), 0.0)
        self.assertAlmostEqual(f["es_day"], 0.01, places=6)
        self.assertAlmostEqual(f["es_night"], -0.01, places=6)
        self.assertAlmostEqual((1 + f["es_day"]) * (1 + f["es_night"]) - 1, f["es"], places=9)
        self.assertEqual((f["nq_day"], f["nq_night"]), (0.0, 0.0))     # input missing: no signal, not an error
        self.assertEqual(tc.us_close(date(2026, 12, 4)).hour, 21)        # EST in winter


class BandAccuracy(unittest.TestCase):
    def test_small_moves_are_scored_on_their_own(self):
        row = {0.0: {"accuracy": 0.76, "share": 1.0}, 0.0025: {"accuracy": 0.90, "share": 0.6},
               0.005: {"accuracy": 0.96, "share": 0.38}, 0.01: {"accuracy": 0.99, "share": 0.1}}
        self.assertAlmostEqual(tc.band_accuracy(row, 0.0), (0.76 - 0.90 * 0.6) / 0.4, places=3)   # 0.55, not 0.76
        self.assertEqual(tc.band_accuracy(row, 0.01), 0.99)                                       # top bucket


if __name__ == "__main__":
    unittest.main()
