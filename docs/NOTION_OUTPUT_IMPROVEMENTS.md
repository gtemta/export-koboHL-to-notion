# Notion 輸出結構改善計畫（劃線頁 + 卡片盒）

> 記錄日期：2026-07-04
> 背景：以「方便閱讀、分享、留下共鳴、思維增長」為目標 review 匯出到 Notion 的結果。
> 使用者實測回報三個問題：卡片 **Tags 沒填**、**來源 relation 沒連到書**、**Key Word 空白**。
> 經 Notion API 比對實際 DB schema，根因是**程式寫入的欄位名稱與實際卡片盒 DB 不一致**。
> 本文件是 `ZETTELKASTEN_IMPROVEMENTS.md` 的後續；該文件的 #3-2/#3-3（卡片橫向連結）仍另案未排。

## 實作進度

- ✅ E1 自動建立卡片盒缺失欄位（來源劃線ID / 品質分數 / 狀態）— KNOWLEDGE_REFINEMENT_PLAN Phase 1
- ✅ E2 Key Word 寫入自由概念標籤
- ✅ E3 Tags 固定分類 + LLM 批次分類
- ✅ E4 來源 relation 修正（反查 + 書名雙保險）
- ✅ E5 dedup 兜底（書不在 Books DB 時不再重複建卡）
- ⬜ A 劃線頁改版（toggle 章節 / quote / 2000 字截斷）
- ⬜ B 卡片頁顯示讀者註記
- ⬜ D 劃線頁 ↔ 卡片盒互連

---

## 關鍵事實（已實地查證，開發時**不需**再連 Notion 重查）

### 卡片盒 DB（`NOTION_ZETTELKASTEN_DATABASE_ID`，🗃️ 卡片盒重點收集）實際 schema

| 欄位 | 型別 | 備註 |
|------|------|------|
| `標題` | title | 程式已正確寫入 |
| `Tags` | multi_select | 既有選項：💞心理學 / 🧠學習技巧 / 💼商務 / 🧘‍♂️人生觀點。**程式目前寫的是不存在的 `主題` 欄位** |
| `Key Word` | rich_text | **程式目前完全沒寫** |
| `來源` | relation | 指向 📚 Personal Reading List。欄位存在，是書名比對失敗才沒連上 |

**不存在**的欄位：`主題`、`來源劃線ID`、`品質分數`、`狀態` —— 因此
`ZettelkastenCardRepository._wants()` 的 schema guard 把這些寫入**全部靜默跳過**，
劃線粒度去重也退化成「整本略過」模式。

DB 有兩個 view：table view（按 `來源` relation 分組）與 board view（按 `Tags` 分組）——
Tags/來源沒填時卡片全部堆在「無分組」，這就是使用者看到的現象。

### Books DB（`NOTION_BOOKS_DATABASE_ID`，📚 Personal Reading List）

- title 欄位名稱是 **`Name`**（不是 Title）。
- 有 **`Kobo EReader` relation** 指向 Kobo 劃線 DB（`NOTION_DATABASE_ID` 那個庫）→
  已知劃線頁 page_id 時可用它**反查**對應的書，比書名比對可靠。
- 書名比對失敗的典型原因：Kobo 書名帶全形冒號「：」與副標
  （現有 `_find_book_page` 只切半形 `:`），或 Notion 只登錄主書名而 Kobo 是完整書名
  （`contains` 方向錯，永遠比不中）。

### 使用者閱讀領域（來自 Notion「Dante 閱讀標籤分類庫」）

Marketing / Psychology / Project Management / Business & Finance / Philosophy & Science /
Learning Skills / Logical Thinking / Software Engineering / Spiritual Inspiration / Others

### 使用者已定案的決策（不要再問）

1. **Tags 用固定分類清單**：LLM 只能從清單挑 1–2 個、不可自由新增選項（避免稀釋 board view）；
   自由概念標籤（如「習慣、複利」）改寫進 `Key Word` 文字欄。
2. **程式自動建立**缺失的 `來源劃線ID` / `品質分數` / `狀態` 三欄（新欄位不會出現在
   既有 view 的 displayProperties，不影響版面）。
3. **來源比對策略**：先用 `Kobo EReader` relation 反查，查不到再退回強化版書名比對。

---

## E. 卡片盒 schema 對齊（最優先，直接修使用者回報的三個問題）

