"""NotionApiRepository 批次切割編排 — 用 fake notion client 驗證 append 拆批。

覆蓋 `_append_chapter_children`（以 toggle 為單位、按含巢狀總 block 數的預算
切批，不得把單一 toggle 拆到兩個 request）、`_append_blocks_returning_ids`
（頂層 block 依 100 上限分塊、累積 results 並保序）與 `sync_book_highlights`
的建立數量不符防呆與整體編排。
"""
import unittest
from types import SimpleNamespace

from src.domain.entities.highlight import Highlight
from src.infrastructure.notion.highlight_page_blocks import (
    PAGE_TITLE,
    chapter_children,
    chapter_tree,
    heading_block,
    total_block_count,
)
from src.infrastructure.notion.notion_api_repository import (
    _BATCH_SIZE,
    NotionApiRepository,
)


class _NoWaitLimiter:
    """retry_with_backoff 只需要 .wait()；這裡不真的睡。"""

    def wait(self):
        pass


class _FakeNotionClient:
    """記錄 blocks.children.append / pages.update；每個 child 回傳遞增的假 id。"""

    def __init__(self, drop_one_result=False):
        self.append_calls = []          # [(block_id, children_list), ...]
        self.update_calls = []          # [kwargs, ...]
        self._counter = 0
        self._drop_one = drop_one_result
        self.blocks = SimpleNamespace(
            children=SimpleNamespace(append=self._append))
        self.pages = SimpleNamespace(update=self._update)

    def _append(self, block_id, children):
        children = list(children)
        self.append_calls.append((block_id, children))
        results = []
        for _ in children:
            results.append({"id": f"blk-{self._counter}"})
            self._counter += 1
        if self._drop_one and results:
            results = results[:-1]
        return {"results": results}

    def _update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {}


def _repo(client):
    repo = NotionApiRepository.__new__(NotionApiRepository)
    repo._client = client
    repo._rate_limiter = _NoWaitLimiter()
    repo._database_id = "db"
    return repo


def _highlight(text, chapter, section=None, annotation="註記"):
    return Highlight(
        text=text,
        chapter_name=chapter,
        chapter_progress=0.0,
        content_id="c1",
        annotation=annotation,
        toc_chapter=chapter,
        toc_section=section,
    )


class TestAppendChapterChildrenBatching(unittest.TestCase):
    def test_budget_split_keeps_toggles_whole(self):
        """5 小節 × 20 帶註記劃線（每 toggle 41 blocks）→ 多批、不拆 toggle。"""
        highlights = [
            _highlight(f"劃線{s}-{i}", "第一章", section=f"小節{s}")
            for s in range(5) for i in range(20)
        ]
        group = chapter_tree(highlights)[0]
        children = chapter_children(group)
        # 每個 toggle = 1(heading) + 20 quote + 20 callout = 41
        self.assertEqual([total_block_count(b) for b in children], [41] * 5)

        client = _FakeNotionClient()
        _repo(client)._append_chapter_children("chap-1", children)

        # 每個 append 都掛在章 block 上、批內含巢狀總數 ≤ 80
        self.assertGreaterEqual(len(client.append_calls), 2)
        for block_id, sent in client.append_calls:
            self.assertEqual(block_id, "chap-1")
            self.assertLessEqual(
                sum(total_block_count(b) for b in sent), _BATCH_SIZE)
        # 各 call 的頂層 children 都是完整 toggle dict、且串接後等於原輸入且保序
        concatenated = [b for _, sent in client.append_calls for b in sent]
        self.assertEqual(concatenated, children)

    def test_single_oversized_toggle_sent_alone(self):
        """單一 90 條註記劃線的 toggle（181 blocks）→ 自己一批單獨送出。"""
        highlights = [
            _highlight(f"劃線{i}", "第一章", section="大節")
            for i in range(90)
        ]
        children = chapter_children(group=chapter_tree(highlights)[0])
        self.assertEqual(len(children), 1)
        self.assertEqual(total_block_count(children[0]), 181)  # 1 + 90*2

        client = _FakeNotionClient()
        _repo(client)._append_chapter_children("chap-1", children)

        self.assertEqual(len(client.append_calls), 1)
        block_id, sent = client.append_calls[0]
        self.assertEqual(block_id, "chap-1")
        self.assertEqual(sent, children)


class TestAppendBlocksReturningIds(unittest.TestCase):
    def test_multi_chunk_preserves_order_and_count(self):
        """150 個 heading → 100+50 兩次 append，回傳 150 個 id 且保序。"""
        blocks = [heading_block(f"h{i}", level=1) for i in range(150)]
        client = _FakeNotionClient()
        created = _repo(client)._append_blocks_returning_ids("page-x", blocks)

        self.assertEqual(len(created), 150)
        self.assertEqual([len(sent) for _, sent in client.append_calls], [100, 50])
        self.assertTrue(all(bid == "page-x" for bid, _ in client.append_calls))
        self.assertEqual([b["id"] for b in created],
                         [f"blk-{n}" for n in range(150)])


class TestSyncBookHighlightsOrchestration(unittest.TestCase):
    def test_created_count_mismatch_raises_and_skips_exported(self):
        """建立數量不符 → RuntimeError，且不勾選 Exported。"""
        highlights = [_highlight("劃線", "第一章")]
        client = _FakeNotionClient(drop_one_result=True)
        with self.assertRaises(RuntimeError):
            _repo(client).sync_book_highlights("page-x", highlights)
        self.assertEqual(client.update_calls, [])

    def test_happy_path_targets_page_then_chapter_blocks(self):
        """2 章（其一含小節）→ 首批頂層掛頁面、後續掛回傳的章 block id。"""
        highlights = [
            _highlight("章一劃線", "第一章", annotation=None),
            _highlight("章二劃線", "第二章", section="小節"),
        ]
        client = _FakeNotionClient()
        _repo(client).sync_book_highlights("page-x", highlights)

        # 首次 append：頁首標題 + 2 章 toggle heading，掛在頁面上
        first_id, first_children = client.append_calls[0]
        self.assertEqual(first_id, "page-x")
        self.assertEqual(len(first_children), 3)
        self.assertEqual(
            first_children[0]["heading_1"]["rich_text"][0]["text"]["content"],
            PAGE_TITLE)
        self.assertTrue(first_children[1]["heading_1"]["is_toggleable"])
        self.assertTrue(first_children[2]["heading_1"]["is_toggleable"])

        # 後續 append 掛在回傳的章 block id（index 0 是頁首標題 → blk-1/blk-2）
        self.assertEqual(client.append_calls[1][0], "blk-1")
        self.assertEqual(client.append_calls[2][0], "blk-2")

        # Exported 勾選呼叫一次
        self.assertEqual(len(client.update_calls), 1)
        self.assertTrue(
            client.update_calls[0]["properties"]["Exported"]["checkbox"])


if __name__ == "__main__":
    unittest.main()
