# 劃線層一次到位（Highlight Page v2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 過濾空白劃線、消滅 rich_text 超長故障類別、劃線頁改為兩層巢狀 toggle（章 → 小節 → quote → 💭 註記），完成後全庫 RESYNC 一次。

**Architecture:** 資料層在 SQL 加 `Bookmark.Type='highlight'` 過濾；`TocChapterResolver` 新增結構化 `resolve_parts()`（章, 小節）；新純函式模組 `highlight_page_blocks.py` 負責分組與 block 建構（可單元測試），`NotionApiRepository` 只做 API 編排（先 append 章 toggle 拿 id，再對每章 append 巢狀小節/quote）。

**Tech Stack:** Python 3、sqlite3、notion-client、unittest（pytest 執行）、ruff。

**Spec:** `docs/superpowers/specs/2026-07-13-knowledge-management-four-batches-design.md` 第 1 批。

## Global Constraints

- 分支：`feat/highlight-page-v2`（自 `feat/toc-chapter-extraction` HEAD 分出）。
- 所有 Notion 寫入走 `retry_with_backoff` + `NotionRateLimiter`（既有機制，勿繞過）。
- rich_text 單段上限 2000 字；單一 block 的 children 上限 100（本計畫用 90 留餘裕）。
- 單一 append 請求：頂層 children ≤ 100（既有 `_MAX_BLOCKS_PER_REQUEST`）；巢狀最多兩層。
- 測試風格：unittest class、中文 docstring（比照 `tests/unit/test_toc_chapter_resolver.py`）。
- Commit 風格：gitmoji + type，一個 commit 一個意圖。
- **Spec 偏差（已分析定案）**：`_SYNC_GENERATED_BLOCK_TYPES` **不新增** `quote`/`heading_2`。
  理由：新版 quote/小節 heading 全部巢狀在章 toggle（heading_1）內，刪父塊即遞迴刪除；
  頂層出現的 quote/heading_2 只可能是使用者手動內容，加入清單會誤刪用戶資料。
  頁首「📌 劃線筆記」與章 toggle 都是 heading_1，既有清單已涵蓋。

---

### Task 1: 建分支 + SQL 資料純度過濾

**Files:**
- Modify: `src/infrastructure/persistence/kobo_sqlite_repository.py:21-51`
- Test: `tests/unit/test_highlight_filter.py`（新檔）

**Interfaces:**
- Produces: `_BOOK_QUERY` / `_HIGHLIGHT_QUERY` 只回 `Type='highlight'` 且未隱藏的劃線；
  `KoboSqliteRepository.get_all_books()` / `get_highlights_with_chapters()` 簽名不變。

- [ ] **Step 1: 建立分支**

```bash
git checkout -b feat/highlight-page-v2
```

- [ ] **Step 2: Write the failing test**

建 `tests/unit/test_highlight_filter.py`：

```python
"""Bookmark.Type / Hidden 過濾 — 空白 dogear/markup 不再混入。"""
import os
import sqlite3
import tempfile
import unittest

from src.infrastructure.persistence.kobo_sqlite_repository import KoboSqliteRepository

_BOOK = "book-1"
_BOOK2 = "book-2-dogear-only"


def _create_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE content ("
        "ContentID TEXT, Title TEXT, Subtitle TEXT, Attribution TEXT, "
        "DateLastRead TEXT, TimeSpentReading INTEGER, Description TEXT, "
        "Publisher TEXT, ___PercentRead INTEGER, LastTimeFinishedReading TEXT, "
        "ISBN TEXT, ChapterIDBookmarked TEXT, CurrentChapterEstimate REAL, "
        "CurrentChapterProgress REAL, ContentType INTEGER, BookID TEXT, "
        "VolumeIndex INTEGER)"
    )
    conn.execute(
        "CREATE TABLE Bookmark ("
        "BookmarkID TEXT, VolumeID TEXT, ContentID TEXT, Text TEXT, "
        "Annotation TEXT, ChapterProgress REAL, StartContainerPath TEXT, "
        "EndContainerPath TEXT, Type TEXT, Hidden TEXT)"
    )
    # 兩本書（content 書籍列）
    for cid, title in ((_BOOK, "真書"), (_BOOK2, "只有摺角的書")):
        conn.execute(
            "INSERT INTO content (ContentID, Title, ContentType) VALUES (?, ?, 6)",
            (cid, title))
    rows = [
        ("bm-1", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "真劃線", "highlight", None),
        ("bm-2", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "", "dogear", None),
        ("bm-3", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "", "markup", None),
        ("bm-4", _BOOK, f"{_BOOK}!OEBPS!Text/ch1.xhtml", "被隱藏的劃線", "highlight", "true"),
        ("bm-5", _BOOK2, f"{_BOOK2}!OEBPS!Text/ch1.xhtml", "", "dogear", None),
    ]
    for bid, vol, cid, text, btype, hidden in rows:
        conn.execute(
            "INSERT INTO Bookmark (BookmarkID, VolumeID, ContentID, Text, "
            "ChapterProgress, Type, Hidden) VALUES (?, ?, ?, ?, 0.5, ?, ?)",
            (bid, vol, cid, text, btype, hidden))
    conn.commit()
    conn.close()


class TestBookmarkTypeFilter(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        _create_db(self.db_path)
        self.repo = KoboSqliteRepository(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_only_real_highlights_returned(self):
        """dogear/markup（Text 全空）與 Hidden 劃線不進結果"""
        highlights = self.repo.get_highlights_with_chapters(_BOOK)
        self.assertEqual([h.text for h in highlights], ["真劃線"])
        self.assertEqual([h.bookmark_id for h in highlights], ["bm-1"])

    def test_book_with_only_dogears_not_listed(self):
        """整本書只有摺角 → 不出現在書單"""
        titles = [b.title for b in self.repo.get_all_books()]
        self.assertEqual(titles, ["真書"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_highlight_filter.py -v`
