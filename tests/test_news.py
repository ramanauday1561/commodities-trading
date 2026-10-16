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

    def test_off_topic_headlines_are_not_shown_but_still_counted(self):
        arts = [art("Silver price rises above $57", "a.com"), art("Cardinals rule out rookie RB for Week 6", "b.com"),
                art("Silver futures slip", "c.com")]
        items, feat = news.summarize(arts, ["silver"])
        self.assertEqual(sorted(i["domain"] for i in items), ["a.com", "c.com"])
        self.assertEqual(feat["articles"], 3)               # the recorded history is unchanged by the filter
        self.assertTrue(news.relevant("Indian stocks rally", ["stock"]))
        self.assertFalse(news.relevant("Livestock fair opens", ["stock"]))   # matched at the start of a word only
        items, _ = news.summarize([art("Cardinals rule out rookie", "b.com")], ["silver"])
        self.assertEqual(len(items), 1)                     # nothing matches: show what there is rather than nothing

    def test_tone(self):
        self.assertGreater(news.tone("Stocks surge to record high"), 0)
        self.assertLess(news.tone("Markets plunge on war fears"), 0)
        self.assertEqual(news.tone("Meeting scheduled"), 0.0)

    def test_gdelt_answer_parsing(self):
        with mock.patch.object(news, "fetch", return_value=json.dumps({"articles": [art("Gold climbs", "a.com")]})):
            self.assertEqual(len(news.from_gdelt("gold")), 1)
        for body in ("{}", "Please limit requests to one every 5 seconds", None):
            with mock.patch.object(news, "fetch", return_value=body):
                self.assertEqual(news.from_gdelt("gold"), [])

    def test_google_rss_parsing(self):
        rss = """<?xml version="1.0"?><rss><channel>
          <item><title>Gold hits record high - Reuters</title><link>https://news.google.com/rss/articles/abc</link>
            <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
          <item><title>No source tag</title><link>https://x.com/1</link><pubDate>bad date</pubDate></item>
        </channel></rss>"""
        with mock.patch.object(news, "fetch", return_value=rss) as f:
            arts = news.from_google('("gold price" OR bullion) sourcelang:english')
        self.assertNotIn("sourcelang", f.call_args[0][0])
        self.assertEqual(arts[0], {"title": "Gold hits record high", "url": "https://news.google.com/rss/articles/abc",
                                   "domain": "Reuters", "seendate": "20261012T100000Z"})
        self.assertIsNone(arts[1]["seendate"])
        with mock.patch.object(news, "fetch", return_value="<html>blocked"):
            self.assertIsNone(news.from_google("gold"))

    def test_falls_back_to_google_and_records_the_source(self):
        insts = [{"key": "gold", "news": {"query": "gold"}}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(news, "from_gdelt", return_value=[]), \
                mock.patch.object(news, "from_google", return_value=[art("Gold climbs", "a.com")]), \
                mock.patch("builtins.open", side_effect=fake_open(insts)):
            news.main(tmp, tmp)
            self.assertEqual(json.load(_real_open(os.path.join(tmp, "news-gold.json")))["source"], "Google News")
            self.assertEqual(json.load(_real_open(os.path.join(tmp, "news", "gold.json")))[0]["src"], "Google News")

    def test_main_writes_page_file_and_one_history_row_per_day(self):
        insts = [{"key": "gold", "news": {"query": "gold"}}, {"key": "plain"}]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(news, "from_gdelt", return_value=[art("Gold climbs", "a.com")]), \
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

    def test_no_news_from_either_source_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(news, "from_gdelt", return_value=[]), \
                mock.patch.object(news, "from_google", return_value=[]), \
                mock.patch("builtins.open", side_effect=fake_open([{"key": "gold", "news": {"query": "gold"}}])):
            news.main(tmp, tmp)
            self.assertFalse(os.path.exists(os.path.join(tmp, "news-gold.json")))


if __name__ == "__main__":
    unittest.main()
