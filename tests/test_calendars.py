"""Trading-day calendars (holidays skipped, weekday fallback)."""
import os
import sys
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import calendars  # noqa: E402
from evalutil import expected_last_session  # noqa: E402

HAVE = calendars.xc is not None


class Calendars(unittest.TestCase):
    def test_weekday_fallback_without_a_calendar(self):
        self.assertEqual(calendars.next_sessions(date(2026, 10, 16), 2, None), [date(2026, 10, 19), date(2026, 10, 20)])
        self.assertEqual(calendars.previous_session(date(2026, 10, 19), None), date(2026, 10, 16))

    @unittest.skipUnless(HAVE, "exchange_calendars not installed")
    def test_nse_holiday_is_skipped(self):
        # 20 Oct 2026 (Dussehra) is an NSE/BSE holiday
        self.assertEqual(calendars.next_sessions(date(2026, 10, 16), 2, "XBOM"), [date(2026, 10, 19), date(2026, 10, 21)])
        self.assertEqual(calendars.previous_session(date(2026, 10, 21), "XBOM"), date(2026, 10, 19))
        on_holiday = datetime(2026, 10, 20, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.assertEqual(expected_last_session(on_holiday, 15, 30, "XBOM"), date(2026, 10, 19))

    @unittest.skipUnless(HAVE, "exchange_calendars not installed")
    def test_us_thanksgiving_is_skipped_for_futures(self):
        self.assertEqual(calendars.next_sessions(date(2026, 11, 25), 1, "XNYS"), [date(2026, 11, 27)])

    @unittest.skipUnless(HAVE, "exchange_calendars not installed")
    def test_far_future_falls_back_to_weekdays(self):
        self.assertEqual(calendars.next_sessions(date(2035, 12, 21), 1, "XBOM"), [date(2035, 12, 24)])

    def test_expected_session_before_and_after_close(self):
        ist = ZoneInfo("Asia/Kolkata")
        self.assertEqual(expected_last_session(datetime(2026, 10, 13, 10, 0, tzinfo=ist), 15, 30), date(2026, 10, 12))
        self.assertEqual(expected_last_session(datetime(2026, 10, 13, 16, 0, tzinfo=ist), 15, 30), date(2026, 10, 13))
        self.assertEqual(expected_last_session(datetime(2026, 10, 12, 9, 0, tzinfo=ist), 15, 30), date(2026, 10, 9))


if __name__ == "__main__":
    unittest.main()
