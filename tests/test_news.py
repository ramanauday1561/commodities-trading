"""Tests for the NewsMCP integration (no network: the API call is replaced)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import news  # noqa: E402

GOLD = {"topics": ["economy"], "keywords": ["gold", "fed"]}
NIFTY = {"topics": ["economy"], "geo": ["india"], "keywords": ["sensex"]}


def ev(i, summary, impact=5, sources=10, geo=(), topics=("economy",), entries=None):
    return {"id": str(i), "summary": summary, "impact_score": impact, "sources_count": sources, "geo": list(geo),
            "topics": list(topics), "last_seen_at": "2026-10-12T10:00:00Z",
            "entries": entries if entries is not None else [{"title": summary, "url": f"https://x.com/{i}", "domain": "x.com"}]}


class News(unittest.TestCase):
    def test_keyword_match_is_whole_word(self):
        self.assertTrue(news.relevant(ev(1, "Gold hits a record"), GOLD))
        self.assertFalse(news.relevant(ev(2, "Goldman Sachs earnings"), GOLD))
        self.assertFalse(news.relevant(ev(3, "Federal holiday announced"), GOLD))

    def test_region_counts_only_for_economy_events(self):
        self.assertTrue(news.relevant(ev(1, "Budget announced", geo=["india"]), NIFTY))
        self.assertFalse(news.relevant(ev(2, "Cricket final", geo=["india"], topics=["sports"]), NIFTY))

    def test_summary_ranks_by_impact_and_drops_unsafe_links(self):
        events = [ev(1, "Gold rally continues", impact=3),
                  ev(2, "Fed signals rate cut", impact=9, entries=[{"title": "t", "url": "javascript:alert(1)", "domain": "evil"},
                                                                  {"title": "ok", "url": "https://a.com", "domain": "a.com"}]),
                  ev(3, "Football results", impact=10)]
        items, feat = news.summarize(events, GOLD)
        self.assertEqual([i["impact"] for i in items], [9, 3])
        self.assertEqual([l["url"] for l in items[0]["links"]], ["https://a.com"])
        self.assertEqual(feat["events"], 2)
        self.assertEqual(feat["max_impact"], 9)

    def test_tone(self):
        self.assertGreater(news.tone(ev(1, "Stocks surge to record high")), 0)
        self.assertLess(news.tone(ev(2, "Markets plunge on war fears")), 0)
        self.assertEqual(news.tone(ev(3, "Meeting scheduled", entries=[])), 0.0)

    def test_main_writes_page_file_and_one_history_row_per_day(self):
        insts = [{"key": "gold", "news": GOLD}, {"key": "plain"}]
        resp = {"events": [ev(1, "Gold climbs"), ev(2, "Tennis")]}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(news, "get", return_value=resp), \
                mock.patch("builtins.open", side_effect=lambda p, *a, **k: io_open(p, insts, *a, **k)):
            data, store = os.path.join(tmp, "data"), os.path.join(tmp, "store")
            os.makedirs(data)
            news.main(data, store)
            news.main(data, store)
            page = json.load(io_open(os.path.join(data, "news-gold.json"), insts))
            hist = json.load(io_open(os.path.join(store, "news", "gold.json"), insts))
            self.assertEqual(page["stats"]["events"], 1)
            self.assertEqual(len(hist), 1)
            self.assertFalse(os.path.exists(os.path.join(data, "news-plain.json")))

    def test_api_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(news, "get", return_value=None), \
                mock.patch("builtins.open", side_effect=lambda p, *a, **k: io_open(p, [{"key": "gold", "news": GOLD}], *a, **k)):
            news.main(tmp, tmp)
            self.assertFalse(os.path.exists(os.path.join(tmp, "news-gold.json")))


_real_open = open


def io_open(path, insts, *a, **k):
    """Serve a fake instruments.json; everything else goes to the real file system."""
    if str(path).endswith("instruments.json"):
        import io
        return io.StringIO(json.dumps(insts))
    return _real_open(path, *a, **k)


if __name__ == "__main__":
    unittest.main()
