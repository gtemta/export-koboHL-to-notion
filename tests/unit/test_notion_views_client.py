"""NotionViewsClient — 全專案唯一使用新版 API 的地方（Views API）。"""
import unittest

from src.infrastructure.notion.notion_views_client import (
    NOTION_VIEWS_API_VERSION,
    NotionViewsClient,
    card_gallery_body,
)


class _NoWait:
    def wait(self):
        pass


class _FakeClient:
    def __init__(self, data_sources=None):
        self.requests = []
        self._data_sources = [{"id": "ds-1"}] if data_sources is None else data_sources

    def request(self, path, method, query=None, body=None, auth=None):
        self.requests.append((method, path, body))
        if path.startswith("databases/"):
            return {"object": "database", "data_sources": self._data_sources}
        if path == "views":
            return {"object": "view", "id": "view-1"}
        raise AssertionError(f"unexpected request {method} {path}")


def _client(fake):
    return NotionViewsClient(token="t", rate_limiter=_NoWait(), client=fake)


class TestCardGalleryBody(unittest.TestCase):
    def test_body_shape(self):
        self.assertEqual(card_gallery_body("ds-1", "page-1", "page-1", "h-notes"), {
            "data_source_id": "ds-1",
            "name": "本書卡片",
            "type": "gallery",
            "create_database": {
                "parent": {"type": "page_id", "page_id": "page-1"},
                "position": {"type": "after_block", "block_id": "h-notes"},
            },
            "filter": {"property": "來源", "relation": {"contains": "page-1"}},
            "sorts": [{"property": "標題", "direction": "ascending"}],
            "configuration": {"type": "gallery", "cover": {"type": "page_cover"}},
        })


class TestNotionViewsClient(unittest.TestCase):
    def test_creates_gallery_after_heading(self):
        fake = _FakeClient()
        view_id = _client(fake).create_card_gallery("page-1", "cards-db", "page-1", "h-notes")
        self.assertEqual(view_id, "view-1")
        self.assertEqual(fake.requests[0][:2], ("GET", "databases/cards-db"))
        method, path, body = fake.requests[1]
        self.assertEqual((method, path), ("POST", "views"))
        self.assertEqual(body, card_gallery_body("ds-1", "page-1", "page-1", "h-notes"))

    def test_data_source_id_cached(self):
        fake = _FakeClient()
        client = _client(fake)
        client.create_card_gallery("p1", "cards-db", "p1", "h1")
        client.create_card_gallery("p2", "cards-db", "p2", "h2")
        db_gets = [r for r in fake.requests if r[1] == "databases/cards-db"]
        self.assertEqual(len(db_gets), 1)

    def test_no_data_source_creates_nothing(self):
        fake = _FakeClient(data_sources=[])
        with self.assertLogs(
            "src.infrastructure.notion.notion_views_client", level="WARNING"
        ):
            self.assertIsNone(_client(fake).create_card_gallery("p1", "cards-db", "p1", "h1"))
        self.assertFalse([r for r in fake.requests if r[1] == "views"])

    def test_default_client_pins_new_api_version(self):
        self.assertEqual(
            NotionViewsClient(token="t")._client.options.notion_version,
            NOTION_VIEWS_API_VERSION)
        self.assertEqual(NOTION_VIEWS_API_VERSION, "2026-03-11")


if __name__ == "__main__":
    unittest.main()
