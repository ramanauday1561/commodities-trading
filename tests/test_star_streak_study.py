import unittest

import star_streak_study as st

B, A, PREM = 0.5, 0.0, 0.01          # option = half NIFTY's move; premium 1% of NIFTY (250 points at 25,000)


def day(stars, ys, size=30.0, side=1, price=25000.0):
    """rows k = 0..len(ys)-1; stars: the rows with a * lean."""
    return {k: (k in stars, size, side, y, price) for k, y in enumerate(ys)}


class DayPicks(unittest.TestCase):
    def test_today_holds_30_minutes_and_skips_leans_while_open(self):
        rows = day({0, 1, 2}, [0.001] * 10)
        p = st.day_picks(rows, {}, B, A, PREM)
        self.assertEqual([(k0, k1) for k0, k1, _ in p], [(0, 2)])     # 1 and 2 skipped: the pick is open

    def test_extend_keeps_the_pick_30_minutes_from_each_same_side_lean(self):
        rows = day({0, 1, 2}, [0.001] * 10)
        p = st.day_picks(rows, {"extend": True}, B, A, PREM)
        self.assertEqual([(k0, k1) for k0, k1, _ in p], [(0, 4)])     # out 30 minutes after the 3rd lean
        move = (1.001 ** 5 - 1) * 25000
        self.assertAlmostEqual(p[0][2], (B * move - st.COST) * st.LOT, places=6)

    def test_extend_ignores_the_other_side_and_small_leans(self):
        rows = day({0, 1, 2}, [0.001] * 10)
        rows[1] = (True, 30.0, -1, 0.001, 25000.0)                    # a * lean the other way
        rows[2] = (True, 10.0, 1, 0.001, 25000.0)                     # same way, but under 25 points
        p = st.day_picks(rows, {"extend": True}, B, A, PREM)
        self.assertEqual([(k0, k1) for k0, k1, _ in p], [(0, 2)])

    def test_stop_is_booked_at_the_close_it_is_seen_at(self):
        rows = day({0}, [-0.004, 0.01, 0.01])                          # -50 option pts, past the 25-point stop
        p = st.day_picks(rows, {}, B, A, PREM)
        self.assertEqual(p[0][:2], (0, 0))
        self.assertAlmostEqual(p[0][2], (B * -0.004 * 25000 - st.COST) * st.LOT, places=6)

    def test_skip_early_and_the_size_filter(self):
        rows = day({1, 5}, [0.0] * 10)
        self.assertEqual([x[0] for x in st.day_picks(rows, {}, B, A, PREM)], [1, 5])
        self.assertEqual([x[0] for x in st.day_picks(rows, {"skip_early": True}, B, A, PREM)], [5])
        self.assertEqual(st.day_picks(day({1}, [0.0] * 5, size=20.0), {}, B, A, PREM), [])

    def test_no_new_pick_after_15_00_and_out_by_15_15(self):
        rows = day({33, 34}, [0.0] * 35)
        p = st.day_picks(rows, {"extend": True}, B, A, PREM)
        self.assertEqual([(k0, k1) for k0, k1, _ in p], [(33, 34)])    # the 14:55 pick, out at 15:15


if __name__ == "__main__":
    unittest.main()