Expected: FAIL — `test_only_real_highlights_returned` 收到 4 筆（含 dogear/markup/hidden）、
`test_book_with_only_dogears_not_listed` 收到 2 本書。

- [ ] **Step 4: Write minimal implementation**

`kobo_sqlite_repository.py`：抽共用過濾條件，改兩條 query（其餘不動）：

```python
# 只取真實劃線：dogear/markup 的 Text 皆空（實測 23+107 筆）、Hidden 防禦性排除
_BOOKMARK_FILTER = (
    "Bookmark.Type = 'highlight' "
    "AND IFNULL(Bookmark.Hidden, 'false') NOT IN ('true', '1')"
)

_BOOK_QUERY = (
    "SELECT DISTINCT content.ContentId, content.Title, content.Subtitle, "
    "content.Attribution, content.DateLastRead, content.TimeSpentReading, "
    "content.Description, content.Publisher, content.___PercentRead, "
    "content.LastTimeFinishedReading, content.ISBN "
    "FROM Bookmark "
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID "
    f"WHERE {_BOOKMARK_FILTER} "
    "ORDER BY content.Title"
)
```

`_HIGHLIGHT_QUERY` 的 `WHERE Bookmark.VolumeID = ? ` 改為
`WHERE Bookmark.VolumeID = ? AND {_BOOKMARK_FILTER} `（用 f-string 串入，其餘不動）。

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_highlight_filter.py -v`
Expected: PASS (2 tests)

Run: `python -m pytest`（全套不弄壞既有測試）
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/persistence/kobo_sqlite_repository.py tests/unit/test_highlight_filter.py
git commit -m "🐛 fix: 過濾 Bookmark.Type/Hidden — 130 筆空白 dogear/markup 不再混入"
```

---

### Task 2: TocChapterResolver 結構化輸出 `resolve_parts()`

**Files:**
- Modify: `src/infrastructure/persistence/toc_chapter_resolver.py:96-136`
- Test: `tests/unit/test_toc_chapter_resolver.py`（追加 test class）

**Interfaces:**
- Produces: `TocChapterResolver.resolve_parts(content_id: str) -> Optional[Tuple[str, Optional[str]]]`
  — 回 `(章標題, 小節標題或 None)`，不截斷；解析不到回 `None`。
  `resolve()` 行為不變（組合 + 60 字截斷），改為呼叫 `resolve_parts()` 的薄包裝。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_toc_chapter_resolver.py` 追加（fixture 沿用檔內既有 `_make_resolver`）：

```python
class TestResolveParts(unittest.TestCase):
    """兩層版面需要結構化（章, 小節），不再解析合併字串。"""

    def setUp(self):
        self.resolver = _make_resolver()

    def test_chapter_with_section(self):
        self.assertEqual(
            self.resolver.resolve_parts(_B + "Text/sec2-1.xhtml"),
            ("Chapter 2", "小節丙"))

    def test_chapter_only(self):
        self.assertEqual(
            self.resolver.resolve_parts(_B + "Text/ch1.xhtml"),
            ("Chapter 1", None))

    def test_unresolvable_returns_none(self):
        self.assertIsNone(self.resolver.resolve_parts(_B + "Text/cover.xhtml"))

    def test_parts_not_truncated(self):
        """resolve() 截 60 字是顯示用；parts 保留原文供 toggle 標題使用"""
        long_title = "很長的章節標題" * 20
        resolver = TocChapterResolver(
            [(_B + "Text/a.xhtml", 0)],
            [(_B + "Text/a.xhtml-1", long_title, 0, 1)])
        chapter, section = resolver.resolve_parts(_B + "Text/a.xhtml")
        self.assertEqual(chapter, long_title)
        self.assertIsNone(section)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_toc_chapter_resolver.py -v`
Expected: FAIL with `AttributeError: ... no attribute 'resolve_parts'`

- [ ] **Step 3: Write implementation**

`toc_chapter_resolver.py`：把 `resolve()` 主體搬進 `resolve_parts()`，`resolve()` 變薄包裝：

```python
    def resolve_parts(self, content_id: str) -> Optional[Tuple[str, Optional[str]]]:
        """Return (chapter, section-or-None) for a bookmark, else None.

        Titles are returned untruncated — display truncation is resolve()'s job.
        """
        pos = self.spine_position(content_id)
        if pos is None or not self._entries:
            return None
        file = _bookmark_file(content_id)

        preceding = [e for e in self._entries if e.spine_pos <= pos]
        if not preceding:
            return None  # 劃線在第一個 TOC 條目之前（封面/前言），交給 fallback

        chapter: Optional[_TocEntry] = None
        for entry in reversed(preceding):
            if entry.depth <= 1:
                chapter = entry
                break

        section: Optional[_TocEntry] = None
        min_skipped_depth = float("inf")
        for entry in reversed(preceding):
            if entry.depth <= 1:
                break  # 回溯到章的起點為止，前一章的小節不算
            if entry.ambiguous and entry.file == file:
                min_skipped_depth = min(min_skipped_depth, entry.depth)
                continue
            if entry.depth < min_skipped_depth:
                section = entry
            break

        if chapter and section:
            return chapter.title, section.title
        if chapter or section:
            return (chapter or section).title, None
        return None

    def resolve(self, content_id: str) -> Optional[str]:
        """Return "章 › 小節" (or just the chapter) for a bookmark, else None."""
        parts = self.resolve_parts(content_id)
        if parts is None:
            return None
        chapter, section = parts
        label = f"{chapter} › {section}" if section else chapter
        if len(label) > _MAX_LABEL_LEN:
            label = label[:_MAX_LABEL_LEN - 3] + "..."
        return label
