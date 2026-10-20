"""Unit tests for the statistics code. Run: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import blend  # noqa: E402
import evalutil  # noqa: E402
import scoreboard  # noqa: E402


def make_rows(rng, n_days, preds):
    """Backtest rows (day index, prev close, actual close, predicted close) for several fake models."""
    t = np.sort(rng.choice(np.arange(600, 3000), n_days, replace=False))
    prev = 1000 + rng.normal(0, 30, n_days)
    true = rng.normal(0, 0.008, n_days)
    actual = prev * (1 + true)
    return {k: np.column_stack([t, prev, actual, f(prev, true, rng)]) for k, f in preds.items()}


class EvalUtil(unittest.TestCase):
    def test_no_change_forecast_counts_as_coin_flip(self):
        rows = np.array([[0, 100, 101, 100], [1, 100, 99, 100]], float)
        self.assertEqual(evalutil.summarize(rows)["direction_accuracy"], 0.5)

    def test_indices_cover_history_and_recent(self):
        idx = evalutil.backtest_indices(3000, 512)
        self.assertGreaterEqual(min(idx), 512)
        self.assertIn(2999, idx)
        self.assertIsNone(evalutil.backtest_indices(300, 512))


class FreshnessAndStale(unittest.TestCase):
    def test_expected_last_session(self):
        from datetime import datetime
        # Monday 12 Oct 2026, after the 15:30 close -> Monday itself; before the close -> the previous Friday
        self.assertEqual(evalutil.expected_last_session(datetime(2026, 10, 12, 16, 0), 15, 30).isoformat(), "2026-10-12")
        self.assertEqual(evalutil.expected_last_session(datetime(2026, 10, 12, 9, 0), 15, 30).isoformat(), "2026-10-09")
        self.assertEqual(evalutil.expected_last_session(datetime(2026, 10, 10, 12, 0), 15, 30).isoformat(), "2026-10-09")  # Saturday

    def test_stale_data_is_not_scored(self):
        d = {"updated": "2026-10-13T00:12:00+00:00", "last_close": 100.0, "candles": [],
             "data_check": {"stale": True}, "models": {"base": {"forecast": [{"time": "2026-10-12", "close": 101.0}]}}}
        self.assertEqual(scoreboard.update_records([], d), [])


class Blend(unittest.TestCase):
    index = pd.bdate_range("2012-01-01", periods=3000)

    def test_useful_model_gets_the_weight(self):
        rng = np.random.default_rng(0)
        rows = make_rows(rng, 150, {"good": lambda p, t, r: p * (1 + 0.5 * t + r.normal(0, 0.004, len(p))),
                                    "noise": lambda p, t, r: p * (1 + r.normal(0, 0.02, len(p)))})
        fit = blend.fit_blend(rows, 3000, self.index)
        self.assertGreater(fit["weights"]["good"], 0.8)
        self.assertLess(fit["weights"]["noise"], 0.2)
        a = fit["stats"]["all"]
        self.assertGreater(a["direction_accuracy"], a["up_rate"] + 0.15)       # out-of-fold, still clearly better

    def test_noise_only_falls_back_to_no_change(self):
        rng = np.random.default_rng(1)
        rows = make_rows(rng, 150, {"a": lambda p, t, r: p * (1 + r.normal(0, 0.02, len(p))),
                                    "b": lambda p, t, r: p * (1 + r.normal(0, 0.02, len(p)))})
        fit = blend.fit_blend(rows, 3000, self.index)
        self.assertGreater(fit["naive_weight"], 0.85)
        self.assertLess(fit["stats"]["all"]["mape_pct"], fit["stats"]["all"]["naive_mape_pct"] * 1.1)

    def test_weights_never_exceed_one(self):
        rng = np.random.default_rng(2)
        rows = make_rows(rng, 150, {"a": lambda p, t, r: p * (1 + 0.2 * t), "b": lambda p, t, r: p * (1 + 0.2 * t)})
        fit = blend.fit_blend(rows, 3000, self.index)
        self.assertLessEqual(sum(fit["weights"].values()), 1.0 + 1e-9)

    def test_bagged_weights_are_stable_across_samples(self):
        rng = np.random.default_rng(7)
        pop = make_rows(rng, 600, {"weak": lambda p, t, r: p * (1 + 0.15 * t + r.normal(0, 0.006, len(p))),
                                   "noise": lambda p, t, r: p * (1 + r.normal(0, 0.02, len(p)))})
        ws = []
        for lo in (0, 150, 300, 450):                        # four disjoint samples of the same population
            sub = {k: v[lo:lo + 150] for k, v in pop.items()}
            ws.append(blend.fit_blend(sub, 3000, self.index)["weights"]["weak"])
        self.assertLess(max(ws) - min(ws), 0.35)

    def test_too_little_overlap_returns_none(self):
        rng = np.random.default_rng(3)
        rows = make_rows(rng, 20, {"a": lambda p, t, r: p, "b": lambda p, t, r: p})
        self.assertIsNone(blend.fit_blend(rows, 3000, self.index))

    def test_platt_is_calibrated_and_not_overconfident(self):
        rng = np.random.default_rng(4)
        s = rng.normal(0, 0.01, 500)
        y = rng.random(500) < 0.5                       # the signal is useless
        cal = blend.platt_fit(s, y)
        self.assertLess(abs(blend.platt_prob(cal, 0.05) - 0.5), 0.15)
        s2 = rng.normal(0, 0.01, 2000)
        y2 = rng.random(2000) < 1 / (1 + np.exp(-s2 / 0.01))   # a real signal
        cal2 = blend.platt_fit(s2, y2)
        self.assertGreater(blend.platt_prob(cal2, 0.01), blend.platt_prob(cal2, -0.01))


class Scoreboard(unittest.TestCase):
    def test_forecasts_are_scored_once_the_close_is_known(self):
        data = {"updated": "2026-10-12T04:00:00+00:00", "last_close": 100.0,
                "models": {"base": {"forecast": [{"time": "2026-10-13", "close": 101.0}]},
                           "blend": {"forecast": [{"time": "2026-10-13", "close": 100.0}]}},
                "candles": [{"time": "2026-10-12", "close": 100.0}]}
        recs = scoreboard.update_records([], data)
        self.assertEqual(len(recs), 2)
        self.assertTrue(all("a" not in r for r in recs))
        data2 = dict(data, candles=data["candles"] + [{"time": "2026-10-13", "close": 99.0}])
        recs = scoreboard.update_records(recs, data2)
        self.assertTrue(all(r["a"] == 99.0 for r in recs))
        b = scoreboard.board(recs)
        self.assertEqual(b["models"]["base"]["all"]["days"], 1)
        self.assertEqual(b["models"]["blend"]["all"]["direction_accuracy"], 0.5)   # "no change" is not a directional call

    def test_settlement_revisions_are_picked_up(self):
        d = {"updated": "2026-10-12T04:00:00+00:00", "last_close": 91.85,
             "models": {"gbm": {"forecast": [{"time": "2026-10-12", "close": 91.9}]}},
             "candles": [{"time": "2026-10-09", "close": 91.85}, {"time": "2026-10-12", "close": 93.16}]}
        recs = scoreboard.update_records([], d)
        self.assertEqual((recs[0]["l"], recs[0]["a"]), (91.85, 93.16))
        later = dict(d, models={}, candles=[{"time": "2026-10-09", "close": 91.8}, {"time": "2026-10-12", "close": 93.74}])
        recs = scoreboard.update_records(recs, later)                 # Yahoo replaced last trade with settlement
        self.assertEqual((recs[0]["l"], recs[0]["a"]), (91.8, 93.74))

    def test_forecast_made_before_a_roll_is_scored_on_its_move(self):
        # 19 Oct 2026: forecast on the November WTI contract (103.66); the page then rescales history to December (-5.2%)
        d = {"updated": "2026-10-19T23:00:00+00:00", "last_close": 103.66,
             "models": {"gbm": {"forecast": [{"time": "2026-10-20", "close": 103.65}]}},
             "candles": [{"time": "2026-10-19", "close": 103.66}]}
        recs = scoreboard.update_records([], d)
        later = dict(d, models={}, candles=[{"time": "2026-10-19", "close": 98.24}, {"time": "2026-10-20", "close": 96.09}])
        recs = scoreboard.update_records(recs, later)
        self.assertAlmostEqual(recs[0]["p"], 98.24 * 103.65 / 103.66, places=2)
        self.assertEqual((recs[0]["l"], recs[0]["a"]), (98.24, 96.09))

    def test_old_records_without_a_move_are_migrated(self):
        old = [{"m": "gbm", "d": "2026-10-13", "f": "2026-10-12T04:00:00+00:00", "l": 100.0, "p": 101.0}]
        d = {"updated": "2026-10-14T04:00:00+00:00", "last_close": 50.0, "models": {},
             "candles": [{"time": "2026-10-12", "close": 50.0}, {"time": "2026-10-13", "close": 50.4}]}
        recs = scoreboard.update_records(old, d)                     # history halved by a roll since the forecast
        self.assertEqual((recs[0]["l"], recs[0]["p"], recs[0]["a"]), (50.0, 50.5, 50.4))

    def test_latest_forecast_for_a_day_replaces_the_earlier_one(self):
        d = {"updated": "2026-10-12T03:00:00+00:00", "last_close": 100.0, "candles": [],
             "models": {"base": {"forecast": [{"time": "2026-10-13", "close": 101.0}]}}}
        recs = scoreboard.update_records([], d)
        d2 = dict(d, updated="2026-10-12T10:00:00+00:00", models={"base": {"forecast": [{"time": "2026-10-13", "close": 102.0}]}})
        recs = scoreboard.update_records(recs, d2)
        self.assertEqual([(r["p"], r["f"]) for r in recs], [(102.0, "2026-10-12T10:00:00+00:00")])

    def test_main_writes_page_files(self):
        import json
        with tempfile.TemporaryDirectory() as store, tempfile.TemporaryDirectory() as data:
            d = {"updated": "2026-10-12T04:00:00+00:00", "last_close": 100.0, "candles": [{"time": "2026-10-12", "close": 100.0}],
                 "models": {"base": {"forecast": [{"time": "2026-10-13", "close": 101.0}]}}}
            json.dump(d, open(os.path.join(data, "nifty.json"), "w"))
            json.dump([], open(os.path.join(data, "index.json"), "w"))        # must be ignored
            scoreboard.main(store, data)
            self.assertTrue(os.path.exists(os.path.join(data, "scoreboard-nifty.json")))
            self.assertTrue(os.path.exists(os.path.join(store, "nifty.json")))
            self.assertFalse(os.path.exists(os.path.join(data, "scoreboard-index.json")))


if __name__ == "__main__":
    unittest.main()
