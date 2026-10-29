"""GIFT Nifty snapshots: reading NSE's answer and appending a row per run (no network)."""
import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gift_record as gr  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
ANSWER = {"data": {"usdInr": {"ltp": "95.5175", "instrument_type": "FUTCUR", "expiry_dt": "26-Nov-2026",
                              "timestamp": "28-Oct-2026 17:00"},
                   "giftNifty": {"instrumenttype": "FUTIDX", "symbol": "NIFTY", "expirydate": "23-Nov-2026",
                                 "lastprice": 22745, "daychange": -7, "perchange": -0.03, "contractstraded": 609,
                                 "timestmp": "29-Oct-2026 07:18"}}}


class Gift(unittest.TestCase):
    def test_rows_from_nse_answer(self):
        r = gr.rows(ANSWER, "2026-10-29T07:20+05:30")
        self.assertEqual([(x["kind"], x["price"]) for x in r], [("gift_nifty", 22745.0), ("usdinr_future", 95.5175)])
        self.assertEqual(r[0]["quote_time"], "29-Oct-2026 07:18")

    def test_appends_one_file_a_month_and_survives_failures(self):
        d = tempfile.mkdtemp()
        now = datetime(2026, 10, 29, 7, 20, tzinfo=IST)
        gr.record(d, now, get=lambda: ANSWER)
        gr.record(d, now, get=lambda: ANSWER)
        rows = list(csv.DictReader(open(os.path.join(d, "gift", "2026-10.csv"))))
        self.assertEqual(len(rows), 4)
        self.assertEqual(gr.record(d, now, get=lambda: (_ for _ in ()).throw(OSError("blocked"))), [])
        self.assertEqual(gr.record(d, now, get=lambda: {"data": {}}), [])


if __name__ == "__main__":
    unittest.main()
