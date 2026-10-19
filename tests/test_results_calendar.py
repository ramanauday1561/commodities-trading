"""Heavyweight results calendar (no network: the dates are given)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import results_calendar as rc  # noqa: E402

CAL = {"HDFCBANK.NS": [date(2026, 10, 17)], "TCS.NS": [date(2026, 10, 8)], "RELIANCE.NS": [date(2026, 10, 21)]}


class Results(unittest.TestCase):
    def test_a_result_moves_the_first_session_after_it(self):
        self.assertEqual(rc.since(CAL, date(2026, 10, 16), date(2026, 10, 19)), ["HDFC Bank"])   # Saturday results
        self.assertEqual(rc.since(CAL, date(2026, 10, 19), date(2026, 10, 21)), [])              # dated 21: not yet
        self.assertEqual(rc.since(CAL, date(2026, 10, 21), date(2026, 10, 22)), ["Reliance"])

    def test_flags_and_upcoming(self):
        idx = pd.bdate_range("2026-10-07", "2026-10-23")
        idx = idx[idx != pd.Timestamp("2026-10-20")]                    # Dussehra
        hit = rc.flags(idx, CAL)
        self.assertEqual([d.isoformat() for d in hit[hit].index.date], ["2026-10-09", "2026-10-19", "2026-10-22"])
        self.assertEqual(rc.upcoming(CAL, date(2026, 10, 19)), [{"date": "2026-10-21", "name": "Reliance"}])

    def test_falls_back_to_the_cache_when_yahoo_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "results", "nifty.json")
            os.makedirs(os.path.dirname(path))
            json.dump({"HDFCBANK.NS": ["2026-10-17"]}, open(path, "w"))
            with mock.patch("yfinance.Ticker", side_effect=RuntimeError("blocked")):
                cal = rc.fetch(path)
            self.assertEqual(cal, {"HDFCBANK.NS": [date(2026, 10, 17)]})


if __name__ == "__main__":
    unittest.main()
