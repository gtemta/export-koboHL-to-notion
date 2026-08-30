# 卡片主張式標題（K1）與章節參照消毒（K4）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓新產生的卡片標題是可獨立成立的論斷，並讓 📖 章節 callout 不再印出被誤判成章名的劃線內文。

**Architecture:** K1 只改 `zettelkasten_generator.py` 兩支產卡 prompt 的文字，審核 prompt 一字不動。K4 新增一個模組層純函式 `_clean_chapter_reference(raw, *, from_toc)`，在**建卡當下**套用於兩個 `chapter_reference=` 賦值點；可信度訊號 `chapter_from_toc` 由 `GenerateBookCardsUseCase._to_dict()` 從 `Highlight.toc_chapter` 帶入。Notion 層只改一個守門條件，不理解任何內容啟發式。

**Tech Stack:** Python 3.13、`unittest`（跑在 pytest 下）、ruff、Ollama（僅真跑驗收需要）。

**設計出處：** `docs/superpowers/specs/2026-08-30-card-claim-titles-and-chapter-sanitization-design.md`

## Global Constraints

- 繁體中文、台灣用語：所有 prompt 文字、log、註解、commit message。
- Commit 慣例：gitmoji + type，一個 commit 一個意圖（例：`✨ feat: ...`、`🐛 fix: ...`、`📝 docs: ...`）。
- 每個 task 結束前 `python -m ruff check .` 與 `python -m pytest` 都要綠燈。
- **不得修改** `CardReviewer._build_review_prompt`（審核四面向與評分規則）。
- **不得修改** `src/infrastructure/persistence/chapter_title_heuristics.py`（源頭收緊超出本批範圍）。
- **不得回填**既有卡片：K1/K4 只影響未來新產生的卡。
- 現有測試 325 passed / 4 skipped 是基準線，不得有既有測試轉紅。

---

### Task 1: `_clean_chapter_reference` 純函式

**Files:**
- Modify: `zettelkasten_generator.py`（在 `@dataclass class ZettelkastenCard` 定義的正上方新增）
- Test: `tests/unit/test_chapter_reference.py`（新建）

**Interfaces:**
- Consumes: 模組既有的 `logger`（`logging.getLogger('kobo_notion_sync')`，檔案第 26 行）
- Produces: `_clean_chapter_reference(raw: Optional[str], *, from_toc: bool) -> str` — Task 2 會在兩個建卡點呼叫它。回傳值一律是去除前後空白後的字串，判定為污染時回空字串。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_chapter_reference.py`：

```python
"""章節參照消毒（K4）：TOC 來源照留，heuristic 猜的才審查。

污染樣本取自 docs/KNOWLEDGE_REFINEMENT_PLAN.md「關鍵事實」#4 的真實輸出。
"""
import unittest

from zettelkasten_generator import _clean_chapter_reference

_POLLUTED = (
    "拮抗理論」：「任何長時間或反覆從享樂或情感中性狀態脫離的情況⋯⋯"
    "都是有其代價的。」50這種代價就是一種..."
)


class TestCleanChapterReference(unittest.TestCase):
    def test_polluted_highlight_text_is_dropped(self):
        self.assertEqual(_clean_chapter_reference(_POLLUTED, from_toc=False), "")

    def test_toc_label_is_kept_even_when_long(self):
        label = "第三章 建立讓好習慣自動發生的系統 › 讓提示顯而易見的環境設計"
        self.assertGreater(len(label), 25)
        self.assertEqual(_clean_chapter_reference(label, from_toc=True), label)

    def test_toc_label_with_quotes_is_kept(self):
        label = "第三章「習慣的力量」"
        self.assertEqual(_clean_chapter_reference(label, from_toc=True), label)

    def test_guessed_label_with_quotes_is_dropped(self):
        # 已知取捨：真實章名若含「」但來自 heuristic 猜測，會被一併清掉。
        # 寧可漏掉一個章名，也不要讓劃線內文印在卡片上。
        self.assertEqual(
            _clean_chapter_reference("第三章「習慣的力量」", from_toc=False), ""
        )

    def test_guessed_label_over_25_chars_is_dropped(self):
        self.assertEqual(_clean_chapter_reference("一" * 26, from_toc=False), "")

    def test_short_guessed_label_is_kept(self):
        self.assertEqual(
            _clean_chapter_reference("第三章 習慣的力量", from_toc=False),
            "第三章 習慣的力量",
        )

    def test_unknown_sentinel_is_dropped_regardless_of_source(self):
        # 'Unknown' 是兩處 highlight.get('chapter_name', 'Unknown') 的哨兵預設值，
        # 不是任何真實章名，來自哪條路徑都該清掉。
        self.assertEqual(_clean_chapter_reference("Unknown", from_toc=True), "")
        self.assertEqual(_clean_chapter_reference("Unknown", from_toc=False), "")

    def test_empty_and_none_are_dropped(self):
        self.assertEqual(_clean_chapter_reference("", from_toc=True), "")
        self.assertEqual(_clean_chapter_reference(None, from_toc=False), "")

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(_clean_chapter_reference("  第一章  ", from_toc=False), "第一章")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `python -m pytest tests/unit/test_chapter_reference.py -v`
Expected: FAIL — `ImportError: cannot import name '_clean_chapter_reference' from 'zettelkasten_generator'`

