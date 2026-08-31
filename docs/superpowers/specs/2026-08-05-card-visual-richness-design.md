# 卡片盒視覺豐富度與回訪機制 — 設計

> 日期：2026-08-05
> 背景：卡片盒累積了數百張卡，但在 Notion 上（a）卡片牆全是純文字標題，滑過去記不住
> 哪張是哪張；（b）建完就沒有任何機制把卡片重新帶到眼前。
> 本文件只處理這兩個痛點。卡片內容深度、卡片間橫向連結（`ZETTELKASTEN_IMPROVEMENTS.md`
> #3-2/#3-3）維持未排。

## 目標與非目標

**目標**
1. 卡片牆一眼可辨：分類靠色卡 cover 區分領域，同一本書內的卡靠 page icon 區分。
2. 回訪有把手：卡片帶「加工狀態」與日期欄位，讓使用者在 Notion 端自行組 view。
3. 既有卡片一次補齊，不留新舊混雜。

**非目標**（明確不做，理由：不在上述兩個痛點上）
- Unsplash 等外部圖庫（新 API key、抽象概念抓不到相關圖、圖床失效即破圖）。
- 卡片間 relation / embedding 連結。
- 排程器與「每日回顧頁」自動產生。
- 把審核分數搬回 Notion（見 CLAUDE.md「卡片審核閘門」：審核痕跡刻意只留本地）。

## 成品長相

### 卡片盒 DB 新增欄位

由 `ZettelkastenCardRepository._ensure_schema()` 自動建立（沿用既有機制，使用者不需手動加）：

| 欄位 | 型別 | 誰填 |
|------|------|------|
| `加工狀態` | select：`🌱未加工` / `🌿已重寫` / `🌳永久筆記` | 程式建卡時一律寫 `🌱未加工`；升級由使用者手動 |
| `建立日期` | created_time | Notion 自行計算，舊卡也立即有值 |
| `上次回顧` | date | 純手動 |

命名為 `加工狀態` 而非 `狀態`，是為了與審核年代已退役的 `狀態` 欄區隔（見
`docs/NOTION_OUTPUT_IMPROVEMENTS.md`）。

### 卡片頁視覺

- **cover**：依 `Tags` 分類對應一張 Notion 內建 cover（external URL）。多分類取第一個。
- **icon**：單一 emoji，來自固定調色盤。

### 使用者手動的一步（程式做不到）

Notion API 無法修改 view 設定。使用者需自行在卡片盒：
1. gallery view 的 Card preview 設為 **Page cover**（否則色卡不顯示）；
2. 另建一個依 `加工狀態` 分組的 board view。

## 分類 → cover 對照

素材為 Notion 自家 CDN 的內建 cover，`https://www.notion.so/images/page-cover/<name>`。
**已於 2026-08-05 以 curl 驗證可用**：`gradients_1.png` ~ `gradients_9.png`、
`solid_beige.png`、`solid_red.png`、`solid_yellow.png`、`solid_blue.png` 皆回 200；
`gradients_10.png` 與 woodblocks 系列已下架（404），不得使用。

| 分類 | cover |
|------|-------|
| 💞心理學 | `gradients_1.png` |
| 🧠學習技巧 | `gradients_2.png` |
| 💼商務 | `gradients_3.png` |
| 🧘‍♂️人生觀點 | `gradients_4.png` |
| 🧩邏輯思考 | `gradients_5.png` |
| 🔬哲學科學 | `gradients_6.png` |
| 💻軟體工程 | `gradients_7.png` |
| 📈行銷 | `gradients_8.png` |
| 📋專案管理 | `gradients_9.png` |
| 💰理財投資 | `solid_blue.png` |
| （無分類） | `solid_beige.png` |

**自訂分類的處理**：分類清單可由 `ZETTELKASTEN_TAG_CATEGORIES` 覆寫，故對照表查不到的
分類名以 **sha1(分類名) 取模** 從 cover 清單挑一張。不可使用 Python 內建 `hash()` —
字串 hash 每個 process 有隨機 salt，同一張卡每次跑會換色，回填工具也會失去冪等性。

比對鍵沿用 `ZettelkastenLLMEnhancer._category_core()`（只留字母/數字，去 emoji），
與既有 Tags 比對慣例一致，`💞心理學` 與 `心理學` 視為同一分類。

## Emoji icon 的產生

### 調色盤（防呆的核心）

