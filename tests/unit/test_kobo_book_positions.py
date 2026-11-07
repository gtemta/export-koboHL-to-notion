"""來源劃線ID → 書中位置（spine 序號, 檔內進度）：最小 SQLite 取代真實 Kobo 資料庫。"""
import os
import sqlite3
import tempfile
import unittest

from src.infrastructure.persistence.kobo_book_positions import KoboBookPositions


class TestKoboBookPositions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = os.path.join(self._tmp.name, "kobo.sqlite")
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE content (ContentID TEXT, BookID TEXT, ContentType INT, VolumeIndex INT);
            CREATE TABLE Bookmark (BookmarkID TEXT, VolumeID TEXT, ContentID TEXT, ChapterProgress REAL);
            INSERT INTO content VALUES ('book-a!OEBPS!ch1.xhtml', 'book-a', 9, 3);
            INSERT INTO content VALUES ('book-a!OEBPS!ch2.xhtml', 'book-a', 9, 10);
            INSERT INTO content VALUES ('book-b!OEBPS!ch1.xhtml', 'book-b', 9, 0);
            INSERT INTO Bookmark VALUES ('bm-1', 'book-a', 'book-a!OEBPS!ch2.xhtml', 0.2);
            INSERT INTO Bookmark VALUES ('bm-null', 'book-a', 'book-a!OEBPS!ch1.xhtml', NULL);
            INSERT INTO Bookmark VALUES ('bm-b', 'book-b', 'book-b!OEBPS!ch1.xhtml', 0.5);
            INSERT INTO Bookmark VALUES ('bm-nospine', 'book-a', 'book-a!OEBPS!gone.xhtml', 0.9);
            """
        )
        conn.commit()
        conn.close()

    def test_position_is_spine_index_and_progress(self):
        self.assertEqual(KoboBookPositions(self.db).positions_for(["bm-1"]), {"bm-1": (10, 0.2)})

    def test_unknown_id_is_omitted(self):
        self.assertEqual(KoboBookPositions(self.db).positions_for(["nope"]), {})

    def test_null_progress_counts_as_zero(self):
        self.assertEqual(KoboBookPositions(self.db).positions_for(["bm-null"])["bm-null"][1], 0.0)

    def test_highlights_of_several_books_are_resolved_in_one_call(self):
        result = KoboBookPositions(self.db).positions_for(["bm-1", "bm-b", "bm-null"])
        self.assertEqual(result, {"bm-1": (10, 0.2), "bm-b": (0, 0.5), "bm-null": (3, 0.0)})

    def test_bookmark_whose_file_is_not_in_the_spine_is_omitted(self):
        self.assertEqual(KoboBookPositions(self.db).positions_for(["bm-nospine"]), {})

    def test_no_ids_means_no_queries(self):
        self.assertEqual(KoboBookPositions("no-such.sqlite").positions_for([]), {})

    def test_missing_database_returns_empty(self):
        with self.assertLogs(level="WARNING"):
            self.assertEqual(KoboBookPositions("no-such.sqlite").positions_for(["bm-1"]), {})

    def test_database_is_never_modified(self):
        before = os.path.getmtime(self.db)
        KoboBookPositions(self.db).positions_for(["bm-1"])
        self.assertEqual(os.path.getmtime(self.db), before)


if __name__ == "__main__":
    unittest.main()
