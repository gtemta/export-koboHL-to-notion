"""卡片盒的看板欄位：建欄、讀出全部卡片、寫回角色／順序／相關卡片。"""
import unittest
from types import SimpleNamespace

from src.domain.entities.board_card import CardUpdate
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)


class _NoWait:
    def wait(self):
        pass


def _full_page(pid="p1"):
    return {
        "id": pid,
        "created_time": "2026-10-01T00:00:00.000Z",
        "properties": {
            "標題": {"type": "title", "title": [{"plain_text": "卡"}, {"plain_text": "一"}]},
            "來源": {"type": "relation", "relation": [{"id": "book-1"}, {"id": "book-2"}]},
            "來源劃線ID": {"type": "rich_text", "rich_text": [{"plain_text": "BM-1"}]},
            "角色": {"type": "select", "select": {"name": "主軸"}},
            "閱讀順序": {"type": "number", "number": 25.5},
            "相關卡片": {
                "type": "relation",
                "relation": [{"id": "a"}, {"id": "b"}],
                "has_more": False,
            },
        },
    }


def _bare_page(pid="p2"):
    return {
        "id": pid,
        "created_time": "2026-10-02T00:00:00.000Z",
        "properties": {"標題": {"type": "title", "title": [{"plain_text": "只有標題"}]}},
    }


class _Fake:
    def __init__(self, db_properties=None, pages=None, blocks=None):
        self.db_properties = db_properties if db_properties is not None else {"標題": {}}
        self.pages_result = pages or []
        self.blocks_result = blocks or []
        self.db_updates, self.queries = [], []
        self.page_updates, self.block_lists = [], []
        self.databases = SimpleNamespace(
            retrieve=self._retrieve, update=self._update, query=self._query,
        )
        self.pages = SimpleNamespace(update=self._page_update)
        self.blocks = SimpleNamespace(children=SimpleNamespace(list=self._block_list))

    def _retrieve(self, database_id):
        return {"properties": dict(self.db_properties)}

    def _update(self, **kwargs):
        self.db_updates.append(kwargs)
        for name in kwargs["properties"]:
            self.db_properties[name] = {}
        return {}

    def _query(self, **kwargs):
        self.queries.append(kwargs)
        return {"results": self.pages_result, "has_more": False}

    def _page_update(self, page_id, properties):
        self.page_updates.append((page_id, properties))
        return {}

    def _block_list(self, **kwargs):
        self.block_lists.append(kwargs)
        return {"results": self.blocks_result}


def _repo(fake):
    repo = ZettelkastenCardRepository(token="dummy", database_id="db",
                                      rate_limiter=_NoWait())
    repo._client = fake
    return repo


class TestEnsureColumns(unittest.TestCase):
    def test_columns_are_created_once_in_option_order(self):
        fake = _Fake({"標題": {}})
        repo = _repo(fake)
        self.assertEqual(set(repo.ensure_card_board_columns()),
                         {"角色", "閱讀順序", "相關卡片"})
        self.assertEqual(len(fake.db_updates), 1)
        props = fake.db_updates[0]["properties"]
        self.assertEqual([o["name"] for o in props["角色"]["select"]["options"]],
                         ["主軸", "支柱", "案例"])
        self.assertEqual(props["閱讀順序"], {"number": {}})
        self.assertEqual(
            props["相關卡片"],
            {"relation": {"database_id": "db", "type": "single_property",
                          "single_property": {}}},
        )

    def test_second_call_in_same_process_is_a_no_op(self):
        fake = _Fake({"標題": {}})
        repo = _repo(fake)
        repo.ensure_card_board_columns()
        self.assertEqual(repo.ensure_card_board_columns(), [])
        self.assertEqual(len(fake.db_updates), 1)

    def test_existing_columns_are_left_alone(self):
        fake = _Fake({"角色": {}, "閱讀順序": {}, "相關卡片": {}})
        self.assertEqual(_repo(fake).ensure_card_board_columns(), [])
        self.assertEqual(fake.db_updates, [])

    def test_only_missing_columns_are_added(self):
        fake = _Fake({"標題": {}, "角色": {}})
        self.assertEqual(set(_repo(fake).ensure_card_board_columns()),
                         {"閱讀順序", "相關卡片"})
        self.assertEqual(set(fake.db_updates[0]["properties"]),
                         {"閱讀順序", "相關卡片"})

    def test_unreadable_schema_writes_nothing(self):
        fake = _Fake()
        fake.databases.retrieve = lambda database_id: (_ for _ in ()).throw(
            RuntimeError("boom"))
        self.assertEqual(_repo(fake).ensure_card_board_columns(), [])
        self.assertEqual(fake.db_updates, [])

    def test_ordinary_sync_does_not_create_board_columns(self):
        fake = _Fake({"標題": {}})
        _repo(fake).ensure_schema()
        for update in fake.db_updates:
            self.assertFalse({"角色", "閱讀順序", "相關卡片"} & set(update["properties"]))