```

（原 `resolve()` 內的註解邏輯已隨主體搬入 `resolve_parts`，勿留重複程式碼。）

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_toc_chapter_resolver.py -v`
Expected: PASS — 新 4 個 + 既有全部（`resolve()` 行為不變是本步驗收重點）

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/persistence/toc_chapter_resolver.py tests/unit/test_toc_chapter_resolver.py
git commit -m "✨ feat: TocChapterResolver.resolve_parts — 結構化（章, 小節）輸出"
```

---

### Task 3: Highlight entity 帶出章/小節 + repository 填入

**Files:**
- Modify: `src/domain/entities/highlight.py`
- Modify: `src/infrastructure/persistence/kobo_sqlite_repository.py:105-131`
- Test: `tests/unit/test_highlight_filter.py`（追加 test class，沿用 Task 1 的 tmp-db fixture）

**Interfaces:**
- Consumes: Task 2 的 `resolve_parts()`。
- Produces: `Highlight.toc_chapter: Optional[str] = None`、
  `Highlight.toc_section: Optional[str] = None`（TOC 命中時為原文標題；fallback 書為 None）。
  `chapter_name` 維持現狀（合併截斷 label / heuristics），下游卡片流程零影響。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_highlight_filter.py` 追加：

```python
class TestTocPartsOnHighlight(unittest.TestCase):
    """TOC 命中時 Highlight 帶結構化章/小節，供兩層 toggle 版面分組。"""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        _create_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        # spine（ContentType=9）與 TOC（ContentType=899）：ch1 檔屬「第一章 › 開場」
        conn.execute(
            "INSERT INTO content (ContentID, ContentType, BookID, VolumeIndex) "
            "VALUES (?, 9, ?, 0)", (f"{_BOOK}!OEBPS!Text/ch1.xhtml", _BOOK))
        conn.execute(
            "INSERT INTO content (ContentID, Title, ContentType, BookID, VolumeIndex, "
            "Depth) VALUES (?, '第一章', 899, ?, 0, 1)",
            (f"{_BOOK}!OEBPS!Text/ch1.xhtml-1", _BOOK))
        conn.execute(
            "INSERT INTO content (ContentID, Title, ContentType, BookID, VolumeIndex, "
            "Depth) VALUES (?, '開場', 899, ?, 1, 2)",
            (f"{_BOOK}!OEBPS!Text/ch1.xhtml#a1-2", _BOOK))
        conn.commit()
        conn.close()
        self.repo = KoboSqliteRepository(self.db_path)

    def tearDown(self):
        os.remove(self.db_path)

    def test_toc_parts_populated(self):
        h = self.repo.get_highlights_with_chapters(_BOOK)[0]
        # 同檔多條目且第二條帶 anchor → 模糊，退回章級
        self.assertEqual(h.toc_chapter, "第一章")
        self.assertIsNone(h.toc_section)
        self.assertEqual(h.chapter_name, "第一章")

    def test_no_toc_leaves_parts_none(self):
        """無 TOC 的書（_BOOK2 無 899 列）parts 為 None，走 fallback"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO Bookmark (BookmarkID, VolumeID, ContentID, Text, "
            "ChapterProgress, Type) VALUES ('bm-9', ?, ?, '無目錄劃線', 0.5, "
            "'highlight')", (_BOOK2, f"{_BOOK2}!OEBPS!Text/x.xhtml"))
        conn.commit()
        conn.close()
        h = self.repo.get_highlights_with_chapters(_BOOK2)[0]
        self.assertIsNone(h.toc_chapter)
        self.assertIsNone(h.toc_section)
```

