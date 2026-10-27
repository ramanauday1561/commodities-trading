"""Status page decisions and when an alert goes out (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import status  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def at(h, m, day=22):
    return datetime(2026, 10, day, h, m, tzinfo=IST)


def today(trade=True, direction="down", st="pre_open", skipped=False, recent=None, recorded="same"):
    """recorded: the from-open call saved before the open ("same" = as the live one, None = no call before the open)."""
    fo = {"direction": direction, "trade": trade, "skipped_for_results": skipped,
          "trade_stats": {"days": 80, "from_open": {"win_rate": 0.575, "avg_pct_after_costs": 0.151}}}
    pre = {"close": {"direction": direction, "tier": "lean"}, "from_open": fo}
    if recorded:
        pre["recorded"] = {"made_at": "08:57", "from_open": {"direction": direction, "trade": trade} if recorded == "same" else recorded}
    return {"date": "2026-10-22", "status": st, "record": {"recent": recent or []}, "preopen": pre}


class Decide(unittest.TestCase):
    def test_trade_day(self):
        self.assertEqual(status.decide(today(direction="down"), at(8, 58))["state"], "PUT")
        self.assertEqual(status.decide(today(direction="up"), at(9, 5))["state"], "CALL")
        s = status.decide(today(direction="up", st="open"), at(10, 0))
        self.assertEqual((s["state"], s["side"]), ("STAY", "CALL"))
        s = status.decide(today(st="open"), at(14, 50))
        self.assertEqual((s["state"], s["side"]), ("SELL", "PUT"))

    def test_no_trade_results_and_early(self):
        kinds = lambda s: (s["state"], s["kind"])
        self.assertEqual(kinds(status.decide(today(trade=False), at(8, 58))), ("NOTHING", "no_trade"))
        self.assertEqual(kinds(status.decide(today(skipped=True, trade=False), at(8, 58))), ("NOTHING", "no_trade"))
        self.assertEqual(kinds(status.decide(today(), at(6, 30))), ("NOTHING", "pending"))
        us = today(trade=False)
        us["preopen"]["from_open"].update({"skipped_for_us_events": True, "us_events": ["Fed decision 28 Oct"]})
        s = status.decide(us, at(8, 58))
        self.assertEqual(kinds(s), ("NOTHING", "no_trade"))
        self.assertIn("Fed decision 28 Oct", s["reason"])
        self.assertEqual(kinds(status.decide({"date": "2026-10-21", "status": "closed"}, at(9, 0))), ("NOTHING", "closed"))
        for h, m in ((6, 30), (8, 58), (10, 0), (14, 50), (16, 0)):
            self.assertIn(status.decide(today(st="open"), at(h, m))["state"], ("CALL", "PUT", "STAY", "SELL", "NOTHING"))

    def test_after_the_open_the_call_recorded_before_the_open_decides(self):
        # 23 Oct 2026: "no trade" at 08:57; a later recompute must not become a STAY for an option never bought
        later = today(trade=True, direction="down", st="open", recorded={"direction": "up", "trade": False})
        for h, m in ((9, 51), (12, 35), (14, 50)):
            self.assertEqual(status.decide(later, at(h, m))["kind"], "no_trade")
        # and a trade bought at the open is held even if a recompute drops below the top 20%
        held = today(trade=False, direction="up", st="open", recorded={"direction": "down", "trade": True})
        s = status.decide(held, at(10, 0))
        self.assertEqual((s["state"], s["side"]), ("STAY", "PUT"))
        self.assertEqual(status.decide(held, at(14, 50))["state"], "SELL")
        rec = [{"d": "2026-10-22", "open": 22742.2, "close": 22600.0}]
        self.assertIn("PUT won", status.decide(dict(held, status="closed", record={"recent": rec}), at(15, 50))["headline"])

    def test_no_call_before_the_open_means_nothing_to_hold(self):
        s = status.decide(today(st="open", recorded=None), at(10, 0))
        self.assertEqual((s["state"], s["kind"]), ("NOTHING", "no_trade"))
        self.assertEqual(status.decide(today(recorded=None), at(8, 58))["state"], "PUT")    # before the open: the live call

    def test_closed_reports_the_trade(self):
        rec = [{"d": "2026-10-22", "open": 22687.75, "close": 22600.0}]
        s = status.decide(today(st="closed", recent=rec), at(15, 50))
        self.assertEqual((s["state"], s["kind"]), ("NOTHING", "closed"))
        self.assertIn("won", s["headline"])


class Stop(unittest.TestCase):
    """0.5% against the trade from the open: SELL (kind "stop"), alerted once, reported at the close."""

    def put_day(self, high, low=22500.0, st="open", recent=None):
        d = today(direction="down", st=st, recent=recent)
        d["intraday"] = {"price": 22600.0, "move_pct": 0.1, "open": 22524.4, "high": high, "low": low}
        return d

    def test_levels(self):
        self.assertAlmostEqual(status.stop_level("PUT", 22524.4), 22637.022, places=3)
        self.assertAlmostEqual(status.stop_level("CALL", 22524.4), 22411.778, places=3)
        self.assertTrue(status.stop_hit("PUT", 22524.4, 22640.0, 22500.0))
        self.assertFalse(status.stop_hit("PUT", 22524.4, 22630.0, 22300.0))
        self.assertTrue(status.stop_hit("CALL", 22524.4, 22600.0, 22400.0))
        self.assertFalse(status.stop_hit("CALL", 22524.4, 22600.0, None))

    def test_stay_shows_the_level_then_the_stop_sells(self):
        s = status.decide(self.put_day(high=22600.0), at(9, 50))
        self.assertEqual(s["state"], "STAY")
        self.assertIn("sell if NIFTY goes above 22,637.02", s["reason"])
        s = status.decide(self.put_day(high=22650.0), at(10, 30))
        self.assertEqual((s["state"], s["kind"], s["side"]), ("SELL", "stop", "PUT"))
        self.assertIn("Stop hit", s["headline"])
        self.assertEqual(status.decide(self.put_day(high=22650.0), at(14, 50))["kind"], "stop")   # no second SELL

    def test_stop_is_alerted_once(self):
        u = Updates()
        alerts = lambda calls: [c.args[0]["kind"] for c in calls if c.args[0]["kind"] != "info"]
        s1, _ = u.run_at(self.put_day(high=22600.0), None, at(9, 50))
        s2, c2 = u.run_at(self.put_day(high=22650.0), s1, at(10, 30))
        s3, c3 = u.run_at(self.put_day(high=22650.0), s2, at(11, 5))
        _, c4 = u.run_at(self.put_day(high=22650.0), s3, at(14, 50))
        self.assertEqual((alerts(c2), alerts(c3), alerts(c4)), (["stop"], [], []))
        self.assertIn("stopped out", c3[0].args[0]["body"])                       # the silent update says so

    def test_close_reports_the_stop(self):
        rec = [{"d": "2026-10-22", "open": 22524.4, "close": 22753.2, "prev_close": 22600.0}]
        s = status.decide(self.put_day(high=22760.0, st="closed", recent=rec), at(15, 50))
        self.assertIn("stopped out", s["headline"])
        self.assertIn("-0.50% for the PUT", s["reason"])
        self.assertIn("would have made -1.02%", s["reason"])

    def test_trade_box_and_today_timeline(self):
        s = status.decide(self.put_day(high=22600.0), at(10, 0))
        box = status.trade_box(s, self.put_day(high=22600.0))
        self.assertEqual(box, {"side": "PUT", "entry": 22524.4, "stop": 22637.02, "price": 22600.0, "pct": -0.34})
        stopped = status.decide(self.put_day(high=22650.0), at(10, 30))
        self.assertEqual(status.trade_box(stopped, self.put_day(high=22650.0))["pct"], -0.5)
        self.assertIsNone(status.trade_box(status.decide(today(trade=False), at(8, 58)), today(trade=False)))
        with tempfile.TemporaryDirectory() as dd, tempfile.TemporaryDirectory() as store:
            json.dump(self.put_day(high=22600.0), open(os.path.join(dd, "today-nifty.json"), "w"))
            with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}), \
                    mock.patch.object(status, "notify", return_value={"telegram": "sent"}):
                status.main(dd, at(9, 50), store)
            self.assertEqual(json.load(open(os.path.join(dd, "status.json")))["trade"]["stop"], 22637.02)
            t = json.load(open(os.path.join(dd, "status-today.json")))
            self.assertEqual((t["date"], t["rows"][0]["at"], t["rows"][0]["state"], t["rows"][0]["alert"]),
                             ("2026-10-22", "09:50", "STAY", True))

    def test_no_trade_day_is_never_stopped(self):
        d = self.put_day(high=23000.0)
        d["preopen"]["recorded"]["from_open"]["trade"] = False
        self.assertEqual(status.decide(d, at(10, 30))["state"], "NOTHING")


class Journal(unittest.TestCase):
    def test_every_run_is_logged(self):
        with tempfile.TemporaryDirectory() as dd, tempfile.TemporaryDirectory() as store:
            json.dump(today(), open(os.path.join(dd, "today-nifty.json"), "w"))
            with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), mock.patch.object(status, "notify", return_value={"ntfy": "sent"}):
                status.main(dd, at(8, 58), store)
                status.main(dd, at(9, 50), store)
            rows = json.load(open(os.path.join(store, "journal", "2026-10-22.json")))
            self.assertEqual([r["state"] for r in rows], ["PUT", "STAY"])
            self.assertTrue(all(r["alert"] for r in rows))
            self.assertEqual(rows[0]["calls"]["from_open"]["trade"], True)


class Alerts(unittest.TestCase):
    def run_at(self, d, prev, now):
        with tempfile.TemporaryDirectory() as dd:
            json.dump(d, open(os.path.join(dd, "today-nifty.json"), "w"))
            if prev:
                json.dump(prev, open(os.path.join(dd, "status.json"), "w"))
            with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), mock.patch.object(status, "notify", return_value={"ntfy": "sent"}) as n:
                out = status.main(dd, now)
            return out, n.call_count

    def test_alert_only_on_change(self):
        s1, n1 = self.run_at(today(), None, at(6, 30))               # NOTHING (pending): quiet
        s2, n2 = self.run_at(today(), s1, at(8, 58))                 # -> PUT: alert
        s3, n3 = self.run_at(today(st="open"), s2, at(9, 50))        # -> STAY: alert
        s4, n4 = self.run_at(today(st="open"), s3, at(11, 5))        # still STAY: no alert
        s5, n5 = self.run_at(today(st="open"), s4, at(14, 50))       # -> SELL: alert
        self.assertEqual((n1, n2, n3, n4, n5), (0, 1, 1, 0, 1))
        self.assertEqual(s4["since"], s3["since"])

    def test_no_trade_morning_still_alerts(self):
        s1, _ = self.run_at(today(trade=False), None, at(6, 30))     # pending
        _, n = self.run_at(today(trade=False), s1, at(8, 58))         # NOTHING -> NOTHING, but now a real "no trade"
        self.assertEqual(n, 1)

    def test_quiet_close_after_no_trade(self):
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        _, n = self.run_at(today(trade=False, st="closed"), s1, at(15, 50))
        self.assertEqual(n, 0)


def live(d, price=22588.0, move=-0.05, opn=22524.4, direction="down", acc=0.64):
    return dict(d, intraday={"price": price, "move_pct": move, "open": opn, "direction": direction, "accuracy": acc})


NEWS = {"items": [{"title": "Infosys falls 7% after results", "seen": "2026-10-22T04:30:00+00:00"},
                  {"title": "Old headline", "seen": "2026-10-21T10:00:00+00:00"}]}


class Updates(unittest.TestCase):
    """Hourly updates (silent, information only) and the summary after the close."""

    def run_at(self, d, prev, now, news=None):
        with tempfile.TemporaryDirectory() as dd:
            json.dump(d, open(os.path.join(dd, "today-nifty.json"), "w"))
            if news:
                json.dump(news, open(os.path.join(dd, "news-nifty.json"), "w"))
            if prev:
                json.dump(prev, open(os.path.join(dd, "status.json"), "w"))
            with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}), \
                    mock.patch.object(status, "notify", return_value={"telegram": "sent"}) as n:
                out = status.main(dd, now)
            return out, n.call_args_list

    def test_hourly_update_on_a_no_trade_day(self):
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        s2, calls = self.run_at(live(today(trade=False, st="open")), s1, at(11, 5), NEWS)
        self.assertEqual(len(calls), 1)
        msg, silent = calls[0].args[0], calls[0].kwargs.get("silent")
        self.assertTrue(silent)
        self.assertEqual(msg["kind"], "info")
        self.assertIn("22,588.00 (-0.05% vs yesterday)", msg["body"])
        self.assertIn("too small a move to call", msg["body"])
        self.assertIn("Status: NOTHING", msg["body"])
        self.assertIn("Infosys falls 7%", msg["body"])
        self.assertEqual(s2["info_at"], "2026-10-22T11:05+05:30")
        _, again = self.run_at(live(today(trade=False, st="open")), s2, at(11, 15), NEWS)   # a retry 10 min later
        self.assertEqual(again, [])
        s3, later = self.run_at(live(today(trade=False, st="open")), s2, at(12, 5), NEWS)    # about hourly
        self.assertEqual(len(later), 1)
        self.assertIn("no new headlines", later[0].args[0]["body"])                        # already sent at 11:05

    def test_a_state_change_sends_the_alert_not_an_update(self):
        s1, _ = self.run_at(today(direction="down"), None, at(8, 58))
        _, calls = self.run_at(live(today(direction="down", st="open")), s1, at(9, 50))
        self.assertEqual([c.args[0]["kind"] for c in calls], ["hold"])
        self.assertFalse(calls[0].kwargs.get("silent"))

    def test_update_on_a_trade_day_shows_the_trade(self):
        s1, _ = self.run_at(today(direction="down"), None, at(8, 58))
        s2, _ = self.run_at(live(today(direction="down", st="open")), s1, at(9, 50))
        _, calls = self.run_at(live(today(direction="down", st="open"), price=22400.0), s2, at(11, 5))
        self.assertIn("Status: STAY", calls[0].args[0]["body"])
        self.assertIn("+0.55% for the PUT since the open", calls[0].args[0]["body"])

    def test_no_update_before_or_after_the_session(self):
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        _, calls = self.run_at(live(today(trade=False, st="open")), s1, at(9, 20))
        self.assertEqual(calls, [])

    def test_summary_once_after_the_close_on_a_no_trade_day(self):
        rec = [{"d": "2026-10-22", "gap": "down", "gap_hit": True, "close_call": "down", "close_hit": True,
                "open": 22687.75, "close": 22687.65, "prev_close": 22811.35}]
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        s2, calls = self.run_at(today(trade=False, st="closed", recent=rec), s1, at(15, 50))
        self.assertEqual(len(calls), 1)
        body = calls[0].args[0]["body"]
        self.assertEqual(calls[0].args[0]["kind"], "summary")
        self.assertIn("Closed 22,687.65 (-0.54%)", body)
        self.assertIn("gap down (right), close down (right)", body)
        self.assertIn("No trade today.", body)
        _, again = self.run_at(today(trade=False, st="closed", recent=rec), s2, at(16, 5))
        self.assertEqual(again, [])

    def test_summary_on_a_trade_day_has_the_result(self):
        rec = [{"d": "2026-10-22", "open": 22742.2, "close": 22600.0, "prev_close": 22687.65}]
        s1, _ = self.run_at(today(direction="down"), None, at(8, 58))
        _, calls = self.run_at(today(direction="down", st="closed", recent=rec), s1, at(15, 50))
        self.assertEqual([c.args[0]["kind"] for c in calls], ["summary"])                  # not a second "closed" alert
        self.assertIn("today's PUT won", calls[0].args[0]["body"])

    def test_no_summary_until_the_close_is_known(self):
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        s2, calls = self.run_at(today(trade=False, st="closed"), s1, at(15, 50))
        self.assertEqual(calls, [])
        self.assertFalse(s2.get("summary_sent"))


class GrokLines(unittest.TestCase):
    """Grok's notes ride along in the 08:57 alert and the summary (information only)."""

    def test_morning_read_in_the_alert_and_the_day_in_the_summary(self):
        with tempfile.TemporaryDirectory() as dd:
            json.dump(today(trade=False), open(os.path.join(dd, "today-nifty.json"), "w"))
            json.dump({"date": "2026-10-22", "morning": {"score": -1, "reasons": ["oil up", "weak Asia"], "big_event": False},
                       "card": {"close": 22687.65, "move_pct": -0.54, "call_close": 22700.0, "call_right": True,
                                "call_miss_pct": 0.06, "runs": 30, "avg_miss_pct": 0.21,
                                "right_side_since": "2026-10-22T11:05+05:30", "note": "Banks fell after results."}},
                      open(os.path.join(dd, "live-nifty.json"), "w"))
            with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}), \
                    mock.patch.object(status, "notify", return_value={"telegram": "sent"}) as n:
                s1 = status.main(dd, at(8, 58))
                self.assertIn("Grok's morning read (info only, not part of the signal): -1 bearish. oil up; weak Asia",
                              n.call_args.args[0]["reason"])
                self.assertNotIn("Grok", s1["reason"])                            # the page keeps the plain reason
                rec = [{"d": "2026-10-22", "gap": "down", "gap_hit": True, "close_call": "down", "close_hit": True,
                        "open": 22687.75, "close": 22687.65, "prev_close": 22811.35}]
                json.dump(today(trade=False, st="closed", recent=rec), open(os.path.join(dd, "today-nifty.json"), "w"))
                status.main(dd, at(15, 50))
                body = n.call_args.args[0]["body"]
                self.assertIn("right side from 11:05", body)
                self.assertIn("Why (Grok): Banks fell after results.", body)


