"""Dukascopy hourly files: parsing, flat closed hours, resuming within a time budget (no network)."""
import os
import struct
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import overnight_data as od  # noqa: E402


def blob(rows):
    return b"".join(struct.pack(">5if", *r) for r in rows)


class Overnight(unittest.TestCase):
    def test_parse_drops_flat_closed_hours(self):
        raw = blob([(0, 5000000, 5001000, 4999000, 5002000, 10.0), (3600, 5001000, 5001000, 5001000, 5001000, 0.0),
                    (7200, 5001000, 5003000, 5000000, 5004000, 5.0)])
        rows = od.parse(raw, 2026, 10)
        self.assertEqual([(t.strftime("%m-%d %H:%M"), c) for t, c in rows], [("10-01 01:00", 5001.0), ("10-01 03:00", 5003.0)])

    def test_update_resumes_and_keeps_saved_months(self):
        d, calls = tempfile.mkdtemp(), []
        get = lambda sym, y, m: calls.append((y, m)) or ([] if (y, m) != (2015, 2) else None)
        od.update("es", d, 5, get=get, today=date(2015, 4, 10))
        self.assertEqual(sorted(os.listdir(os.path.join(d, "es"))), ["2015-01.csv", "2015-03.csv", "2015-04.csv"])
        calls.clear()
        od.update("es", d, 5, get=get, today=date(2015, 4, 10))
        self.assertEqual(calls, [(2015, 2), (2015, 4)])            # not published, and the current month again


if __name__ == "__main__":
    unittest.main()