新增 `_ICON_PALETTE`：約 40 個 emoji 的固定清單。Prompt 只讓模型從清單裡挑，parser 只
接受清單內的值。

**因此不需要撰寫 emoji codepoint 驗證邏輯**，也不可能送出 Notion 拒收的畸形 ZWJ 序列
導致 `pages.create` 整張卡失敗。

調色盤入選條件：
1. **單一 codepoint，不含 ZWJ (U+200D) 與 variation selector (U+FE0F)，不含膚色修飾符**。
   所以 `⚠️`、`🗝️`、`🏛️` 這類需要 VS 的字元一律排除，改用 `🚧`、`🔑`、`🧱` 等純單碼點替代。
2. **不得與任何分類自帶的 emoji 重複**（💞🧠💼🧘🧩🔬💻📈📋💰）。這讓下節
   「行內出現的調色盤 emoji 必為 icon」的解析規則嚴格成立，而非只是機率上成立。

兩條不變條件皆由單元測試把關（第 2 條以 `settings.DEFAULT_TAG_CATEGORIES` 為對照）。

初版清單（實作時可微調，維持上述不變條件）：
🧭 🪞 🎯 🔑 🧪 🌱 🔁 🪜 🧱 🔍 💡 🧨 🚧 🪤 🎭 🧊 🔥 🌊 🌉 🚀
🧬 🦴 🩺 🪐 📉 🧯 🪺 🫧 🪃 🧲 🪢 🌀 🍀 🐘 🦉 🐜 🌗 🧵 🪟 🚪

### 搭既有分類呼叫的便車

`ZettelkastenLLMEnhancer.classify_cards()` 本來就是「一本書一次批次 Ollama 呼叫」。
在該呼叫上加產 emoji，**不動產卡與審核 prompt**（那兩支最脆弱，且審核不過會重產）。
也不增加額外一輪 LLM 呼叫。

- `_build_classification_prompt`：附上調色盤，輸出格式改為
  `CARD_編號：分類、分類｜emoji`，並明示「emoji 只能從清單挑、只挑一個」。
- `_parse_classification(text, n, allowed)`：回傳型別由 `List[List[str]]` 改為
  `List[Tuple[List[str], str]]`（每張卡的 `(categories, icon)`）。
- `classify_cards`：把 icon 寫回 `card.icon`。

### 解析容錯（照現有 parser 的寬鬆風格）

1. 行內有 `｜`（或半形 `|`）→ 前段解析分類、後段取第一個落在調色盤內的 emoji。
2. 模型沒照格式 → 掃整行找第一個落在調色盤內的 emoji。給模型的分類名本來就已去 emoji
   （`_build_classification_prompt` 既有行為），且調色盤與分類 emoji 不相交（見上節第 2
   條），因此行內出現的調色盤 emoji 必為模型挑的 icon，不可能是分類自帶的 emoji。
3. 都找不到 → 留空字串，交給 fallback。

### `_fallback_icon(card) -> str`

一份 Key Word 關鍵字 → 調色盤 emoji 的小對照表（如 習慣/循環→🔁、風險/陷阱→🪤、
方向/選擇→🧭，值必須取自調色盤），依序比對卡片的 `tags`；沒命中則用分類預設 emoji
（分類→調色盤 emoji 的固定對照，同樣不得使用分類自帶的 emoji）；分類也沒有則用調色盤
第一個。

**保證 icon 永不空白。** 這不是裝飾——扛「同書 16 張卡可辨」的是 icon，而 icon 靠本地
小模型，fallback 是保底。

## 模組切分

責任邊界：**generator 決定「哪個 emoji」**（它才掌握卡片語意），**Notion 層決定
「哪張 cover URL」**（它才知道 Notion）。每個決定只有一個擁有者，避免 `_split_tags`
那次兩邊漂移的問題。

`zettelkasten_generator.py` 不得 import `src.*`——`legacy/` 那條 sys.path 路徑會壞。

### `zettelkasten_generator.py`
- `ZettelkastenCard` 加 `icon: str = ""`，納入 `to_dict()` / `from_dict()`
  （`cards_output/*.json` 一併留存，續傳不掉 icon）。
- 新增 `_ICON_PALETTE`、`_fallback_icon()`。
- `_build_classification_prompt` / `_parse_classification` / `classify_cards` 如上修改。

### `src/infrastructure/notion/card_visuals.py`（新，純函式）
- `cover_url_for(categories: List[str]) -> str`
- 內含分類→cover 對照表、cover 清單、sha1 fallback。
- 唯一知道 Notion cover URL 長相的地方，repository 與回填工具共用。
- 零 IO，直接單元測試。

