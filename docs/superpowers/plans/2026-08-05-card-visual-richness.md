# 卡片盒視覺豐富度與回訪機制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓卡片盒的每張卡在 Notion 上帶有「分類色卡 cover ＋ 語意 emoji icon ＋ 加工狀態」，使卡片牆一眼可辨、且有回訪的把手；既有卡片以回填工具一次補齊。

**Architecture:** cover 由分類決定（純規則，`src/infrastructure/notion/card_visuals.py`），icon 由 emoji 決定（`zettelkasten_generator.py`，搭既有的批次分類 Ollama 呼叫便車，固定調色盤 + 規則 fallback 保底）。責任邊界刻意分開：generator 知道卡片語意、Notion 層知道 Notion。回填工具走同一批函式，不另寫一份邏輯。

**Tech Stack:** Python 3.13、`notion-client`、Ollama REST（既有 `_ollama_generate`）、pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-08-05-card-visual-richness-design.md`

## Global Constraints

- **`zettelkasten_generator.py` 不得 import `src.*`** — `legacy/` 那條 sys.path 路徑會壞。反向（`src/` import generator）是既有慣例，可以。
- **emoji 調色盤兩條不變條件**：每個元素恰為 1 個 codepoint（不含 ZWJ U+200D、variation selector U+FE0F、膚色修飾符）；且與 `settings.DEFAULT_TAG_CATEGORIES` 自帶的 emoji 零交集。兩條都要有測試。
- **穩定雜湊一律用 `hashlib.sha1`，禁止 Python 內建 `hash()`** — 字串 hash 每個 process 有隨機 salt，會讓同一張卡每次跑換色、回填失去冪等性。
- **可用的 Notion 內建 cover**（2026-08-05 curl 驗證）：`gradients_1.png`～`gradients_9.png`、`solid_beige.png`、`solid_red.png`、`solid_yellow.png`、`solid_blue.png`。**`gradients_10.png` 與 woodblocks 系列為 404，不得使用。**
- **`DRY_RUN=true` 驗不到卡片流程**（`container.py` 在 dry-run 一律跳過），最終驗證必須真跑 `python main.py`。
- Quality gate：`python -m ruff check .` 與 `python -m pytest` 全綠。
- Commit 慣例：gitmoji + type，一個 commit 一個意圖。開 feature branch，`main` 永遠可跑。
- **不准留已知會壞的測試**：改到既有測試就地修，不得另建一份平行測試檔。

## File Structure

| 檔案 | 動作 | 責任 |
|------|------|------|
| `src/infrastructure/notion/card_visuals.py` | 新增 | 分類 → Notion cover URL（純函式、零 IO）。唯一知道 cover URL 長相的地方 |
| `tests/unit/test_card_visuals.py` | 新增 | cover 對照、多分類取首、未知分類 sha1 穩定性 |
| `zettelkasten_generator.py` | 修改 | `_ICON_PALETTE`、`_fallback_icon`、`ZettelkastenCard.icon`、分類 prompt/parser 產 emoji |
| `tests/unit/test_card_icons.py` | 新增 | 調色盤不變條件、`_fallback_icon` |
| `tests/unit/test_card_categories.py` | 修改 | `_parse_classification` 回傳型別變了，既有測試就地改 |
| `src/infrastructure/notion/zettelkasten_card_repository.py` | 修改 | 新欄位 schema、`加工狀態` 寫入、`pages.create` 帶 icon/cover |
| `tests/unit/test_card_visual_upload.py` | 新增 | schema to_add、properties、create payload |
| `tools/backfill_card_visuals.py` | 新增 | 舊卡回填（`--dry-run`、冪等） |
| `tests/unit/test_backfill_card_visuals.py` | 新增 | 頁面欄位讀取與 update payload 組裝（純函式） |
| `CLAUDE.md` / `docs/DECISIONS.md` | 修改 | 同圈更新地圖 |

---

### Task 0: 開 feature branch

- [ ] **Step 1: 從目前分支開新分支**

```bash
git checkout -b feat/card-visual-richness
git status
```

Expected: `On branch feat/card-visual-richness`、working tree clean。

---

### Task 1: 分類 → cover URL（純函式）

**Files:**
- Create: `src/infrastructure/notion/card_visuals.py`
- Test: `tests/unit/test_card_visuals.py`

**Interfaces:**
- Consumes: `ZettelkastenLLMEnhancer._category_core(name) -> str`（既有，`zettelkasten_generator.py:589`；只留字母/數字，去 emoji）
- Produces: `cover_url_for(categories: Optional[Sequence[str]]) -> str` — 回傳完整 https URL，永遠不回空字串

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_card_visuals.py`：

```python
"""卡片 cover 選色：分類 → Notion 內建 cover URL（純邏輯）。"""
import unittest

from src.config.settings import DEFAULT_TAG_CATEGORIES
from src.infrastructure.notion.card_visuals import (
    _COVER_BASE,
    _DEFAULT_COVER,
    _FALLBACK_COVERS,
    cover_url_for,
)


class TestCoverUrlFor(unittest.TestCase):
    def test_known_category(self):
        self.assertEqual(
            cover_url_for(["💞心理學"]), _COVER_BASE + "gradients_1.png")

    def test_plain_text_category_matches_emoji_version(self):
        # 本地小模型常常不照抄 emoji；比對走 text core
        self.assertEqual(cover_url_for(["心理學"]), cover_url_for(["💞心理學"]))

    def test_zwj_category(self):
        self.assertEqual(
            cover_url_for(["🧘‍♂️人生觀點"]), _COVER_BASE + "gradients_4.png")

    def test_multi_category_takes_first(self):
        self.assertEqual(
            cover_url_for(["💼商務", "💞心理學"]), _COVER_BASE + "gradients_3.png")

    def test_empty_falls_back_to_default(self):
        self.assertEqual(cover_url_for([]), _COVER_BASE + _DEFAULT_COVER)

    def test_none_falls_back_to_default(self):
        self.assertEqual(cover_url_for(None), _COVER_BASE + _DEFAULT_COVER)

    def test_blank_category_skipped(self):
        # 只有 emoji、沒有文字核心的分類視為無效，往下一個找
        self.assertEqual(
            cover_url_for(["🔥", "💼商務"]), _COVER_BASE + "gradients_3.png")

    def test_every_default_category_has_a_cover(self):
        for cat in DEFAULT_TAG_CATEGORIES:
            url = cover_url_for([cat])
            self.assertTrue(url.startswith(_COVER_BASE), cat)
            self.assertNotEqual(url, _COVER_BASE + _DEFAULT_COVER, cat)

    def test_default_categories_map_to_distinct_covers(self):
        urls = {cover_url_for([c]) for c in DEFAULT_TAG_CATEGORIES}
        self.assertEqual(len(urls), len(DEFAULT_TAG_CATEGORIES))


class TestUnknownCategoryFallback(unittest.TestCase):
    """自訂分類（ZETTELKASTEN_TAG_CATEGORIES 覆寫）也要拿得到 cover。"""

    def test_unknown_category_gets_a_real_cover(self):
        url = cover_url_for(["量子力學"])
        self.assertIn(url.replace(_COVER_BASE, ""), _FALLBACK_COVERS)

    def test_unknown_category_is_stable_within_process(self):
        self.assertEqual(cover_url_for(["量子力學"]), cover_url_for(["量子力學"]))

    def test_unknown_category_is_stable_across_processes(self):
        # sha1 的硬編期望值：用內建 hash() 會因 PYTHONHASHSEED 隨機化而失敗
        self.assertEqual(
            cover_url_for(["量子力學"]), _COVER_BASE + "solid_yellow.png")
        self.assertEqual(
            cover_url_for(["建築學"]), _COVER_BASE + "gradients_4.png")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/unit/test_card_visuals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.infrastructure.notion.card_visuals'`

- [ ] **Step 3: 寫實作**

建立 `src/infrastructure/notion/card_visuals.py`：

