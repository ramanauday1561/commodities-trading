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
