import csv
import os
import tempfile
import unittest

import star_size_study as ss


class StrikeNumbers(unittest.TestCase):
    def test_otm_strike_is_one_step_out_and_moves_with_nifty(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "snapshots"))
            with open(os.path.join(d, "snapshots", "2026-11-16.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["at", "expiry", "strike", "type", "ltp", "spot"])
                w.writeheader()
                for i in range(120):                       # 10-minute runs; NIFTY steps 0, +10, 0, +10 ...
                    h, m = 9 + (15 + 10 * i) // 60, (15 + 10 * i) % 60
                    spot = 25000 + 10 * (i % 2)
                    for strike, typ, ltp in ((25000, "CE", 100 + 5 * (i % 2)), (25050, "CE", 60 + 3 * (i % 2)),
                                             (25000, "PE", 100 - 5 * (i % 2)), (24950, "PE", 60 - 3 * (i % 2))):
                        w.writerow({"at": f"{h:02d}:{m:02d}", "expiry": "2026-11-17", "strike": strike, "type": typ, "ltp": ltp, "spot": spot})
            atm, otm = ss.strike_numbers(d, 0), ss.strike_numbers(d, 1)
        self.assertAlmostEqual(atm["b"], 0.5, places=2)
        self.assertAlmostEqual(otm["b"], 0.3, places=2)
        self.assertLess(otm["prem_pct"], atm["prem_pct"])


if __name__ == "__main__":
    unittest.main()
