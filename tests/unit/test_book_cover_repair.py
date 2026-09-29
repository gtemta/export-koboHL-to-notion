"""劃線頁封面：沒封面就補；舊 Open Library 透明圖重驗不過就換掉或清掉；有效封面不重驗。"""
import unittest
from types import SimpleNamespace

from src.domain.entities.book import Book
from src.infrastructure.notion.notion_api_repository import NotionApiRepository

LEGACY = "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg"
KOBO = "https://cdn.kobo.com/book-images/img-1/353/569/90/False/image.jpg"
GOOGLE = "http://books.google.com/books/content?id=x&zoom=3"
BOOK = Book(id="b1", title="多巴胺國度", isbn="9786267195185", image_id="img-1")


class _NoWait:
    def wait(self):
        pass


class _FakeFinder:
    def __init__(self, found=None, valid=()):
        self.found = found
        self.valid = set(valid)
        self.find_calls = 0

    def find(self, book):
        self.find_calls += 1
        return self.found

    def is_valid_image(self, url):
        return url in self.valid


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


def _repo(page, finder):
    repo = NotionApiRepository.__new__(NotionApiRepository)
    repo._client = _FakeClient(page)
    repo._rate_limiter = _NoWait()
    repo._database_id = "db"
    repo._cover_finder = finder
    return repo


class TestAddBookCover(unittest.TestCase):
    def test_page_without_cover_gets_one(self):
        repo = _repo({"icon": None, "cover": None}, _FakeFinder(found=KOBO))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": _ext(KOBO), "cover": _ext(KOBO)}])

    def test_valid_existing_cover_untouched(self):
        finder = _FakeFinder(found=KOBO)
        repo = _repo({"icon": _ext(GOOGLE), "cover": _ext(GOOGLE)}, finder)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(finder.find_calls, 0)

    def test_broken_legacy_cover_replaced(self):
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, _FakeFinder(found=KOBO))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": _ext(KOBO), "cover": _ext(KOBO)}])

    def test_broken_legacy_cover_cleared_when_nothing_found(self):
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, _FakeFinder(found=None))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": None, "cover": None}])

    def test_legacy_url_that_still_works_is_kept(self):
        finder = _FakeFinder(found=KOBO, valid={LEGACY})
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, finder)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(finder.find_calls, 0)

    def test_nothing_found_and_no_existing_cover(self):
        repo = _repo({"icon": None, "cover": None}, _FakeFinder(found=None))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])


if __name__ == "__main__":
    unittest.main()