```python
"""卡片頁 cover 選色 — 分類 → Notion 內建 cover URL（純函式，零 IO）。

用 Notion 自家 CDN 的內建 cover：不需 API key、不需上傳檔案，也沒有第三方圖床
失效導致整面卡片牆破圖的風險。URL 於 2026-08-05 實地驗證；`gradients_10.png`
與 woodblocks 系列已下架（404），不得加入。

這是整個 repo 唯一知道 cover URL 長相的地方，repository 與回填工具共用，
避免像 `_split_tags` 那次一樣兩邊各寫一份而漂移。
"""
import hashlib
from typing import Optional, Sequence

# 比對鍵沿用分類的 text core（去 emoji），與 Tags 的 emoji-insensitive 慣例一致。
from zettelkasten_generator import ZettelkastenLLMEnhancer

_COVER_BASE = "https://www.notion.so/images/page-cover/"

# 分類 text core → cover 檔名。key 已去 emoji，故 "💞心理學" 與 "心理學" 同解。
_CATEGORY_COVERS = {
    "心理學": "gradients_1.png",
    "學習技巧": "gradients_2.png",
    "商務": "gradients_3.png",
    "人生觀點": "gradients_4.png",
    "邏輯思考": "gradients_5.png",
    "哲學科學": "gradients_6.png",
    "軟體工程": "gradients_7.png",
    "行銷": "gradients_8.png",
    "專案管理": "gradients_9.png",
    "理財投資": "solid_blue.png",
}

# ZETTELKASTEN_TAG_CATEGORIES 可覆寫分類清單，對照表查不到的分類從這裡挑。
_FALLBACK_COVERS = (
    "gradients_1.png", "gradients_2.png", "gradients_3.png",
    "gradients_4.png", "gradients_5.png", "gradients_6.png",
    "gradients_7.png", "gradients_8.png", "gradients_9.png",
    "solid_blue.png", "solid_red.png", "solid_yellow.png",
)

# 完全沒有分類的卡片。
_DEFAULT_COVER = "solid_beige.png"


def cover_url_for(categories: Optional[Sequence[str]]) -> str:
    """卡片 cover 的完整 URL；取第一個有效分類，無分類則用預設色。"""
    for category in categories or []:
        core = ZettelkastenLLMEnhancer._category_core(category)
        if not core:
            continue
        return _COVER_BASE + (_CATEGORY_COVERS.get(core) or _stable_cover(core))
    return _COVER_BASE + _DEFAULT_COVER


def _stable_cover(core: str) -> str:
    """未知分類的固定配色。

    必須用 sha1 而非內建 hash()：字串 hash 每個 process 有隨機 salt，
    會讓同一張卡每次跑換色，回填工具也會失去冪等性。
    """
    digest = hashlib.sha1(core.encode("utf-8")).digest()
    return _FALLBACK_COVERS[int.from_bytes(digest[:4], "big") % len(_FALLBACK_COVERS)]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_card_visuals.py -v`
Expected: PASS（14 個測試全過）

- [ ] **Step 5: Lint 並 commit**

```bash
python -m ruff check .
git add src/infrastructure/notion/card_visuals.py tests/unit/test_card_visuals.py
git commit -m "✨ feat: 分類 → Notion 內建 cover URL 對照（純函式）"
```

---

### Task 2: emoji 調色盤與規則 fallback

**Files:**
- Modify: `zettelkasten_generator.py`（在 `ZettelkastenLLMEnhancer` 類別前加模組級常數；`_fallback_icon` 加為 classmethod）
- Test: `tests/unit/test_card_icons.py`

**Interfaces:**
- Produces:
  - `_ICON_PALETTE: Tuple[str, ...]` — 40 個單 codepoint emoji（模組級）
  - `_ICON_PALETTE_SET: FrozenSet[str]`
  - `ZettelkastenLLMEnhancer._fallback_icon(card: ZettelkastenCard) -> str` — 永不回空字串
- Consumes: `ZettelkastenLLMEnhancer._category_core`（既有）；`card.tags` / `card.title` / `card.categories`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_card_icons.py`：

```python
"""卡片 page icon：固定 emoji 調色盤的不變條件，與規則式 fallback。"""
import unicodedata
import unittest

from src.config.settings import DEFAULT_TAG_CATEGORIES
from zettelkasten_generator import (
    _ICON_PALETTE,
    _ICON_PALETTE_SET,
    ZettelkastenCard,
    ZettelkastenLLMEnhancer,
)


def _card(title="卡片標題", tags=None, categories=None):
    return ZettelkastenCard(
        id="id", title=title, content="內容", source_highlight="劃線",
        chapter_reference="第一章", chapter_progress=0.5,
        tags=list(tags or []), categories=list(categories or []),
    )


class TestPaletteInvariants(unittest.TestCase):
    """兩條不變條件壞掉會直接讓 Notion 建卡失敗或讓 parser 誤判，必須有測試把關。"""

    def test_no_duplicates(self):
        self.assertEqual(len(set(_ICON_PALETTE)), len(_ICON_PALETTE))

    def test_every_entry_is_a_single_codepoint(self):
        # 多碼點序列（ZWJ / variation selector）是 Notion icon 最常見的拒收原因
        for emoji in _ICON_PALETTE:
            self.assertEqual(len(emoji), 1, f"{emoji!r} 不是單一 codepoint")

    def test_no_zwj_or_variation_selector(self):
        for emoji in _ICON_PALETTE:
            self.assertNotIn("‍", emoji)
            self.assertNotIn("️", emoji)

    def test_disjoint_from_category_emoji(self):
        # parser 靠「行內出現的調色盤 emoji 必為 icon」判讀，兩者相交規則就不成立
        category_symbols = {
            ch for cat in DEFAULT_TAG_CATEGORIES for ch in cat
            if unicodedata.category(ch)[0] not in ("L", "N")
        }
        self.assertEqual(set(_ICON_PALETTE) & category_symbols, set())

    def test_set_matches_tuple(self):
        self.assertEqual(_ICON_PALETTE_SET, frozenset(_ICON_PALETTE))

    def test_palette_is_non_trivial(self):
        # 太小的調色盤會讓同一本書的卡片撞 icon，痛點就沒解掉
        self.assertGreaterEqual(len(_ICON_PALETTE), 30)


