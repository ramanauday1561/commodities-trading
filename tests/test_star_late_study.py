import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import star_late_study as sl  # noqa: E402


class StarLateTest(unittest.TestCase):
    def test_cut_from_the_1445_lean(self):
        self.assertFalse(sl.late(at="14:35"))
        self.assertTrue(sl.late(at="14:45"))
        self.assertTrue(sl.late(at="14:55"))
        self.assertFalse(sl.late(k=31))                                  # 14:35
        self.assertTrue(sl.late(k=32))                                   # 14:45


if __name__ == "__main__":
    unittest.main()
