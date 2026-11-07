"""NotionViewsClient — 全專案唯一使用新版 API 的地方（Views API）。"""
import unittest

from src.infrastructure.notion.notion_views_client import (
    NOTION_VIEWS_API_VERSION,
    NotionViewsClient,
    ViewSwap,
    card_board_body,
    plan_view_swap,
)

ROLE_ID = "%7B%3Da%7D"
ORDER_ID = "%5BC%7DU"


class _NoWait:
    def wait(self):
        pass


class _FakeClient:
    def __init__(self, data_sources=None, views=None, properties=None):
        self.requests = []
        self._data_sources = [{"id": "ds-1"}] if data_sources is None else data_sources
        self._views = list(views or [])
        self._properties = ({"角色": {"id": ROLE_ID}, "閱讀順序": {"id": ORDER_ID}}
                            if properties is None else properties)

    def request(self, path, method, query=None, body=None, auth=None):
        self.requests.append((method, path, body))
        if path.startswith("databases/"):
            return {"object": "database", "data_sources": self._data_sources}
        if path.startswith("data_sources/"):
            return {"object": "data_source", "properties": self._properties}
        if path == "views" and method == "GET":
            assert query == {"database_id": "linked"}, query
            return {"results": [{"object": "view", "id": v["id"]} for v in self._views]}
        if path == "views":
            return {"object": "view", "id": "view-1"}
        if path.startswith("views/") and method == "GET":
            return next(v for v in self._views if v["id"] == path.split("/")[1])
        if path.startswith("views/") and method == "DELETE":
            return {"object": "view", "id": path.split("/")[1]}
        raise AssertionError(f"unexpected request {method} {path}")


def _client(fake):
    return NotionViewsClient(token="t", rate_limiter=_NoWait(), client=fake)


def _view(view_id, name, view_type):
    return {"id": view_id, "name": name, "type": view_type}


def _board_body(placement):
    return card_board_body("ds-1", "page-1", placement, ROLE_ID, ORDER_ID)


class TestCardBoardBody(unittest.TestCase):
    def test_board_body_shape(self):
        placement = {"database_id": "linked"}
        self.assertEqual(card_board_body("ds-1", "page-1", placement, "%7B%3Da%7D", "%5BC%7DU"), {
            "data_source_id": "ds-1",
            "name": "本書卡片",
            "type": "board",
            "database_id": "linked",
            "filter": {"property": "來源", "relation": {"contains": "page-1"}},
            "sorts": [{"property": "閱讀順序", "direction": "ascending"}],
            "configuration": {
                "type": "board",
                "group_by": {"type": "select", "property_id": "%7B%3Da%7D",
                             "sort": {"type": "manual"}, "hide_empty_groups": False},
                "cover": {"type": "page_cover"},
                "properties": [{"property_id": "%5BC%7DU", "visible": True}],
            },
        })

    def test_placement_is_merged_in_as_given(self):
        placement = {"create_database": {
            "parent": {"type": "page_id", "page_id": "page-1"},
            "position": {"type": "after_block", "block_id": "h-notes"}}}
        body = _board_body(placement)
        self.assertEqual(body["create_database"], placement["create_database"])
        self.assertNotIn("database_id", body)


class TestPlanViewSwap(unittest.TestCase):
    def test_gallery_alone_is_swapped(self):
        self.assertEqual(plan_view_swap([_view("g", "本書卡片", "gallery")]), ViewSwap(True, "g"))

    def test_swap_after_interrupted_run_only_deletes_gallery(self):
        views = [_view("g", "本書卡片", "gallery"), _view("b", "本書卡片", "board")]
        self.assertEqual(plan_view_swap(views), ViewSwap(False, "g"))

    def test_board_already_there_needs_nothing(self):
        self.assertEqual(plan_view_swap([_view("b", "本書卡片", "board")]), ViewSwap(False, None))

    def test_other_views_are_left_alone(self):
        for views in ([_view("t", "我的表格", "table")], [_view("r", "改過名", "gallery")]):
            self.assertEqual(plan_view_swap(views), ViewSwap(False, None))

    def test_no_views_needs_nothing(self):
        self.assertEqual(plan_view_swap([]), ViewSwap(False, None))