class TestFallbackIcon(unittest.TestCase):
    def test_keyword_hit_from_tags(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(_card(tags=["習慣迴圈"]))
        self.assertEqual(icon, "🔁")

    def test_keyword_hit_from_title(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(_card(title="認知偏誤的陷阱"))
        self.assertEqual(icon, "🪤")

    def test_falls_back_to_category_default(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(
            _card(title="無關詞", tags=["無關詞"], categories=["💼商務"]))
        self.assertEqual(icon, "🪐")

    def test_category_default_is_emoji_insensitive(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(
            _card(title="無關詞", tags=[], categories=["商務"]))
        self.assertEqual(icon, "🪐")

    def test_last_resort_never_empty(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(_card(title="無關詞", tags=[]))
        self.assertIn(icon, _ICON_PALETTE_SET)

    def test_keyword_beats_category(self):
        icon = ZettelkastenLLMEnhancer._fallback_icon(
            _card(title="習慣的力量", categories=["💼商務"]))
        self.assertEqual(icon, "🔁")

    def test_all_results_are_in_palette(self):
        for cat in DEFAULT_TAG_CATEGORIES:
            icon = ZettelkastenLLMEnhancer._fallback_icon(
                _card(title="無關詞", tags=[], categories=[cat]))
            self.assertIn(icon, _ICON_PALETTE_SET, cat)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/unit/test_card_icons.py -v`
Expected: FAIL — `ImportError: cannot import name '_ICON_PALETTE' from 'zettelkasten_generator'`

- [ ] **Step 3: 寫實作**

在 `zettelkasten_generator.py` 的 `class ZettelkastenLLMEnhancer` 定義**之前**加入模組級常數（放在 `ZettelkastenCard` 之後即可）：

```python
# ----- page icon 調色盤 -----
# 兩條不變條件（有測試把關，見 tests/unit/test_card_icons.py）：
#   1. 每個元素恰為 1 個 codepoint，不含 ZWJ / variation selector / 膚色修飾符
#      —— 多碼點序列是 Notion icon 最常見的拒收原因，會讓整張卡建立失敗。
#   2. 與分類自帶的 emoji 零交集 —— parser 靠「行內出現的調色盤 emoji 必為
#      模型挑的 icon」判讀，兩者相交這條規則就只是機率上成立。
# 讓模型「從清單裡挑」而非自由生成，因此不需要任何 codepoint 驗證邏輯。
_ICON_PALETTE = (
    "🧭", "🪞", "🎯", "🔑", "🧪", "🌱", "🔁", "🪜", "🧱", "🔍",
    "💡", "🧨", "🚧", "🪤", "🎭", "🧊", "🔥", "🌊", "🌉", "🚀",
    "🧬", "🦴", "🩺", "🪐", "📉", "🧯", "🪺", "🫧", "🪃", "🧲",
    "🪢", "🌀", "🍀", "🐘", "🦉", "🐜", "🌗", "🧵", "🪟", "🚪",
)
_ICON_PALETTE_SET = frozenset(_ICON_PALETTE)

# 關鍵字 → icon。模型沒挑或挑了清單外的值時接手；值必須取自 _ICON_PALETTE。
_ICON_KEYWORD_HINTS = (
    (("習慣", "循環", "重複", "迴圈"), "🔁"),
    (("風險", "陷阱", "偏誤", "謬誤"), "🪤"),
    (("方向", "選擇", "決策", "策略"), "🧭"),
    (("時間", "階段", "週期"), "🌗"),
    (("學習", "練習", "記憶"), "🧪"),
    (("關係", "連結", "網絡"), "🪢"),
    (("成長", "起點", "萌芽"), "🌱"),
    (("情緒", "動機", "慾望"), "🔥"),
    (("溝通", "表達", "敘事"), "🎭"),
    (("金錢", "投資", "資產", "成本"), "🧯"),
    (("結構", "系統", "框架"), "🧱"),
    (("觀察", "洞察", "發現"), "🔍"),
)

# 分類 text core → 預設 icon（同樣取自 _ICON_PALETTE，且刻意不用分類自帶的 emoji）。
_CATEGORY_ICON_DEFAULTS = {
    "心理學": "🪺",
    "學習技巧": "🧪",
    "商務": "🪐",
    "人生觀點": "🧭",
    "邏輯思考": "🪢",
    "哲學科學": "🧬",
    "軟體工程": "🧱",
    "行銷": "🎯",
    "專案管理": "🪜",
    "理財投資": "🧯",
}
```

在 `ZettelkastenLLMEnhancer` 內，緊接 `_category_core` 之後加入：

```python
    @classmethod
    def _fallback_icon(cls, card: 'ZettelkastenCard') -> str:
        """模型沒給 icon（或給了清單外的值）時的決定性遞補。

        扛「同一本書的卡彼此可辨」的是 icon，而 icon 來自本地小模型，
        所以這不是裝飾而是保底 —— 保證 icon 永不空白。
        """
        haystack = "".join(card.tags or []) + (card.title or "")
        for keywords, emoji in _ICON_KEYWORD_HINTS:
            if any(k in haystack for k in keywords):
                return emoji
        for category in card.categories or []:
            emoji = _CATEGORY_ICON_DEFAULTS.get(cls._category_core(category))
            if emoji:
                return emoji
        return _ICON_PALETTE[0]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_card_icons.py -v`
Expected: PASS（13 個測試全過）

- [ ] **Step 5: Lint 並 commit**

```bash
python -m ruff check .
git add zettelkasten_generator.py tests/unit/test_card_icons.py
git commit -m "✨ feat: 卡片 icon 固定 emoji 調色盤 + 規則式 fallback"
```

---

### Task 3: `ZettelkastenCard.icon` 欄位與本地留存

**Files:**
- Modify: `zettelkasten_generator.py:143-206`（dataclass、`to_dict`、`from_dict`）
- Test: `tests/unit/test_card_icons.py`（新增一個 class）

**Interfaces:**
- Produces: `ZettelkastenCard.icon: str`（預設 `""`），並進出 `to_dict()` / `from_dict()`

**Why:** `cards_output/*.json` 是續傳的依據；icon 不落地的話，上傳中斷後續傳的卡會沒有 icon。

- [ ] **Step 1: 寫失敗的測試**

在 `tests/unit/test_card_icons.py` 的 `if __name__` 之前追加：

```python
class TestIconPersistence(unittest.TestCase):
    def test_default_is_empty(self):
        self.assertEqual(_card().icon, "")

    def test_roundtrip_preserves_icon(self):
        card = _card()
        card.icon = "🧭"
        self.assertEqual(ZettelkastenCard.from_dict(card.to_dict()).icon, "🧭")

    def test_from_dict_without_icon_is_back_compatible(self):
        # icon 欄位存在之前產生的 JSON 必須照樣載入
        card = ZettelkastenCard.from_dict({"id": "x", "title": "t", "content": "c"})
        self.assertEqual(card.icon, "")

    def test_from_dict_null_icon(self):
        card = ZettelkastenCard.from_dict({"id": "x", "title": "t", "icon": None})
        self.assertEqual(card.icon, "")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/unit/test_card_icons.py::TestIconPersistence -v`
Expected: FAIL — `AttributeError: 'ZettelkastenCard' object has no attribute 'icon'`

- [ ] **Step 3: 寫實作**

在 `zettelkasten_generator.py` 的 `ZettelkastenCard` dataclass，於 `categories` 之後加一行：

```python
    categories: List[str] = field(default_factory=list)  # Fixed Tags classification (1-2)
    icon: str = ""                    # Notion page icon emoji (from _ICON_PALETTE)
```

`to_dict()` 於 `'categories': self.categories,` 之後加：

```python
            'icon': self.icon,
```

`from_dict()` 於 `categories=list(d.get('categories') or []),` 之後加：

```python
            icon=d.get('icon', '') or '',
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_card_icons.py tests/unit/test_card_store.py -v`
Expected: PASS（新的 4 個測試通過，`test_card_store.py` 既有測試不受影響）

- [ ] **Step 5: Lint 並 commit**

```bash
python -m ruff check .
git add zettelkasten_generator.py tests/unit/test_card_icons.py
git commit -m "✨ feat: ZettelkastenCard 加 icon 欄位並納入本地留存"
```

---

### Task 4: 分類呼叫順便產 emoji

**Files:**
- Modify: `zettelkasten_generator.py:602-701`（`_parse_classification`、`_build_classification_prompt`、`classify_cards`）
- Modify: `tests/unit/test_card_categories.py:14-104`（回傳型別變了，就地改）

**Interfaces:**
- Consumes: `_ICON_PALETTE_SET`、`ZettelkastenLLMEnhancer._fallback_icon`（Task 2）；`ZettelkastenCard.icon`（Task 3）
- Produces（**兩個既有簽章改變**）：
  - `_parse_classification(text: str, n: int, allowed: List[str]) -> List[Tuple[List[str], str]]` — 由 `List[List[str]]` 改為每張卡 `(categories, icon)`；icon 找不到時為 `""`
  - `classify_cards(cards, categories, book_title="") -> bool` — 由 `None` 改為回傳「Ollama 是否給出可解析的回應」，供回填工具區分「模型沒挑這張」與「整批呼叫失敗」
  - `_pick_palette_emoji(text: str) -> str`（新，classmethod）

**相容性已查證**：`backfill_zettelkasten.py:243` 只呼叫 `classify_cards`（就地改 card、忽略回傳值），不碰 `_parse_classification`，故不會被這次型別變更打到。

- [ ] **Step 1: 改既有測試（會失敗）**

`tests/unit/test_card_categories.py` 的 `TestParseClassification` 與 `TestEmojiInsensitiveMatching` 全部改為比對 tuple。整段取代 `class TestParseClassification` 到 `class TestBookTitleMatching` 之前的內容：

```python
class TestParseClassification(unittest.TestCase):
    """E3: 每行 `CARD_i：分類｜emoji` → (categories, icon)。"""

    def test_basic_lines(self):
        text = "CARD_1：💞心理學、🧠學習技巧｜🧭\nCARD_2：💼商務｜🎯"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 2, ALLOWED)
        self.assertEqual(
            parsed, [(["💞心理學", "🧠學習技巧"], "🧭"), (["💼商務"], "🎯")])

    def test_drops_values_outside_allowed(self):
        text = "CARD_1：💞心理學、亂造的分類｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭")])

    def test_empty_when_nothing_matches(self):
        text = "CARD_1：完全不相關"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [([], "")])

    def test_caps_at_two(self):
        text = "CARD_1：💞心理學、🧠學習技巧、💼商務、🧘‍♂️人生觀點｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(len(parsed[0][0]), 2)

    def test_missing_card_stays_empty(self):
        text = "CARD_1：💞心理學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 3, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭"), ([], ""), ([], "")])

    def test_out_of_range_index_ignored(self):
        text = "CARD_9：💞心理學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 2, ALLOWED)
        self.assertEqual(parsed, [([], ""), ([], "")])

    def test_strips_thinking_prefix(self):
        text = "Thinking...\nreasoning\n...done thinking.\nCARD_1：💼商務｜🎯"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "🎯")])

    def test_no_allowed_list_returns_empty(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification("CARD_1：x｜🧭", 1, [])
        self.assertEqual(parsed, [([], "")])


class TestParseIcon(unittest.TestCase):
    """icon 解析的容錯 —— 本地小模型幾乎不會完全照格式。"""

    def test_halfwidth_pipe(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務|🎯", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "🎯")])

    def test_missing_icon_leaves_empty(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "")])

    def test_off_palette_icon_rejected(self):
        # 🍕 不在調色盤裡 → 視同沒挑，交給 fallback
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務｜🍕", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "")])

    def test_icon_found_without_separator(self):
        # 格式跑掉但行內有調色盤 emoji → 仍然抓得到
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務 🎯", 1, ALLOWED)
        self.assertEqual(parsed, [(["💼商務"], "🎯")])

    def test_first_palette_emoji_wins(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💼商務｜🎯 🧭", 1, ALLOWED)
        self.assertEqual(parsed[0][1], "🎯")

    def test_category_emoji_never_mistaken_for_icon(self):
        # 分類自帶的 emoji 與調色盤零交集，所以不會被誤判成 icon
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：💞心理學", 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "")])

    def test_icon_only_line_still_parses(self):
        parsed = ZettelkastenLLMEnhancer._parse_classification(
            "CARD_1：｜🧭", 1, ALLOWED)
        self.assertEqual(parsed, [([], "🧭")])

    def test_pick_palette_emoji_direct(self):
        pick = ZettelkastenLLMEnhancer._pick_palette_emoji
        self.assertEqual(pick("前面 🧭 後面"), "🧭")
        self.assertEqual(pick("沒有 emoji"), "")
        self.assertEqual(pick(""), "")
```

`TestEmojiInsensitiveMatching` 內四個 `_parse_classification` 測試同樣改為 tuple 比對：

```python
    def test_plain_text_maps_to_canonical(self):
        text = "CARD_1：心理學、學習技巧｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學", "🧠學習技巧"], "🧭")])

    def test_zwj_emoji_category_plain_output(self):
        # 🧘‍♂️ is a multi-codepoint ZWJ sequence; plain output must still match.
        text = "CARD_1：人生觀點｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["🧘‍♂️人生觀點"], "🧭")])

    def test_mangled_emoji_still_matches(self):
        # model echoes a partial emoji (🧘 without ZWJ+♂️+VS16)
        text = "CARD_1：🧘人生觀點｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["🧘‍♂️人生觀點"], "🧭")])

    def test_exact_emoji_output_still_matches(self):
        text = "CARD_1：💞心理學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭")])

    def test_invented_category_still_dropped(self):
        text = "CARD_1：心理學、量子力學｜🧭"
        parsed = ZettelkastenLLMEnhancer._parse_classification(text, 1, ALLOWED)
        self.assertEqual(parsed, [(["💞心理學"], "🧭")])
```

並在 `test_prompt_lists_plain_names` 之後追加：

```python
    def test_prompt_lists_icon_palette(self):
        enhancer = ZettelkastenLLMEnhancer()
        card = ZettelkastenCard(
            id="x", title="t", content="c", source_highlight="h",
            chapter_reference="ch", chapter_progress=0.0,
        )
        prompt = enhancer._build_classification_prompt([card], ALLOWED)
        self.assertIn("🧭", prompt)
        self.assertIn("｜", prompt)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/unit/test_card_categories.py -v`
Expected: FAIL — 多個 `AssertionError: [['💞心理學', ...]] != [(['💞心理學', ...], '🧭')]`，且 `_pick_palette_emoji` 不存在。

- [ ] **Step 3: 寫實作**

3a. `zettelkasten_generator.py` 檔頭 typing import 補上 `Tuple`（若尚未 import）。

3b. 在 `_category_core` 之後、`_parse_classification` 之前加入：

```python
    @classmethod
    def _pick_palette_emoji(cls, text: str) -> str:
        """文字中第一個落在 _ICON_PALETTE 的 emoji，沒有則回空字串。

        因為調色盤與分類自帶的 emoji 零交集，且 prompt 給模型的分類名已去 emoji，
        所以行內出現的調色盤 emoji 必為模型挑的 icon —— 可以放心掃整行，
        不必依賴模型有沒有照 `｜` 格式輸出。
        """
        for ch in text or "":
            if ch in _ICON_PALETTE_SET:
                return ch
        return ""
```

3c. `_parse_classification` 整個取代為：

```python
    _ICON_SEPARATOR = re.compile(r'[｜|]')

    @classmethod
    def _parse_classification(
        cls, text: str, n: int, allowed: List[str]
    ) -> List[Tuple[List[str], str]]:
        """Parse `CARD_i: 分類A、分類B｜emoji` lines into per-card (categories, icon).

        Category names are matched on their text core (emoji-insensitive) and
        written back as the canonical `allowed` value, so Notion multi_select
        options keep their emoji prefix. At most 2 categories per card; the icon
        is `""` when the model gave none or gave one outside the palette.
        Pure — no Ollama, unit-testable.
        """
        result: List[Tuple[List[str], str]] = [([], "") for _ in range(n)]
        if not text or not allowed:
            return result
        canonical = {cls._category_core(a): a for a in allowed if cls._category_core(a)}
        cleaned = cls._strip_thinking(text)
        for line in cleaned.splitlines():
            m = cls._CLASSIFY_LINE.search(line)
            if not m:
                continue
            try:
                idx = int(m.group(1))
            except ValueError:
                continue
            if not (1 <= idx <= n):
                continue
            remainder = m.group(2).strip()
            # 分類只看 ｜ 之前，icon 掃整行（模型常常不照格式）
            category_part = cls._ICON_SEPARATOR.split(remainder, maxsplit=1)[0]
            picked: List[str] = []
            for part in cls._CLASSIFY_SPLIT.split(category_part.strip()):
                name = canonical.get(cls._category_core(part))
                if name and name not in picked:
                    picked.append(name)
                if len(picked) >= 2:
                    break
            result[idx - 1] = (picked, cls._pick_palette_emoji(remainder))
        return result
```

3d. `_build_classification_prompt` 的 return 整個取代為：

```python
        icons = " ".join(_ICON_PALETTE)
        return f"""你是一位知識分類助理。以下是 {len(cards)} 張卡片筆記，請為每張卡片挑選最貼切的分類與一個代表 emoji。

可用分類（只能從這裡挑，不可自創）：
{allowed}

可用 emoji（只能從這裡挑，不可自創）：
{icons}

卡片：
{cards_section}

規則：
1. 每張卡片挑 1-2 個最貼切的分類，只能從上面清單挑，用頓號（、）分隔
2. 如果沒有任何分類貼切，該卡片分類留空（不要硬塞、不要發明新分類）
3. 每張卡片再挑「一個」最能代表它的 emoji，只能從上面的 emoji 清單挑
4. 嚴格依照格式逐行輸出，每張卡片一行：CARD_編號：分類｜emoji
5. 不要加任何解釋或結語

請直接輸出："""
```

3e. `classify_cards` 的尾段（`parsed = ...` 之後）取代為：

```python
        parsed = self._parse_classification(raw, len(cards), categories)
        assigned = 0
        model_icons = 0
        for card, (cats, icon) in zip(cards, parsed):
            card.categories = cats
            # 先寫 categories，_fallback_icon 才吃得到分類預設
            card.icon = icon or self._fallback_icon(card)
            if cats:
                assigned += 1
            if icon:
                model_icons += 1
        parsed_ok = any(cats or icon for cats, icon in parsed)
        logger.info(
            f"Ollama classify done: {assigned}/{len(cards)} cards tagged, "
            f"{model_icons}/{len(cards)} icons from model "
            f"({len(cards) - model_icons} via fallback)"
        )
        return parsed_ok
```

並把 `classify_cards` 的簽章與 docstring 改為：

```python
    def classify_cards(
        self, cards: List[ZettelkastenCard], categories: List[str],
        book_title: str = "",
    ) -> bool:
        """Assign fixed-category Tags + a page icon to each card in place.

        One Ollama call per book. Returns whether the response was parseable at
        all — callers (the visual backfill tool) use it to tell "the model
        didn't pick for this card" apart from "the whole call failed", so a
        failed batch can be retried later instead of being frozen with
        rule-based icons.

        No-op returning False if there are no cards or no category list. On any
        Ollama failure the cards keep empty `categories`; `icon` still gets a
        deterministic fallback so it is never blank.
        """
        if not cards or not categories:
            return False
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_card_categories.py tests/unit/test_card_icons.py -v`
Expected: PASS

- [ ] **Step 5: 跑全套測試確認沒打到別人**

Run: `python -m pytest`
Expected: 全綠

- [ ] **Step 6: Lint 並 commit**

```bash
python -m ruff check .
git add zettelkasten_generator.py tests/unit/test_card_categories.py
git commit -m "✨ feat: 分類 LLM 呼叫順便產卡片 icon（固定調色盤）"
```

---

### Task 5: repository 寫入 cover / icon / 加工狀態

**Files:**
- Modify: `src/infrastructure/notion/zettelkasten_card_repository.py`（常數區、`_ensure_schema`、`_build_properties`、`upload_cards` 的 `pages.create`）
- Test: `tests/unit/test_card_visual_upload.py`

**Interfaces:**
- Consumes: `cover_url_for`（Task 1）、`card.icon`（Task 3）
- Produces:
  - 常數 `_STAGE_PROPERTY = "加工狀態"`、`_STAGE_UNPROCESSED = "🌱未加工"`、`_CREATED_PROPERTY = "建立日期"`、`_REVIEWED_PROPERTY = "上次回顧"`
  - `ZettelkastenCardRepository._build_visuals(card) -> dict` — `pages.create` 的 icon/cover kwargs
  - `ZettelkastenCardRepository._schema_additions(existing: dict) -> dict` — 由 `_ensure_schema` 抽出的純函式，方便測試

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_card_visual_upload.py`：

```python
"""卡片上傳時的視覺欄位：cover / icon / 加工狀態，以及自動建欄。"""
import unittest

from src.infrastructure.notion.card_visuals import _COVER_BASE
from src.infrastructure.notion.zettelkasten_card_repository import (
    _CREATED_PROPERTY,
    _REVIEWED_PROPERTY,
    _STAGE_PROPERTY,
    _STAGE_UNPROCESSED,
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard


def _card(icon="🧭", categories=None):
    card = ZettelkastenCard(
        id="id", title="卡片標題", content="內容", source_highlight="劃線",
        chapter_reference="第一章", chapter_progress=0.5,
        categories=list(categories or ["💞心理學"]),
    )
    card.icon = icon
    return card


def _repo():
    # Client(auth=...) does no network at construction.
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    repo._schema_props = None  # 跳過 schema 抓取；照舊寫入全部屬性
    return repo


class TestBuildVisuals(unittest.TestCase):
    def test_cover_from_first_category(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card())
        self.assertEqual(
            visuals["cover"],
            {"type": "external",
             "external": {"url": _COVER_BASE + "gradients_1.png"}},
        )

    def test_icon_written_as_emoji(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card(icon="🎯"))
        self.assertEqual(visuals["icon"], {"type": "emoji", "emoji": "🎯"})

    def test_blank_icon_key_omitted(self):
        # 送 icon=None 會被 Notion 拒收；沒有就整個 key 不要出現
        visuals = ZettelkastenCardRepository._build_visuals(_card(icon=""))
        self.assertNotIn("icon", visuals)
        self.assertIn("cover", visuals)

    def test_whitespace_icon_omitted(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card(icon="  "))
        self.assertNotIn("icon", visuals)

    def test_no_category_still_gets_a_cover(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card(categories=[]))
        self.assertTrue(visuals["cover"]["external"]["url"].startswith(_COVER_BASE))


class TestStageProperty(unittest.TestCase):
    def test_new_card_is_unprocessed(self):
        props = _repo()._build_properties(_card(), books_page_id=None)
        self.assertEqual(
            props[_STAGE_PROPERTY], {"select": {"name": _STAGE_UNPROCESSED}})

    def test_skipped_when_db_lacks_the_column(self):
        repo = _repo()
        repo._schema_props = {"標題"}  # DB 只有標題
        props = repo._build_properties(_card(), books_page_id=None)
        self.assertNotIn(_STAGE_PROPERTY, props)


class TestSchemaAdditions(unittest.TestCase):
    def test_adds_all_three_when_missing(self):
        add = ZettelkastenCardRepository._schema_additions({"標題": {}})
        self.assertIn(_STAGE_PROPERTY, add)
        self.assertIn(_CREATED_PROPERTY, add)
        self.assertIn(_REVIEWED_PROPERTY, add)

    def test_stage_seeds_three_options(self):
        add = ZettelkastenCardRepository._schema_additions({})
        names = [o["name"] for o in add[_STAGE_PROPERTY]["select"]["options"]]
        self.assertEqual(len(names), 3)
        self.assertIn(_STAGE_UNPROCESSED, names)

    def test_created_is_created_time_type(self):
        add = ZettelkastenCardRepository._schema_additions({})
        self.assertEqual(add[_CREATED_PROPERTY], {"created_time": {}})

    def test_reviewed_is_date_type(self):
        add = ZettelkastenCardRepository._schema_additions({})
        self.assertEqual(add[_REVIEWED_PROPERTY], {"date": {}})

    def test_existing_columns_left_alone(self):
        existing = {_STAGE_PROPERTY: {}, _CREATED_PROPERTY: {}, _REVIEWED_PROPERTY: {}}
        self.assertEqual(ZettelkastenCardRepository._schema_additions(existing), {})


class TestCreatePayload(unittest.TestCase):
    """pages.create 必須同時帶 properties / children / icon / cover。"""

    def test_create_receives_icon_and_cover(self):
        repo = _repo()
        calls = []

        class _FakePages:
            def create(self, **kwargs):
                calls.append(kwargs)
                return {"id": "new-page"}

        class _FakeDatabases:
            # upload_cards 在沒有 Books DB 時會走 _filter_new_cards_by_query，
            # 逐卡查「來源劃線ID」——不擋掉就會對 Notion 發真的 HTTP 請求。
            def query(self, **kwargs):
                return {"results": []}

        repo._client.pages = _FakePages()
        repo._client.databases = _FakeDatabases()
        repo._schema_ensured = True  # 跳過 _ensure_schema 的網路呼叫
        created = repo.upload_cards([_card()], book_title="某書")

        self.assertEqual(created, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["icon"], {"type": "emoji", "emoji": "🧭"})
        self.assertTrue(calls[0]["cover"]["external"]["url"].startswith(_COVER_BASE))
        self.assertIn("標題", calls[0]["properties"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/unit/test_card_visual_upload.py -v`
Expected: FAIL — `ImportError: cannot import name '_STAGE_PROPERTY'`

- [ ] **Step 3: 寫實作**

3a. `zettelkasten_card_repository.py` import 區加入：

```python
from .card_visuals import cover_url_for
```

3b. 常數區（`_TAGS_PROPERTY` 附近）加入：

```python
# 回訪機制用的欄位。加工狀態刻意不叫「狀態」——審核年代那個已退役的 `狀態` 欄
# 語意完全不同（見 docs/NOTION_OUTPUT_IMPROVEMENTS.md），同名會混淆。
_STAGE_PROPERTY = "加工狀態"
_STAGE_UNPROCESSED = "🌱未加工"
_STAGE_REWRITTEN = "🌿已重寫"
_STAGE_PERMANENT = "🌳永久筆記"
# 建立日期用 Notion 的 created_time 型別：值由 Notion 自己算，舊卡也立即有值。
_CREATED_PROPERTY = "建立日期"
_REVIEWED_PROPERTY = "上次回顧"
```

3c. 新增兩個方法（放在 `_tags_options_update` 之後）：

```python
    @staticmethod
    def _schema_additions(existing: dict) -> dict:
        """回訪欄位中，卡片盒還缺的那些的 databases.update body（純函式）。"""
        to_add: dict = {}
        if _STAGE_PROPERTY not in (existing or {}):
            to_add[_STAGE_PROPERTY] = {
                "select": {
                    "options": [
                        {"name": _STAGE_UNPROCESSED},
                        {"name": _STAGE_REWRITTEN},
                        {"name": _STAGE_PERMANENT},
                    ]
                }
            }
        if _CREATED_PROPERTY not in (existing or {}):
            to_add[_CREATED_PROPERTY] = {"created_time": {}}
        if _REVIEWED_PROPERTY not in (existing or {}):
            to_add[_REVIEWED_PROPERTY] = {"date": {}}
        return to_add

    @staticmethod
    def _build_visuals(card: ZettelkastenCard) -> dict:
        """pages.create 的 icon / cover kwargs。

        cover 永遠有值（無分類也有預設色）；icon 為空時整個 key 不送 ——
        Notion 收到 icon=None 會拒收整張卡。
        """
        visuals: dict = {
            "cover": {
                "type": "external",
                "external": {
                    "url": cover_url_for(getattr(card, "categories", None))
                },
            }
        }
        icon = (getattr(card, "icon", "") or "").strip()
        if icon:
            visuals["icon"] = {"type": "emoji", "emoji": icon}
        return visuals
```

3d. `_ensure_schema` 內，`tags_update` 那段之後加一行合併：

```python
        tags_update = self._tags_options_update(existing.get(_TAGS_PROPERTY))
        if tags_update is not None:
            to_add[_TAGS_PROPERTY] = tags_update

        to_add.update(self._schema_additions(existing))
```

3e. `_build_properties` 內，`if books_page_id and self._wants("來源"):` 之前加入：

```python
        if self._wants(_STAGE_PROPERTY):
            props[_STAGE_PROPERTY] = {"select": {"name": _STAGE_UNPROCESSED}}
```

3f. `upload_cards` 的建立迴圈改為：

```python
            try:
                properties = self._build_properties(card, books_page_id)
                children = self._build_children(card)
                visuals = self._build_visuals(card)
                retry_with_backoff(
                    lambda p=properties, c=children, v=visuals: (
                        self._client.pages.create(
                            parent={"database_id": self._database_id},
                            properties=p,
                            children=c,
                            **v,
                        )
                    ),
                    self._rate_limiter,
                )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_card_visual_upload.py tests/unit/test_card_dedup.py -v`
Expected: PASS

- [ ] **Step 5: Lint 並 commit**

```bash
python -m ruff check .
git add src/infrastructure/notion/zettelkasten_card_repository.py tests/unit/test_card_visual_upload.py
git commit -m "✨ feat: 卡片上傳帶 cover/icon/加工狀態，並自動建回訪欄位"
```

---

### Task 6: 舊卡回填工具

**Files:**
- Create: `tools/backfill_card_visuals.py`
- Test: `tests/unit/test_backfill_card_visuals.py`

**Interfaces:**
- Consumes: `cover_url_for`（Task 1）、`classify_cards(...) -> bool`（Task 4）、`_fallback_icon`（Task 2）、`_STAGE_PROPERTY` / `_STAGE_UNPROCESSED`（Task 5）、既有 `Settings`、`NotionRateLimiter`、`retry_with_backoff`
- Produces（純函式，供測試）：
  - `card_title(page) -> str`、`card_keywords(page) -> str`、`card_categories(page) -> List[str]`
  - `missing_cover(page) -> bool`、`missing_icon(page) -> bool`、`missing_stage(page) -> bool`
  - `needs_work(page) -> bool`
  - `build_update(page: dict, icon: str) -> dict`

**設計要點**：`--dry-run` 預覽、重跑冪等（**已有的 icon/cover 一律不覆蓋**，所以不會蓋掉手動換過的圖）。cover 純規則不花 LLM；icon 才走 Ollama，且只用查詢結果裡就有的 `標題` + `Key Word`，不為了讀內文再打一次 API。Ollama 整批失敗時只補 cover，icon 留給下次重跑。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_backfill_card_visuals.py`：

```python
"""回填工具的純邏輯：頁面欄位讀取與 pages.update payload 組裝。"""
import unittest

from src.infrastructure.notion.card_visuals import _COVER_BASE
from src.infrastructure.notion.zettelkasten_card_repository import (
    _STAGE_PROPERTY,
    _STAGE_UNPROCESSED,
)
from tools.backfill_card_visuals import (
    build_update,
    card_categories,
    card_keywords,
    card_title,
    missing_cover,
    missing_icon,
    missing_stage,
    needs_work,
)


def _page(cover=None, icon=None, tags=("💞心理學",), title="卡片標題",
          keywords="專注、心流", stage=None):
    props = {
        "標題": {"type": "title",
                 "title": [{"plain_text": title}]},
        "Tags": {"type": "multi_select",
                 "multi_select": [{"name": t} for t in tags]},
        "Key Word": {"type": "rich_text",
                     "rich_text": [{"plain_text": keywords}]},
    }
    if stage is not None:
        props[_STAGE_PROPERTY] = {"type": "select", "select": {"name": stage}}
    return {"id": "page-1", "cover": cover, "icon": icon, "properties": props}


class TestPageReaders(unittest.TestCase):
    def test_title(self):
        self.assertEqual(card_title(_page(title="專注的代價")), "專注的代價")

    def test_title_missing(self):
        self.assertEqual(card_title({"properties": {}}), "")

    def test_keywords(self):
        self.assertEqual(card_keywords(_page()), "專注、心流")

    def test_keywords_missing(self):
        self.assertEqual(card_keywords({"properties": {}}), "")

    def test_categories(self):
        self.assertEqual(card_categories(_page(tags=("💼商務",))), ["💼商務"])

    def test_categories_empty(self):
        self.assertEqual(card_categories(_page(tags=())), [])


class TestMissingChecks(unittest.TestCase):
    def test_missing_cover_true_when_none(self):
        self.assertTrue(missing_cover(_page(cover=None)))

    def test_missing_cover_false_when_present(self):
        page = _page(cover={"type": "external", "external": {"url": "x"}})
        self.assertFalse(missing_cover(page))

    def test_missing_icon_true_when_none(self):
        self.assertTrue(missing_icon(_page(icon=None)))

    def test_missing_icon_false_when_present(self):
        self.assertFalse(missing_icon(_page(icon={"type": "emoji", "emoji": "🧭"})))

    def test_missing_stage_true_when_absent(self):
        self.assertTrue(missing_stage(_page()))

    def test_missing_stage_false_when_set(self):
        self.assertFalse(missing_stage(_page(stage=_STAGE_UNPROCESSED)))

    def test_needs_work_false_when_complete(self):
        page = _page(cover={"external": {"url": "x"}},
                     icon={"emoji": "🧭"}, stage=_STAGE_UNPROCESSED)
        self.assertFalse(needs_work(page))

    def test_needs_work_true_when_any_missing(self):
        self.assertTrue(needs_work(_page(icon={"emoji": "🧭"},
                                         stage=_STAGE_UNPROCESSED)))


class TestBuildUpdate(unittest.TestCase):
    def test_fills_all_three(self):
        upd = build_update(_page(), icon="🧭")
        self.assertEqual(
            upd["cover"]["external"]["url"], _COVER_BASE + "gradients_1.png")
        self.assertEqual(upd["icon"], {"type": "emoji", "emoji": "🧭"})
        self.assertEqual(
            upd["properties"][_STAGE_PROPERTY],
            {"select": {"name": _STAGE_UNPROCESSED}},
        )

    def test_does_not_overwrite_existing_cover(self):
        page = _page(cover={"type": "external", "external": {"url": "keep-me"}})
        self.assertNotIn("cover", build_update(page, icon="🧭"))

    def test_does_not_overwrite_existing_icon(self):
        page = _page(icon={"type": "emoji", "emoji": "🎯"})
        self.assertNotIn("icon", build_update(page, icon="🧭"))

    def test_does_not_overwrite_existing_stage(self):
        page = _page(stage="🌳永久筆記")
        self.assertNotIn("properties", build_update(page, icon="🧭"))

    def test_blank_icon_omitted(self):
        # Ollama 整批失敗時只補 cover，icon 留給下次重跑
        upd = build_update(_page(), icon="")
        self.assertNotIn("icon", upd)
        self.assertIn("cover", upd)

    def test_complete_page_yields_empty_update(self):
        page = _page(cover={"external": {"url": "x"}},
                     icon={"emoji": "🧭"}, stage=_STAGE_UNPROCESSED)
        self.assertEqual(build_update(page, icon="🎯"), {})

    def test_no_category_still_gets_cover(self):
        upd = build_update(_page(tags=()), icon="🧭")
        self.assertTrue(upd["cover"]["external"]["url"].startswith(_COVER_BASE))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/unit/test_backfill_card_visuals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.backfill_card_visuals'`

- [ ] **Step 3: 讓 `tools/` 可被 import**

`tools/` 目前沒有 `__init__.py`（`tests/unit/test_fix_card_tags.py` 用 sys.path 技巧）。為了讓測試能 `from tools.backfill_card_visuals import ...`，建立空的 `tools/__init__.py`：

```bash
python -c "open('tools/__init__.py','w').close()"
```

- [ ] **Step 4: 寫實作**

建立 `tools/backfill_card_visuals.py`：

```python
#!/usr/bin/env python
"""為卡片盒既有卡片補上 cover / icon / 加工狀態。

新卡在建立時就帶這三樣（見 ZettelkastenCardRepository），但既有卡片不會自動有。
本工具掃過整個卡片盒，只補「缺的那一項」：

  - cover：純規則，由卡片的 Tags 分類決定，不花任何 LLM 呼叫；
  - icon ：以「標題 + Key Word」批次送 Ollama 挑 emoji（兩個欄位在 query 回應裡
           就有，不必為了讀內文再打一次 API）。Ollama 不可用時只補 cover，
           icon 留給下次重跑；
  - 加工狀態：一律補「🌱未加工」。

已有值的一律不覆蓋 —— 重跑冪等，也不會蓋掉你在 Notion 上手動換過的圖。

    python tools/backfill_card_visuals.py --dry-run
    python tools/backfill_card_visuals.py
"""
import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

# allow `python tools/backfill_card_visuals.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notion_client import Client  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.infrastructure.container import (  # noqa: E402
    setup_file_and_console_logging,
)
from src.infrastructure.notion.card_visuals import cover_url_for  # noqa: E402
from src.infrastructure.notion.rate_limiter import NotionRateLimiter  # noqa: E402
from src.infrastructure.notion.retry_policy import retry_with_backoff  # noqa: E402
from src.infrastructure.notion.zettelkasten_card_repository import (  # noqa: E402
    _STAGE_PROPERTY,
    _STAGE_UNPROCESSED,
)
from zettelkasten_generator import (  # noqa: E402
    ZettelkastenCard,
    ZettelkastenLLMEnhancer,
)

logger = logging.getLogger("backfill_card_visuals")

_TITLE_PROP = "標題"
_TAGS_PROP = "Tags"
_KEYWORD_PROP = "Key Word"
# 一次送給 Ollama 的卡片數。跟產卡時的單書張數同量級，prompt 不會爆 num_ctx。
_ICON_BATCH_SIZE = 20


# ----- 純函式：讀頁面欄位 -----

def card_title(page: dict) -> str:
    prop = (page.get("properties") or {}).get(_TITLE_PROP) or {}
    return "".join(
        p.get("plain_text", "") for p in (prop.get("title") or [])
    ).strip()


def card_keywords(page: dict) -> str:
    prop = (page.get("properties") or {}).get(_KEYWORD_PROP) or {}
    return "".join(
        p.get("plain_text", "") for p in (prop.get("rich_text") or [])
    ).strip()


def card_categories(page: dict) -> List[str]:
    prop = (page.get("properties") or {}).get(_TAGS_PROP) or {}
    return [o.get("name", "") for o in (prop.get("multi_select") or []) if o.get("name")]


def missing_cover(page: dict) -> bool:
    return not page.get("cover")


def missing_icon(page: dict) -> bool:
    return not page.get("icon")


def missing_stage(page: dict) -> bool:
    prop = (page.get("properties") or {}).get(_STAGE_PROPERTY) or {}
    return not (prop.get("select") or {}).get("name")


def needs_work(page: dict) -> bool:
    return missing_cover(page) or missing_icon(page) or missing_stage(page)


def build_update(page: dict, icon: str) -> dict:
    """pages.update 的 kwargs —— 只包含這張卡真正缺的東西。

    空 icon 代表這批 Ollama 呼叫失敗；此時不寫 icon，讓下次重跑補上，
    而不是用規則值把它凍住。
    """
    update: Dict = {}
    if missing_cover(page):
        update["cover"] = {
            "type": "external",
            "external": {"url": cover_url_for(card_categories(page))},
        }
    if icon and missing_icon(page):
        update["icon"] = {"type": "emoji", "emoji": icon}
    if missing_stage(page):
        update["properties"] = {
            _STAGE_PROPERTY: {"select": {"name": _STAGE_UNPROCESSED}}
        }
    return update


# ----- IO -----

def fetch_all_cards(client, database_id: str, limiter) -> List[dict]:
    pages: List[dict] = []
    cursor: Optional[str] = None
    while True:
        kwargs = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        result = retry_with_backoff(
            lambda k=kwargs: client.databases.query(**k), limiter
        ) or {}
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return pages


def icons_for(enhancer, pages: List[dict], categories: List[str]) -> List[str]:
    """為一批頁面挑 icon；整批 Ollama 失敗時回傳全空字串。

    只用「標題 + Key Word」組出臨時卡片 —— 兩者都在 query 回應裡，不必為了讀
    內文再打一次 API。classify_cards 會覆寫 card.categories，所以事後還原成
    Notion 上的真實分類，_fallback_icon 才會依真實分類遞補。
    """
    cards = [
        ZettelkastenCard(
            id=page.get("id", ""),
            title=card_title(page),
            content=card_keywords(page),
            source_highlight="",
            chapter_reference="",
            chapter_progress=0.0,
            tags=[t for t in card_keywords(page).split("、") if t],
            categories=card_categories(page),
        )
        for page in pages
    ]
    original = [list(c.categories) for c in cards]
    try:
        ok = enhancer.classify_cards(cards, categories)
    except Exception as e:  # noqa: BLE001 — Ollama 掛掉不該中止整個回填
        logger.warning(f"Ollama 分類呼叫失敗，本批只補 cover: {e}")
        return ["" for _ in cards]
    if not ok:
        logger.warning("Ollama 回應無法解析，本批只補 cover（下次重跑會再試）")
        return ["" for _ in cards]
    for card, cats in zip(cards, original):
        card.categories = cats  # 本工具不改 Tags，還原以免 fallback 用到亂猜的分類
    return [c.icon or ZettelkastenLLMEnhancer._fallback_icon(c) for c in cards]


def run(dry_run: bool = False) -> Dict[str, int]:
    settings = Settings.from_env()
    if not settings.notion_zettelkasten_database_id:
        print("未設定 NOTION_ZETTELKASTEN_DATABASE_ID，無事可做")
        return {"scanned": 0, "pending": 0, "updated": 0, "failed": 0}

    limiter = NotionRateLimiter()
    client = Client(auth=settings.notion_token)
    enhancer = ZettelkastenLLMEnhancer()

    pages = fetch_all_cards(client, settings.notion_zettelkasten_database_id, limiter)
    pending = [p for p in pages if needs_work(p)]
    stats = {"scanned": len(pages), "pending": len(pending), "updated": 0, "failed": 0}
    print(f"掃描 {len(pages)} 張卡片，其中 {len(pending)} 張需要補齊")
    if not pending:
        return stats

    for start in range(0, len(pending), _ICON_BATCH_SIZE):
        batch = pending[start:start + _ICON_BATCH_SIZE]
        need_icon = any(missing_icon(p) for p in batch)
        icons = (
            icons_for(enhancer, batch, settings.zettelkasten_tag_categories)
            if need_icon else ["" for _ in batch]
        )
        for page, icon in zip(batch, icons):
            update = build_update(page, icon)
            if not update:
                continue
            title = card_title(page) or "?"
            cover_name = (
                update.get("cover", {}).get("external", {}).get("url", "")
                .rsplit("/", 1)[-1]
            )
            print(f"   {title}\n      cover={cover_name or '（保留）'} "
                  f"icon={update.get('icon', {}).get('emoji', '（保留）')}")
            if dry_run:
                continue
            try:
                retry_with_backoff(
                    lambda pid=page["id"], u=update: client.pages.update(
                        page_id=pid, **u
                    ),
                    limiter,
                )
                stats["updated"] += 1
            except Exception as e:  # noqa: BLE001 — 單張失敗不該中止整批
                logger.error(f"卡片 '{title}' 更新失敗: {e}")
                stats["failed"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="為卡片盒既有卡片補上 cover / icon / 加工狀態"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="只印出將要寫入的 cover / icon，不實際寫回")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不寫入）" if args.dry_run else "正式執行"
    print(f"=== 卡片視覺回填 — {mode} ===")

    stats = run(dry_run=args.dry_run)

    print(
        f"\n=== 總結 ===\n"
        f"掃描 {stats['scanned']} 張，需補齊 {stats['pending']} 張，"
        f"已更新 {stats['updated']} 張，失敗 {stats['failed']} 張"
    )
    if args.dry_run and stats["pending"]:
        print("\n確認無誤後拿掉 --dry-run 正式執行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 跑測試確認通過**

Run: `python -m pytest tests/unit/test_backfill_card_visuals.py -v`
Expected: PASS（20 個測試全過）

- [ ] **Step 6: CLI 冒煙測試**

`Settings` 的欄位名已查證為 `notion_zettelkasten_database_id` 與
`zettelkasten_tag_categories`（2026-08-05 實地確認），上面的程式碼直接可用。

Run: `python tools/backfill_card_visuals.py --help`
Expected: 印出 argparse 說明，無 import error。

- [ ] **Step 7: Lint 並 commit**

```bash
python -m ruff check .
git add tools/__init__.py tools/backfill_card_visuals.py tests/unit/test_backfill_card_visuals.py
git commit -m "🔧 chore: 卡片視覺回填工具（cover/icon/加工狀態）"
```

---

### Task 7: 真跑驗證與文件更新

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/DECISIONS.md`

**前置**：需要 Ollama 服務在跑、`.env` 已設好 Notion token 與卡片盒 DB id。

- [ ] **Step 1: 全套 quality gate**

```bash
python -m ruff check .
python -m pytest
```

Expected: 兩者全綠。

- [ ] **Step 2: 回填工具 dry-run**

Run: `python tools/backfill_card_visuals.py --dry-run`
Expected: 印出「掃描 N 張卡片，其中 M 張需要補齊」與逐卡的 `cover=... icon=...` 對照。**人工檢查**：icon 是否與卡片標題語意相符；若大量卡片撞同一個 icon，代表 prompt 或調色盤需調整（回到 Task 4 調整後重跑）。

- [ ] **Step 3: 正式回填**

Run: `python tools/backfill_card_visuals.py`
Expected: 「已更新 M 張，失敗 0 張」。

- [ ] **Step 4: 重跑確認冪等**

Run: `python tools/backfill_card_visuals.py --dry-run`
Expected: 「其中 0 張需要補齊」。這證明「已有值不覆蓋」確實成立。

- [ ] **Step 5: Notion 上肉眼驗收**

在卡片盒手動設定（API 改不了 view）：
1. gallery view → Card preview 設為 **Page cover**；
2. 新增一個依 `加工狀態` 分組的 board view。

Expected: 卡片牆出現分類色塊、每張卡有 emoji icon、board 上所有舊卡都在「🌱未加工」欄。

- [ ] **Step 6: 新卡真跑**

Run: `python main.py`（`ENABLE_ZETTELKASTEN_CARDS=true`，至少一本符合門檻的書）
Expected: log 出現 `icons from model` 統計；Notion 上新建的卡片出生就帶 cover / icon / 🌱未加工。

- [ ] **Step 7: 更新 CLAUDE.md**

在 **Maintenance tools (`tools/`)** 段落追加：

```markdown
- **Backfill card visuals**: `python tools/backfill_card_visuals.py --dry-run`（預覽
  「卡片 → cover/icon」）／不帶 `--dry-run` 正式寫回。為卡片盒既有卡片補上 cover
  （依 Tags 純規則）、page icon（標題＋Key Word 批次送 Ollama 挑 emoji）與
  `加工狀態=🌱未加工`。**已有值一律不覆蓋** → 重跑冪等，也不會蓋掉手動換過的圖。
  Ollama 不可用時只補 cover，icon 留待下次重跑。
```

在 **Notion 卡片盒 database** 說明中，於既有欄位清單後追加：

```markdown
  回訪／視覺欄位（同樣由 `_ensure_schema` 自動建立）：`加工狀態` (select：
  🌱未加工/🌿已重寫/🌳永久筆記，建卡時一律寫 🌱)、`建立日期` (created_time，值由
  Notion 自算)、`上次回顧` (date，純手動)。每張卡另有 page **cover**（依 Tags 分類
  對應 Notion 內建漸層，`card_visuals.cover_url_for`）與 page **icon**（emoji）。
  ⚠️ **gallery view 需手動把 Card preview 設為 Page cover**，色卡才會顯示 ——
  Notion API 無法修改 view 設定。
```

在 **卡片審核閘門** 之後新增一節：

```markdown
### 卡片視覺與回訪（2026-08-05）

卡片牆的辨識度靠兩層：**cover 分領域、icon 分卡片**。
- **cover**：`src/infrastructure/notion/card_visuals.py`（純函式）把分類對到 Notion
  內建 cover URL。這是全 repo 唯一知道 cover URL 長相的地方，repository 與回填工具
  共用。未在對照表內的自訂分類走 **sha1** 穩定雜湊挑色——**不可用內建 `hash()`**，
  字串 hash 每 process 有隨機 salt，會讓同一張卡每次跑換色。
  `gradients_10.png` 與 woodblocks 系列已下架（404），不得使用。
- **icon**：`zettelkasten_generator.py` 的 `_ICON_PALETTE`（40 個 emoji）。模型只能
  「從清單裡挑」而非自由生成，因此不需要 codepoint 驗證，也不會送出 Notion 拒收的
  畸形 ZWJ 序列。調色盤有兩條由測試把關的不變條件：**單一 codepoint**、且**與分類
  自帶的 emoji 零交集**（後者讓 parser「行內出現的調色盤 emoji 必為 icon」這條規則
  嚴格成立）。
- **搭便車**：icon 由既有的批次分類呼叫 `classify_cards` 順便產出（格式
  `CARD_i：分類｜emoji`），**不動產卡與審核 prompt**，也不多一輪 LLM。
  `classify_cards` 回傳 bool 表示「回應是否可解析」，讓回填工具能區分「模型沒挑
  這張」與「整批呼叫失敗」。
- **`_fallback_icon` 是保底不是裝飾**：扛「同書 16 張卡可辨」的是 icon，而 icon 來自
  本地小模型；模型沒挑或挑了清單外的值時由關鍵字表／分類預設遞補，保證永不空白。
```

- [ ] **Step 8: 更新 docs/DECISIONS.md**

追加兩筆輕量 ADR（依該檔既有格式）：

```markdown
## 2026-08-05：卡片視覺用「分類色卡 + emoji icon」，不接外部圖庫

**決定**：卡片 cover 用 Notion 內建漸層（依 Tags 分類），icon 用固定 emoji 調色盤；
不接 Unsplash 等外部圖庫。

**為什麼**：外部圖庫要新 API key、抽象概念幾乎抓不到相關圖，且圖床失效會讓整面卡片牆
破圖。Notion 內建 cover 是自家 CDN、純 URL、零依賴。代價是同分類的卡同色——所以真正
扛「同書可辨」的責任被推給 icon。

## 2026-08-05：icon 走固定調色盤，不讓模型自由生成 emoji

**決定**：`_ICON_PALETTE` 40 個單 codepoint emoji，prompt 只讓模型「從清單挑」，
parser 只接受清單內的值。

**為什麼**：自由生成會冒出多碼點 ZWJ 序列與 variation selector，那是 Notion icon 最
常見的拒收原因——一個壞 emoji 會讓整張卡 `pages.create` 失敗。「從清單挑」把驗證問題
變成集合查表，順帶讓「調色盤 ∩ 分類 emoji = ∅」這條不變條件撐起 parser 的容錯規則。
```

- [ ] **Step 9: Commit**

```bash
git add CLAUDE.md docs/DECISIONS.md
git commit -m "📝 docs: 卡片視覺與回訪機制的架構說明與 ADR"
```

- [ ] **Step 10: 收掉 spec**

依 CLAUDE.md「計畫文件有生命週期」：本 plan 與 spec 在執行完 48 小時內，價值已濃縮進
CLAUDE.md 與 DECISIONS.md，屆時刪除 `docs/superpowers/specs/2026-08-05-card-visual-richness-design.md`
與本檔案。

---

## 附錄：可能絆倒你的地方

- **Windows 主控台編碼**：`python -c "print('🧭')"` 在 cp950 主控台會炸
  `UnicodeEncodeError`。跑工具或除錯印 emoji 前先設 `PYTHONIOENCODING=utf-8`。
  這不影響寫進 Notion 的內容，只影響終端輸出。
- **`_CLASSIFY_SPLIT` 本來就把 `|` 和 `｜` 當分隔符**（`zettelkasten_generator.py:586`）。
  所以務必**先**用 `_ICON_SEPARATOR` 切出分類段，再對分類段套 `_CLASSIFY_SPLIT`；
  順序反了 emoji 會被當成一個分類值去比對。
- **`_fallback_icon` 依賴 `card.categories`**，所以 `classify_cards` 迴圈裡必須先
  `card.categories = cats` 再算 icon。順序反了分類預設永遠吃不到。
- **Notion 的 `icon: None`**：送 `icon=None` 會被拒收，必須整個 key 不出現。
  `_build_visuals` 與 `build_update` 都靠這點，測試也有守。
- **`tools/__init__.py`**：Task 6 才新增。既有的 `tests/unit/test_fix_card_tags.py`
  用 sys.path 技巧 import，新增 `__init__.py` 後仍可運作，但跑完整測試套件時要確認
  它沒被打到。
