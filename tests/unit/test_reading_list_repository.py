"""ReadingListRepository — Reading List 書頁補完需要的讀寫（M1）。"""
import unittest
from types import SimpleNamespace

from src.infrastructure.notion.reading_list_repository import (
    BOOK_TYPE_PROPERTY,
    ReadingListRepository,
)


class _NoWait:
    def wait(self):
        pass


class _FakeClient:
    """記錄每次呼叫；回應由各測試設定。"""

    def __init__(self):
        self.me_calls = 0
        self.me_error = None
        self.queries = []          # (database_id, kwargs)
        self.query_results = {}    # database_id -> list of pages
        self.children = {}         # block_id -> list of blocks
        self.appends = []          # kwargs of each append
        self.updates = []          # kwargs of each pages.update
        self.dbs = {}              # database_id -> retrieve() result
        self.retrieve_calls = []   # database_id of each databases.retrieve call
        self.users = SimpleNamespace(me=self._me)
        self.blocks = SimpleNamespace(
            children=SimpleNamespace(list=self._list, append=self._append))
        self.pages = SimpleNamespace(update=self._update, create=self._create)
        self.databases = SimpleNamespace(query=self._query, retrieve=self._retrieve)

    def _me(self):
        self.me_calls += 1
        if self.me_error:
            raise self.me_error
        return {"object": "user", "id": "bot-1", "type": "bot"}

    def _list(self, block_id, page_size=100, start_cursor=None):
        items = self.children.get(block_id, [])
        start = int(start_cursor or 0)
        end = start + 2  # tiny pages so pagination is exercised
        more = end < len(items)
        return {"results": items[start:end], "has_more": more,
                "next_cursor": str(end) if more else None}

    def _append(self, block_id, children, after=None):
        self.appends.append({"block_id": block_id, "children": children, "after": after})
        n = len(self.appends)
        return {"results": [{"id": f"a{n}-{i}"} for i in range(len(children))]}

    def _update(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def _create(self, **kwargs):
        raise AssertionError("find_page must never create a page")

    def _query(self, database_id, **kwargs):
        self.queries.append((database_id, kwargs))
        return {"results": list(self.query_results.get(database_id, [])),
                "has_more": False}

    def _retrieve(self, database_id):
        self.retrieve_calls.append(database_id)
        return self.dbs.get(database_id, {"properties": {}})


def _repo(client=None, database_id="books-db"):
    return ReadingListRepository(
        token="t", database_id=database_id,
        rate_limiter=_NoWait(), client=client or _FakeClient(),
    )


def _type_page(page_id, name):
    return {"id": page_id, "properties": {
        "領域（標籤名）": {"type": "title", "title": [{"plain_text": name}]}}}


class TestFindPage(unittest.TestCase):
    def test_reverse_lookup_returns_full_page(self):
        client = _FakeClient()
        page = {"id": "rl-1", "created_by": {"id": "bot-1"}, "properties": {}}
        client.query_results["books-db"] = [page]
        self.assertIs(_repo(client).find_page("書", "kobo-1"), page)
        self.assertEqual(
            client.queries[0][1]["filter"]["relation"], {"contains": "kobo-1"})

    def test_not_found_never_creates(self):
        self.assertIsNone(_repo().find_page("完全不存在的書", "kobo-1"))

    def test_no_database_returns_none(self):
        self.assertIsNone(_repo(database_id=None).find_page("書", "kobo-1"))


class _RoutingClient:
    """依 filter 的 property 分流：反查（Kobo EReader）與書名比對各自一組結果，
    讓測試能各別控制「反查沒中、書名比對中」這種組合（_FakeClient 不分 filter，
    兩種查詢會拿到同一包結果，測不出 F1 要的情境）。"""

    def __init__(self, reverse_results=None, title_results=None):
        self.reverse_results = list(reverse_results or [])
        self.title_results = list(title_results or [])
        self.databases = SimpleNamespace(query=self._query, retrieve=self._retrieve)

    def _query(self, database_id, filter=None, **kwargs):
        prop = (filter or {}).get("property")
        results = self.reverse_results if prop == "Kobo EReader" else self.title_results
        return {"results": list(results), "has_more": False}

    def _retrieve(self, database_id):
        return {"properties": {}}


def _repo_routing(reverse_results=None, title_results=None):
    return ReadingListRepository(
        token="t", database_id="books-db", rate_limiter=_NoWait(),
        client=_RoutingClient(reverse_results, title_results),
    )


class TestFindPageOtherBook(unittest.TestCase):
    """F1：書名比對命中的頁若已關聯到別的劃線頁，視為不同書、不處理。"""

    @staticmethod
    def _matched_page(relation_ids):
        return {"id": "rl-2", "properties": {
            "Kobo EReader": {"type": "relation",
                             "relation": [{"id": i} for i in relation_ids]}}}

    def test_relation_points_to_a_different_highlight_page_returns_none(self):
        page = self._matched_page(["other-highlight-id"])
        repo = _repo_routing(reverse_results=[], title_results=[page])
        with self.assertLogs(
            "src.infrastructure.notion.reading_list_repository", level="INFO"
        ) as logs:
            self.assertIsNone(repo.find_page("書", "kobo-1"))
        self.assertTrue(any("視為不同書" in line for line in logs.output))

    def test_empty_relation_is_still_accepted(self):
        page = self._matched_page([])
        repo = _repo_routing(reverse_results=[], title_results=[page])
        self.assertIs(repo.find_page("書", "kobo-1"), page)

    def test_relation_id_matching_source_in_different_dash_case_is_accepted(self):
        page = self._matched_page(["abcd1234"])
        repo = _repo_routing(reverse_results=[], title_results=[page])
        self.assertIs(repo.find_page("書", "AbCd-1234"), page)


class TestCreatedByIntegration(unittest.TestCase):
    def test_bot_created_page(self):
        self.assertTrue(
            _repo().is_created_by_integration({"created_by": {"id": "bot-1"}}))

    def test_user_created_page(self):
        self.assertFalse(
            _repo().is_created_by_integration({"created_by": {"id": "user-9"}}))

    def test_bot_identity_fetched_once(self):
        client = _FakeClient()
        repo = _repo(client)
        repo.is_created_by_integration({"created_by": {"id": "bot-1"}})
        repo.is_created_by_integration({"created_by": {"id": "bot-1"}})
        self.assertEqual(client.me_calls, 1)

    def test_identity_failure_fails_closed(self):
        client = _FakeClient()
        client.me_error = RuntimeError("offline")
        with self.assertLogs(
            "src.infrastructure.notion.reading_list_repository", level="WARNING"
        ):
            self.assertFalse(
                _repo(client).is_created_by_integration({"created_by": {"id": "bot-1"}}))


class TestListBlocks(unittest.TestCase):
    def test_paginates_in_order(self):
        client = _FakeClient()
        client.children["page-1"] = [{"id": f"b{i}"} for i in range(5)]
        blocks = _repo(client).list_blocks("page-1")
        self.assertEqual([b["id"] for b in blocks], ["b0", "b1", "b2", "b3", "b4"])


class TestAppendBlocks(unittest.TestCase):
    def test_single_batch_after_anchor(self):
        client = _FakeClient()
        created = _repo(client).append_blocks("page-1", [{"x": 1}] * 3, after="h-1")
        self.assertEqual(len(client.appends), 1)
        self.assertEqual(client.appends[0]["after"], "h-1")
        self.assertEqual(len(created), 3)

    def test_batches_chain_after_last_created(self):
        client = _FakeClient()
        created = _repo(client).append_blocks("page-1", [{"x": 1}] * 150)
        self.assertEqual(len(client.appends), 2)
        self.assertIsNone(client.appends[0]["after"])
        self.assertEqual(len(client.appends[0]["children"]), 100)
        self.assertEqual(client.appends[1]["after"], "a1-99")
        self.assertEqual(len(created), 150)


class TestUpdatePage(unittest.TestCase):
    def test_cover_icon_and_properties_in_one_call(self):
        client = _FakeClient()
        _repo(client).update_page(
            "page-1", properties={"P": {"x": 1}},
            cover_url="https://c/cover.jpg", icon_url="https://c/cover.jpg")
        self.assertEqual(client.updates, [{
            "page_id": "page-1",
            "properties": {"P": {"x": 1}},
            "cover": {"type": "external", "external": {"url": "https://c/cover.jpg"}},
            "icon": {"type": "external", "external": {"url": "https://c/cover.jpg"}},
        }])

    def test_nothing_to_update_skips_call(self):
        client = _FakeClient()
        _repo(client).update_page("page-1")
        self.assertEqual(client.updates, [])


class TestTypePageIds(unittest.TestCase):
    def _client(self):
        client = _FakeClient()
        client.dbs["books-db"] = {"properties": {BOOK_TYPE_PROPERTY: {
            "type": "relation", "relation": {"database_id": "types-db"}}}}
        client.query_results["types-db"] = [
            _type_page("t-psy", "Psychology"), _type_page("t-mkt", "Marketing")]
        return client

    def test_resolves_names_via_relation_target(self):
        repo = _repo(self._client())
        self.assertEqual(
            repo.type_page_ids(["Psychology", "Nope"]), {"Psychology": "t-psy"})

    def test_index_is_cached(self):
        client = self._client()
        repo = _repo(client)
        repo.type_page_ids(["Psychology"])
        repo.type_page_ids(["Marketing"])
        type_queries = [q for q in client.queries if q[0] == "types-db"]
        self.assertEqual(len(type_queries), 1)

    def test_books_db_without_type_property(self):
        with self.assertLogs(
            "src.infrastructure.notion.reading_list_repository", level="WARNING"
        ):
            self.assertEqual(_repo().type_page_ids(["Psychology"]), {})


class TestBookTypesAvailable(unittest.TestCase):
    """F2：relation 看不到時只警告一次、不重複查，且回報「不可用」讓上層跳過。"""

    def test_relation_missing_from_schema_warns_once_and_caches(self):
        client = _FakeClient()
        repo = _repo(client)
        with self.assertLogs(
            "src.infrastructure.notion.reading_list_repository", level="WARNING"
        ) as logs:
            self.assertFalse(repo.book_types_available())
            self.assertFalse(repo.book_types_available())
        self.assertEqual(len(logs.output), 1)
        self.assertIn("分享給 integration", logs.output[0])
        self.assertEqual(len(client.retrieve_calls), 1)

    def test_relation_present(self):
        client = _FakeClient()
        client.dbs["books-db"] = {"properties": {BOOK_TYPE_PROPERTY: {
            "type": "relation", "relation": {"database_id": "types-db"}}}}
        client.query_results["types-db"] = [_type_page("t-psy", "Psychology")]
        self.assertTrue(_repo(client).book_types_available())


if __name__ == "__main__":
    unittest.main()