- [ ] **Step 3: 寫最小實作**

在 `zettelkasten_generator.py` 中 `@dataclass class ZettelkastenCard` 的正上方插入：

```python
# 章節參照消毒（K4）。污染唯一來源是 chapter_title_heuristics.extract_real_chapter_title()
# ——它拿劃線正文去猜章名、容忍到 150 字，只要含「：」就給 3 分信心，於是整段內文會被
# 當成章名印在卡片的 📖 callout 上。TOC 來源的章名是 Kobo 目錄的真實標題，不做任何判斷。
_CHAPTER_JUNK_CHARS = ('」', '「', '⋯', '。')
_CHAPTER_MAX_LEN = 25
_CHAPTER_UNKNOWN = 'Unknown'


def _clean_chapter_reference(raw: Optional[str], *, from_toc: bool) -> str:
    """回傳可信的章節標籤；判定為劃線內文時回空字串。

    `from_toc=True` 代表章名來自 Kobo 目錄（`Highlight.toc_chapter` 非 None），
    一律照留。其餘都是猜的，才套長度與標點的審查規則。
    """
    text = (raw or '').strip()
    if not text or text == _CHAPTER_UNKNOWN:
        return ''
    if from_toc:
        return text
    if len(text) > _CHAPTER_MAX_LEN or any(c in text for c in _CHAPTER_JUNK_CHARS):
        logger.debug(f"章節參照疑似劃線內文，已捨棄：{text[:30]}")
        return ''
    return text
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_chapter_reference.py -v`
Expected: PASS（9 個測試全綠）

- [ ] **Step 5: 跑 lint 與全量測試**

Run: `python -m ruff check . ; python -m pytest -q`
Expected: ruff 無錯誤；pytest 334 passed / 4 skipped（原 325 + 新增 9）

- [ ] **Step 6: Commit**

```bash
git add zettelkasten_generator.py tests/unit/test_chapter_reference.py
git commit -m "✨ feat: 章節參照消毒純函式（TOC 來源照留，猜的才審查）"
```

---

### Task 2: 兩個建卡點套用消毒 + `chapter_from_toc` 資料流

**Files:**
- Modify: `zettelkasten_generator.py`（`generate_card` 的 `chapter_reference=` 賦值、`_parse_batch_response` 的 `chapter_reference=` 賦值）
- Modify: `src/application/use_cases/generate_book_cards_use_case.py`（`_to_dict()`）
- Test: `tests/unit/test_chapter_reference.py`（在 Task 1 的檔案末尾追加兩個 class）

**Interfaces:**
- Consumes: Task 1 的 `_clean_chapter_reference(raw, *, from_toc)`
- Produces: highlight dict 多一個鍵 `chapter_from_toc: bool`。兩個建卡點以 `highlight.get('chapter_from_toc', False)` 讀取——**缺鍵時預設 False（不信任、套審查）**，這樣 legacy 入口與舊測試傳的 dict 會走保守路線。

- [ ] **Step 1: 寫失敗的測試**

把 `tests/unit/test_chapter_reference.py` 最上方的 import 區補成：

```python
import unittest
from unittest.mock import patch

from src.application.use_cases.generate_book_cards_use_case import GenerateBookCardsUseCase
from src.domain.entities.highlight import Highlight
from zettelkasten_generator import ZettelkastenLLMEnhancer, _clean_chapter_reference
```

在 `if __name__ == "__main__":` 之前追加：

