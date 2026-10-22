"""CardStore 的唯讀查找（概念圖卡用）與全書地圖存檔。"""
import json
import os
import shutil
import tempfile
import unittest

from src.domain.entities.infographic_spec import MapEntry, Neighbor
from src.infrastructure.persistence.book_map_store import BookMapStore
from src.infrastructure.persistence.card_store import CardStore, card_source_id
from zettelkasten_generator import ZettelkastenCard


def _card_dict(title, bookmark_id="", highlight="劃線"):
    return {
        "id": f"id-{title}", "title": title, "content": "內容", "source_highlight": highlight,
        "chapter_reference": "", "chapter_progress": 0.1, "source_bookmark_id": bookmark_id,
    }


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.store = CardStore(self.dir)

    def write(self, filename, book_title, cards, uploaded=True, **extra):
        payload = {"book_title": book_title, "uploaded": uploaded, "cards": cards, **extra}
        with open(os.path.join(self.dir, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)


class TestSavedCards(_StoreCase):
    def test_uploaded_batches_are_included(self):
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "BM-1")], uploaded=True)
        self.assertEqual([s.card.title for s in self.store.saved_cards()], ["甲"])

    def test_rejected_cards_are_never_returned(self):
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "BM-1")],
                   rejected=[_card_dict("被退", "BM-2")])
        self.assertEqual([s.card.title for s in self.store.saved_cards()], ["甲"])

    def test_missing_dir_and_broken_files_are_tolerated(self):
        self.assertEqual(CardStore(os.path.join(self.dir, "nope")).saved_cards(), [])
        with open(os.path.join(self.dir, "壞_1.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        with open(os.path.join(self.dir, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(os.path.join(self.dir, "maps"))
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "BM-1")])
        self.assertEqual([s.card.title for s in self.store.saved_cards()], ["甲"])

    def test_same_highlight_in_a_newer_batch_replaces_the_older_card_in_place(self):
        self.write("書_20260101_000000.json", "書",
                   [_card_dict("甲舊", "BM-1"), _card_dict("乙", "BM-2")])
        self.write("書_20260202_000000.json", "書",
                   [_card_dict("甲新", "BM-1"), _card_dict("丙", "BM-3")])
        titles = [s.card.title for s in self.store.saved_cards()]
        self.assertEqual(titles, ["甲新", "乙", "丙"])

    def test_same_bookmark_id_in_different_books_stays_separate(self):
        self.write("書A_20260101_000000.json", "書A", [_card_dict("甲", "BM-1")])
        self.write("書B_20260101_000000.json", "書B", [_card_dict("乙", "BM-1")])
        self.assertEqual(len(self.store.saved_cards()), 2)


class TestLookup(_StoreCase):
    def test_book_cards_keeps_batch_order_then_card_order(self):
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "1"), _card_dict("乙", "2")])
        self.write("書_20260202_000000.json", "書", [_card_dict("丙", "3")])
        self.write("別本_20260101_000000.json", "別本", [_card_dict("丁", "4")])
        self.assertEqual([c.title for c in self.store.book_cards("書")], ["甲", "乙", "丙"])

    def test_find_by_source_id_returns_book_and_card(self):
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "BM-1"), _card_dict("乙", "BM-2")])
        found = self.store.find_by_source_id("BM-2")
        self.assertEqual((found.book_title, found.card.title), ("書", "乙"))

    def test_find_by_source_id_misses_cleanly(self):
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "BM-1")])
        self.assertIsNone(self.store.find_by_source_id("BM-404"))

    def test_cards_without_bookmark_id_are_found_by_their_hash_id(self):
        self.write("書_20260101_000000.json", "書", [_card_dict("甲", "", highlight="某段劃線")])
        card = ZettelkastenCard.from_dict(_card_dict("甲", "", highlight="某段劃線"))
        sid = card_source_id(card)
        self.assertTrue(sid.startswith("sha1:"))
        self.assertEqual(self.store.find_by_source_id(sid).card.title, "甲")


class TestBookMapStore(_StoreCase):
    TITLES = ["甲", "乙", "丙"]

    def entries(self):
        return {
            "甲": MapEntry("主軸", [Neighbor("導向", "乙")]),
            "乙": MapEntry("支柱", [Neighbor("前提", "甲")]),
            "丙": MapEntry("案例"),
        }

    def test_round_trip(self):
        maps = BookMapStore(self.dir)
        maps.save("書", self.TITLES, "全書主軸", self.entries())
        theme, entries = maps.load("書", self.TITLES)
        self.assertEqual(theme, "全書主軸")
        self.assertEqual(entries, self.entries())

    def test_map_is_stored_outside_the_card_batch_files(self):
        BookMapStore(self.dir).save("書", self.TITLES, "t", self.entries())
        self.assertEqual(self.store.saved_cards(), [])
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "maps")))

    def test_load_is_a_miss_when_the_card_set_changed(self):
        maps = BookMapStore(self.dir)
        maps.save("書", self.TITLES, "t", self.entries())
        self.assertIsNone(maps.load("書", self.TITLES + ["丁"]))
        self.assertIsNone(maps.load("書", ["甲", "乙"]))

    def test_load_ignores_card_order(self):
        maps = BookMapStore(self.dir)
        maps.save("書", self.TITLES, "t", self.entries())
        self.assertIsNotNone(maps.load("書", list(reversed(self.TITLES))))

    def test_load_misses_cleanly_on_absent_or_corrupt_file(self):
        maps = BookMapStore(self.dir)
        self.assertIsNone(maps.load("書", self.TITLES))
        os.makedirs(os.path.join(self.dir, "maps"))
        with open(os.path.join(self.dir, "maps", "書.json"), "w", encoding="utf-8") as f:
            f.write("{oops")
        self.assertIsNone(maps.load("書", self.TITLES))

    def test_save_overwrites_the_previous_map_of_the_same_book(self):
        maps = BookMapStore(self.dir)
        maps.save("書", self.TITLES, "舊", self.entries())
        maps.save("書", self.TITLES, "新", self.entries())
        self.assertEqual(maps.load("書", self.TITLES)[0], "新")


if __name__ == "__main__":
    unittest.main()
