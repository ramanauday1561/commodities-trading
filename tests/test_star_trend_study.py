"""star_trend_study.py: which * leans bet against a trending day (no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import star_trend_study as st  # noqa: E402


class Against(unittest.TestCase):
    def test_rule(self):
        self.assertTrue(st.against(1, -0.012, 0.6, 10))      # 23 Nov: an up lean on a day falling steadily
        self.assertFalse(st.against(-1, -0.012, 0.6, 10))    # a down lean with that day: kept
        self.assertFalse(st.against(1, -0.012, 0.2, 10))     # choppy day (er under 0.4): kept
        self.assertFalse(st.against(1, -0.012, 0.9, 1))      # under 30 minutes in: kept
        self.assertFalse(st.against(1, 0.0, 0.9, 10))        # flat since the open: kept


if __name__ == "__main__":
    unittest.main()