注意：`test_toc_parts_populated` 的 TOC 條目需要 `Depth` 欄位——Task 1 的
`_create_db` schema 已含 `content.VolumeIndex`，但**沒有 `Depth`**；本步先在
`_create_db` 的 content CREATE TABLE 中加一欄 `Depth INTEGER`（放在 `VolumeIndex` 後）。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_highlight_filter.py -v`
Expected: FAIL — `Highlight.__init__() got an unexpected keyword argument 'toc_chapter'`
（或 `AttributeError: 'Highlight' object has no attribute 'toc_chapter'`）

- [ ] **Step 3: Write implementation**

`highlight.py` dataclass 追加兩欄（放 `bookmark_id` 之後）：

```python
    toc_chapter: Optional[str] = None
    toc_section: Optional[str] = None
```

`kobo_sqlite_repository.py` 的 `get_highlights_with_chapters` 迴圈內，
把現有 `toc_chapter = resolver.resolve(content_id or '')` 改為：

```python
                    toc_parts = resolver.resolve_parts(content_id or '')
                    toc_label = resolver.resolve(content_id or '')
                    if toc_label:
                        resolved_count += 1
                    highlight = Highlight(
                        text=text or '',
                        chapter_name=toc_label or self._initial_chapter_name(
                            text or '', content_id or '', start_path, chapter_id_bookmarked),
                        chapter_progress=chapter_progress or 0.0,
                        content_id=content_id or '',
                        start_container_path=start_path,
                        end_container_path=end_path,
                        chapter_id_bookmarked=chapter_id_bookmarked,
                        current_chapter_estimate=cur_chapter_est,
                        current_chapter_progress=cur_chapter_prog,
                        annotation=annotation,
                        bookmark_id=bookmark_id,
                        toc_chapter=toc_parts[0] if toc_parts else None,
                        toc_section=toc_parts[1] if toc_parts else None,
                    )
```

（原變數名 `toc_chapter` 更名 `toc_label`，同函式內其後引用一併改名。）

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_highlight_filter.py tests/unit/test_toc_chapter_resolver.py -v`
Expected: PASS；再跑 `python -m pytest` 全綠。

- [ ] **Step 5: Commit**

```bash
git add src/domain/entities/highlight.py src/infrastructure/persistence/kobo_sqlite_repository.py tests/unit/test_highlight_filter.py
git commit -m "✨ feat: Highlight 帶結構化 toc_chapter/toc_section"
```

---

### Task 4: 純函式模組 highlight_page_blocks（拆段 / block 建構 / 章節樹）

**Files:**
- Create: `src/infrastructure/notion/highlight_page_blocks.py`
- Test: `tests/unit/test_highlight_page_blocks.py`（新檔）

**Interfaces:**
- Consumes: `Highlight`（含 Task 3 的 `toc_chapter`/`toc_section`）。
- Produces（Task 5 依賴，簽名照抄）：
  - `PAGE_TITLE: str = "📌 劃線筆記"`
  - `split_rich_text(text: str, limit: int = 2000) -> List[Dict]` — rich_text 段列表
  - `heading_block(text: str, level: int = 1, toggleable: bool = False) -> Dict`
  - `quote_block(h: Highlight) -> Dict` — 有註記時 💭 callout 為 quote 的 child
  - `chapter_tree(highlights: List[Highlight]) -> List[ChapterGroup]`
  - `chapter_children(group: ChapterGroup) -> List[Dict]` — 該章 toggle 內的全部 blocks
  - `total_block_count(block: Dict) -> int` — 含巢狀的 block 數（批次預算用）

- [ ] **Step 1: Write the failing test**

建 `tests/unit/test_highlight_page_blocks.py`：

