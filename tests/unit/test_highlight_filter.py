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
        # Hidden 無宣告型別 → NONE/BLOB affinity，保留插入時的原始型別
        # （真實 Kobo 資料的 Hidden 可能是整數 1，不是文字 '1'）
        "EndContainerPath TEXT, Type TEXT, Hidden)"
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
        # Hidden 為整數 1（非文字 '1'）——舊過濾 NOT IN ('true','1') 漏掉整數
        ("bm-6", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "整數隱藏劃線", "highlight", 1),
        ("bm-5", _BOOK2, f"{_BOOK2}!OEBPS!Text/ch1.xhtml", "", "dogear", None),
    ]
    for bid, vol, cid, text, btype, hidden in rows:
        conn.execute(
            "INSERT INTO Bookmark (BookmarkID, VolumeID, ContentID, Text, "
            "ChapterProgress, Type, Hidden) VALUES (?, ?, ?, ?, 0.5, ?, ?)",
            (bid, vol, cid, text, btype, hidden))
    conn.commit()
    conn.close()


class TestTocPartsOnHighlight(unittest.TestCase):
    """TOC 命中時 Highlight 帶結構化章/小節，供兩層 toggle 版面分組。"""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        _create_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        # spine（ContentType=9）與 TOC（ContentType=899）：ch1 檔屬「第一章 › 開場」
        conn.execute(
            "INSERT INTO content (ContentID, ContentType, BookID, VolumeIndex) "
            "VALUES (?, 9, ?, 0)", (f"{_BOOK}!OEBPS!Text/ch1.xhtml", _BOOK))
        conn.execute(
            "INSERT INTO content (ContentID, Title, ContentType, BookID, VolumeIndex, "
            "Depth) VALUES (?, '第一章', 899, ?, 0, 1)",
            (f"{_BOOK}!OEBPS!Text/ch1.xhtml-1", _BOOK))
        conn.execute(
            "INSERT INTO content (ContentID, Title, ContentType, BookID, VolumeIndex, "
            "Depth) VALUES (?, '開場', 899, ?, 1, 2)",
            (f"{_BOOK}!OEBPS!Text/ch1.xhtml#a1-2", _BOOK))
        conn.commit()
        conn.close()
        self.repo = KoboSqliteRepository(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_toc_parts_populated(self):
        h = self.repo.get_highlights_with_chapters(_BOOK)[0]
        # 同檔多條目且第二條帶 anchor → 模糊，退回章級
        self.assertEqual(h.toc_chapter, "第一章")
        self.assertIsNone(h.toc_section)
        self.assertEqual(h.chapter_name, "第一章")

    def test_no_toc_leaves_parts_none(self):
        """無 TOC 的書（_BOOK2 無 899 列）parts 為 None，走 fallback"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO Bookmark (BookmarkID, VolumeID, ContentID, Text, "
            "ChapterProgress, Type) VALUES ('bm-9', ?, ?, '無目錄劃線', 0.5, "
            "'highlight')", (_BOOK2, f"{_BOOK2}!OEBPS!Text/x.xhtml"))
        conn.commit()
        conn.close()
        h = self.repo.get_highlights_with_chapters(_BOOK2)[0]
        self.assertIsNone(h.toc_chapter)
        self.assertIsNone(h.toc_section)


class TestBookmarkTypeFilter(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        _create_db(self.db_path)
        self.repo = KoboSqliteRepository(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_only_real_highlights_returned(self):
        """dogear/markup（Text 全空）與 Hidden 劃線（文字 'true' 與整數 1）不進結果"""
        highlights = self.repo.get_highlights_with_chapters(_BOOK)
        self.assertEqual([h.text for h in highlights], ["真劃線"])
        self.assertEqual([h.bookmark_id for h in highlights], ["bm-1"])

    def test_integer_hidden_excluded(self):
        """Hidden 為整數 1 的劃線被排除（NOT IN 需含整數 1，非只 '1'）"""
        highlights = self.repo.get_highlights_with_chapters(_BOOK)
        self.assertNotIn("整數隱藏劃線", [h.text for h in highlights])
        self.assertNotIn("bm-6", [h.bookmark_id for h in highlights])

    def test_book_with_only_dogears_not_listed(self):
        """整本書只有摺角 → 不出現在書單"""
        titles = [b.title for b in self.repo.get_all_books()]
        self.assertEqual(titles, ["真書"])


if __name__ == "__main__":
    unittest.main()
