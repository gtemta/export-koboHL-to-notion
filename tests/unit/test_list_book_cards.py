"""ZettelkastenCardRepository.list_book_cards — 依「來源」讀回某本書的卡片（屬性）。"""
import unittest
from types import SimpleNamespace

from src.infrastructure.notion.zettelkasten_card_repository import (
    _SOURCE_ID_PROPERTY,
    ZettelkastenCardRepository,
)


class _NoWait:
    def wait(self):
        pass


def _card(pid, title, tags, keyword):
    return {"id": pid, "properties": {
        "標題": {"type": "title", "title": [{"plain_text": title}]},
        "Tags": {"type": "multi_select", "multi_select": [{"name": t} for t in tags]},
        "Key Word": {"type": "rich_text",
                     "rich_text": [{"plain_text": keyword}] if keyword else []},
    }}


def _source_page(pid, source_id):
    return {"id": pid, "properties": {
        _SOURCE_ID_PROPERTY: {"rich_text": [{"plain_text": source_id}]},
    }}


class _FakeClient:
    def __init__(self, pages_by_cursor=None, error=None):
        self.queries = []
        self._pages = pages_by_cursor or {}
        self._error = error
        self.databases = SimpleNamespace(query=self._query)

    def _query(self, **kwargs):
        self.queries.append(kwargs)
        if self._error:
            raise self._error
        return self._pages[kwargs.get("start_cursor")]


def _repo(client):
    repo = ZettelkastenCardRepository(token="dummy", database_id="cards-db",
                                      rate_limiter=_NoWait())
    repo._client = client
    return repo


class TestListBookCards(unittest.TestCase):
    def test_paginates_and_parses(self):
        client = _FakeClient({
            None: {"results": [_card("c1", "卡一", ["💞心理學"], "成癮、延遲滿足")],
                   "has_more": True, "next_cursor": "p2"},
            "p2": {"results": [_card("c2", "卡二", [], "語言學・社會合作")],
                   "has_more": False},
        })
        cards = _repo(client).list_book_cards("rl-1")
        self.assertEqual([c.page_id for c in cards], ["c1", "c2"])
        self.assertEqual(cards[0].title, "卡一")
        self.assertEqual(cards[0].tags, ["💞心理學"])
        self.assertEqual(cards[0].keywords, ["成癮", "延遲滿足"])
        self.assertEqual(cards[1].keywords, ["語言學", "社會合作"])
        self.assertEqual(
            client.queries[0]["filter"], {"property": "來源", "relation": {"contains": "rl-1"}})
        self.assertEqual(client.queries[0]["database_id"], "cards-db")

    def test_query_failure_returns_empty(self):
        client = _FakeClient(error=RuntimeError("boom"))
        with self.assertLogs(
            "src.infrastructure.notion.zettelkasten_card_repository", level="WARNING"
        ):
            self.assertEqual(_repo(client).list_book_cards("rl-1"), [])


class TestExistingSourceIds(unittest.TestCase):
    """_existing_source_ids shares _cards_linked_to's pagination with
    list_book_cards — this covers that shared loop from the other caller."""

    def test_paginates_and_collects_ids(self):
        client = _FakeClient({
            None: {"results": [_source_page("c1", "BM-1")],
                   "has_more": True, "next_cursor": "p2"},
            "p2": {"results": [_source_page("c2", "BM-2")],
                   "has_more": False},
        })
        ids, total = _repo(client)._existing_source_ids("rl-1")
        self.assertEqual(ids, {"BM-1", "BM-2"})
        self.assertEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
