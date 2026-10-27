"""The "₹2 lakh today" box: per-lot rupees for the app, following the AI and the intraday rules (no network)."""
import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import daymoney as dm  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def bars(closes):
    t0 = datetime(2026, 10, 27, 9, 15, tzinfo=IST)
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        out.append((t0 + timedelta(minutes=5 * k), prev, max(prev, c), min(prev, c), c))
        prev = c
    return out


class Money(unittest.TestCase):
    def test_following_the_ai_switches_and_pays_costs(self):
        steps = [{"ai_close": 101.0, "price": 100.0}, {"ai_close": None, "price": 99.0},
                 {"ai_close": 98.0, "price": 99.0}, {"ai_close": 97.0, "price": 98.0}]
        t = dm.follow_ai(steps, 100.0, 97.0)
        self.assertEqual(len(t), 2)                                       # long 100 -> 99, then short 99 -> 97
        self.assertAlmostEqual(t[0], -1.0 - dm.COST)
        self.assertAlmostEqual(t[1], (97 / 99 - 1) * -100 - dm.COST)

    def test_rows_per_lot_and_no_trade_for_the_app(self):
        b = bars([22800.0] * 75)
        m = dm.money(b, 22750.0, morning_side=-1, app_side=0, steps=[{"ai_close": 22900.0, "price": 22800.0}])
        self.assertEqual([r["key"] for r in m["rows"]],
                         ["app", "ai", "flip (27 Oct pattern)", "chase 0.25", "fade 0.25", "chase 0.25 + morning"])
        self.assertEqual((m["rows"][0]["rs"], m["rows"][0]["trades"]), (0, 0))
        ai = m["rows"][1]                                                 # one long trade, flat day: just the costs
        self.assertEqual((ai["trades"], ai["rs"]), (1, round(-dm.COST / 100 * 22800 * dm.LOT)))

    def test_the_app_trade_uses_its_stop(self):
        b = bars([22800.0] * 10 + [22600.0] * 65)                         # -0.88%: the 0.5% stop is hit on a long
        m = dm.money(b, 22750.0, morning_side=1, app_side=1)
        self.assertAlmostEqual(m["rows"][0]["rs"], round((-0.5 - dm.COST) / 100 * 22800 * dm.LOT), delta=1)
        self.assertIsNone(dm.money(bars([22800.0] * 20), 22750.0))         # too few candles


if __name__ == "__main__":
    unittest.main()
