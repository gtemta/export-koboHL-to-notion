"""READING_LIST_PAGES 設定，以及 SyncBooksUseCase 在執行緒池結束後依序補頁。"""
import os
import unittest
from unittest import mock

from src.application.use_cases.sync_books_use_case import SyncBooksUseCase
from src.config.settings import Settings
from src.domain.entities.book import Book
from src.domain.services.chapter_extractor import ChapterExtractor


class TestReadingListSettings(unittest.TestCase):
    def test_disabled_when_unset(self):
        s = Settings(notion_token="t", notion_database_id="d")
        self.assertEqual(s.reading_list_pages, [])
        self.assertFalse(s.reading_list_matches("任何書"))

    def test_substrings_and_all(self):
        s = Settings(notion_token="t", notion_database_id="d",
                     reading_list_pages=Settings._parse_resync("多巴胺, 重要事"))
        self.assertTrue(s.reading_list_matches("多巴胺國度：在縱慾年代找到身心平衡"))
        self.assertFalse(s.reading_list_matches("異數"))
        s_all = Settings(notion_token="t", notion_database_id="d", reading_list_pages=["all"])
        self.assertTrue(s_all.reading_list_matches("異數"))

    def test_resync_matching_unchanged(self):
        s = Settings(notion_token="t", notion_database_id="d",
                     resync_highlights=["物哀"])
        self.assertTrue(s.resync_matches("日本美學1：物哀：櫻花落下後"))
        self.assertFalse(s.resync_matches("迷因"))

    def test_from_env_plumbing(self):
        env = {"NOTION_TOKEN": "t", "NOTION_DATABASE_ID": "d",
               "READING_LIST_PAGES": "all", "GOOGLE_BOOKS_API_KEY": "k-1"}
        with mock.patch.dict(os.environ, env):
            s = Settings.from_env()
        self.assertEqual(s.reading_list_pages, ["all"])
        self.assertEqual(s.google_books_api_key, "k-1")


class _FakeBookRepo:
    def __init__(self, titles):
        self._books = [Book(id=f"id-{t}", title=t) for t in titles]

    def get_all_books(self):
        return list(self._books)

    def get_highlights_with_chapters(self, book_id):
        return []


class _FakeNotionRepo:
    """已匯出的書：走更新元數據分支；劃線頁 id = kobo-<書名>。"""

    def check_book_exists(self, title, is_exported=True):
        return {"is_target_valid": is_exported, "pageId": f"kobo-{title}"}

    def update_book_metadata(self, page_id, book):
        pass

    def add_book_cover(self, page_id, book):
        pass

    def replace_book_highlights(self, page_id, highlights):
        pass


class _FakePageUseCase:
    def __init__(self, fail_on=None):
        self.calls = []
        self._fail_on = fail_on

    def execute(self, book, kobo_page_id):
        if book.title == self._fail_on:
            raise RuntimeError("boom")
        self.calls.append((book.title, kobo_page_id))


def _use_case(page_use_case, should_complete_page=lambda _t: True):
    return SyncBooksUseCase(
        book_repo=_FakeBookRepo(["B-book", "A-book"]),
        notion_repo=_FakeNotionRepo(),
        chapter_extractor=ChapterExtractor(),
        max_workers=2,
        page_use_case=page_use_case,
        should_complete_page=should_complete_page,
    )


class TestSyncThenCompletePages(unittest.TestCase):
    def test_pages_completed_after_sync_in_title_order(self):
        pages = _FakePageUseCase()
        result = _use_case(pages).execute()
        self.assertEqual(result.successful_syncs, 2)
        self.assertEqual(pages.calls, [("A-book", "kobo-A-book"), ("B-book", "kobo-B-book")])

    def test_only_matching_titles_completed(self):
        pages = _FakePageUseCase()
        _use_case(pages, should_complete_page=lambda t: t == "B-book").execute()
        self.assertEqual(pages.calls, [("B-book", "kobo-B-book")])

    def test_page_failure_recorded_but_sync_counts(self):
        pages = _FakePageUseCase(fail_on="A-book")
        result = _use_case(pages).execute()
        self.assertEqual(result.successful_syncs, 2)
        self.assertEqual(result.failed_syncs, 0)
        self.assertTrue(any("補頁失敗: A-book" in e for e in result.errors))
        self.assertEqual(pages.calls, [("B-book", "kobo-B-book")])

    def test_without_page_use_case_nothing_happens(self):
        result = _use_case(None).execute()
        self.assertEqual(result.successful_syncs, 2)
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