```python
"""劃線頁 v2 純函式：拆段、quote/toggle 建構、章節樹分組。"""
import unittest

from src.domain.entities.highlight import Highlight
from src.infrastructure.notion.highlight_page_blocks import (
    chapter_children,
    chapter_tree,
    heading_block,
    quote_block,
    split_rich_text,
    total_block_count,
)


def _h(text="劃線", chapter=None, section=None, annotation=None,
       chapter_name="未知章節"):
    return Highlight(
        text=text, chapter_name=chapter_name, chapter_progress=0.5,
        content_id="cid", annotation=annotation,
        toc_chapter=chapter, toc_section=section)


class TestSplitRichText(unittest.TestCase):
    def test_short_text_single_segment(self):
        segs = split_rich_text("hello")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"]["content"], "hello")

    def test_long_text_split_lossless(self):
        """超過 2000 字切多段，內容零遺失（取代舊的截斷）"""
        text = "字" * 4500
        segs = split_rich_text(text)
        self.assertEqual([len(s["text"]["content"]) for s in segs],
                         [2000, 2000, 500])
        self.assertEqual("".join(s["text"]["content"] for s in segs), text)


class TestQuoteBlock(unittest.TestCase):
    def test_plain_quote(self):
        block = quote_block(_h())
        self.assertEqual(block["type"], "quote")
        self.assertNotIn("children", block["quote"])

    def test_annotation_nested_as_child(self):
        """💭 callout 是 quote 的 child（縮排從屬），不再是同層 sibling"""
        block = quote_block(_h(annotation="我的想法"))
        children = block["quote"]["children"]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["type"], "callout")
        self.assertEqual(children[0]["callout"]["icon"]["emoji"], "💭")

    def test_long_annotation_lossless(self):
        block = quote_block(_h(annotation="註" * 3000))
        segs = block["quote"]["children"][0]["callout"]["rich_text"]
        self.assertEqual(sum(len(s["text"]["content"]) for s in segs), 3000)


class TestHeadingBlock(unittest.TestCase):
    def test_toggleable_flag(self):
        block = heading_block("第一章", level=1, toggleable=True)
        self.assertEqual(block["type"], "heading_1")
        self.assertTrue(block["heading_1"]["is_toggleable"])

    def test_plain_heading_has_no_flag(self):
        block = heading_block("📌 劃線筆記", level=1)
        self.assertNotIn("is_toggleable", block["heading_1"])


class TestChapterTree(unittest.TestCase):
    def test_groups_by_chapter_then_section_in_order(self):
        tree = chapter_tree([
            _h("a", chapter="第一章", section="開場"),
            _h("b", chapter="第一章", section="開場"),
            _h("c", chapter="第一章", section="轉折"),
            _h("d", chapter="第二章"),
        ])
        self.assertEqual([g.title for g in tree], ["第一章", "第二章"])
        self.assertEqual([(t, [h.text for h in items])
                          for t, items in tree[0].sections],
                         [("開場", ["a", "b"]), ("轉折", ["c"])])
        self.assertEqual([h.text for h in tree[1].direct], ["d"])

    def test_fallback_book_uses_chapter_name(self):
        """無 TOC 的書：chapter_name 當章、無小節；未知章節改「其他內容」"""
        tree = chapter_tree([_h("x", chapter_name="未知章節")])
        self.assertEqual(tree[0].title, "其他內容")
        self.assertEqual([h.text for h in tree[0].direct], ["x"])
        self.assertEqual(tree[0].sections, [])

    def test_same_section_nonadjacent_merges(self):
        """同名小節非連續出現仍併同一 toggle（每小節恰一個 toggle）"""
        tree = chapter_tree([
            _h("a", chapter="第一章", section="開場"),
            _h("b", chapter="第一章", section="轉折"),
            _h("c", chapter="第一章", section="開場"),
        ])
        self.assertEqual([(t, [h.text for h in items])
                          for t, items in tree[0].sections],
                         [("開場", ["a", "c"]), ("轉折", ["b"])])


class TestChapterChildren(unittest.TestCase):
    def test_direct_quotes_then_section_toggles(self):
        tree = chapter_tree([
            _h("直下劃線", chapter="第一章"),
            _h("小節劃線", chapter="第一章", section="開場"),
        ])
        blocks = chapter_children(tree[0])
        self.assertEqual([b["type"] for b in blocks], ["quote", "heading_2"])
        toggle = blocks[1]
        self.assertTrue(toggle["heading_2"]["is_toggleable"])
        self.assertEqual(
            [b["type"] for b in toggle["heading_2"]["children"]], ["quote"])

    def test_oversized_section_split_into_continuation(self):
        """小節超過 90 條 → 拆「(續)」toggle，children 皆 ≤ 90"""
        items = [_h(f"劃線{i}", chapter="第一章", section="長節")
                 for i in range(95)]
        blocks = chapter_children(chapter_tree(items)[0])
        self.assertEqual(len(blocks), 2)
        titles = [b["heading_2"]["rich_text"][0]["text"]["content"]
                  for b in blocks]
        self.assertEqual(titles, ["長節", "長節 (續)"])
        self.assertEqual(len(blocks[0]["heading_2"]["children"]), 90)
        self.assertEqual(len(blocks[1]["heading_2"]["children"]), 5)

    def test_empty_text_highlight_skipped(self):
        tree = chapter_tree([_h("", chapter="第一章")])
        self.assertEqual(chapter_children(tree[0]), [])


class TestTotalBlockCount(unittest.TestCase):
    def test_counts_nested(self):
        quote = quote_block(_h(annotation="想法"))     # quote + callout = 2
        self.assertEqual(total_block_count(quote), 2)
        tree = chapter_tree([_h("a", chapter="章", section="節",
                                annotation="想法")])
        toggle = chapter_children(tree[0])[0]          # toggle + quote + callout
        self.assertEqual(total_block_count(toggle), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_highlight_page_blocks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.infrastructure.notion.highlight_page_blocks'`

- [ ] **Step 3: Write implementation**

建 `src/infrastructure/notion/highlight_page_blocks.py`：

