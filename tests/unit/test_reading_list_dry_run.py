"""Reading List 補頁的 DRY_RUN decorator 與 container 組裝。"""
import unittest

from src.application.use_cases.complete_reading_list_page_use_case import (
    CompleteReadingListPageUseCase,
)
from src.config.settings import Settings
from src.infrastructure.container import build_use_case
from src.infrastructure.notion.dry_run_reading_list_repository import (
    DryRunNotionViewsClient,
    DryRunReadingListRepository,
)


class _Inner:
    def __init__(self):
        self.writes = []

    def find_page(self, title, source_page_id=None):
        return {"id": "rl-1"}

    def is_created_by_integration(self, page):
        return True

    def type_page_ids(self, names):
        return {"Psychology": "t-psy"}

    def list_blocks(self, page_id):
        return [{"type": "paragraph", "id": "real-1"}]

    def append_blocks(self, page_id, blocks, after=None):
        self.writes.append("append")
        return []

    def update_page(self, page_id, properties=None, cover_url=None, icon_url=None):
        self.writes.append("update")

    def data_source_id(self, database_id):
        return "ds-1"

    def create_card_gallery(self, page_id, cards_database_id, book_page_id, after_block_id):
        self.writes.append("gallery")
        return "view-1"


class TestDryRunReadingList(unittest.TestCase):
    def test_writes_never_reach_inner(self):
        inner = _Inner()
        repo = DryRunReadingListRepository(inner)
        with self.assertLogs(
            "src.infrastructure.notion.dry_run_reading_list_repository", level="INFO"
        ):
            created = repo.append_blocks("rl-1", [{"type": "heading_2"}])
            repo.update_page("rl-1", cover_url="https://c/x.jpg")
        self.assertEqual(inner.writes, [])
        self.assertEqual(created[0]["type"], "heading_2")
        self.assertTrue(created[0]["id"].startswith("dry-run-"))

    def test_list_blocks_includes_blocks_written_this_run(self):
        repo = DryRunReadingListRepository(_Inner())
        repo.append_blocks("rl-1", [{"type": "heading_2"}])
        self.assertEqual([b["id"] for b in repo.list_blocks("rl-1")][0], "real-1")
        self.assertEqual(len(repo.list_blocks("rl-1")), 2)
        self.assertEqual(len(repo.list_blocks("other-page")), 1)

    def test_reads_delegate(self):
        repo = DryRunReadingListRepository(_Inner())
        self.assertEqual(repo.find_page("書", "kobo-1"), {"id": "rl-1"})
        self.assertTrue(repo.is_created_by_integration({}))
        self.assertEqual(repo.type_page_ids(["Psychology"]), {"Psychology": "t-psy"})

    def test_views_create_is_logged_only(self):
        inner = _Inner()
        views = DryRunNotionViewsClient(inner)
        with self.assertLogs(
            "src.infrastructure.notion.dry_run_reading_list_repository", level="INFO"
        ):
            self.assertIsNone(views.create_card_gallery("rl-1", "cards", "rl-1", "h-1"))
        self.assertEqual(inner.writes, [])
        self.assertEqual(views.data_source_id("cards"), "ds-1")


class TestContainerWiring(unittest.TestCase):
    def _settings(self, **overrides):
        fields = dict(notion_token="t", notion_database_id="d",
                      notion_books_database_id="books", notion_zettelkasten_database_id="cards",
                      reading_list_pages=["all"], dry_run=False)
        fields.update(overrides)
        return Settings(**fields)

    def test_page_use_case_built_when_enabled(self):
        uc = build_use_case(self._settings())
        self.assertIsInstance(uc.page_use_case, CompleteReadingListPageUseCase)
        self.assertTrue(uc.should_complete_page("任何書"))

    def test_dry_run_wraps_writes(self):
        uc = build_use_case(self._settings(dry_run=True))
        self.assertIsInstance(uc.page_use_case._reading_list, DryRunReadingListRepository)
        self.assertIsInstance(uc.page_use_case._views, DryRunNotionViewsClient)

    def test_disabled_by_default(self):
        uc = build_use_case(self._settings(reading_list_pages=[]))
        self.assertIsNone(uc.page_use_case)
        self.assertFalse(uc.should_complete_page("任何書"))

    def test_missing_books_database_disables(self):
        uc = build_use_case(self._settings(notion_books_database_id=None))
        self.assertIsNone(uc.page_use_case)

    def test_missing_cards_database_keeps_layout_only(self):
        uc = build_use_case(self._settings(notion_zettelkasten_database_id=None))
        self.assertIsNone(uc.page_use_case._views)
        self.assertIsNone(uc.page_use_case._card_repo)


if __name__ == "__main__":
    unittest.main()
