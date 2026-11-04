"""Kite Connect: the morning login, the stored day token and the candles (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import kite  # noqa: E402
import live  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
KEY, SECRET = "k" * 16, "s" * 32


def at(d, h, m):
    return datetime(2026, 11, d, h, m, tzinfo=IST)


class Session(unittest.TestCase):

    def test_expires_at_six_next_morning(self):
        self.assertEqual(kite.expires(at(4, 8, 40)), at(5, 6, 0))
        self.assertEqual(kite.expires(at(4, 5, 30)), at(4, 6, 0))

    def test_login_saves_the_token_encrypted_and_load_reads_it_until_six(self):
        sent = {}

        def post(path, data=None, **k):
            sent.update(path=path, **data)
            return {"data": {"access_token": "ACCESS123"}}
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(kite.login("REQ", d, KEY, SECRET, now=at(4, 8, 40), post=post), "ACCESS123")
            self.assertEqual(sent["path"], "/session/token")
            import hashlib
            self.assertEqual(sent["checksum"], hashlib.sha256((KEY + "REQ" + SECRET).encode()).hexdigest())
            raw = open(os.path.join(d, kite.SESSION)).read()
            self.assertNotIn("ACCESS123", raw)                              # the branch is public
            self.assertNotIn("ACCESS123", open(os.path.join(d, kite.STATUS)).read())
            self.assertEqual(kite.load(d, SECRET, now=at(4, 15, 0)), "ACCESS123")
            self.assertIsNone(kite.load(d, SECRET, now=at(5, 6, 1)))       # expired
            self.assertIsNone(kite.load(d, "wrong" * 7, now=at(4, 15, 0)))  # another secret cannot read it
        self.assertIsNone(kite.load("/nonexistent", SECRET))


class Candles(unittest.TestCase):

    def answer(self, *a, **k):
        return {"data": {"candles": [["2026-11-04T09:15:00+0530", 23800, 23820.5, 23790, 23810, 0],
                                     ["2026-11-04T09:20:00+0530", 23810, 23815, 23800, 23805.25, 0]]}}

    def test_candles_parse(self):
        b = kite.candles(KEY, "T", "2026-11-04", get=self.answer)
        self.assertEqual(b[0][0], at(4, 9, 15))
        self.assertEqual(b[1][1:], (23810.0, 23815.0, 23800.0, 23805.25))

    def test_bars5_needs_secrets_and_a_login(self):
        with mock.patch.dict(os.environ, {"KITE_API_KEY": "", "KITE_API_SECRET": "", "KITE_DIR": ""}):
            self.assertIsNone(kite.bars5(get=self.answer))
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"KITE_API_KEY": KEY, "KITE_API_SECRET": SECRET, "KITE_DIR": d}):
            self.assertIsNone(kite.bars5(now=at(4, 10, 0), get=self.answer))           # no login today
            kite.login("REQ", d, KEY, SECRET, now=at(4, 8, 40), post=lambda *a, **k: {"data": {"access_token": "A"}})
            b = kite.bars5(now=at(4, 10, 0), get=self.answer)
            self.assertEqual((len(b), b.feed), (2, "kite"))

            def down(*a, **k):
                raise kite.KiteError("HTTP 503 NetworkException: down")
            self.assertIsNone(kite.bars5(now=at(4, 10, 0), get=down))                  # Yahoo then

    def test_kite_bars_skip_the_frozen_feed_check(self):
        # a quiet 5-minute bar after 15:00 would count as Yahoo's frozen feed; Kite's are real
        flat = [(at(4, 15, 0), 23800.0, 23800.5, 23800.0, 23800.2), (at(4, 15, 5), 23800.2, 23800.4, 23800.1, 23800.3),
                (at(4, 15, 10), 23800.3, 23800.4, 23800.2, 23800.3)]
        kept, paused = live.drop_frozen(kite.Bars(flat))
        self.assertEqual((len(kept), paused), (3, []))
        self.assertTrue(live.drop_frozen(flat)[1])                                      # as Yahoo's: left out


if __name__ == "__main__":
    unittest.main()