class TestNotionViewsClient(unittest.TestCase):
    def test_creates_board_after_heading(self):
        fake = _FakeClient()
        view_id = _client(fake).create_card_board("page-1", "cards-db", "page-1", "h-notes")
        self.assertEqual(view_id, "view-1")
        self.assertEqual(fake.requests[0][:2], ("GET", "databases/cards-db"))
        self.assertEqual(fake.requests[1][:2], ("GET", "data_sources/ds-1"))
        method, path, body = fake.requests[2]
        self.assertEqual((method, path), ("POST", "views"))
        self.assertEqual(body, _board_body({"create_database": {
            "parent": {"type": "page_id", "page_id": "page-1"},
            "position": {"type": "after_block", "block_id": "h-notes"}}}))

    def test_data_source_id_cached(self):
        fake = _FakeClient()
        client = _client(fake)
        client.create_card_board("p1", "cards-db", "p1", "h1")
        client.create_card_board("p2", "cards-db", "p2", "h2")
        db_gets = [r for r in fake.requests if r[1] == "databases/cards-db"]
        self.assertEqual(len(db_gets), 1)

    def test_no_data_source_creates_nothing(self):
        fake = _FakeClient(data_sources=[])
        with self.assertLogs(
            "src.infrastructure.notion.notion_views_client", level="WARNING"
        ):
            self.assertIsNone(_client(fake).create_card_board("p1", "cards-db", "p1", "h1"))
        self.assertFalse([r for r in fake.requests if r[1] == "views"])

    def test_board_property_ids_are_read_once_and_passed_encoded(self):
        fake = _FakeClient()
        client = _client(fake)
        self.assertEqual(client.board_property_ids("cards-db"), (ROLE_ID, ORDER_ID))
        client.board_property_ids("cards-db")
        self.assertEqual(len([r for r in fake.requests if r[1] == "data_sources/ds-1"]), 1)

    def test_missing_board_column_raises(self):
        fake = _FakeClient(properties={"閱讀順序": {"id": ORDER_ID}})
        with self.assertRaises(RuntimeError):
            _client(fake).board_property_ids("cards-db")
        fake = _FakeClient(properties={"角色": {"id": ROLE_ID}})
        with self.assertRaises(RuntimeError):
            _client(fake).board_property_ids("cards-db")

    def test_describe_swap_reads_every_view_and_writes_nothing(self):
        fake = _FakeClient(views=[_view("g", "本書卡片", "gallery"), _view("t", "表格", "table")])
        swap = _client(fake).describe_swap("linked")
        self.assertEqual(swap, ViewSwap(True, "g"))
        self.assertEqual([r[:2] for r in fake.requests],
                         [("GET", "views"), ("GET", "views/g"), ("GET", "views/t")])

    def test_swap_adds_before_deleting(self):
        fake = _FakeClient(views=[_view("g", "本書卡片", "gallery")])
        self.assertTrue(_client(fake).swap_gallery_for_board("linked", "cards-db", "page-1"))
        writes = [r for r in fake.requests if r[0] in ("POST", "DELETE")]
        self.assertEqual([w[:2] for w in writes], [("POST", "views"), ("DELETE", "views/g")])
        self.assertEqual(writes[0][2], _board_body({"database_id": "linked"}))

    def test_swap_after_interrupted_run_only_deletes(self):
        fake = _FakeClient(views=[_view("g", "本書卡片", "gallery"), _view("b", "本書卡片", "board")])
        self.assertTrue(_client(fake).swap_gallery_for_board("linked", "cards-db", "page-1"))
        writes = [r[:2] for r in fake.requests if r[0] in ("POST", "DELETE")]
        self.assertEqual(writes, [("DELETE", "views/g")])
        self.assertFalse([r for r in fake.requests if r[1].startswith("data_sources/")])

    def test_swap_with_nothing_to_do_writes_nothing(self):
        fake = _FakeClient(views=[_view("b", "本書卡片", "board")])
        self.assertFalse(_client(fake).swap_gallery_for_board("linked", "cards-db", "page-1"))
        self.assertFalse([r for r in fake.requests if r[0] in ("POST", "DELETE")])

    def test_swap_keeps_gallery_when_board_cannot_be_added(self):
        fake = _FakeClient(views=[_view("g", "本書卡片", "gallery")], properties={})
        with self.assertRaises(RuntimeError):
            _client(fake).swap_gallery_for_board("linked", "cards-db", "page-1")
        self.assertFalse([r for r in fake.requests if r[0] in ("POST", "DELETE")])

    def test_default_client_pins_new_api_version(self):
        self.assertEqual(
            NotionViewsClient(token="t")._client.options.notion_version,
            NOTION_VIEWS_API_VERSION)
        self.assertEqual(NOTION_VIEWS_API_VERSION, "2026-03-11")


if __name__ == "__main__":
    unittest.main()
