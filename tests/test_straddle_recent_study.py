"""The 50%-stop short straddle since 2022: the rule and the 5-minutes-late seller (no network)."""
import os
import sys
import unittest
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import straddle_recent_study as sr  # noqa: E402


def rows(pts, stopped=0, dte=1, start=date(2022, 1, 3), n=600):
    d = [start + timedelta(days=k) for k in range(n)]
    return pd.DataFrame({"d": d, "pts": pts, "stopped": stopped, "dte": dte, "margin": 240000.0})


class Rule(unittest.TestCase):

    def test_a_steady_earner_passes_and_hard_costs_can_fail_it(self):
        out = sr.judge(rows(10.0))
        self.assertTrue(out["passes"])
        self.assertEqual(out["hard_costs_avg_pts"], 10.0 - 2 * 1.85)                 # no stops: only the doubled costs
        thin = sr.judge(rows(5.0, stopped=1))                                        # 5 - 3.70 - 3 points of slippage
        self.assertEqual(thin["hard_costs_avg_pts"], -1.7)
        self.assertFalse(thin["rule"]["4 hard costs up, 4 of 5 years"])
        self.assertFalse(thin["passes"])

    def test_a_losing_year_or_expiry_days_only_fails(self):
        g = rows(10.0)
        g.loc[g["d"].map(lambda x: x.year) == 2023, "pts"] = -1.0
        self.assertFalse(sr.judge(g)["rule"]["1 every year up"])
        g = rows(-1.0)
        g.loc[::5, ["pts", "dte"]] = [100.0, 0]                                      # all the gain on expiry days
        out = sr.judge(g)
        self.assertGreater(out["avg_pts"], 0)
        self.assertFalse(out["rule"]["3 non-expiry days up"])
        big = rows(10.0)
        big.loc[300, "pts"] = -2000.0                                                # one day beyond 25% of the margin
        self.assertFalse(sr.judge(big)["rule"]["6 worst day and drawdown"])


class Late(unittest.TestCase):

    def test_sold_at_0920_stops_from_later_candles(self):
        def leg(typ, bars):
            return [{"datetime": f"2026-11-04 {t}", "expiry": "2026-11-09", "strike": "23750.0", "type": typ,
                     "high": str(h), "close": str(c)} for t, h, c in bars]
        c = leg("CE", [("09:15", 400, 100), ("09:20", 120, 110), ("15:25", 160, 150)])   # 09:15's own high is before the sale
        p = leg("PE", [("09:15", 90, 80), ("09:20", 85, 70), ("15:25", 60, 20)])
        self.assertEqual(sr.late_seller(c + p, 23750, "2026-11-09"), round((-50 - 2) + (80 - 20) - 2 * 1.85, 2))
        self.assertIsNone(sr.late_seller(c, 23750, "2026-11-09"))                    # no PUT candles


if __name__ == "__main__":
    unittest.main()
