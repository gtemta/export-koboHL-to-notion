import os
import unittest
from unittest import mock

from src.application.use_cases.sync_books_use_case import SyncBooksUseCase
from src.config.settings import Settings
from src.domain.entities.book import Book
from src.domain.entities.highlight import Highlight
from src.domain.services.chapter_extractor import ChapterExtractor
from src.infrastructure.notion.notion_api_repository import NotionApiRepository


class TestResyncSettings(unittest.TestCase):
    def _settings(self, raw):
        return Settings(
            notion_token="t", notion_database_id="d",
            resync_highlights=Settings._parse_resync(raw))

    def test_empty_means_disabled(self):
        s = self._settings(None)
        self.assertFalse(s.resync_matches("任何書"))
        s = self._settings("  ")
        self.assertFalse(s.resync_matches("任何書"))

    def test_all_matches_everything(self):
        s = self._settings("all")
        self.assertTrue(s.resync_matches("物哀"))
        self.assertTrue(s.resync_matches("anything"))

    def test_substring_match(self):
        s = self._settings("物哀, 主控力")
        self.assertTrue(s.resync_matches("日本美學1：物哀：櫻花落下後"))
        self.assertTrue(s.resync_matches("主控力：全球領導力大師"))
        self.assertFalse(s.resync_matches("迷因"))

    def test_from_env_plumbing(self):
        env = {
            "NOTION_TOKEN": "t", "NOTION_DATABASE_ID": "d",
            "RESYNC_HIGHLIGHTS": "物哀",
        }
        with mock.patch.dict(os.environ, env):
            s = Settings.from_env()
        self.assertEqual(s.resync_highlights, ["物哀"])


class TestSyncGeneratedBlockFilter(unittest.TestCase):
    def test_sync_generated_types(self):
        for t in ("heading_1", "bulleted_list_item", "callout", "divider"):
            self.assertTrue(
                NotionApiRepository._is_sync_generated({"type": t}), t)

    def test_user_content_types_preserved(self):
        for t in ("paragraph", "toggle", "image", "quote", "heading_2",
                  "to_do", "child_page"):
            self.assertFalse(
                NotionApiRepository._is_sync_generated({"type": t}), t)


class _FakeBookRepo:
    def __init__(self, book, highlights):
        self._book = book
        self._highlights = highlights

    def get_all_books(self):
        return [self._book]

    def get_highlights_with_chapters(self, book_id):
        return list(self._highlights)


class _FakeNotionRepo:
    """已存在且已 Exported 的書；記錄 replace 是否被呼叫。"""

    def __init__(self):
        self.replace_calls = []
        self.sync_calls = []

    def check_book_exists(self, title, is_exported=True):
        return {"is_target_valid": is_exported, "pageId": "page-1"}

    def create_book_entry(self, title):
        raise AssertionError("exported book should not be re-created")

    def sync_book_highlights(self, page_id, highlights):
        self.sync_calls.append((page_id, highlights))

    def replace_book_highlights(self, page_id, highlights):
        self.replace_calls.append((page_id, highlights))

    def update_book_metadata(self, page_id, book):
        pass

    def add_book_cover(self, page_id, title, isbn=None):
        pass


def _use_case(notion_repo, should_resync):
    book = Book(id="b1", title="日本美學1：物哀：櫻花落下後")
    highlights = [Highlight(text="劃線", chapter_name="導讀",
                            chapter_progress=0.1, content_id="c1")]
    return SyncBooksUseCase(
        book_repo=_FakeBookRepo(book, highlights),
        notion_repo=notion_repo,
        chapter_extractor=ChapterExtractor(),
        max_workers=1,
        should_resync=should_resync,
    )


class TestUseCaseResyncBranch(unittest.TestCase):
    def test_exported_book_matching_resync_is_rebuilt(self):
        repo = _FakeNotionRepo()
        result = _use_case(repo, should_resync=lambda t: "物哀" in t).execute()
        self.assertEqual(result.successful_syncs, 1)
        self.assertEqual(len(repo.replace_calls), 1)
        self.assertEqual(repo.replace_calls[0][0], "page-1")
        self.assertEqual(len(repo.sync_calls), 0)

    def test_exported_book_without_resync_untouched(self):
        repo = _FakeNotionRepo()
        result = _use_case(repo, should_resync=None).execute()
        self.assertEqual(result.successful_syncs, 1)
        self.assertEqual(len(repo.replace_calls), 0)
        self.assertEqual(len(repo.sync_calls), 0)


if __name__ == "__main__":
    unittest.main()
