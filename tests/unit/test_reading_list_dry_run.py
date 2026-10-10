"""Reading List 補頁的 DRY_RUN decorator 與 container 組裝。"""
import unittest

from src.application.use_cases.complete_reading_list_page_use_case import (
    CompleteReadingListPageUseCase,
)
from src.config.settings import Settings
from src.domain.entities.book import Book
from src.infrastructure.container import build_use_case
from src.infrastructure.external.cover_fetcher import CoverImage
from src.infrastructure.notion.cover_uploader import CoverUploader
from src.infrastructure.notion.dry_run_notion_repository import DRY_RUN_PAGE_ID_PREFIX
from src.infrastructure.notion.dry_run_reading_list_repository import (
    DryRunCoverUploader,
    DryRunNotionViewsClient,
    DryRunReadingListRepository,
)


class _Inner:
    def __init__(self):
        self.writes = []
        self.find_page_calls = []

    def find_page(self, title, source_page_id=None):
        self.find_page_calls.append((title, source_page_id))
        return {"id": "rl-1"}

    def is_created_by_integration(self, page):
        return True

    def type_page_ids(self, names):
        return {"Psychology": "t-psy"}

    def book_types_available(self):
        return True

    def list_blocks(self, page_id):
        return [{"type": "paragraph", "id": "real-1"}]

    def append_blocks(self, page_id, blocks, after=None):
        self.writes.append("append")
        return []

    def update_page(self, page_id, properties=None, cover_file_id=None, icon_file_id=None):
        self.writes.append("update")

    def replace_image(self, block_id, file_id):
        self.writes.append("replace_image")

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
            repo.update_page("rl-1", cover_file_id="file-1")
            repo.replace_image("blk-1", "file-1")
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
        self.assertTrue(repo.book_types_available())

    def test_views_create_is_logged_only(self):
        inner = _Inner()
        views = DryRunNotionViewsClient(inner)
        with self.assertLogs(
            "src.infrastructure.notion.dry_run_reading_list_repository", level="INFO"
        ):
            self.assertIsNone(views.create_card_gallery("rl-1", "cards", "rl-1", "h-1"))
        self.assertEqual(inner.writes, [])
        self.assertEqual(views.data_source_id("cards"), "ds-1")


class _Finder:
    def __init__(self, image):
        self.image = image
        self.calls = 0

    def find_image(self, book):
        self.calls += 1
        return self.image


class _InnerUploader:
    def __init__(self, image):
        self.finder = _Finder(image)
        self.uploads = 0

    def upload(self, book):
        self.uploads += 1
        return "real-file-id"


_IMAGE = CoverImage(url="https://cdn.kobo.com/x.jpg", content_type="image/jpeg",
                    data=b"x" * 5000, source="kobo")


class TestDryRunCoverUploader(unittest.TestCase):
    """預覽時照常查封面（讀取），但絕不真的上傳給 Notion。"""

    def test_never_uploads_but_reports_a_fake_id_when_a_cover_exists(self):
        inner = _InnerUploader(_IMAGE)
        uploader = DryRunCoverUploader(inner)
        with self.assertLogs(
            "src.infrastructure.notion.dry_run_reading_list_repository", level="INFO"
        ) as logs:
            file_id = uploader.upload(Book(id="b1", title="多巴胺國度"))
        self.assertEqual(inner.uploads, 0)
        self.assertEqual(inner.finder.calls, 1)
        self.assertTrue(file_id.startswith("dry-run-"))
        self.assertTrue(any("多巴胺國度" in line and "[DRY RUN]" in line for line in logs.output))

    def test_no_cover_means_none_and_no_log(self):
        inner = _InnerUploader(None)
        self.assertIsNone(DryRunCoverUploader(inner).upload(Book(id="b1", title="書")))
        self.assertEqual(inner.uploads, 0)


class TestFindPageDryRunSourceId(unittest.TestCase):
    """F3：DRY_RUN 本輪建立的假 page id 不可流入 find_page 的反查。"""

    def test_fake_prefixed_id_reaches_inner_as_none(self):
        inner = _Inner()
        repo = DryRunReadingListRepository(inner)
        repo.find_page("書", f"{DRY_RUN_PAGE_ID_PREFIX}3")
        self.assertEqual(inner.find_page_calls, [("書", None)])

    def test_real_id_passes_through_unchanged(self):
        inner = _Inner()
        repo = DryRunReadingListRepository(inner)
        repo.find_page("書", "real-kobo-page-id")
        self.assertEqual(inner.find_page_calls, [("書", "real-kobo-page-id")])


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

    def test_dry_run_never_uploads_covers(self):
        uc = build_use_case(self._settings(dry_run=True))
        self.assertIsInstance(uc.page_use_case._cover_uploader, DryRunCoverUploader)

    def test_real_run_uploads_covers_and_both_cover_steps_share_one_uploader(self):
        """劃線頁與書頁補完共用同一個 uploader：同一本書本輪只上傳一次。"""
        uc = build_use_case(self._settings())
        self.assertIsInstance(uc.page_use_case._cover_uploader, CoverUploader)
        self.assertIs(uc.notion_repo._cover_uploader, uc.page_use_case._cover_uploader)

    def test_disabled_by_default(self):
        uc = build_use_case(self._settings(reading_list_pages=[]))
        self.assertIsNone(uc.page_use_case)
        self.assertFalse(uc.should_complete_page("任何書"))

    def test_missing_books_database_disables(self):
        uc = build_use_case(self._settings(notion_books_database_id=None))
        self.assertIsNone(uc.page_use_case)

    def test_card_repo_shares_reading_list_rate_limiter(self):
        """F6：卡片寫入與書頁補完共用同一個限速器，不是各自一個 ~3 req/s。"""
        uc = build_use_case(self._settings(enable_zettelkasten_cards=True))
        self.assertIsNotNone(uc.card_use_case)
        self.assertIs(
            uc.card_use_case._card_repo._rate_limiter,
            uc.page_use_case._reading_list._rate_limiter)

    def test_missing_cards_database_keeps_layout_only(self):
        uc = build_use_case(self._settings(notion_zettelkasten_database_id=None))
        self.assertIsNone(uc.page_use_case._views)
        self.assertIsNone(uc.page_use_case._card_repo)


if __name__ == "__main__":
    unittest.main()