```python
_BATCH_RESPONSE = (
    "### CARD_1\n"
    "【標題】延遲滿足會反過來擴大痛苦\n"
    "【內容】" + "內" * 100 + "\n"
    "【標籤】習慣、複利\n"
)


class TestCardConstructionSanitisesChapter(unittest.TestCase):
    """建卡當下就清乾淨，讓 cards_output/*.json 落地的就是可信值。"""

    def test_batch_parse_drops_polluted_chapter(self):
        highlights = [{
            "text": "原始劃線",
            "chapter_name": _POLLUTED,
            "chapter_progress": 0.42,
        }]
        cards = ZettelkastenLLMEnhancer()._parse_batch_response(
            _BATCH_RESPONSE, highlights
        )
        self.assertEqual(cards[0].chapter_reference, "")
        # 進度是 Kobo 硬數據，不受章名判定影響
        self.assertEqual(cards[0].chapter_progress, 0.42)

    def test_batch_parse_keeps_toc_chapter(self):
        label = "第三章 建立讓好習慣自動發生的系統 › 讓提示顯而易見的環境設計"
        highlights = [{
            "text": "原始劃線",
            "chapter_name": label,
            "chapter_progress": 0.42,
            "chapter_from_toc": True,
        }]
        cards = ZettelkastenLLMEnhancer()._parse_batch_response(
            _BATCH_RESPONSE, highlights
        )
        self.assertEqual(cards[0].chapter_reference, label)

    def test_generate_card_drops_polluted_chapter(self):
        highlight = {
            "text": "原始劃線",
            "chapter_name": _POLLUTED,
            "chapter_progress": 0.42,
        }
        single_response = (
            "【標題】延遲滿足會反過來擴大痛苦\n"
            "【內容】" + "內" * 100 + "\n"
            "【標籤】習慣、複利\n"
        )
        with patch(
            "zettelkasten_generator._ollama_generate",
            return_value=single_response,
        ):
            card = ZettelkastenLLMEnhancer().generate_card(highlight, "書名")
        self.assertEqual(card.chapter_reference, "")

    def test_unknown_default_never_reaches_the_card(self):
        # highlight dict 沒有 chapter_name → 兩處建卡點的 .get 預設值 'Unknown'
        highlights = [{"text": "原始劃線", "chapter_progress": 0.0}]
        cards = ZettelkastenLLMEnhancer()._parse_batch_response(
            _BATCH_RESPONSE, highlights
        )
        self.assertEqual(cards[0].chapter_reference, "")


class TestHighlightDictCarriesTocFlag(unittest.TestCase):
    """可信度訊號的唯一來源：Highlight.toc_chapter 非 None ⟺ 章名來自 Kobo 目錄。"""

    @staticmethod
    def _highlight(**overrides):
        kwargs = dict(
            text="劃線內容",
            chapter_name="第一章",
            chapter_progress=0.5,
            content_id="cid",
        )
        kwargs.update(overrides)
        return Highlight(**kwargs)

    def test_toc_backed_highlight_is_marked_trusted(self):
        h = self._highlight(toc_chapter="第一章", toc_section="小節")
        self.assertTrue(GenerateBookCardsUseCase._to_dict(h)["chapter_from_toc"])

    def test_guessed_highlight_is_marked_untrusted(self):
        h = self._highlight(toc_chapter=None)
        self.assertFalse(GenerateBookCardsUseCase._to_dict(h)["chapter_from_toc"])
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `python -m pytest tests/unit/test_chapter_reference.py -v`
Expected: FAIL — `TestCardConstructionSanitisesChapter` 的三個清除案例回傳的是原始污染字串而非 `""`；`TestHighlightDictCarriesTocFlag` 兩個都 `KeyError: 'chapter_from_toc'`

- [ ] **Step 3: 寫最小實作**

`zettelkasten_generator.py` — `generate_card` 內，把

```python
        chapter = highlight.get('chapter_name', 'Unknown')
```

改為

```python
        chapter = _clean_chapter_reference(
            highlight.get('chapter_name', 'Unknown'),
            from_toc=bool(highlight.get('chapter_from_toc', False)),
        )
```

`zettelkasten_generator.py` — `_parse_batch_response` 內，把

```python
            chapter = highlight.get('chapter_name', 'Unknown')
```

改為（縮排是迴圈內的 12 空格）

```python
            chapter = _clean_chapter_reference(
                highlight.get('chapter_name', 'Unknown'),
                from_toc=bool(highlight.get('chapter_from_toc', False)),
            )