```python
"""Pure block builders for the highlight page (v2 兩層巢狀 toggle 版面).

No Notion client here — NotionApiRepository owns API orchestration; this
module owns grouping and block construction so layout stays unit-testable.

Notion API 限制（本模組據此設計）：
- rich_text 單段 ≤ 2000 字 → split_rich_text 切多段（零遺失）
- 單一 block 的 children ≤ 100 → 小節 toggle 超過 90 條拆「(續)」
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ...domain.entities.highlight import Highlight

PAGE_TITLE = "📌 劃線筆記"
RICH_TEXT_LIMIT = 2000
MAX_TOGGLE_CHILDREN = 90


def split_rich_text(text: str, limit: int = RICH_TEXT_LIMIT) -> List[Dict[str, Any]]:
    text = text or ""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    return [
        {"type": "text", "text": {"content": text[i:i + limit]}}
        for i in range(0, len(text), limit)
    ]


def heading_block(text: str, level: int = 1,
                  toggleable: bool = False) -> Dict[str, Any]:
    key = f"heading_{level}"
    payload: Dict[str, Any] = {"rich_text": split_rich_text(text)}
    if toggleable:
        payload["is_toggleable"] = True
    return {"object": "block", "type": key, key: payload}


def _annotation_callout(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💭"},
            "rich_text": split_rich_text(text),
        },
    }


def quote_block(h: Highlight) -> Dict[str, Any]:
    block: Dict[str, Any] = {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": split_rich_text(h.text)},
    }
    if h.has_annotation():
        block["quote"]["children"] = [_annotation_callout(h.annotation.strip())]
    return block


@dataclass
class ChapterGroup:
    title: str
    direct: List[Highlight] = field(default_factory=list)  # 章直下（無小節）
    sections: List[Tuple[str, List[Highlight]]] = field(default_factory=list)


def _sanitize_chapter_name(name: str) -> str:
    if name in ("未知章節", "未知章节"):
        return "其他內容"
    return name[:47] + "..." if len(name) > 50 else name


def chapter_tree(highlights: List[Highlight]) -> List[ChapterGroup]:
    """依（章, 小節）分組，維持輸入順序（上游已按 spine+progress 排序）。"""
    groups: List[ChapterGroup] = []
    index: Dict[str, ChapterGroup] = {}
    for h in highlights:
        chapter = h.toc_chapter or _sanitize_chapter_name(
            h.chapter_name or "未知章節")
        group = index.get(chapter)
        if group is None:
            group = ChapterGroup(title=chapter)
            index[chapter] = group
            groups.append(group)
        if h.toc_section:
            for title, items in group.sections:
                if title == h.toc_section:
                    items.append(h)
                    break
            else:
                group.sections.append((h.toc_section, [h]))
        else:
            group.direct.append(h)
    return groups


def _section_toggles(title: str, items: List[Highlight]) -> List[Dict[str, Any]]:
    quotes = [quote_block(h) for h in items if h.text]
    toggles: List[Dict[str, Any]] = []
    for i in range(0, len(quotes), MAX_TOGGLE_CHILDREN):
        label = title if i == 0 else f"{title} (續)"
        toggle = heading_block(label, level=2, toggleable=True)
        toggle["heading_2"]["children"] = quotes[i:i + MAX_TOGGLE_CHILDREN]
        toggles.append(toggle)
    return toggles


def chapter_children(group: ChapterGroup) -> List[Dict[str, Any]]:
    """一個章 toggle 內的全部 blocks：直下 quotes 先、小節 toggles 後。"""
    blocks = [quote_block(h) for h in group.direct if h.text]
    for title, items in group.sections:
        blocks.extend(_section_toggles(title, items))
    return blocks


def total_block_count(block: Dict[str, Any]) -> int:
    """含巢狀 children 的總 block 數（append 批次預算用）。"""
    payload = block.get(block.get("type", ""), {})
    children = payload.get("children", [])
    return 1 + sum(total_block_count(c) for c in children)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_highlight_page_blocks.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/highlight_page_blocks.py tests/unit/test_highlight_page_blocks.py
git commit -m "✨ feat: highlight_page_blocks 純函式模組 — 拆段/quote/toggle/章節樹"
```

---

### Task 5: NotionApiRepository 兩層巢狀上傳編排

**Files:**
- Modify: `src/infrastructure/notion/notion_api_repository.py`
- Modify: `src/infrastructure/notion/dry_run_notion_repository.py:53-59`
- Modify: `tests/unit/test_annotation.py:30-53`（block 測試改綁新模組）
- Test: `tests/unit/test_highlight_page_blocks.py`（Task 4 已涵蓋純邏輯；本 task 靠既有
  `tests/unit/test_resync.py` + fake-client 驗證編排不炸）

**Interfaces:**
- Consumes: Task 4 全部匯出（`PAGE_TITLE`、`heading_block`、`chapter_tree`、
  `chapter_children`、`total_block_count`）。
- Produces: `sync_book_highlights(page_id, highlights)` 對外簽名/語意不變
  （上傳 + 勾 Exported）；`replace_book_highlights` 不變。
  新增私有 `_append_blocks_returning_ids(parent_id, blocks) -> List[Dict]`。

- [ ] **Step 1: 改寫 test_annotation.py 的 block 測試（先紅後綠的紅）**

`tests/unit/test_annotation.py`：刪除 `TestNotionAnnotationBlocks` 整個 class
（bullet 版面已死），改為：

