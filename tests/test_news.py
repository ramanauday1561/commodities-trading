"""Tests for the news module (no network: the API call is replaced)."""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import news  # noqa: E402

_real_open = open


def art(title, domain, url=None, seen="20261012T100000Z"):
    return {"title": title, "domain": domain, "url": url or f"https://{domain}/{abs(hash(title))}", "seendate": seen}


def fake_open(insts):
    """Serve a fake instruments.json; everything else goes to the real file system."""
    return lambda p, *a, **k: io.StringIO(json.dumps(insts)) if str(p).endswith("instruments.json") else _real_open(p, *a, **k)


class News(unittest.TestCase):
    def test_syndicated_copies_are_grouped_and_ranked_first(self):
        arts = [art("Gold hits record high", "a.com"), art("Gold Hits Record High!", "b.com"),
                art("Gold hits record high", "a.com"), art("Silver steady", "c.com")]
        items, feat = news.summarize(arts)
        self.assertEqual(items[0]["sources"], 2)            # a.com twice counts once
        self.assertEqual(feat["stories"], 2)
        self.assertEqual(feat["articles"], 4)
        self.assertEqual(items[0]["seen"], "2026-10-12T10:00:00+00:00")

    def test_unsafe_links_are_dropped(self):
        items, _ = news.summarize([art("x", "evil.com", url="javascript:alert(1)"), art("y", "ok.com")])
        self.assertEqual([i["domain"] for i in items], ["ok.com"])

    def test_tone(self):
        self.assertGreater(news.tone("Stocks surge to record high"), 0)
        self.assertLess(news.tone("Markets plunge on war fears"), 0)
        self.assertEqual(news.tone("Meeting scheduled"), 0.0)

    def test_main_writes_page_file_and_one_history_row_per_day(self):
        insts = [{"key": "gold", "news": {"query": "gold"}}, {"key": "plain"}]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(news, "get", return_value={"articles": [art("Gold climbs", "a.com")]}), \
                mock.patch("builtins.open", side_effect=fake_open(insts)):
            data, store = os.path.join(tmp, "data"), os.path.join(tmp, "store")
            os.makedirs(data)
            news.main(data, store)
            news.main(data, store)
            page = json.load(_real_open(os.path.join(data, "news-gold.json")))
            hist = json.load(_real_open(os.path.join(store, "news", "gold.json")))
            self.assertEqual(page["stats"]["stories"], 1)
            self.assertEqual(len(hist), 1)
            self.assertFalse(os.path.exists(os.path.join(data, "news-plain.json")))

    def test_api_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(news, "get", return_value=None), \
                mock.patch("builtins.open", side_effect=fake_open([{"key": "gold", "news": {"query": "gold"}}])):
            news.main(tmp, tmp)
            self.assertFalse(os.path.exists(os.path.join(tmp, "news-gold.json")))


if __name__ == "__main__":
    unittest.main()
