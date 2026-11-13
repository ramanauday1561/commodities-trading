import unittest

import star_target_study as st


def b(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


class Rules(unittest.TestCase):
    up = [b(100, 104, 99, 103), b(103, 112, 102, 111), b(111, 118, 110, 117), b(117, 119, 106, 107), b(107, 108, 101, 102), b(102, 104, 100, 103)]

    def rs(self, x):
        return round(x * 65 - 120)

    def test_today_holds_30_minutes(self):
        self.assertEqual(st.run_rule(self.up, {}), self.rs(103 - 100))

    def test_a_target_sells_at_the_target(self):
        self.assertEqual(st.run_rule(self.up, {"target": 0.10}), self.rs(110 - 100))
        self.assertEqual(st.run_rule(self.up, {"target": 0.30}), self.rs(103 - 100))

    def test_trailing_stop_follows_the_high(self):                 # high 118 -> stop 106.2, hit by the next candle's low
        self.assertEqual(st.run_rule(self.up, {"trail": 0.10}), self.rs(106.2 - 100))

    def test_breakeven_after_10_percent(self):
        down_after = self.up[:2] + [b(111, 111, 98, 99)] + self.up[3:]
        self.assertEqual(st.run_rule(down_after, {"breakeven": 0.10}), self.rs(0))
        self.assertEqual(st.run_rule(down_after, {}), self.rs(103 - 100))

    def test_a_candle_with_both_counts_as_the_stop(self):
        both = [b(100, 120, 89, 95)] + self.up[1:]
        self.assertEqual(st.run_rule(both, {"target": 0.10}), self.rs(90 - 100))


if __name__ == "__main__":
    unittest.main()
