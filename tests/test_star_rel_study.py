import unittest

import pandas as pd

import star_rel_study as rel
import star_streak_study as st

B, A, PREM = 0.5, 0.0, 0.01


class Rules(unittest.TestCase):
    def test_ratio_judges_the_move_against_the_usual_one(self):
        rows = {0: (True, 30.0, 1, 0.0, 25000.0, 28.0),          # 30 pts, usual 28: 1.07x
                1: (False, 0.0, 1, 0.0, 25000.0, 20.0), 2: (False, 0.0, 1, 0.0, 25000.0, 20.0), 3: (False, 0.0, 1, 0.0, 25000.0, 20.0),
                4: (True, 22.0, 1, 0.0, 25000.0, 15.0)}          # 22 pts, usual 15: 1.47x
        pick = lambda r: [x[0] for x in st.day_picks(rows, r, B, A, PREM)]
        self.assertEqual(pick({}), [0])                          # 25 points: only the first
        self.assertEqual(pick({"min_ratio": 1.0}), [0, 4])
        self.assertEqual(pick({"min_ratio": 1.4}), [4])

    def test_late_buys_the_15_05_lean_and_sells_at_15_15(self):
        rows = {k: (k == 34, 30.0, 1, 0.001, 25000.0, 20.0) for k in range(35)}
        self.assertEqual(st.day_picks(rows, {}, B, A, PREM), [])
        self.assertEqual([x[:2] for x in st.day_picks(rows, {"last_entry_k": 34}, B, A, PREM)], [(34, 34)])

    def test_years_without_picks_do_not_count(self):
        years = pd.Series([2017, 2018, 2024, 2025, 2026])
        base = pd.Series([0.0, 0.0, -10.0, -10.0, -10.0])
        x = pd.Series([0.0, 0.0, 5.0, 5.0, -20.0])
        r = rel.compare(x, base, years)
        self.assertEqual(r["years_better_with_picks"], "2/3")
        self.assertFalse(r["passes"])                            # 2 of 3 is under 70%


if __name__ == "__main__":
    unittest.main()