主要檔案：`src/infrastructure/notion/zettelkasten_card_repository.py`

### E1. 自動建立缺失欄位

- 首次上傳前檢查 schema（沿用現有 `_fetch_property_names()` + `_UNSET` sentinel 快取機制），
  缺失時用 Notion `databases.update` 補上：
  - `來源劃線ID`：rich_text
  - `品質分數`：number
  - `狀態`：select，選項 `草稿` / `已審` / `永久筆記`
- 建立成功後**刷新 `_schema_props` 快取**（重設為 `_UNSET` 或直接更新集合），
  讓同一 run 內後續 `_wants()` 判斷生效。
- schema 讀取失敗（`_fetch_property_names()` 回 `None`）時**不要**嘗試建立，維持現有
  「照舊寫入全部屬性」的 fallback。

### E2. Key Word：寫入自由概念標籤

- `_build_properties()`：`card.tags`（LLM 產的概念標籤，已存在）以「、」join 寫入
  `Key Word` rich_text，截 2000 字。
- 移除對不存在欄位 `主題`（常數 `_TOPIC_PROPERTY`）的寫入。

### E3. Tags：固定分類 + LLM 批次分類

- 預設分類清單（沿用既有 emoji 風格，對齊使用者閱讀領域）：
  `💞心理學、🧠學習技巧、💼商務、🧘‍♂️人生觀點、🧩邏輯思考、🔬哲學科學、💻軟體工程、📈行銷、📋專案管理、💰理財投資`
- 清單放 `src/config/settings.py`，env `ZETTELKASTEN_TAG_CATEGORIES`（逗號分隔）可覆寫；
  `.env.example` 同步補說明。
- Repository 啟動時用 `databases.update` 把清單中 DB 尚缺的 multi_select 選項補進 `Tags`。
- 產卡流程加**每本書一次**的批次分類 LLM 呼叫（放 `zettelkasten_generator.py`，
  Gemini 優先、無 API key 退 Ollama）：輸入 N 張卡的標題+內容+允許分類清單，
  要求每張卡回 1–2 個分類；**只能從清單挑，歸不進去回空**（空 = 留給使用者手動分類，
  不要發明「其他」）。
- 結果存 `ZettelkastenCard.categories: List[str]` 新欄位
  （`to_dict`/`from_dict` 同步；`from_dict` 用 `.get` 天然向後相容舊 JSON）。
- `_build_properties()`：`categories` 寫入 `Tags` multi_select；不在允許清單內的值直接丟棄。

### E4. 來源 relation 修正（反查 + 書名雙保險）

- `GenerateBookCardsUseCase.execute()` 加參數 `source_page_id: Optional[str] = None`
  （劃線頁的 Notion page_id），一路傳到 `upload_cards()` → `_find_book_page()`。
- `SyncBooksUseCase._process_single_book()` **兩處**呼叫點都要傳：
  「已導出更新 metadata」分支與「新書同步」分支（兩處都已持有 `page_id`）。
- `_find_book_page()` 改為策略鏈：
  1. **反查**：`databases.query(Books DB, filter={"property": "Kobo EReader", "relation": {"contains": source_page_id}})`，有結果直接用。
  2. **強化書名比對**（反查無結果或無 page_id 時）：
     - 正規化：全形「：」與半形「:」都切出主標、全形空白→半形、strip；
     - 依序試 `Name equals 主標` → `Name contains 主標`；
     - 仍無 → 分頁抓 Books DB 全部頁面（每 run 快取一次即可，庫不大），
       本地做「正規化後雙向包含」比對（Notion Name ⊆ Kobo 主標 或反向）。
  3. 都失敗：維持現況（建卡不連 relation）+ log warning。

### E5. dedup 兜底（修「重跑重複建卡」bug）

- 現況 bug：`_existing_source_ids()` 在 `books_page_id=None`（書不在 Books DB）時
  回傳空集合 → **每次重跑都把整批卡重複建一次**。
- 修法：`books_page_id` 為 None 且 DB 有 `來源劃線ID`（E1 之後必有）時，
  改為逐卡查 `{"property": "來源劃線ID", "rich_text": {"equals": sid}}` 判重
  （單書 ≤ `ZETTELKASTEN_MAX_CARDS`=16 張，查詢成本可接受）。

---

## A. 劃線頁改版（閱讀體驗）

主要檔案：`src/infrastructure/notion/notion_api_repository.py`

