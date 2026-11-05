"""卡片盒 repository 的重審部分：找出標記的卡、讀卡片頁、把結果寫到頁尾。"""
import unittest
from types import SimpleNamespace

from src.domain.services.card_revision_rules import RESULT_MARKER
from src.infrastructure.notion.zettelkasten_card_repository import (
    _STAGE_DISCARDED,
    _STAGE_NEEDS_FIX,
    _STAGE_PROPERTY,
    ZettelkastenCardRepository,
)


class _NoWait:
    def wait(self):
        pass


def _block(kind, text, block_id="b", has_children=False, **extra):
    return {
        "id": block_id,
        "type": kind,
        "has_children": has_children,
        kind: {"rich_text": [{"plain_text": text}], **extra},
    }


class _FakeDatabases:
    def __init__(self, props, results=()):
        self.props, self.results = props, list(results)
        self.queries = []

    def retrieve(self, database_id):
        return {"properties": self.props}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"results": self.results, "has_more": False}


class _FakeChildren:
    def __init__(self, by_parent=None):
        self.by_parent = by_parent or {}
        self.listed, self.appended = [], []

    def list(self, block_id, page_size=100):
        self.listed.append(block_id)
        return {"results": self.by_parent.get(block_id, []), "has_more": False}

    def append(self, block_id, children):
        self.appended.append((block_id, children))
        return {}


def _repo(databases=None, children=None, pages=None):
    repo = ZettelkastenCardRepository(token="dummy", database_id="cards-db",
                                      rate_limiter=_NoWait())
    repo._client = SimpleNamespace(
        databases=databases,
        blocks=SimpleNamespace(children=children),
        pages=pages,
    )
    return repo


class TestListMarkedForRevision(unittest.TestCase):
    def test_queries_only_cards_marked_as_needing_a_fix(self):
        dbs = _FakeDatabases({"標題": {}, _STAGE_PROPERTY: {}})
        _repo(dbs).list_cards_marked_for_revision()
        self.assertEqual(
            dbs.queries[0]["filter"],
            {"property": _STAGE_PROPERTY, "select": {"equals": _STAGE_NEEDS_FIX}},
        )

    def test_returns_page_title_and_book(self):
        page = {
            "id": "p1",
            "properties": {
                "標題": {"title": [{"plain_text": "卡一"}]},
                "來源": {"relation": [{"id": "book-1"}]},
            },
        }
        dbs = _FakeDatabases({"標題": {}, _STAGE_PROPERTY: {}}, [page])
        [card] = _repo(dbs).list_cards_marked_for_revision()
        self.assertEqual((card.page_id, card.title, card.book_page_id), ("p1", "卡一", "book-1"))

    def test_card_box_without_the_column_has_nothing_marked(self):
        dbs = _FakeDatabases({"標題": {}})
        self.assertEqual(_repo(dbs).list_cards_marked_for_revision(), [])
        self.assertEqual(dbs.queries, [])


class TestReadCardBlocks(unittest.TestCase):
    def test_keeps_reading_order_and_skips_blocks_without_text(self):
        children = _FakeChildren({"p": [
            _block("paragraph", "內文"),
            {"id": "i", "type": "image", "has_children": False, "image": {}},
            _block("quote", "原文"),
        ]})
        blocks = _repo(children=children).read_card_blocks("p")
        self.assertEqual([(b.kind, b.text) for b in blocks],
                         [("paragraph", "內文"), ("image", ""), ("quote", "原文")])

    def test_old_chapter_callout_is_not_part_of_the_card(self):
        children = _FakeChildren({"p": [
            _block("paragraph", "內文"),
            _block("callout", "第一章（進度 50%）", icon={"type": "emoji", "emoji": "📖"}),
        ]})
        blocks = _repo(children=children).read_card_blocks("p")
        self.assertEqual([b.text for b in blocks], ["內文"])

    def test_nested_blocks_are_flattened_in_place(self):
        children = _FakeChildren({
            "p": [
                _block("bulleted_list_item", "父項", block_id="parent", has_children=True),
                _block("paragraph", "後面"),
            ],
            "parent": [_block("bulleted_list_item", "子項")],
        })
        blocks = _repo(children=children).read_card_blocks("p")
        self.assertEqual([b.text for b in blocks], ["父項", "子項", "後面"])

    def test_does_not_read_inside_an_earlier_result(self):
        children = _FakeChildren({"p": [
            _block("toggle", f"{RESULT_MARKER} 2026-11-06｜通過〔abc〕",
                   block_id="result", has_children=True),
        ]})
        _repo(children=children).read_card_blocks("p")
        self.assertEqual(children.listed, ["p"])


class TestAppendRevisionResult(unittest.TestCase):
    def test_appends_one_toggle_holding_every_line(self):
        children = _FakeChildren()
        _repo(children=children).append_revision_result("p", "標題〔abc〕", ["第一段", "第二段"])
        [(block_id, blocks)] = children.appended
        self.assertEqual(block_id, "p")
        [toggle] = blocks
        self.assertEqual(toggle["type"], "toggle")
        self.assertEqual(toggle["toggle"]["rich_text"][0]["text"]["content"], "標題〔abc〕")
        self.assertEqual(
            [c["paragraph"]["rich_text"][0]["text"]["content"] for c in toggle["toggle"]["children"]],
            ["第一段", "第二段"],
        )

    def test_long_line_is_split_instead_of_rejected_by_notion(self):
        children = _FakeChildren()
        _repo(children=children).append_revision_result("p", "標題", ["字" * 2500])
        rich = children.appended[0][1][0]["toggle"]["children"][0]["paragraph"]["rich_text"]
        self.assertEqual([len(r["text"]["content"]) for r in rich], [2000, 500])


class TestBookTitle(unittest.TestCase):
    def test_reads_the_title_whatever_the_column_is_called(self):
        pages = SimpleNamespace(retrieve=lambda page_id: {
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "主控力"}]}},
        })
        self.assertEqual(_repo(pages=pages).book_title("book-1"), "主控力")


class TestNewStageOptions(unittest.TestCase):
    def test_a_card_box_created_from_scratch_gets_every_stage(self):
        add = ZettelkastenCardRepository._schema_additions({})
        names = [o["name"] for o in add[_STAGE_PROPERTY]["select"]["options"]]
        self.assertIn(_STAGE_NEEDS_FIX, names)
        self.assertIn(_STAGE_DISCARDED, names)


if __name__ == "__main__":
    unittest.main()
