"""star_stop_study.py: the stop priced inside each 5-minute candle (no network)."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import star_stop_study as ss  # noqa: E402


def bars(rows, day="2026-11-20", start="09:35"):
    idx = pd.date_range(f"{day} {start}", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


class Path(unittest.TestCase):
    def test_dip_inside_a_candle_hits_the_stop_then_the_rally_does_not_count(self):
        # 20 Nov 2026, roughly: NIFTY dips 30 points inside the first candle, then rises 70 (CALL, entry 25463)
        w = bars([(25463, 25470, 25433, 25460), (25460, 25500, 25455, 25495), (25495, 25540, 25490, 25535)])
        prem = 125.0
        tight = ss.path_pick(25463, 1, w, prem, 0.57, 0.0, 0.10)          # 0.57 x -30 = -17.1 < -12.5: stopped
        self.assertAlmostEqual(tight, -12.5)
        wide = ss.path_pick(25463, 1, w, prem, 0.57, 0.0, 0.20)           # -17.1 > -25: held to the close
        self.assertAlmostEqual(wide, 0.57 * (25535 - 25463))
        self.assertAlmostEqual(ss.path_pick(25463, 1, w, prem, 0.57, 0.0, None), wide)

    def test_put_uses_the_high_and_a_gap_past_the_stop_sells_at_the_open(self):
        w = bars([(25500, 25510, 25490, 25505), (25560, 25570, 25550, 25565)])
        # PUT from 25500: the second candle opens 60 points against, past a 10% stop of a 100 premium
        got = ss.path_pick(25500, -1, w, 100.0, 0.5, 0.0, 0.10)
        self.assertAlmostEqual(got, 0.5 * (25500 - 25560))                 # -30, worse than the -10 stop

    def test_bars_after_cut_at_15_15(self):
        day = bars([(1, 1, 1, 1)] * 75, start="09:15")
        w = ss.bars_after(day, 33)                                         # the 14:55 lean: 14:55 .. 15:10
        self.assertEqual([t.strftime("%H:%M") for t in w.index], ["14:55", "15:00", "15:05", "15:10"])
        self.assertEqual(len(ss.bars_after(day, 0)), 6)                    # the 09:25 lean: 30 minutes


class Real(unittest.TestCase):
    def test_real_pick_stop_and_time(self):
        rows = []
        for t, o, h, lo, c in (("09:35", 125.45, 134.3, 109.8, 116.5), ("09:40", 116.5, 139.2, 110.4, 132.4),
                               ("09:45", 132.1, 154.75, 125.1, 144.75), ("09:50", 144.05, 163.5, 138.35, 161.75),
                               ("09:55", 162.25, 168.0, 151.75, 155.9), ("10:00", 157.3, 168.6, 142.05, 147.1)):
            rows.append({"datetime": f"2026-11-20 {t}", "expiry": "2026-11-23", "type": "CE", "strike": "25450.0",
                         "open": o, "high": h, "low": lo, "close": c})
        stopped = ss.real_pick(rows, "2026-11-20", "09:35", "up", 25463.4, 0.10)
        self.assertEqual(stopped["rs"], round((125.45 * 0.9 - 125.45) * 65 - 120))
        held = ss.real_pick(rows, "2026-11-20", "09:35", "up", 25463.4, 0.15)
        self.assertEqual(held["rs"], round((147.1 - 125.45) * 65 - 120))


if __name__ == "__main__":
    unittest.main()
