import unittest

import star_rules_study as sr


def bar(t, o, h, l, c, strike=25250.0, typ="PE", exp="2026-11-17"):
    return {"datetime": f"2026-11-12 {t}", "tradingsymbol": "X", "expiry": exp, "strike": str(strike), "type": typ,
            "open": str(o), "high": str(h), "low": str(l), "close": str(c)}


class RealPick(unittest.TestCase):
    rows = [bar("09:35", 200, 205, 196, 198), bar("09:40", 198, 199, 185, 186), bar("09:45", 186, 190, 170, 172),
            bar("09:50", 172, 180, 171, 179), bar("09:55", 179, 190, 178, 188), bar("10:00", 188, 195, 187, 194),
            bar("09:35", 50, 50, 50, 50, strike=25300.0)]

    def test_the_10_percent_stop_sells_at_the_stop(self):
        r = sr.real_pick(self.rows, "2026-11-12", "09:35", "down", 25262, 0.10)
        self.assertEqual(r["entry"], 200.0)
        self.assertEqual(r["rs"], round((180 - 200) * 65 - 120))

    def test_without_a_stop_it_is_sold_after_30_minutes(self):
        self.assertEqual(sr.real_pick(self.rows, "2026-11-12", "09:35", "down", 25262, None)["rs"], round((194 - 200) * 65 - 120))

    def test_a_25_percent_stop_is_not_reached(self):
        self.assertEqual(sr.real_pick(self.rows, "2026-11-12", "09:35", "down", 25262, 0.25)["rs"], round((194 - 200) * 65 - 120))

    def test_no_candles_for_a_call_is_no_trade(self):
        self.assertIsNone(sr.real_pick(self.rows, "2026-11-12", "09:35", "up", 25262, 0.10))


class Times(unittest.TestCase):
    def test_row_k_makes_the_lean_for_09_25_plus_10k(self):
        self.assertEqual([sr.hhmm(k) for k in (0, 3, 16, 28, 34)], ["09:25", "09:55", "12:05", "14:05", "15:05"])


if __name__ == "__main__":
    unittest.main()
