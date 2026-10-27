"""The live chart: 10-minute candles, big moves, the scorecard and Grok's budget (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import grok  # noqa: E402
import live  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def bars(closes, start=(9, 15)):
    """5-minute candles from 09:15 IST with these closes (open = previous close)."""
    t0 = datetime(2026, 10, 27, *start, tzinfo=IST)
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        out.append((t0 + timedelta(minutes=5 * k), prev, max(prev, c) + 1, min(prev, c) - 1, c))
        prev = c
    return out


class Candles(unittest.TestCase):
    def test_two_5_minute_candles_make_one_10_minute_candle(self):
        c = live.candles10(bars([100.0, 102.0, 101.0, 99.0]))
        self.assertEqual(len(c), 2)
        self.assertEqual((c[0]["open"], c[0]["high"], c[0]["low"], c[0]["close"]), (100.0, 103.0, 99.0, 102.0))
        self.assertEqual(c[1]["time"] - c[0]["time"], 600)
        self.assertEqual(datetime.utcfromtimestamp(c[0]["time"]).strftime("%H:%M"), "09:15")   # IST clock time


class Moves(unittest.TestCase):
    def test_a_drop_of_0_4_pct_in_20_minutes_is_found_once(self):
        closes = [22800.0] * 6 + [22780.0, 22740.0, 22700.0, 22690.0, 22680.0, 22670.0]
        m = live.find_moves(bars(closes))
        self.assertEqual([x["dir"] for x in m], ["down"])                      # not again within 30 minutes
        self.assertLessEqual(m[0]["pct"], -0.4)

    def test_small_wiggles_are_not_moves(self):
        self.assertEqual(live.find_moves(bars([22800.0, 22830.0, 22790.0, 22820.0, 22800.0] * 3)), [])

    def test_known_moves_are_kept(self):
        closes = [22800.0] * 6 + [22700.0] * 4
        first = live.find_moves(bars(closes))
        self.assertEqual(live.find_moves(bars(closes), first), first)


class Scorecard(unittest.TestCase):
    def test_right_side_since_and_the_call(self):
        preds = [{"at": "2026-10-27T09:25+05:30", "pred": 22700.0}, {"at": "2026-10-27T11:05+05:30", "pred": 22780.0},
                 {"at": "2026-10-27T13:05+05:30", "pred": 22770.0}]
        c = live.scorecard(preds, 22753.2, 22749.75 + 50, call_pct=-0.116)
        self.assertEqual(c["right_side_since"], "2026-10-27T11:05+05:30")
        self.assertFalse(c["call_right"])
        self.assertEqual(c["runs"], 3)


class Budget(unittest.TestCase):
    def test_stops_at_the_daily_cap_and_needs_the_key(self):
        st = {"grok_calls": grok.DAILY_CAP}
        with mock.patch.object(grok, "ask") as a:
            self.assertIsNone(grok.Budget(st).ask("x"))
        a.assert_not_called()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(grok.ask("x"))

    def test_json_from_an_answer(self):
        self.assertEqual(grok.json_from('Sure: {"score": -1, "reasons": ["a"]} ok'), {"score": -1, "reasons": ["a"]})
        self.assertIsNone(grok.json_from("no json"))


class Main(unittest.TestCase):
    def setUp(self):
        self.dd, self.store = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.today = {"date": "2026-10-27", "status": "open",
                      "preopen": {"prev_close": 22753.2, "moves_pct": {}, "close": {"direction": "down", "pred_pct": -0.1},
                                  "recorded": {"made_at": "08:57", "close": {"direction": "down", "pred_pct": -0.116},
                                               "from_open": {"direction": "down", "trade": True}}},
                      "intraday": {"price": 22700.0, "move_pct": -0.23, "open": 22760.0, "direction": "down"},
                      "record": {"recent": []}}
        json.dump(self.today, open(os.path.join(self.dd, "today-nifty.json"), "w"))
        json.dump({"pred_close": 22690.0, "p10": 22600.0, "p90": 22780.0}, open(os.path.join(self.dd, "intraday-nifty.json"), "w"))

    def run_at(self, mode, h, m, closes=None, grok_answer="Oil fell on reports of a ceasefire."):
        with mock.patch.object(grok, "ask", return_value=grok_answer) as a, \
                mock.patch("status.notify", return_value={"telegram": "sent"}) as n:
            out = live.main(self.dd, self.store, mode, datetime(2026, 10, 27, h, m, tzinfo=IST),
                            get_bars=lambda: bars(closes or [22760.0, 22750.0]))
        return out, a, n

    def test_morning_read_once(self):
        ans = '{"score": -1, "reasons": ["Infosys fell", "oil up", "weak Asia"], "big_event": false, "event": ""}'
        out, a, _ = self.run_at("morning", 8, 50, grok_answer=ans)
        self.assertEqual((out["morning"]["score"], len(out["morning"]["reasons"])), (-1, 3))
        _, a2, _ = self.run_at("morning", 8, 57, grok_answer=ans)
        a2.assert_not_called()

    def test_run_adds_a_prediction_candles_trade_lines_and_a_move_alert(self):
        closes = [22760.0] * 6 + [22740.0, 22700.0, 22660.0, 22650.0]               # 09:15-10:05, then a drop
        out, a, n = self.run_at("run", 10, 5, closes)
        self.assertEqual(out["preds"][-1]["pred"], 22690.0)
        self.assertEqual(len(out["candles"]), 5)
        self.assertEqual(out["trade"], {"side": "PUT", "entry": 22760.0, "stop": 22873.8})
        self.assertEqual(out["call"]["target"], round(22753.2 * (1 - 0.116 / 100), 2))
        self.assertEqual(len(out["moves"]), 1)
        self.assertIn("Why (Grok): Oil fell", n.call_args.args[0]["body"])
        _, _, n2 = self.run_at("run", 10, 15, closes)                                # the same move is not sent again
        n2.assert_not_called()

    def test_old_moves_on_a_first_run_are_kept_but_not_alerted(self):
        closes = [22760.0] * 6 + [22740.0, 22700.0, 22660.0, 22650.0]
        out, a, n = self.run_at("run", 13, 0, closes)
        self.assertEqual(len(out["moves"]), 1)
        n.assert_not_called()
        a.assert_not_called()

    def test_no_session_no_file(self):
        self.today["date"] = "2026-10-26"
        json.dump(self.today, open(os.path.join(self.dd, "today-nifty.json"), "w"))
        self.assertIsNone(self.run_at("run", 10, 5)[0])


if __name__ == "__main__":
    unittest.main()