```

`src/application/use_cases/generate_book_cards_use_case.py` — `_to_dict()` 加一個鍵：

```python
    @staticmethod
    def _to_dict(h: Highlight) -> dict:
        return {
            "text": h.text,
            "chapter_name": h.chapter_name,
            "chapter_progress": h.chapter_progress,
            "current_chapter_progress": h.current_chapter_progress,
            "annotation": h.annotation,
            "bookmark_id": h.bookmark_id,
            # 章名來自 Kobo 目錄還是 heuristic 猜的——決定 _clean_chapter_reference
            # 要不要審查它。缺這個鍵時預設 False（不信任），legacy 入口因此走保守路線。
            "chapter_from_toc": h.toc_chapter is not None,
        }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_chapter_reference.py -v`
Expected: PASS（15 個測試全綠）

- [ ] **Step 5: 跑 lint 與全量測試**

Run: `python -m ruff check . ; python -m pytest -q`
Expected: ruff 無錯誤；pytest 340 passed / 4 skipped。若 `tests/unit/test_card_store.py` 或 `test_review_gate.py` 有測試因章名被清而轉紅，代表那些測試用了 >25 字或含「」的假章名——把假資料改短即可，**不要**放寬 `_CHAPTER_MAX_LEN`。

- [ ] **Step 6: Commit**

```bash
git add zettelkasten_generator.py src/application/use_cases/generate_book_cards_use_case.py tests/unit/test_chapter_reference.py
git commit -m "🐛 fix: 建卡時清掉被誤判成章名的劃線內文"
```

---

### Task 3: 📖 callout 守門改為「章名或進度任一有值」

**Files:**
- Modify: `src/infrastructure/notion/zettelkasten_card_repository.py`（`_build_children()` 內的 `if card.chapter_reference:`，約第 744 行）
- Test: `tests/unit/test_chapter_reference.py`（追加一個 class）

**Interfaces:**
- Consumes: Task 2 之後 `card.chapter_reference` 可能是空字串
- Produces: 無新介面。行為契約：章名空但進度非 0 → callout 內容為 `（進度 42%）`；兩者皆空 → 完全沒有 callout。

- [ ] **Step 1: 寫失敗的測試**

在 `tests/unit/test_chapter_reference.py` 的 import 區再補：

```python
from src.infrastructure.notion.zettelkasten_card_repository import ZettelkastenCardRepository
from zettelkasten_generator import ZettelkastenCard
```

追加：

```python
def _repo():
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    repo._schema_props = None  # 預先塞快取，避免任何網路呼叫
    return repo


def _card(**overrides):
    kwargs = dict(
        id="id", title="標題", content="內容", source_highlight="劃線",
        chapter_reference="", chapter_progress=0.0,
    )
    kwargs.update(overrides)
    return ZettelkastenCard(**kwargs)


class TestChapterCalloutFallsBackToProgress(unittest.TestCase):
    """進度是 Kobo 硬數據，不該被章名的問題連坐。"""

    @staticmethod
    def _callouts(blocks):
        return [b for b in blocks if b["type"] == "callout"
                and b["callout"]["icon"]["emoji"] == "📖"]

    def test_progress_only_callout_when_chapter_was_dropped(self):
        blocks = _repo()._build_children(_card(chapter_reference="", chapter_progress=0.42))
        callouts = self._callouts(blocks)
        self.assertEqual(len(callouts), 1)
        self.assertEqual(
            callouts[0]["callout"]["rich_text"][0]["text"]["content"],
            "（進度 42%）",
        )

    def test_no_callout_when_both_chapter_and_progress_are_empty(self):
        blocks = _repo()._build_children(_card(chapter_reference="", chapter_progress=0.0))
        self.assertEqual(self._callouts(blocks), [])

    def test_chapter_and_progress_together_unchanged(self):
        blocks = _repo()._build_children(
            _card(chapter_reference="第一章", chapter_progress=0.42)
        )
        self.assertEqual(
            self._callouts(blocks)[0]["callout"]["rich_text"][0]["text"]["content"],
            "第一章（進度 42%）",
        )
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `python -m pytest tests/unit/test_chapter_reference.py::TestChapterCalloutFallsBackToProgress -v`
Expected: FAIL — `test_progress_only_callout_when_chapter_was_dropped` 得到 0 個 callout（現有守門條件是 `if card.chapter_reference:`）

- [ ] **Step 3: 寫最小實作**