class Channels(unittest.TestCase):
    def test_telegram_and_ntfy_each_get_the_alert_and_one_failing_does_not_stop_the_other(self):
        sent = []

        def fake(req, timeout=15):
            sent.append(req.full_url)
            if "ntfy" in req.full_url:
                raise OSError("down")
            return mock.Mock(read=lambda: b'{"ok": true}')
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42", "NTFY_TOPIC": "t"}
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", fake):
            res = status.notify({"kind": "put", "side": "PUT", "headline": "Buy a NIFTY PUT at the open", "reason": "x"})
        self.assertEqual(res["telegram"], "sent")
        self.assertTrue(res["ntfy"].startswith("failed"))
        self.assertTrue(any("api.telegram.org/bottok/sendMessage" in u for u in sent))

    def test_silent_messages_are_sent_without_sound(self):
        bodies = []

        def fake(req, timeout=15):
            bodies.append(json.loads(req.data))
            return mock.Mock(read=lambda: b'{"ok": true}')
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"}, clear=True), \
                mock.patch("urllib.request.urlopen", fake):
            status.notify({"kind": "info", "body": "line 1\nline 2"}, silent=True)
            status.notify({"kind": "put", "side": "PUT", "headline": "Buy", "reason": "x"})
        self.assertEqual([b["disable_notification"] for b in bodies], [True, False])
        self.assertTrue(bodies[0]["text"].endswith("(info, not a trade signal)\nline 1\nline 2"))

    def test_no_channel_no_alert(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(status.notify({"kind": "test", "headline": "h", "reason": "r"}), {})


if __name__ == "__main__":
    unittest.main()
