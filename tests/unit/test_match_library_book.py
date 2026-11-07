"""Reading List 頁名 → Kobo 書庫的同一本書（補封面用）：寧可不配也不配錯。"""
import os
import sqlite3
import tempfile
import unittest

from src.domain.entities.book import Book
from src.domain.services.reading_list_rules import match_library_book
from src.infrastructure.persistence.kobo_sqlite_repository import KoboSqliteRepository


def _book(cid, title, image_id="img"):
    return Book(id=cid, title=title, image_id=image_id)


class TestMatchLibraryBook(unittest.TestCase):
    def test_exact_full_title(self):
        library = [_book("a", "過度努力：為什麼我們越拼命越焦慮"), _book("b", "奇才")]
        self.assertEqual(
            match_library_book("過度努力：為什麼我們越拼命越焦慮", library).id, "a")

    def test_page_has_only_the_main_title(self):
        library = [_book("a", "過度努力：為什麼我們越拼命越焦慮")]
        self.assertEqual(match_library_book("過度努力", library).id, "a")

    def test_library_has_only_the_main_title(self):
        library = [_book("a", "人生4千個禮拜")]
        self.assertEqual(match_library_book("人生4千個禮拜：不稀釋、不焦慮的時間管理", library).id, "a")

    def test_punctuation_width_case_and_whitespace_do_not_matter(self):
        library = [_book("a", "Refactoring: Improving The Design Of Existing Code")]
        self.assertEqual(
            match_library_book("refactoring： improving the design of existing code", library).id,
            "a")

    def test_newline_inside_the_page_title(self):
        library = [_book("a", "故事課1：3分鐘說18萬個故事，打造影響力")]
        self.assertEqual(
            match_library_book("故事課1\n：3分鐘說18萬個故事，打造影響力", library).id, "a")

    def test_no_match(self):
        self.assertIsNone(match_library_book("Clean Code", [_book("a", "奇才")]))
        self.assertIsNone(match_library_book("Clean Code", []))

    def test_a_substring_is_not_a_match(self):
        """"原則" 是 "原則：生活和工作" 的主書名才算；單純被包含（例如 "生活和工作"）不算。"""
        library = [_book("a", "原則：生活和工作")]
        self.assertIsNone(match_library_book("生活和工作", library))
        self.assertIsNone(match_library_book("工作", library))

    def test_different_books_sharing_a_main_title_are_ambiguous(self):
        library = [_book("a", "心態：成功的新心理學", "img-a"),
                   _book("b", "心態：另一本書", "img-b")]
        self.assertIsNone(match_library_book("心態", library))

    def test_full_title_wins_over_main_title_ambiguity(self):
        library = [_book("a", "心態：成功的新心理學", "img-a"),
                   _book("b", "心態：另一本書", "img-b")]
        self.assertEqual(match_library_book("心態：成功的新心理學", library).id, "a")

    def test_duplicate_entries_of_the_same_book_are_not_ambiguous(self):
        library = [_book("a1", "奇才", "img-1"), _book("a2", "奇才", "img-1")]
        self.assertEqual(match_library_book("奇才", library).image_id, "img-1")

    def test_one_character_main_title_is_too_short_to_trust(self):
        library = [_book("a", "鏈：另一本書")]
        self.assertIsNone(match_library_book("鏈", library))

    def test_empty_title(self):
        self.assertIsNone(match_library_book("", [_book("a", "奇才")]))
        self.assertIsNone(match_library_book("   ", [_book("a", "奇才")]))


class TestGetLibraryBooks(unittest.TestCase):
    """書庫裡所有的書（不只有劃線的）——手動建立的 Reading List 頁很多是沒劃線的書。"""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE content (ContentID TEXT, Title TEXT, Attribution TEXT, ISBN TEXT, "
            "ContentType INTEGER, ImageId TEXT)")
        rows = [
            ("b1", "有劃線的書", "作者甲", "9786267195185", 6, "img-1"),
            ("b2", "沒劃線的書", None, None, 6, "img-2"),
            ("b3", "沒封面的書", None, None, 6, None),
            ("c1", "章節列", None, None, 9, "img-x"),
            ("t1", None, None, None, 6, "img-3"),
        ]
        conn.executemany("INSERT INTO content VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.remove(self.db_path)

    def test_returns_every_book_row_with_a_title(self):
        books = KoboSqliteRepository(self.db_path).get_library_books()
        self.assertEqual([b.title for b in books], ["有劃線的書", "沒劃線的書", "沒封面的書"])
        first = books[0]
        self.assertEqual((first.id, first.author, first.isbn, first.image_id),
                         ("b1", "作者甲", "9786267195185", "img-1"))

    def test_missing_image_id_stays_none(self):
        books = KoboSqliteRepository(self.db_path).get_library_books()
        self.assertIsNone(books[2].image_id)


if __name__ == "__main__":
    unittest.main()