`src/infrastructure/notion/zettelkasten_card_repository.py`，把

```python
        if card.chapter_reference:
```

改為

```python
        # 章名可能被 _clean_chapter_reference 清成空字串（誤判成章名的劃線內文），
        # 但進度是 Kobo 硬數據、永遠可信，不該一起消失。
        if card.chapter_reference or card.chapter_progress:
```

其餘組字邏輯不動。

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_chapter_reference.py -v`
Expected: PASS（18 個測試全綠）

- [ ] **Step 5: 跑 lint 與全量測試**

Run: `python -m ruff check . ; python -m pytest -q`
Expected: ruff 無錯誤；pytest 343 passed / 4 skipped

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/notion/zettelkasten_card_repository.py tests/unit/test_chapter_reference.py
git commit -m "🐛 fix: 章名被清掉時 📖 callout 仍保留閱讀進度"
```

---

### Task 4: K1 主張式標題（兩支 prompt）

**Files:**
- Modify: `zettelkasten_generator.py`（`_build_prompt` 的【標題】規則與注意事項第 1 條、`generate_card` docstring、`_build_batch_prompt` 的 format 範例與規則 5）
- Test: `tests/unit/test_card_claim_title.py`（新建）

**Interfaces:**
- Consumes: 無
- Produces: 無程式介面改變。`【標題】` 標記與 `_parse_response` 的解析規則完全不動，只換 prompt 內的規則文字。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_card_claim_title.py`：

```python
"""K1：產卡 prompt 要主張句，審核 prompt 不動。

斷言刻意只抓規則的關鍵字與長度數字——prompt 文案會微調，但「要求主張句」
與「5-20 字」這兩件事若消失就是回歸。
"""
import unittest

from zettelkasten_generator import CardReviewer, ZettelkastenCard, ZettelkastenLLMEnhancer


