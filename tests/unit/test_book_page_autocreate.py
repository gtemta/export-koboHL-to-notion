"""Unit tests for Reading-List auto-creation when a book has no page:
status derivation, create-page payload, and Kobo-relation backfill."""
import unittest

from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)


class _FakeLimiter:
    def wait(self):
        pass


class _FakePages:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.created.append(kwargs)
        return {"id": "new-books-page"}

    def update(self, **kwargs):
        self._parent.updated.append(kwargs)
        return {}


class _FakeDatabases:
    def __init__(self, parent, books_schema):
        self._parent = parent
        self._books_schema = books_schema

    def retrieve(self, database_id):
        return {"properties": self._books_schema}

    def query(self, **kwargs):
        self._parent.queries.append(kwargs)
        return {"results": [], "has_more": False}


class _FakeClient:
    def __init__(self, books_schema):
        self.created = []
        self.updated = []
        self.queries = []
        self.pages = _FakePages(self)
        self.databases = _FakeDatabases(self, books_schema)


_FULL_BOOKS_SCHEMA = {
    "Name": {"type": "title"},
    "Kobo EReader": {"type": "relation"},
    "Status": {"type": "select"},
}


def _make_repo(books_schema=None):
    repo = ZettelkastenCardRepository(
        token="fake-token",
        database_id="cards-db",
        books_database_id="books-db",
        rate_limiter=_FakeLimiter(),
    )
    repo._client = _FakeClient(
        _FULL_BOOKS_SCHEMA if books_schema is None else books_schema
    )
    return repo


class TestBookStatusName(unittest.TestCase):
    def test_finished_book(self):
        self.assertEqual(
            ZettelkastenCardRepository._book_status_name(100), "🔖閱讀完畢")
        self.assertEqual(
            ZettelkastenCardRepository._book_status_name(99), "🔖閱讀完畢")

    def test_in_progress_book(self):
        self.assertEqual(
            ZettelkastenCardRepository._book_status_name(42), "📖 閱讀中")

    def test_unknown_progress_counts_as_reading(self):
        self.assertEqual(
            ZettelkastenCardRepository._book_status_name(None), "📖 閱讀中")


class TestCreateBookPage(unittest.TestCase):
    def test_full_payload(self):
        repo = _make_repo()
        page_id = repo._create_book_page("多巴胺國度：副標", "kobo-page-1", 100)
        self.assertEqual(page_id, "new-books-page")

        created = repo._client.created[0]
        self.assertEqual(created["parent"], {"database_id": "books-db"})
        props = created["properties"]
        self.assertEqual(
            props["Name"]["title"][0]["text"]["content"], "多巴胺國度：副標")
        self.assertEqual(
            props["Kobo EReader"]["relation"], [{"id": "kobo-page-1"}])
        self.assertEqual(props["Status"]["select"]["name"], "🔖閱讀完畢")

    def test_no_source_page_skips_relation(self):
        repo = _make_repo()
        repo._create_book_page("佛教入門", None, 50)
        props = repo._client.created[0]["properties"]
        self.assertNotIn("Kobo EReader", props)
        self.assertEqual(props["Status"]["select"]["name"], "📖 閱讀中")

    def test_missing_schema_columns_skipped(self):
        repo = _make_repo(books_schema={"Name": {"type": "title"}})
        repo._create_book_page("佛教入門", "kobo-page-1", 100)
        props = repo._client.created[0]["properties"]
        self.assertEqual(set(props.keys()), {"Name"})

    def test_no_books_database_returns_none(self):
        repo = ZettelkastenCardRepository(
            token="fake-token", database_id="cards-db",
            books_database_id=None, rate_limiter=_FakeLimiter(),
        )
        self.assertIsNone(repo._create_book_page("x", None, None))


class TestBackfillKoboRelation(unittest.TestCase):
    def _page(self, relation):
        return {
            "id": "books-page-1",
            "properties": {
                "Name": {"type": "title", "title": []},
                "Kobo EReader": {"type": "relation", "relation": relation},
            },
        }

    def test_fills_empty_relation(self):
        repo = _make_repo()
        repo._backfill_kobo_relation(self._page([]), "kobo-page-1")
        updated = repo._client.updated[0]
        self.assertEqual(updated["page_id"], "books-page-1")
        self.assertEqual(
            updated["properties"]["Kobo EReader"]["relation"],
            [{"id": "kobo-page-1"}],
        )

    def test_existing_relation_untouched(self):
        repo = _make_repo()
        repo._backfill_kobo_relation(
            self._page([{"id": "already-linked"}]), "kobo-page-1")
        self.assertEqual(repo._client.updated, [])

    def test_page_without_property_untouched(self):
        repo = _make_repo()
        repo._backfill_kobo_relation(
            {"id": "p", "properties": {"Name": {"type": "title"}}}, "kobo-page-1")
        self.assertEqual(repo._client.updated, [])


class TestFindBookPageAutoCreates(unittest.TestCase):
    def test_falls_through_to_create(self):
        repo = _make_repo()
        page_id = repo._find_book_page("完全不存在的書", "kobo-page-1", 100)
        self.assertEqual(page_id, "new-books-page")
        # reverse lookup + equals + contains queries all ran and found nothing
        self.assertGreaterEqual(len(repo._client.queries), 3)


if __name__ == "__main__":
    unittest.main()
