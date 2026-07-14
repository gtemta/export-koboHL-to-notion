"""Bookmark.Type / Hidden 過濾 — 空白 dogear/markup 不再混入。"""
import os
import sqlite3
import tempfile
import unittest

from src.infrastructure.persistence.kobo_sqlite_repository import KoboSqliteRepository

_BOOK = "book-1"
_BOOK2 = "book-2-dogear-only"


def _create_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE content ("
        "ContentID TEXT, Title TEXT, Subtitle TEXT, Attribution TEXT, "
        "DateLastRead TEXT, TimeSpentReading INTEGER, Description TEXT, "
        "Publisher TEXT, ___PercentRead INTEGER, LastTimeFinishedReading TEXT, "
        "ISBN TEXT, ChapterIDBookmarked TEXT, CurrentChapterEstimate REAL, "
        "CurrentChapterProgress REAL, ContentType INTEGER, BookID TEXT, "
        "VolumeIndex INTEGER, Depth INTEGER)"
    )
    conn.execute(
        "CREATE TABLE Bookmark ("
        "BookmarkID TEXT, VolumeID TEXT, ContentID TEXT, Text TEXT, "
        "Annotation TEXT, ChapterProgress REAL, StartContainerPath TEXT, "
        "EndContainerPath TEXT, Type TEXT, Hidden TEXT)"
    )
    # 兩本書（content 書籍列）
    for cid, title in ((_BOOK, "真書"), (_BOOK2, "只有摺角的書")):
        conn.execute(
            "INSERT INTO content (ContentID, Title, ContentType) VALUES (?, ?, 6)",
            (cid, title))
    rows = [
        ("bm-1", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "真劃線", "highlight", None),
        ("bm-2", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "", "dogear", None),
        ("bm-3", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "", "markup", None),
        ("bm-4", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "被隱藏的劃線", "highlight", "true"),
        ("bm-5", _BOOK2, f"{_BOOK2}!OEBPS!Text/ch1.xhtml", "", "dogear", None),
    ]
    for bid, vol, cid, text, btype, hidden in rows:
        conn.execute(
            "INSERT INTO Bookmark (BookmarkID, VolumeID, ContentID, Text, "
            "ChapterProgress, Type, Hidden) VALUES (?, ?, ?, ?, 0.5, ?, ?)",
            (bid, vol, cid, text, btype, hidden))
    conn.commit()
    conn.close()


class TestBookmarkTypeFilter(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        _create_db(self.db_path)
        self.repo = KoboSqliteRepository(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_only_real_highlights_returned(self):
        """dogear/markup（Text 全空）與 Hidden 劃線不進結果"""
        highlights = self.repo.get_highlights_with_chapters(_BOOK)
        self.assertEqual([h.text for h in highlights], ["真劃線"])
        self.assertEqual([h.bookmark_id for h in highlights], ["bm-1"])

    def test_book_with_only_dogears_not_listed(self):
        """整本書只有摺角 → 不出現在書單"""
        titles = [b.title for b in self.repo.get_all_books()]
        self.assertEqual(titles, ["真書"])


if __name__ == "__main__":
    unittest.main()
