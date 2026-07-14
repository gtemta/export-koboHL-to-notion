"""DryRunNotionRepository：讀委派、寫只記 log、假 page_id 讓流程走通。"""
import unittest
from types import SimpleNamespace

from src.infrastructure.notion.dry_run_notion_repository import DryRunNotionRepository


class FakeNotionRepository:
    """記錄呼叫的假 repo：查詢永遠找不到，寫入呼叫都留下足跡。"""

    def __init__(self):
        self.write_calls = []

    def check_book_exists(self, title, is_exported=True):
        return {"is_target_valid": False, "pageId": None}

    def create_book_entry(self, title):
        self.write_calls.append(("create", title))
        return True

    def sync_book_highlights(self, page_id, highlights):
        self.write_calls.append(("sync", page_id))

    def update_book_metadata(self, page_id, book):
        self.write_calls.append(("metadata", page_id))

    def add_book_cover(self, page_id, title, isbn=None):
        self.write_calls.append(("cover", page_id))


class TestDryRunNotionRepository(unittest.TestCase):
    def setUp(self):
        self.inner = FakeNotionRepository()
        self.repo = DryRunNotionRepository(self.inner)

    def test_writes_never_reach_inner(self):
        book = SimpleNamespace(title="測試書")
        highlight = SimpleNamespace(
            chapter_name="第一章", toc_chapter=None, toc_section=None)
        self.repo.create_book_entry("測試書")
        self.repo.sync_book_highlights("page-1", [highlight])
        self.repo.update_book_metadata("page-1", book)
        self.repo.add_book_cover("page-1", "測試書")
        self.assertEqual(self.inner.write_calls, [])

    def test_created_book_gets_fake_page_id_on_requery(self):
        self.assertTrue(self.repo.create_book_entry("測試書"))
        result = self.repo.check_book_exists("測試書", is_exported=False)
        self.assertTrue(result["is_target_valid"])
        self.assertTrue(result["pageId"].startswith("dry-run-page-"))

    def test_fake_page_id_not_returned_for_exported_query(self):
        self.repo.create_book_entry("測試書")
        result = self.repo.check_book_exists("測試書", is_exported=True)
        self.assertFalse(result["is_target_valid"])

    def test_unknown_book_delegates_inner_result(self):
        result = self.repo.check_book_exists("沒建立過的書", is_exported=False)
        self.assertFalse(result["is_target_valid"])
        self.assertIsNone(result["pageId"])


if __name__ == "__main__":
    unittest.main()