class TestClaimStyleTitleRule(unittest.TestCase):
    def test_single_card_prompt_asks_for_a_claim(self):
        prompt = ZettelkastenLLMEnhancer()._build_prompt("劃線文字", "書名")
        self.assertIn("論斷", prompt)
        self.assertIn("5-20", prompt)
        self.assertNotIn("5-15", prompt)

    def test_single_card_prompt_forbids_inventing_conclusions(self):
        # 與審核 correctness 面向共存的接縫：原文沒論斷時不得自行推論。
        prompt = ZettelkastenLLMEnhancer()._build_prompt("劃線文字", "書名")
        self.assertIn("不要自行推論出原文沒有的結論", prompt)

    def test_batch_prompt_asks_for_a_claim(self):
        highlights = [{"text": "劃線一"}, {"text": "劃線二"}]
        prompt = ZettelkastenLLMEnhancer()._build_batch_prompt(highlights, "書名")
        self.assertIn("論斷", prompt)
        self.assertIn("5-20", prompt)
        self.assertNotIn("5-15", prompt)

    def test_review_prompt_is_untouched(self):
        # 標題風格不進審核關卡：不放寬 correctness，也不加嚴 consistency。
        card = ZettelkastenCard(
            id="id", title="標題", content="內容",
            source_highlight="劃線", chapter_reference="", chapter_progress=0.0,
        )
        prompt = CardReviewer()._build_review_prompt(card, "書名", "", [])
        self.assertNotIn("論斷", prompt)
        self.assertNotIn("主張句", prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認它失敗**

Run: `python -m pytest tests/unit/test_card_claim_title.py -v`
Expected: FAIL — 前三個測試都在 `assertIn("論斷", prompt)` 掛掉（現行文字是「概括這段話的核心概念」）。

若 `test_review_prompt_is_untouched` 因 `CardReviewer()` 或 `_build_review_prompt` 的簽章不符而 error，先跑

```bash
python -c "import inspect, zettelkasten_generator as z; print(inspect.signature(z.CardReviewer.__init__)); print(inspect.signature(z.CardReviewer._build_review_prompt))"
```

對出真正的參數再修測試——**不要**為了配合測試去改 `CardReviewer`。

- [ ] **Step 3: 寫最小實作**

`zettelkasten_generator.py` — `_build_prompt` 內，把

```
【標題】5-15個字，概括這段話的核心概念
```

改為（三行）

```
【標題】5-20個字，寫成一句可以獨立成立的論斷，讓人不看內容也知道這張卡主張什麼
（✅「語言愈先進，謊言愈精美」／❌「語言的進化與欺騙藝術的關係」）
若原文只是定義或描述、本身沒有論斷，就寫成精準的概念陳述句，不要自行推論出原文沒有的結論
```

同一支 prompt 的「注意事項」第 1 條，把

```
1. 標題要精準、簡潔，能讓人一眼看出核心概念
```

改為

```
1. 標題要精準、簡潔，能讓人一眼看出這張卡主張什麼
```

`zettelkasten_generator.py` — `_build_batch_prompt` 的 format 範例，把

```python
                f"### CARD_{i}\n【標題】5-15個字...\n【內容】100-150個字...\n"
```

改為

```python
                f"### CARD_{i}\n【標題】5-20個字的論斷句...\n【內容】100-150個字...\n"
```

同一支 prompt 的規則 5，把

```
5. 標題 5-15 個字，內容 100-150 個字
```

改為（三行）

```
5. 標題 5-20 個字，要寫成一句可以獨立成立的論斷，讓人不看內容也知道這張卡主張什麼
   （✅「語言愈先進，謊言愈精美」／❌「語言的進化與欺騙藝術的關係」）；若原文只是定義
   或描述、本身沒有論斷，就寫成精準的概念陳述句，不要自行推論出原文沒有的結論。內容 100-150 個字
```

`generate_card` 的 docstring，把

```python
        - Title: 5-15 characters summarizing the core concept
```

改為

```python
        - Title: a 5-20 character claim the card can stand on
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_card_claim_title.py -v`
Expected: PASS（4 個測試全綠）

- [ ] **Step 5: 跑 lint 與全量測試**

Run: `python -m ruff check . ; python -m pytest -q`
Expected: ruff 無錯誤；pytest 347 passed / 4 skipped

- [ ] **Step 6: Commit**

```bash
git add zettelkasten_generator.py tests/unit/test_card_claim_title.py
git commit -m "✨ feat: 產卡 prompt 改要求主張式標題（審核 prompt 不動）"
```

---

### Task 5: 文件同步與真跑驗收

**Files:**
- Modify: `CLAUDE.md`（Project Architecture，接在「卡片視覺與回訪（2026-08-05）」之後）
- Modify: `docs/KNOWLEDGE_REFINEMENT_PLAN.md`（總進度的 Phase 4 那一行）

**Interfaces:**
- Consumes: Task 1–4 的全部行為
- Produces: 無程式介面。

- [ ] **Step 1: 更新 `docs/KNOWLEDGE_REFINEMENT_PLAN.md` 的總進度**

把

```markdown
- ⬜ Phase 4：知識抽取精練（K1 主張式標題 / K2 延伸段 / K3 註記上卡 / K4 章節消毒）
```

改為

```markdown
- 🟡 Phase 4：知識抽取精練 — K1（主張式標題）、K4（章節消毒）完成 2026-08-30，
  見 `docs/superpowers/specs/2026-08-30-card-claim-titles-and-chapter-sanitization-design.md`。
  K1 採「忠於原文優先」：prompt 要主張句，但原文只是定義／描述時寫概念陳述句，
  **審核 prompt 一字未動**。K4 採來源分流：`Highlight.toc_chapter` 非 None 的章名照留，
  heuristic 猜的才套長度／標點審查；**未動 `chapter_title_heuristics.py` 源頭**。
  ⬜ K2（延伸段）、K3（註記上卡）仍未做。
```

- [ ] **Step 2: 更新 `CLAUDE.md`**

在「卡片視覺與回訪（2026-08-05）」段落之後，新增一段：

```markdown
### 卡片標題與章節參照（2026-08-30）

- **標題是主張句**：兩支產卡 prompt（`_build_prompt` 與 `_build_batch_prompt`）都要求
  5-20 字的獨立論斷，**兩處必須同步改**——`main.py` 實際走的是批次那支。原文只是定義或
  描述時退回精準的概念陳述句，不得自行推論；這是為了與審核 `correctness` 面向
  （禁止加入原文沒說的結論）共存，**審核 prompt 因此一字未動**。
- **章名消毒**：`_clean_chapter_reference(raw, *, from_toc)` 在**建卡當下**套用於兩個
  `chapter_reference=` 賦值點，讓 `cards_output/*.json` 落地的就是可信值（不在 Notion
  層 render 時才清——那樣 JSON 會留髒值，續傳與未來取材都會吃到）。
  `from_toc` 由 `GenerateBookCardsUseCase._to_dict()` 從 `Highlight.toc_chapter is not None`
  帶入，**缺鍵預設 False**（legacy 入口走保守路線）。污染唯一來源是
  `chapter_title_heuristics.extract_real_chapter_title()`——它拿劃線正文猜章名、容忍到
  150 字；該檔案刻意未收緊，收緊它會連帶改變無 TOC 書籍的劃線頁分章。
- 章名被清成空字串時，📖 callout 仍會保留閱讀進度（守門條件是
  `chapter_reference or chapter_progress`）——進度是 Kobo 硬數據，不受章名判定連坐。
```

- [ ] **Step 3: 跑完整品質關卡**

Run: `python -m ruff check . ; python -m pytest -q`
Expected: ruff 無錯誤；347 passed / 4 skipped

- [ ] **Step 4: Commit 文件**

```bash
git add CLAUDE.md docs/KNOWLEDGE_REFINEMENT_PLAN.md
git commit -m "📝 docs: 卡片主張式標題與章節消毒的架構說明"
```

- [ ] **Step 5: 真跑驗收（DoD 第 3 條，不可略過）**

`DRY_RUN` **驗不到**卡片流程（`container.py` 在 dry-run 一律跳過），必須真跑。需要 Ollama
在線且 `OLLAMA_MODEL` 與 `OLLAMA_REVIEW_MODEL` 都已 pull。

```bash
ENABLE_ZETTELKASTEN_CARDS=true python main.py
```

- **K1 驗收**：挑一本這次新產卡的書，在卡片盒看新卡標題是否為論斷句而非主題名。
- **K4 驗收**：需要**一本無 TOC 的書**（有 TOC 的書走 `from_toc=True`、行為完全不變）。
  先確認手上的 `KoboReader.sqlite` 有哪些書沒有 TOC 條目：

```bash
python -c "import sqlite3; c=sqlite3.connect('KoboReader.sqlite'); rows=c.execute(\"select b.Title, (select count(*) from content t where t.ContentType=899 and t.BookID=b.ContentID) from content b where b.ContentType=6\").fetchall(); print([r[0] for r in rows if r[1]==0][:10])"
```

  驗收點：該書新卡的 📖 callout 沒有出現引號、刪節號或整段內文；被清掉章名的卡仍看得到
  「（進度 xx%）」。

- [ ] **Step 6: 收工說明**

在回報中寫出實際觀察到的證據（卡片標題樣本、📖 callout 樣本）。
**若沒有取得無-TOC 書籍的實跑證據，必須明確寫出「K4 僅以單元測試驗證，未取得無-TOC
書籍的實跑證據」**，不得含混帶過。

---

## Self-Review

**Spec 覆蓋檢查：**

| Spec 要求 | 對應 Task |
|-----------|-----------|
| K1 兩處 prompt 同步改、長度 5-20 | Task 4 Step 3 |
| 審核 prompt 一字不動 | Task 4 的 `test_review_prompt_is_untouched` + Global Constraints |
| `_clean_chapter_reference` 五步判斷順序 | Task 1 Step 3 |
| `'Unknown'` 哨兵不看 `from_toc` | Task 1 的 `test_unknown_sentinel_is_dropped_regardless_of_source` |
| DEBUG log 只在第 3、4 步 | Task 1 Step 3（`logger.debug` 只在審查分支內） |
| 套用於兩個建卡點、建卡當下清 | Task 2 Step 3 |
| `chapter_from_toc` 由 `_to_dict` 帶入、缺鍵預設 False | Task 2 Step 3 + `TestHighlightDictCarriesTocFlag` |
| 📖 callout 守門改為章名或進度 | Task 3 |
| 不動 `chapter_title_heuristics.py` | Global Constraints |
| 不回填既有卡片 | Global Constraints |
| 真跑驗收需無-TOC 書籍，取不到要明講 | Task 5 Step 5–6 |

**Placeholder 掃描：** 無 TBD／TODO；每個 code step 都附可直接貼上的完整程式碼。

**型別一致性：** `_clean_chapter_reference(raw: Optional[str], *, from_toc: bool) -> str` 在
Task 1 定義、Task 2 呼叫，函式名與關鍵字參數一致；`chapter_from_toc` 這個鍵名在生產端
（`_to_dict`）與消費端（兩個建卡點）拼寫一致；`_POLLUTED` 在 Task 1 定義、Task 2 沿用同一個檔案。