### `src/infrastructure/notion/zettelkasten_card_repository.py`
- `pages.create` 帶上：
  - `icon={"type": "emoji", "emoji": card.icon}`（icon 非空時）
  - `cover={"type": "external", "external": {"url": cover_url_for(card.categories)}}`
- `_build_properties` 加 `加工狀態` = `🌱未加工`，照舊走 `_wants()` guard
  （DB 沒該欄則靜默跳過）。
- `_ensure_schema` 的 `to_add` 加入三個新欄位；`加工狀態` 需一併 seed 三個 select option。

## 回填工具 `tools/backfill_card_visuals.py`

慣例照 `tools/fix_card_tags.py`：`--dry-run` 預覽、重跑冪等。

1. 分頁撈卡片盒**所有**頁，篩出 `icon` 或 `cover` 為空者。**已有的不覆蓋** → 重跑安全，
   也不會蓋掉使用者手動換過的圖。
2. **cover 純規則**：直接由查詢結果內的 `Tags` 算出，零 LLM、零額外 API 呼叫。
3. **icon 走 LLM**：以 `標題` + `Key Word` 兩個 property 組批（每批約 20 張）走
   `classify_cards` 同一條路徑。這兩個欄位都在 `databases.query` 的回應裡，
   **不需為了讀內文再打一次 API**。
   Ollama 不可用時只補 cover、icon 留待下次重跑，不整批失敗。
4. `加工狀態` 為空者補 `🌱未加工`。
5. 每張卡 **1 次 `pages.update`**，同時寫 icon + cover + 加工狀態。

`--dry-run` 輸出「卡片標題 → cover 檔名 / icon」對照，比照 `fix_card_tags.py` 的
「原標籤 → 新標籤」格式。

## 測試

domain/純邏輯改動必附單元測試（CLAUDE.md DoD 第 2 條）。

- `card_visuals.cover_url_for`：各分類命中、多分類取首、空分類 fallback、
  未知分類走 sha1 且**跨 process 穩定**（同輸入同輸出）。
- `_ICON_PALETTE` 不變條件：每個元素恰為 1 個 codepoint、不含 U+200D 與 U+FE0F。
- `_parse_classification` 新格式：正常 `分類｜emoji`、模型漏 emoji、模型給清單外 emoji、
  格式跑掉但行內有調色盤 emoji、分類與 emoji 皆缺。
- `_fallback_icon`：命中關鍵字表 / 退分類預設 / 兩者皆無。
- **既有 `_parse_classification` 測試須就地修改**（回傳型別變了），不得另建一份平行測試
  ——CLAUDE.md 禁止留下已知會壞的測試，`tests/` 也已有重複測試檔的技術債。

## 驗證（DRY_RUN 驗不到卡片流程，必須真跑）

1. `python tools/backfill_card_visuals.py --dry-run` — 檢視對照表輸出是否合理。
2. 正式回填 → 到 Notion 把 gallery 的 Card preview 切成 Page cover → 肉眼確認卡片牆。
3. `python main.py` 對至少一本新書實跑 → 確認新卡出生即帶 cover / icon / `🌱未加工`。
4. `python -m ruff check .` 與 `python -m pytest` 全綠。

## 已知風險

- **色卡只有 11 種**，同分類的卡 cover 同色；真正扛「同書可辨」的是 emoji icon，
  而 icon 來自本地小模型。第一次回填後應抽樣檢查 icon 是否合理，不合理即代表
  調色盤或 prompt 需調整。`_fallback_icon` 是保底而非裝飾。
- **`classify_cards` 回傳契約改變**會同時影響 `backfill_zettelkasten.py`
  （已 import `ZettelkastenLLMEnhancer`），需一併檢查。
- Notion 內建 cover URL 屬未公開介面，Notion 若下架（如 `gradients_10` 的前例）會破圖。
  影響僅為視覺，不影響資料；屆時換 URL 即可。

## 文件更新（同圈完成，不留到之後）

- CLAUDE.md：卡片盒 DB 欄位清單補三個新欄位、`tools/` 段落補回填工具、
  新增本設計的簡述與「gallery view 需手動設 Page cover」這條使用者須知。
- `docs/DECISIONS.md`：記錄「色卡＋emoji icon，不走外部圖庫」與
  「emoji 走固定調色盤而非自由生成」兩個決定及理由。