class TestListBoardCards(unittest.TestCase):
    def test_reads_all_fields_and_treats_missing_columns_as_blank(self):
        fake = _Fake(pages=[_full_page(), _bare_page()])
        full, bare = _repo(fake).list_board_cards()

        self.assertEqual(full.page_id, "p1")
        self.assertEqual(full.title, "卡一")
        self.assertEqual(full.book_page_id, "book-1")
        self.assertEqual(full.source_id, "BM-1")
        self.assertEqual(full.created_time, "2026-10-01T00:00:00.000Z")
        self.assertEqual(full.role, "主軸")
        self.assertEqual(full.reading_order, 25.5)
        self.assertEqual(full.related_ids, ("a", "b"))
        self.assertTrue(full.related_complete)
        self.assertEqual(full.content, "")

        self.assertEqual(bare.title, "只有標題")
        self.assertEqual(bare.book_page_id, "")
        self.assertEqual(bare.source_id, "")
        self.assertEqual(bare.role, "")
        self.assertIsNone(bare.reading_order)
        self.assertEqual(bare.related_ids, ())
        self.assertTrue(bare.related_complete)

    def test_null_select_and_number_are_blank(self):
        page = _bare_page()
        page["properties"]["角色"] = {"type": "select", "select": None}
        page["properties"]["閱讀順序"] = {"type": "number", "number": None}
        card = _repo(_Fake(pages=[page])).list_board_cards()[0]
        self.assertEqual(card.role, "")
        self.assertIsNone(card.reading_order)

    def test_truncated_relation_is_marked_incomplete(self):
        page = _full_page()
        page["properties"]["相關卡片"]["has_more"] = True
        card = _repo(_Fake(pages=[page])).list_board_cards()[0]
        self.assertFalse(card.related_complete)

    def test_queries_every_titled_card(self):
        fake = _Fake()
        _repo(fake).list_board_cards()
        self.assertEqual(fake.queries[0]["filter"],
                         {"property": "標題", "title": {"is_not_empty": True}})

    def test_api_failure_propagates(self):
        fake = _Fake()

        def boom(**kwargs):
            raise RuntimeError("query failed")

        fake.databases.query = boom
        with self.assertRaises(RuntimeError):
            _repo(fake).list_board_cards()


class TestCardText(unittest.TestCase):
    def test_joins_top_level_paragraphs_only(self):
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": [
                {"plain_text": "第一"}, {"plain_text": "段"}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "不要"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "第二段"}]}},
        ]
        fake = _Fake(blocks=blocks)
        self.assertEqual(_repo(fake).card_text("p1"), "第一段 第二段")
        self.assertEqual(fake.block_lists[0]["block_id"], "p1")

    def test_api_failure_propagates(self):
        fake = _Fake()

        def boom(**kwargs):
            raise RuntimeError("blocks failed")

        fake.blocks.children.list = boom
        with self.assertRaises(RuntimeError):
            _repo(fake).card_text("p1")


class TestUpdateBoardFields(unittest.TestCase):
    def test_update_sends_only_given_fields(self):
        fake = _Fake()
        _repo(fake).update_board_fields(CardUpdate(page_id="p", reading_order=30))
        self.assertEqual(fake.page_updates, [("p", {"閱讀順序": {"number": 30}})])

    def test_update_writes_role_as_select(self):
        fake = _Fake()
        _repo(fake).update_board_fields(CardUpdate(page_id="p", role="支柱"))
        self.assertEqual(fake.page_updates, [("p", {"角色": {"select": {"name": "支柱"}}})])

    def test_update_writes_full_relation_list(self):
        fake = _Fake()
        _repo(fake).update_board_fields(CardUpdate(page_id="p", related_ids=("a", "b")))
        self.assertEqual(fake.page_updates[0][1],
                         {"相關卡片": {"relation": [{"id": "a"}, {"id": "b"}]}})

    def test_empty_relation_list_clears_the_column(self):
        fake = _Fake()
        _repo(fake).update_board_fields(CardUpdate(page_id="p", related_ids=()))
        self.assertEqual(fake.page_updates[0][1], {"相關卡片": {"relation": []}})

    def test_zero_reading_order_is_still_sent(self):
        fake = _Fake()
        _repo(fake).update_board_fields(CardUpdate(page_id="p", reading_order=0))
        self.assertEqual(fake.page_updates[0][1], {"閱讀順序": {"number": 0}})

    def test_nothing_to_send_makes_no_api_call(self):
        fake = _Fake()
        _repo(fake).update_board_fields(CardUpdate(page_id="p"))
        self.assertEqual(fake.page_updates, [])

    def test_api_failure_propagates(self):
        fake = _Fake()

        def boom(page_id, properties):
            raise RuntimeError("update failed")

        fake.pages.update = boom
        with self.assertRaises(RuntimeError):
            _repo(fake).update_board_fields(CardUpdate(page_id="p", role="主軸"))


if __name__ == "__main__":
    unittest.main()
