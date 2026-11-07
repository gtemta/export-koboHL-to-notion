"""劃線頁封面：沒封面就補；舊 Open Library 透明圖重驗不過就換掉或清掉；有效封面不重驗；
非舊 Open Library 的既有封面（emoji、file、使用者手動設定的其他 external）一律信任；
讀取頁面失敗時完全不寫入。

封面一律是上傳到 Notion 的檔案（file_upload）：Kobo 圖床會擋 Notion 的伺服器，舊版寫下的
Kobo 圖床網址在 Notion 裡是「Permission denied」，要逐欄（icon／cover）換掉。"""
import unittest
from types import SimpleNamespace

from src.domain.entities.book import Book
from src.infrastructure.notion.notion_api_repository import NotionApiRepository

LEGACY = "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg"
KOBO = "https://cdn.kobo.com/book-images/img-1/353/569/90/False/image.jpg"
GOOGLE = "http://books.google.com/books/content?id=x&zoom=3"
BOOK = Book(id="b1", title="多巴胺國度", isbn="9786267195185", image_id="img-1")
FILE_ID = "file-1"
FILE_REF = {"type": "file_upload", "file_upload": {"id": FILE_ID}}


class _NoWait:
    def wait(self):
        pass


class _FakeFinder:
    """只負責重驗舊 Open Library 網址。"""

    def __init__(self, valid=()):
        self.valid = set(valid)

    def is_valid_image(self, url):
        return url in self.valid


class _FakeUploader:
    """found=False：哪裡都找不到封面；fail=True：找到了但上傳失敗。"""

    def __init__(self, found=True, fail=False, valid=()):
        self.found = found
        self.fail = fail
        self.finder = _FakeFinder(valid)
        self.upload_calls = 0

    def upload(self, book):
        self.upload_calls += 1
        if self.fail:
            raise RuntimeError("upload down")
        return FILE_ID if self.found else None


