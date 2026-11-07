"""卡片盒的「做圖」勾選欄：建欄與讀出被勾選的卡。"""
import unittest
from types import SimpleNamespace

from src.infrastructure.notion.zettelkasten_card_repository import (
    _SOURCE_ID_PROPERTY,
    ZettelkastenCardRepository,
)


class _NoWait:
    def wait(self):
        pass


def _page(pid, title, source_id):
    props = {"標題": {"type": "title", "title": [{"plain_text": title}]}}
    props[_SOURCE_ID_PROPERTY] = {
        "type": "rich_text", "rich_text": [{"plain_text": source_id}] if source_id else [],
    }
    return {"id": pid, "properties": props}


class _FakeDatabases:
    def __init__(self, props=None, pages_by_cursor=None, retrieve_error=None):
        self.props = props if props is not None else {"標題": {}, "做圖": {}}
        self.pages = pages_by_cursor or {None: {"results": [], "has_more": False}}
        self.retrieve_error = retrieve_error
        self.queries, self.updates = [], []

    def retrieve(self, database_id):
        if self.retrieve_error:
            raise self.retrieve_error
        return {"properties": self.props}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.pages[kwargs.get("start_cursor")]

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def _repo(databases):
    repo = ZettelkastenCardRepository(token="dummy", database_id="cards-db",
                                      rate_limiter=_NoWait())
    repo._client = SimpleNamespace(databases=databases)
    return repo


class TestListMarked(unittest.TestCase):
    def test_returns_title_and_source_id_and_paginates(self):
        dbs = _FakeDatabases(pages_by_cursor={
            None: {"results": [_page("p1", "卡一", "BM-1")], "has_more": True, "next_cursor": "c2"},
            "c2": {"results": [_page("p2", "卡二", "BM-2")], "has_more": False},
        })
        marked = _repo(dbs).list_cards_marked_for_infographic()
        self.assertEqual([(m.page_id, m.title, m.source_id) for m in marked],
                         [("p1", "卡一", "BM-1"), ("p2", "卡二", "BM-2")])

    def test_queries_only_checked_cards(self):
        dbs = _FakeDatabases()
        _repo(dbs).list_cards_marked_for_infographic()
        self.assertEqual(dbs.queries[0]["filter"],
                         {"property": "做圖", "checkbox": {"equals": True}})
        self.assertEqual(dbs.queries[0]["database_id"], "cards-db")

    def test_card_without_source_id_is_still_listed_with_empty_id(self):
        dbs = _FakeDatabases(pages_by_cursor={
            None: {"results": [_page("p1", "手動卡", "")], "has_more": False}})
        marked = _repo(dbs).list_cards_marked_for_infographic()
        self.assertEqual((marked[0].title, marked[0].source_id), ("手動卡", ""))

    def test_missing_column_means_nothing_marked_and_no_query(self):
        dbs = _FakeDatabases(props={"標題": {}})
        self.assertEqual(_repo(dbs).list_cards_marked_for_infographic(), [])
        self.assertEqual(dbs.queries, [])

    def test_unreadable_schema_still_tries_the_query(self):
        dbs = _FakeDatabases(retrieve_error=RuntimeError("boom"))
        _repo(dbs).list_cards_marked_for_infographic()
        self.assertEqual(len(dbs.queries), 1)


class TestEnsureColumn(unittest.TestCase):
    def test_creates_a_checkbox_column_when_absent(self):
        dbs = _FakeDatabases(props={"標題": {}})
        created = _repo(dbs).ensure_infographic_column()
        self.assertTrue(created)
        self.assertEqual(dbs.updates[0]["properties"], {"做圖": {"checkbox": {}}})
        self.assertEqual(dbs.updates[0]["database_id"], "cards-db")

    def test_leaves_an_existing_column_alone(self):
        dbs = _FakeDatabases(props={"標題": {}, "做圖": {}})
        self.assertFalse(_repo(dbs).ensure_infographic_column())
        self.assertEqual(dbs.updates, [])

    def test_ensure_does_not_touch_the_sync_time_schema(self):
        # 一般同步的 _schema_additions 不該因為這個功能多出欄位
        add = ZettelkastenCardRepository._schema_additions({})
        self.assertNotIn("做圖", add)


if __name__ == "__main__":
    unittest.main()
