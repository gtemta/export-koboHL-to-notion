"""tools/remove_card_chapter_callouts.py：清除既有卡片的 📖 章名／進度那行（Notion 以假物件取代）。"""
import unittest

from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
    is_chapter_callout,
)
from tools.remove_card_chapter_callouts import run


def _callout(emoji):
    return {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": emoji}}}


class FakeRepo:
    def __init__(self, fail_on=None):
        self.items = [
            ("卡片甲", "c1", "第一章（進度 42%）"),
            ("卡片乙", "c2", "（進度 7%）"),
        ]
        self.deleted = []
        self.fail_on = fail_on

    def list_chapter_callouts(self):
        return [item for item in self.items if item[1] not in self.deleted]

    def delete_block(self, block_id):
        if block_id == self.fail_on:
            raise RuntimeError("boom")
        self.deleted.append(block_id)


class TestIsChapterCallout(unittest.TestCase):
    def test_only_book_emoji_callouts_match(self):
        self.assertTrue(is_chapter_callout(_callout("📖")))
        self.assertFalse(is_chapter_callout(_callout("💡")))
        self.assertFalse(is_chapter_callout({"type": "quote", "quote": {}}))
        self.assertFalse(is_chapter_callout({"type": "callout", "callout": {"icon": None}}))

    def test_custom_icon_or_missing_callout_body_does_not_match(self):
        self.assertFalse(is_chapter_callout(
            {"type": "callout", "callout": {"icon": {"type": "external", "external": {"url": "x"}}}}
        ))
        self.assertFalse(is_chapter_callout({"type": "callout"}))


    def test_callout_with_children_does_not_match(self):
        block = _callout("📖")
        block["has_children"] = True
        self.assertFalse(is_chapter_callout(block))
        block["has_children"] = False
        self.assertTrue(is_chapter_callout(block))


class _ListingClient:
    """databases.query / blocks.children.list 的假 client。"""

    def __init__(self, pages, blocks_by_page, fail_blocks_for=None):
        self._pages = pages
        self._blocks = blocks_by_page
        self._fail = fail_blocks_for
        self.databases = self
        self.blocks = self
        self.children = self
        self.deleted = []

    def query(self, **kwargs):
        return {"results": self._pages, "has_more": False}

    def list(self, block_id, **kwargs):
        if block_id == self._fail:
            raise RuntimeError("read failed")
        return {"results": self._blocks.get(block_id, [])}

    def delete(self, block_id):
        self.deleted.append(block_id)
        return {}


def _page(page_id, title):
    return {"id": page_id, "properties": {"標題": {"type": "title", "title": [{"plain_text": title}]}}}


def _real_callout(block_id, text, emoji="📖"):
    block = _callout(emoji)
    block["id"] = block_id
    block["callout"]["rich_text"] = [{"plain_text": text}]
    return block


def _repo_with(client):
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    repo._client = client
    return repo


class TestRepositoryListing(unittest.TestCase):
    def test_lists_only_chapter_callouts_with_card_title_and_text(self):
        client = _ListingClient(
            [_page("p1", "卡片甲"), _page("p2", "卡片乙")],
            {
                "p1": [
                    {"id": "q", "type": "quote", "quote": {}},
                    _real_callout("c1", "第一章（進度 42%）"),
                    _real_callout("x", "別的提示", emoji="💡"),
                ],
                "p2": [],
            },
        )
        self.assertEqual(
            _repo_with(client).list_chapter_callouts(),
            [("卡片甲", "c1", "第一章（進度 42%）")],
        )

    def test_callout_with_children_is_never_listed(self):
        nested = _real_callout("c9", "手動加過內容的章名")
        nested["has_children"] = True
        childless = _real_callout("c1", "第一章（進度 42%）")
        childless["has_children"] = False
        client = _ListingClient([_page("p1", "卡片甲")], {"p1": [nested, childless]})
        self.assertEqual(
            _repo_with(client).list_chapter_callouts(),
            [("卡片甲", "c1", "第一章（進度 42%）")],
        )

    def test_failed_block_read_propagates_instead_of_looking_clean(self):
        client = _ListingClient([_page("p1", "卡片甲")], {}, fail_blocks_for="p1")
        with self.assertRaises(RuntimeError):
            _repo_with(client).list_chapter_callouts()

    def test_delete_block_calls_the_api(self):
        client = _ListingClient([], {})
        _repo_with(client).delete_block("c1")
        self.assertEqual(client.deleted, ["c1"])


class TestRun(unittest.TestCase):
    def test_dry_run_lists_text_and_deletes_nothing(self):
        fake = FakeRepo()
        report, code = run(True, repo=fake)
        self.assertIn("第一章（進度 42%）", report)
        self.assertIn("卡片甲", report)
        self.assertEqual(fake.deleted, [])
        self.assertEqual(code, 0)

    def test_real_run_deletes_each_callout_and_rerun_finds_none(self):
        fake = FakeRepo()
        report, code = run(False, repo=fake)
        self.assertEqual(fake.deleted, ["c1", "c2"])
        self.assertEqual(fake.list_chapter_callouts(), [])
        self.assertEqual(code, 0)
        report, code = run(False, repo=fake)
        self.assertEqual(code, 0)
        self.assertEqual(fake.deleted, ["c1", "c2"])

    def test_one_failed_delete_is_reported_and_the_rest_continue(self):
        fake = FakeRepo(fail_on="c1")
        report, code = run(False, repo=fake)
        self.assertEqual(fake.deleted, ["c2"])
        self.assertEqual(code, 1)
        self.assertIn("c1", report)

    def test_nothing_to_clean_says_so(self):
        fake = FakeRepo()
        fake.items = []
        report, code = run(False, repo=fake)
        self.assertEqual(code, 0)
        self.assertIn("沒有", report)

    def test_failed_initial_read_is_an_error(self):
        class Broken(FakeRepo):
            def list_chapter_callouts(self):
                raise RuntimeError("api down")

        report, code = run(True, repo=Broken())
        self.assertEqual(code, 1)
        self.assertIn("api down", report)


if __name__ == "__main__":
    unittest.main()