```python
class TestNotionAnnotationBlocks(unittest.TestCase):
    """v2 版面：註記 callout 巢狀在 quote 之下。"""

    def test_quote_only_without_annotation(self):
        block = quote_block(_highlight())
        self.assertEqual(block["type"], "quote")
        self.assertNotIn("children", block["quote"])

    def test_callout_nested_with_annotation(self):
        block = quote_block(_highlight(annotation="這段讓我想到複利效應"))
        children = block["quote"]["children"]
        self.assertEqual(children[0]["type"], "callout")
        self.assertEqual(children[0]["callout"]["icon"]["emoji"], "💭")
        self.assertEqual(
            children[0]["callout"]["rich_text"][0]["text"]["content"],
            "這段讓我想到複利效應")

    def test_annotation_over_2000_lossless(self):
        block = quote_block(_highlight(annotation="字" * 3000))
        segs = block["quote"]["children"][0]["callout"]["rich_text"]
        self.assertEqual(sum(len(s["text"]["content"]) for s in segs), 3000)
```

檔頭 import 改為：

```python
from src.infrastructure.notion.highlight_page_blocks import quote_block
```

（`NotionApiRepository` import 若無其他引用即移除。）

- [ ] **Step 2: 改寫 sync_book_highlights 與相關 helpers**

`notion_api_repository.py`：

檔頭 import 追加：

```python
from .highlight_page_blocks import (
    PAGE_TITLE,
    chapter_children,
    chapter_tree,
    heading_block,
    total_block_count,
)
```

`sync_book_highlights` 全文改為：

```python
    def sync_book_highlights(self, page_id: str, highlights: List[Highlight]) -> None:
        """Upload highlights as 章 toggle → 小節 toggle → quote（💭 註記為
        quote 的 child），then mark book as exported."""
        tree = chapter_tree(highlights)
        logger.info(
            f"開始同步 {len(highlights)} 個劃線（{len(tree)} 章）到 page {page_id}")

        top_blocks = [heading_block(PAGE_TITLE, level=1)]
        top_blocks += [heading_block(g.title, level=1, toggleable=True)
                       for g in tree]
        created = self._append_blocks_returning_ids(page_id, top_blocks)
        if len(created) != len(top_blocks):
            raise RuntimeError(
                f"頂層 block 建立數量不符: 預期 {len(top_blocks)} 實得 {len(created)}")

        for group, block in zip(tree, created[1:]):  # created[0] 是頁首標題
            n_sections = len(group.sections)
            logger.info(
                f"章節: {group.title}（直下 {len(group.direct)} 條、"
                f"{n_sections} 小節）")
            self._append_chapter_children(block["id"], chapter_children(group))

        retry_with_backoff(
            lambda: self._client.pages.update(
                page_id=page_id,
                properties={"Exported": {"checkbox": True}},
            ),
            self._rate_limiter,
        )
```

新增兩個 helpers（放 `_append_blocks` 附近）：

```python
    def _append_blocks_returning_ids(
            self, parent_id: str,
            blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Append top-level blocks and return the created block objects
        (in order) — 章 toggle 需要 id 才能掛 children."""
        created: List[Dict[str, Any]] = []
        for i in range(0, len(blocks), _MAX_BLOCKS_PER_REQUEST):
            batch = blocks[i:i + _MAX_BLOCKS_PER_REQUEST]
            response = retry_with_backoff(
                lambda b=batch: self._client.blocks.children.append(
                    block_id=parent_id, children=b,
                ),
                self._rate_limiter,
            )
            created.extend(response.get("results", []))
        return created

    def _append_chapter_children(self, chapter_block_id: str,
                                 blocks: List[Dict[str, Any]]) -> None:
        """以 toggle 為單位切批（不得把一個 toggle 的 children 拆到兩個
        request），批次預算按含巢狀的總 block 數計。"""
        batch: List[Dict[str, Any]] = []
        budget = 0
        for block in blocks:
            size = total_block_count(block)
            if batch and budget + size > _BATCH_SIZE:
                self._append_blocks(chapter_block_id, batch)
                batch, budget = [], 0
            batch.append(block)
            budget += size
        if batch:
            self._append_blocks(chapter_block_id, batch)
```

刪除已無人引用的舊 helpers：`_group_by_chapter`、`_sanitize_chapter_name`、
`_heading_block`、`_highlight_blocks`、`_annotation_callout`、`_bulleted_block`。
`_SYNC_GENERATED_BLOCK_TYPES` **維持原樣**（見 Global Constraints 的 spec 偏差說明），
但更新其上方註解：

```python
# sync_book_highlights 產生的「頂層」block 類型；resync 重建時只刪這些
# （v2 版面的 quote/小節 heading_2 巢狀在章 toggle=heading_1 內，隨父塊遞迴刪除；
# bulleted_list_item/divider 保留是為了清掉 v1 舊版頁面）。
# 頂層的 paragraph、toggle、quote、heading_2… 視為使用者手動內容，一律保留。
```

- [ ] **Step 3: 更新 DryRun 字樣**

`dry_run_notion_repository.py` 的 `replace_book_highlights` log 訊息改為：

