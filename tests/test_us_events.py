import os
import sys
import unittest
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import us_events as ue  # noqa: E402

PAGE = """<h4>2026 FOMC Meetings</h4><div>January</div><div>27-28</div> Statement: PDF | HTML
Minutes: (Released February 18, 2026) <div>March</div> <div>17-18*</div> <div>Apr/May</div><div>30-1</div>
<div>October</div><div>6</div> (unscheduled) <div>December</div><div>8-9*</div>
* Meeting associated with a Summary of Economic Projections. Note: A two-day meeting is scheduled for January 26-27, 2027.
<h4>2025 FOMC Meetings</h4> January 28-29 Statement"""


class Events(unittest.TestCase):
    def test_current_page(self):
        y = ue.parse_fomc_current(PAGE)
        self.assertEqual(y[2026], [date(2026, 1, 28), date(2026, 3, 18), date(2026, 5, 1), date(2026, 12, 9)])
        # unscheduled dropped; "January 26-27, 2027" in the note is not a 2026 meeting
        self.assertEqual(y[2025], [date(2025, 1, 29)])

    def test_historical_page(self):
        html = "January 29-30 Meeting - 2019 ... October 4 (unscheduled) Meeting - 2019 ... Apr/May 30-1 Meeting - 2019"
        self.assertEqual(ue.parse_fomc_historical(html, 2019), [date(2019, 1, 30), date(2019, 5, 1)])

    def test_timing(self):
        idx = pd.DatetimeIndex(["2026-10-13", "2026-10-14", "2026-10-15"])     # Tue, Wed, Thu sessions
        ev = {"cpi": [date(2026, 10, 14)], "fomc": [date(2026, 10, 14)]}
        nifty = ue.features(idx, date(2026, 10, 16), ev, "after_close")
        # NIFTY: CPI at 08:30 ET on 14 Oct arrives after NIFTY's 14 Oct close -> the move 14 Oct -> 15 Oct
        self.assertEqual(list(nifty["ev_cpi"]), [0.0, 1.0, 0.0])
        fut = ue.features(idx, date(2026, 10, 16), ev, "us_session")
        # futures: CPI lands before the 14 Oct settlement -> the move 13 Oct -> 14 Oct; the Fed (14:00 ET) after it
        self.assertEqual(list(fut["ev_cpi"]), [1.0, 0.0, 0.0])
        self.assertEqual(list(fut["ev_fomc"]), [0.0, 1.0, 0.0])
        self.assertEqual(list(fut["ev_any"]), [1.0, 1.0, 0.0])

    def test_no_events_no_columns(self):
        self.assertEqual(len(ue.features(pd.DatetimeIndex(["2026-10-13"]), date(2026, 10, 14), {}).columns), 0)


if __name__ == "__main__":
    unittest.main()