class _FakeClient:
    def __init__(self, page):
        self.page = page
        self.updates = []
        self.pages = SimpleNamespace(retrieve=lambda page_id: self.page,
                                     update=self._update)

    def _update(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def _ext(url):
    return {"type": "external", "external": {"url": url}}


def _repo(page, uploader):
    repo = NotionApiRepository.__new__(NotionApiRepository)
    repo._client = _FakeClient(page)
    repo._rate_limiter = _NoWait()
    repo._database_id = "db"
    repo._cover_uploader = uploader
    repo._cover_finder = uploader.finder
    return repo


class _RaisingClient:
    """pages.retrieve 直接炸掉，模擬查詢封面狀態失敗（例如頁面被刪、網路中斷）。"""

    def __init__(self):
        self.updates = []
        self.pages = SimpleNamespace(retrieve=self._retrieve, update=self._update)

    def _retrieve(self, page_id):
        raise RuntimeError("boom")

    def _update(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def _repo_with_raising_retrieve(uploader):
    repo = NotionApiRepository.__new__(NotionApiRepository)
    repo._client = _RaisingClient()
    repo._rate_limiter = _NoWait()
    repo._database_id = "db"
    repo._cover_uploader = uploader
    repo._cover_finder = uploader.finder
    return repo


class TestAddBookCover(unittest.TestCase):
    def test_page_without_cover_gets_one(self):
        repo = _repo({"icon": None, "cover": None}, _FakeUploader())
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": FILE_REF, "cover": FILE_REF}])

    def test_valid_existing_cover_untouched(self):
        uploader = _FakeUploader()
        repo = _repo({"icon": _ext(GOOGLE), "cover": _ext(GOOGLE)}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(uploader.upload_calls, 0)

    def test_broken_legacy_cover_replaced(self):
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, _FakeUploader())
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": FILE_REF, "cover": FILE_REF}])

    def test_broken_legacy_cover_cleared_when_nothing_found(self):
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, _FakeUploader(found=False))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": None, "cover": None}])

    def test_legacy_url_that_still_works_is_kept(self):
        uploader = _FakeUploader(valid={LEGACY})
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(uploader.upload_calls, 0)

    def test_nothing_found_and_no_existing_cover(self):
        repo = _repo({"icon": None, "cover": None}, _FakeUploader(found=False))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])

    def test_emoji_icon_without_cover_is_trusted(self):
        uploader = _FakeUploader()
        repo = _repo({"icon": {"type": "emoji", "emoji": "📚"}, "cover": None}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(uploader.upload_calls, 0)

    def test_file_cover_without_icon_is_trusted(self):
        uploader = _FakeUploader()
        file_cover = {"type": "file", "file": {"url": "https://s3.example.com/x.png"}}
        repo = _repo({"icon": None, "cover": file_cover}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(uploader.upload_calls, 0)

    def test_mixed_broken_legacy_icon_and_user_file_cover_is_trusted(self):
        uploader = _FakeUploader()
        file_cover = {"type": "file", "file": {"url": "https://s3.example.com/x.png"}}
        repo = _repo({"icon": _ext(LEGACY), "cover": file_cover}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(uploader.upload_calls, 0)

    def test_retrieve_failure_skips_write_and_logs_warning(self):
        uploader = _FakeUploader()
        repo = _repo_with_raising_retrieve(uploader)
        with self.assertLogs(
                "src.infrastructure.notion.notion_api_repository", level="WARNING"):
            repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(uploader.upload_calls, 0)


class TestKoboCdnVisuals(unittest.TestCase):
    """舊版把 Kobo 圖床網址直接寫成 icon／cover：Notion 讀不到（Permission denied），
    逐欄換成上傳的書封；另一欄若是使用者自己設的就不動。"""

    def test_kobo_cdn_icon_and_cover_are_replaced(self):
        uploader = _FakeUploader()
        repo = _repo({"icon": _ext(KOBO), "cover": _ext(KOBO)}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": FILE_REF, "cover": FILE_REF}])
        self.assertEqual(uploader.upload_calls, 1)

    def test_only_the_kobo_slot_is_replaced(self):
        emoji = {"type": "emoji", "emoji": "📚"}
        repo = _repo({"icon": emoji, "cover": _ext(KOBO)}, _FakeUploader())
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [{"page_id": "page-1", "cover": FILE_REF}])

    def test_kobo_icon_is_replaced_even_when_the_cover_is_the_users(self):
        file_cover = {"type": "file", "file": {"url": "https://s3.example.com/x.png"}}
        repo = _repo({"icon": _ext(KOBO), "cover": file_cover}, _FakeUploader())
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [{"page_id": "page-1", "icon": FILE_REF}])

    def test_upload_failure_writes_nothing_and_warns(self):
        repo = _repo({"icon": _ext(KOBO), "cover": _ext(KOBO)}, _FakeUploader(fail=True))
        with self.assertLogs(
                "src.infrastructure.notion.notion_api_repository", level="WARNING") as logs:
            repo.add_book_cover("page-1", BOOK)
        self.assertTrue(any("封面上傳失敗" in line for line in logs.output))
        self.assertEqual(repo._client.updates, [])

    def test_kobo_visuals_are_not_cleared_when_no_cover_is_found(self):
        """找不到只代表這輪沒查到（例如圖床暫時連不上），不要因此把頁面清空。"""
        repo = _repo({"icon": _ext(KOBO), "cover": _ext(KOBO)}, _FakeUploader(found=False))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])

    def test_already_uploaded_cover_is_not_touched_again(self):
        uploaded = {"type": "file", "file": {"url": "https://prod-files/x.jpg"}}
        uploader = _FakeUploader()
        repo = _repo({"icon": uploaded, "cover": uploaded}, uploader)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual((repo._client.updates, uploader.upload_calls), ([], 0))


if __name__ == "__main__":
    unittest.main()
