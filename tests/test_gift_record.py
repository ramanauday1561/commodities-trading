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


class Gap(unittest.TestCase):
    def test_gap_after_the_premium_at_yesterdays_close(self):
        # 28 Oct: NIFTY closed 22,698.85 and GIFT was 22,752 at 15:24, a +53.15 premium (the 15:04 row is too early)
        d, dd = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "gift"))
        with open(os.path.join(d, "gift", "2026-10.csv"), "w") as f:
            f.write(",".join(gr.COLS[:8]) + "\n")                                     # an old file without the gap columns
            f.write("2026-10-28T15:05+05:30,gift_nifty,28-Oct-2026 15:04,22700.0,0,0,1,23-Nov-2026\n")
            f.write("2026-10-28T15:25+05:30,gift_nifty,28-Oct-2026 15:24,22752.0,0,0,1,23-Nov-2026\n")
        import json
        json.dump({"date": "2026-10-29", "preopen": {"prev_close": 22698.85}}, open(os.path.join(dd, "today-nifty.json"), "w"))
        r = gr.record(d, datetime(2026, 10, 29, 8, 57, tzinfo=IST), get=lambda: ANSWER, data_dir=dd)[0]
        self.assertEqual(r["premium"], 53.15)
        self.assertAlmostEqual(r["gap_pct"], round(((22745 - 53.15) / 22698.85 - 1) * 100, 3))
        rows = list(csv.DictReader(open(os.path.join(d, "gift", "2026-10.csv"))))
        self.assertEqual(list(rows[0].keys()), gr.COLS)                                # the old file was upgraded
        self.assertEqual(json.load(open(os.path.join(dd, "gift-nifty.json")))["price"], 22745.0)

    def test_weekend_uses_the_last_close_and_skips_non_session_rows(self):
        # 31 Oct 2026 (Saturday): today's file has no previous close; NIFTY's last close comes from nifty.json, and the
        # Saturday 07:28 row is not a session, so the premium is Friday's (GIFT 23,087 at 15:25 vs NIFTY 23,053.10)
        import json
        d, dd = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "gift"))
        with open(os.path.join(d, "gift", "2026-10.csv"), "w") as f:
            f.write(",".join(gr.COLS) + "\n")
            f.write("2026-10-30T15:25+05:30,gift_nifty,30-Oct-2026 15:24,23087.0,0,0,1,23-Nov-2026,,,\n")
            f.write("2026-10-31T07:28+05:30,gift_nifty,31-Oct-2026 02:29,23242.5,0,0,1,23-Nov-2026,,,\n")
        json.dump({"date": "2026-10-31", "status": "holiday"}, open(os.path.join(dd, "today-nifty.json"), "w"))
        json.dump({"last_date": "2026-10-30", "last_close": 23053.1}, open(os.path.join(dd, "nifty.json"), "w"))
        self.assertEqual(gr.last_close_day(d, "2026-11-02"), "2026-10-30")
        answer = {"data": {"giftNifty": {**ANSWER["data"]["giftNifty"], "lastprice": 23242.5}}}
        r = gr.record(d, datetime(2026, 11, 1, 10, 0, tzinfo=IST), get=lambda: answer, data_dir=dd)[0]
        self.assertEqual((r["nifty_prev_close"], r["premium"]), (23053.1, 33.9))
        self.assertAlmostEqual(r["gap_pct"], round(((23242.5 - 33.9) / 23053.1 - 1) * 100, 3))
        json.dump({"last_date": "2026-10-29", "last_close": 22936.75}, open(os.path.join(dd, "nifty.json"), "w"))
        r = gr.record(d, datetime(2026, 11, 1, 10, 5, tzinfo=IST), get=lambda: answer, data_dir=dd)[0]
        self.assertIsNone(r["gap_pct"])                                                # a close of another day: no gap

    def test_no_recorded_premium_no_gap(self):
        d, dd = tempfile.mkdtemp(), tempfile.mkdtemp()
        import json
        json.dump({"date": "2026-10-29", "preopen": {"prev_close": 22698.85}}, open(os.path.join(dd, "today-nifty.json"), "w"))
        r = gr.record(d, datetime(2026, 10, 29, 8, 57, tzinfo=IST), get=lambda: ANSWER, data_dir=dd)[0]
        self.assertEqual((r["nifty_prev_close"], r["premium"], r["gap_pct"]), (22698.85, None, None))


if __name__ == "__main__":
    unittest.main()