- **A1 可收合章節**：`_heading_block()` 支援 `is_toggleable: true`；章節從 heading_1 改
  **toggle heading_2**，該章劃線 blocks 放進 heading 的 `children`。
  - Notion API 限制：單一 block 的 nested `children` 一次最多 100 個；
    章節劃線（含 annotation callout）超過 ~90 個 blocks 時拆成多個同名 toggle（加 `(續)`）。
  - 現有 `_BATCH_SIZE=80` 的平鋪切批邏輯（`sync_book_highlights`）需改為
    「以 toggle heading 為單位」切批，不能把一個 toggle 的 children 拆到兩個 request。
- **A2 quote 化**：劃線 `bulleted_list_item` → `quote` block；💭 annotation callout
  改為 quote 的 `children`（縮排從屬，明確「這條註記回應這條劃線」）。
- **A3 截斷 bug**：`_bulleted_block()` 目前**沒有**截 2000 字——超長劃線會讓整批
  append 失敗且該章丟失（現有 `_append_in_smaller_chunks` 只救「block 太多」，
  救不了「單一 rich_text 過長」）。改名 `_quote_block()` 並 `text[:2000]`，超長 log warning。
- **A4**：頁首 `# Highlights` 改 `📌 劃線筆記`（與整頁中文一致）。

## B. 卡片頁顯示讀者註記（共鳴）

檔案：`zettelkasten_generator.py`、`src/infrastructure/notion/zettelkasten_card_repository.py`

- 現況：highlight 的 `annotation` 有餵給 LLM 當產卡 context，但卡片頁面上看不到
  讀者自己寫的想法——Zettelkasten 的靈魂是自己的思考，這是「共鳴」的最大缺口。
- `ZettelkastenCard` 加 `source_annotation: str = ""`（`to_dict`/`from_dict` 同步）。
- `generate_card()` 與 `_parse_batch_response()` 建卡時帶入 `highlight.get('annotation')`。
- `_build_children()`：原文 quote 之後、📖 章節 callout 之前，若有註記加
  「💭 我的註記」callout（截 2000 字）。

## D. 劃線頁 ↔ 卡片盒互連（思維增長）

- 現況：劃線頁與卡片盒互不相通（兩個不同 DB），從書看不到長出哪些卡。
- 上傳卡片成功**且本次有新卡**時，在劃線頁尾端 append callout：
  `🗃️ 本書已產生 N 張知識卡片` + 卡片盒 DB URL。
  （E4 已把 `source_page_id` 傳進 card use case，此處直接可用。）
- 0 新卡不 append，避免重跑重複；不需掃描既有 blocks。

## 不做 / 不改程式

- 卡片間橫向連結（`ZETTELKASTEN_IMPROVEMENTS.md` #3-2/#3-3）：價值高但成本高，另案。
- `來源劃線ID` 等機器用欄位不必從程式隱藏——使用者在 Notion view 端隱藏即可。

---

## 建議執行順序

| 順位 | 項目 | 理由 |
|------|------|------|
| 1 | E1–E5 schema 對齊 | 使用者回報的三個問題 + 重複建卡 bug，全部在此修掉 |
| 2 | A 劃線頁改版 | 閱讀體驗最大改善；A3 是資料丟失 bug 應儘早 |
| 3 | B 讀者註記上卡 | 小改動，補「共鳴」缺口 |
| 4 | D 互連 callout | 依賴 E4 的 source_page_id，最後做 |

每組獨立 commit。

## 驗證方式

1. 煙霧測試：無測試框架，用 `python -c` 驗證 import 與 block/property builder 的輸出結構。
2. 端對端（真實 Notion + 現有 `KoboReader.sqlite`，`ENABLE_ZETTELKASTEN_CARDS=true`）：
   - 跑 `python main.py` → 卡片盒 DB 自動長出三個新欄位、`Tags` 補齊新選項；
   - 新建卡片：`Tags` 有分類、`Key Word` 有概念標籤、`來源` 連到 Personal Reading List 對應書；
   - 挑一本**不在** Books DB 的書重跑兩次 → 卡片不重複（E5）；
   - 劃線頁：章節可收合、劃線為 quote、💭 縮排在 quote 下、頁尾出現卡片盒 callout；
   - 已匯出書籍重跑：metadata 更新正常、內文不重複 append（`Exported=true` 分支本就不重傳）。