```python
        logger.info(
            f"{_PREFIX} 將刪除 page {page_id} 上同步產生的頂層 block，"
            f"並以兩層 toggle 版面重建 {len(highlights)} 個劃線"
            f"（{len(chapters)} 個章節）"
        )
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest -v`
Expected: all PASS —
`test_annotation.py` 新 block 測試綠、`test_resync.py`（block filter + use case 分支）
不需改動且全綠、`test_highlight_page_blocks.py` 全綠。

Run: `python -m ruff check .`
Expected: no errors（特別注意刪掉舊 helpers 後不留 unused import，如 `math`/`re` 仍有人用勿誤刪）。

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/notion_api_repository.py src/infrastructure/notion/dry_run_notion_repository.py tests/unit/test_annotation.py
git commit -m "✨ feat: 劃線頁 v2 — 兩層巢狀 toggle 版面（章→小節→quote→💭）"
```

---

### Task 6: 端對端驗證 + 全庫 RESYNC

**Files:**
- Modify: `CLAUDE.md`（架構節、Known Cleanup Debt 的資料純度條目、劃線頁版面說明）
- Modify: `docs/NOTION_OUTPUT_IMPROVEMENTS.md`（A 項打勾 + 註記 v2 兩層版面取代原 A1 單層規劃）

**Interfaces:**
- Consumes: Task 1–5 全部。

- [ ] **Step 1: DRY_RUN 全流程**

Run: `DRY_RUN=true python main.py`（PowerShell：`$env:DRY_RUN='true'; python main.py`）
Expected: 讀取照常、劃線數量比先前少（130 筆空白劃線消失）、寫入全部 `[DRY RUN]`、exit 0。

- [ ] **Step 2: 單書真實重建（多層 TOC 的書）**

Run: `$env:DRY_RUN='false'; $env:RESYNC_HIGHLIGHTS='多巴胺'; python main.py`
（或挑任一已匯出且 TOC 命中率高的書）

Expected: log 顯示刪除舊 block、按章上傳；exit 0。

- [ ] **Step 3: Notion 目視驗收（以觀察收尾，不以宣稱收尾）**

在 Notion 打開該書頁面確認：
1. 頁首「📌 劃線筆記」；
2. 章為可收合 toggle，展開後小節再一層 toggle；
3. 劃線是 quote block；有註記的劃線其 💭 callout 縮排在 quote 之下;
4. 無空白劃線、無舊版 bullet 殘留；
5. 使用者手動加的內容（若該頁有）仍在。

- [ ] **Step 4: 無 TOC 書驗證（fallback 路徑）**

挑一本 sideload/無 TOC 的書：
Run: `$env:RESYNC_HIGHLIGHTS='<書名子字串>'; python main.py`
Expected: 單層章 toggle（無小節層）、quote 版面正常。

- [ ] **Step 5: 全庫重建（需使用者確認後執行）**

**此步為長時間、全庫寫入操作——執行前向使用者確認時點**（Ollama 無關，但
`ENABLE_ZETTELKASTEN_CARDS=true` 時卡片流程會逐書跑，建議此輪暫設 `false` 加速）。

Run: `$env:RESYNC_HIGHLIGHTS='all'; $env:ENABLE_ZETTELKASTEN_CARDS='false'; python main.py`
Expected: 全部書籍重建成功、`SyncResult` 無 errors、exit 0。抽查 3 本
（多層 TOC / 單層 / 無 TOC 各一）版面正確。

- [ ] **Step 6: 文件同步 + 收尾 commit**

- `CLAUDE.md`：Chapter Extraction 節補 `resolve_parts`；「資料純度」債務條目改為已解
  （Type/Hidden 已過濾）；Configuration/架構描述提到劃線頁 v2 兩層 toggle 版面與
  `highlight_page_blocks.py`。
- `docs/NOTION_OUTPUT_IMPROVEMENTS.md`：A 項打勾，註記「以兩層巢狀 toggle 實作，
  規格見 2026-07-13 spec；A3 以無損拆段取代截斷」。

```bash
git add CLAUDE.md docs/NOTION_OUTPUT_IMPROVEMENTS.md
git commit -m "📝 docs: 劃線頁 v2 完成 — 更新 CLAUDE.md 地圖與 A 項進度"
```

- [ ] **Step 7: 分支收尾**

實作全綠且端對端驗證通過後，用 superpowers:finishing-a-development-branch 決定
merge / PR。

---

## Self-Review 紀錄

- **Spec coverage**：1-1 過濾（Task 1）、1-2 拆段（Task 4 `split_rich_text`）、
  1-3 兩層 toggle（Task 4+5）、1-4 resolver 結構化（Task 2+3）、1-5 RESYNC 對齊
  （Task 5 註解 + Task 6 全庫重建；刪除清單經分析維持原樣，偏差已記錄）。
- **巢狀深度**：單一 append 最深為「小節 toggle → quote → callout」= 頂層下兩層，
  在 Notion API 允許範圍內；章層 children 由第二輪 append（對章 block id）掛入。
- **Type consistency**：`resolve_parts` 回傳 tuple 在 Task 2 定義、Task 3 消費；
  `quote_block(h: Highlight)` 在 Task 4 定義、Task 5 的 test_annotation 消費；
  `total_block_count`/`chapter_children` 名稱前後一致。
