# 知識精練執行計畫（卡片盒地基修復 → 抽取精練 → 分享投影層）

> 記錄日期：2026-07-06
> 背景：檢視 `cards_output/` 14 本書約 230 張卡片與 Notion 上傳鏈路後，確認三個「知識層失效」問題
> （詳見下方「關鍵事實」）。本文件是 [`NOTION_OUTPUT_IMPROVEMENTS.md`](NOTION_OUTPUT_IMPROVEMENTS.md)
> 的擴充執行版：**Phase 1 完整吸收該文件的 E1–E5 與 B 項**，並新增標籤修復、審核層 Gemma 化、
> 既有卡回填、知識抽取精練、社群分享貼文等後續工程。
> 執行方式：本計畫已經使用者核准，交由實作 agent 按 Phase 依序執行，**每個 Phase 獨立 commit**。
> 分支：`feat/zettelkasten-improvements`。

## 總進度

- ✅ Phase 1：卡片盒 schema 對齊（E1–E5）— 完成 2026-07-09；單元＋fake-client 煙霧驗證通過，待真實 Notion 端對端
- ⬜ Phase 2：標籤修復（T1 解析 / T2 既有 JSON 重切）
- ⬜ Phase 3：審核層 Gemma 化（R1 後端抽象 / R2 移除假分數 / R3 重審 CLI）
- ⬜ Phase 4：知識抽取精練（K1 主張式標題 / K2 延伸段 / K3 註記上卡 / K4 章節消毒）
- ⬜ Phase 5：既有卡完整回填（backfill 工具）
- ⬜ Phase 6：分享貼文投影層（P1 金句卡 / P2 讀畢書摘 / P3 跨書主題串）

---

## 使用者已定案的決策（不要再問）

1. **審核後端用 Gemma（Ollama）**，不用 Gemini（使用者沒有 Gemini API key）。Gemini 保留為可選後端。
2. **既有 ~230 張已上傳 Notion 的卡片要完整回填**：重審後的品質分數、狀態、Key Word、
   來源劃線ID 全部回寫，用「標題比對」認卡（當時上傳時 DB 還沒有這些欄位）。
3. **分享貼文輸出到 Notion 📚 Personal Reading List（Books DB）對應書籍頁面的子區塊**
   （統一放在 toggle heading「📣 分享草稿」下），不是本地 markdown。
4. 沿用 `NOTION_OUTPUT_IMPROVEMENTS.md` 既有的三項定案：Tags 用固定分類清單（LLM 不可自由新增）、
   程式自動建立缺失欄位、來源比對先 relation 反查再書名比對。

## 關鍵事實（已實地查證，開發時不需重查）

### 失效證據（來自 `cards_output/*.json`，2026-07-04 產出的 14 本書）

1. **標籤黏連**：LLM 沒有照 prompt 用頓號分隔，實際出現三種格式，而
   `_TAG_SPLIT = re.compile(r'[、,，/|｜\s]+')`（`zettelkasten_generator.py:444`）都切不開：
   - 全形冒號串：`"語言演化：社交結構：謊言藝術"`（《多巴胺國度》全書 16 張）
   - 破折號串：`"資本結構—負債比率—金融風險"`（《大威脅》）
   - 日文中點串：`"・說服論述・故事架構・聽眾心理"`（《說理Ⅱ》，注意有前導中點）
2. **審核層從未跑過**：全部 230 張卡 `quality_score` 一律 7、`revision_notes` 一律空字串
   —— 是 `GeminiReviewer` 未配置時的 default 值（多處 `card.quality_score = 7` fallback）。
3. **內容雜訊**：卡片 content 偶有 LLM 雜訊（例：《多巴胺國度》card_03「導致**의**羞恥感」混入韓文字）。
4. **章節參照污染**：`chapter_reference` 有時是劃線內文截斷，例：
   `"拮抗理論」：「任何長時間或反覆從享樂或情感中性狀態脫離的情況⋯⋯都是有其代價的。」50這種代價就是一種..."`。

### Notion DB schema（引自 NOTION_OUTPUT_IMPROVEMENTS.md 的實地查證）

- 卡片盒 DB（`NOTION_ZETTELKASTEN_DATABASE_ID`）實際欄位：`標題`(title)、`Tags`(multi_select，
  既有選項 💞心理學/🧠學習技巧/💼商務/🧘‍♂️人生觀點)、`Key Word`(rich_text)、`來源`(relation → Books DB)。
  **不存在**：`主題`、`來源劃線ID`、`品質分數`、`狀態`（程式現在寫這些會被 `_wants()` 靜默跳過）。
- Books DB（`NOTION_BOOKS_DATABASE_ID`，📚 Personal Reading List）：title 欄位名是 **`Name`**；
  有 **`Kobo EReader` relation** 指向 Kobo 劃線 DB（`NOTION_DATABASE_ID`），可用劃線頁 page_id 反查書。
- 卡片盒有 table view（按 `來源` 分組）與 board view（按 `Tags` 分組）。

### 程式碼錨點

| 位置 | 內容 |
|------|------|
| `zettelkasten_generator.py` | `ZettelkastenCard` dataclass（含 `to_dict`/`from_dict`）、`CardSelectionAlgorithm`、`ZettelkastenLLMEnhancer`（Ollama 串流請求、`_build_prompt`/`_build_batch_prompt`、`_parse_response`/`_parse_batch_response`、`_strip_thinking`、`_extract_tags`）、`GeminiReviewer`（`_build_review_prompt` JSON 契約、`_parse_review_response`）、`ZettelkastenCardGenerator.generate_cards()` |
| `src/infrastructure/notion/zettelkasten_card_repository.py` | `_TOPIC_PROPERTY = "主題"`(:28)、`_wants()`/`_known_properties()`/`_fetch_property_names()` + `_UNSET` 快取(:261-281)、`_find_book_page()`(:115，目前只切半形 `:`)、`_existing_source_ids()`(:144)、`_build_properties()`(:228)、`_build_children()`(:299)、`_card_source_id()`(:201) |
| `src/application/use_cases/generate_book_cards_use_case.py` | `execute(book, highlights)`：續傳 → 產卡 → `CardStore.save` → 上傳 → `mark_uploaded` |
| `src/application/use_cases/sync_books_use_case.py` | `card_use_case.execute()` 兩處呼叫點：**:82**（已導出更新 metadata 分支）與 **:123**（新書同步分支），兩處都已持有劃線頁 `page_id` |
| `src/infrastructure/persistence/card_store.py` | `save`/`load_pending`/`mark_uploaded`、`_slug()` 檔名規則 |
| `src/infrastructure/container.py` | `_build_card_use_case()` 組裝點 |
| `src/config/settings.py` | `Settings.from_env()`，所有新 env 都在這裡加 |

### 既有可複用元件

- `src/infrastructure/notion/rate_limiter.py`（`NotionRateLimiter`）與 `retry_policy.py`
  （`retry_with_backoff`）——所有新的 Notion 呼叫（包含 tools/）一律沿用。
- `_strip_thinking()`：thinking 模型（gemma4 系列）輸出清洗，審核解析也要用。
- `CardStore.from_dict` 已對缺欄位天然向後相容（`.get` + default），新增卡片欄位時維持此模式。

---

## Phase 1：地基 — 卡片盒 schema 對齊（E1–E5）

> 規格完整版在 `NOTION_OUTPUT_IMPROVEMENTS.md` 的 E 節，此處為執行摘要＋補充。
> 改動檔案：`src/infrastructure/notion/zettelkasten_card_repository.py`、`src/config/settings.py`、
> `zettelkasten_generator.py`、`src/application/use_cases/generate_book_cards_use_case.py`、
> `src/application/use_cases/sync_books_use_case.py`、`src/infrastructure/container.py`、`.env.example`。

### E1 自動建立缺失欄位

- 首次上傳前檢查 schema（沿用 `_fetch_property_names()` + `_UNSET` 快取），缺失時用
  `databases.update` 補上：`來源劃線ID`(rich_text)、`品質分數`(number)、
  `狀態`(select：`草稿`/`已審`/`永久筆記`)。
- 建立成功後**刷新 `_schema_props` 快取**，讓同一 run 內後續 `_wants()` 生效。
- `_fetch_property_names()` 回 `None`（schema 讀取失敗）時**不要**嘗試建立，維持現有
  「照舊寫入全部屬性」fallback。

### E2 Key Word 寫入自由概念標籤

- `_build_properties()`：`card.tags` 以「、」join 寫入 `Key Word` rich_text（截 2000 字）。
- 移除 `_TOPIC_PROPERTY = "主題"` 常數與其寫入（該欄位在 DB 不存在）。

### E3 Tags 固定分類 + LLM 批次分類

- 預設分類清單放 `src/config/settings.py`，env `ZETTELKASTEN_TAG_CATEGORIES`（逗號分隔）可覆寫：
  `💞心理學、🧠學習技巧、💼商務、🧘‍♂️人生觀點、🧩邏輯思考、🔬哲學科學、💻軟體工程、📈行銷、📋專案管理、💰理財投資`
- Repository 啟動時用 `databases.update` 把 DB 尚缺的 multi_select 選項補進 `Tags`。
- 產卡流程加**每本書一次**的批次分類 LLM 呼叫（放 `zettelkasten_generator.py`，**用 Ollama**）：
  輸入 N 張卡的標題+內容+允許清單，每張卡回 1–2 個分類；**只能從清單挑，歸不進去回空**
  （空 = 留給使用者手動，不要發明「其他」）。
- 結果存 `ZettelkastenCard.categories: List[str]` 新欄位（`to_dict`/`from_dict` 同步，
  `from_dict` 用 `.get` 向後相容舊 JSON）。
- `_build_properties()`：`categories` 寫入 `Tags` multi_select；不在允許清單內的值直接丟棄。

### E4 來源 relation 修正（反查 + 書名雙保險）

- `GenerateBookCardsUseCase.execute()` 加參數 `source_page_id: Optional[str] = None`，
  一路傳到 `upload_cards()` → `_find_book_page()`。
- `SyncBooksUseCase._process_single_book()` **兩處**呼叫點（:82 與 :123）都傳 `page_id`。
- `_find_book_page()` 改策略鏈：
  1. **反查**：`databases.query(Books DB, filter={"property": "Kobo EReader", "relation": {"contains": source_page_id}})`，有結果直接用。
  2. **強化書名比對**（反查無果或無 page_id）：正規化（全形「：」與半形「:」都切主標、
     全形空白→半形、strip）→ 依序 `Name equals 主標` → `Name contains 主標` →
     分頁抓 Books DB 全部頁面（每 run 快取一次）做「正規化後雙向包含」。
  3. 都失敗：建卡不連 relation + log warning（維持現況）。

### E5 dedup 兜底（修「重跑重複建卡」bug）

- 現況 bug：`_existing_source_ids()` 在 `books_page_id=None` 時回空集合 → 每次重跑整批重複建卡。
- 修法：`books_page_id` 為 None 且 DB 有 `來源劃線ID`（E1 之後必有）時，改為逐卡查
  `{"property": "來源劃線ID", "rich_text": {"equals": sid}}` 判重（單書 ≤ 16 張，成本可接受）。

### Phase 1 驗收

- `python main.py`（`ENABLE_ZETTELKASTEN_CARDS=true`）跑完：卡片盒 DB 長出三個新欄位、
  `Tags` 選項補齊；新卡有 Key Word、Tags 分類、來源 relation。
- 挑一本**不在** Books DB 的書重跑兩次 → 卡片不重複（E5）。
- `NOTION_OUTPUT_IMPROVEMENTS.md` 實作進度 E1–E5 打勾。

---

## Phase 2：標籤修復（T）

> 改動檔案：`zettelkasten_generator.py`、新增 `tools/fix_card_tags.py`。

### T1 解析修復（`_extract_tags` / `_TAG_SPLIT`）

- `_TAG_SPLIT` 分隔符加入：`：`（全形冒號）、`:`（半形冒號）、`—`（em dash）、`–`（en dash）、
  `・`（日文中點）、`·`（間隔號）。
- 解析後逐一清洗：去頭尾標點符號（含前導 `・`）、去 `#`；單一 tag 長度上限 15 字；
  清洗後為空或仍含上述連接符的丟棄。維持最多 3 個、去重。
- prompt 修正（`_build_prompt` 與 `_build_batch_prompt` **兩處**的【標籤】規則）加負面規則：
  「標籤之間只用頓號（、）分隔，不要用冒號、破折號或中點連接」。

### T2 既有 JSON 重切工具

- 新增 `tools/fix_card_tags.py`（`tools/` 為新目錄，加 `__init__.py` 不必要——用
  `python tools/fix_card_tags.py` 直接執行，檔頭自行把專案根加進 `sys.path` 以 import
  `zettelkasten_generator`）。
- 行為：掃 `cards_output/*.json` → 對每張卡的 `tags`，把黏連字串用 T1 的新規則重切 → 寫回
  JSON（**保留 `uploaded`、`uploaded_at` 等既有欄位，不動其他內容**）。
- CLI：`--dry-run`（印出「原 tags → 新 tags」預覽不寫檔）、`--dir`（預設 `cards_output`）。

### Phase 2 驗收

- 煙霧測試：三種實際壞格式（見「關鍵事實」）各餵 `_extract_tags`，輸出為乾淨的 2–3 個 tag。
- `python tools/fix_card_tags.py --dry-run` 顯示 14 本書的重切預覽；正式跑後抽查
  《多巴胺國度》《大威脅》《說理Ⅱ》三個 JSON 的 tags 已是陣列多元素。

---

## Phase 3：審核層 Gemma 化（R）

> 改動檔案：`zettelkasten_generator.py`（審核類都在這裡，**不搬家**以控制改動範圍）、
> `src/infrastructure/container.py`（若組裝需要）、`.env.example`、新增 `tools/rereview_cards.py`。

### R1 後端抽象

- 抽一個模組層 helper `_ollama_generate(prompt, *, model, timeout_s, num_predict, num_ctx=None) -> Optional[str]`：
  封裝現在 `ZettelkastenLLMEnhancer.generate_card()` 裡的串流 POST（stream=True、keep_alive、
  逐行累積、timeout 時回傳已累積的部分文字），供產卡與審核共用。改完後
  `generate_card()`/`_batch_generate_single_call()` 內部改呼叫它（行為不變）。
- 新增 `OllamaReviewer`：
  - 審核 prompt **沿用** `GeminiReviewer._build_review_prompt` 的 JSON 契約
    （title/content/quality_score/revision_notes）——把該方法與 `_parse_review_response`
    提到共用 base class（如 `_BaseReviewer`）或模組函式，兩個 reviewer 共用。
  - 輸出解析：先 `_strip_thinking()` → 剝 ```json code fence``` → 現有 regex
    `\{[^{}]*\}` 抽 JSON → 失敗時 fallback 取第一個 `{` 到最後一個 `}` 再 `json.loads`。
  - env：`OLLAMA_REVIEW_MODEL`（預設同 `OLLAMA_MODEL`）、`OLLAMA_REVIEW_TIMEOUT_SECONDS`
    （預設同 `OLLAMA_TIMEOUT_SECONDS`）。temperature 用 0.3（同 Gemini 審核）。
- 工廠 `build_reviewer() -> reviewer`：env `ZETTELKASTEN_REVIEWER=auto|ollama|gemini|none`，
  預設 `auto`（有 `GEMINI_API_KEY` → Gemini，否則 → Ollama）；`none` 回傳 no-op（不審、不給分）。
  `ZettelkastenCardGenerator.__init__` 改用工廠取得 reviewer。
- 門檻語意不變：分數 < `GEMINI_REVIEW_THRESHOLD`（預設 6，env 名沿用）才套用 reviewer 改寫的
  title/content，否則保留原稿只記分數。

### R2 移除假分數

- 刪掉所有「未審核／審核失敗」路徑的 `card.quality_score = 7`（`review_and_refine` 不可用分支、
  API error 分支、exception 分支、`batch_review` 不可用分支、`generate_cards()` 跳過審核分支、
  JSON 解析失敗分支）→ 一律維持 `quality_score = 0`。
- 下游已安全：`_build_properties` 只在 `score > 0` 時寫「品質分數」；`_status_name` 0 分落「草稿」。
- 審核失敗與審核成功要能區分：只有 reviewer 真的回傳合法 JSON 才設分數。

### R3 重審 CLI

- 新增 `tools/rereview_cards.py`：逐一載入 `cards_output/*.json`
  （用 `ZettelkastenCard.from_dict`），對每張卡跑 `build_reviewer()` 的審核，更新
  `quality_score`/`revision_notes`（低於門檻同現行邏輯套用改寫後 title/content），寫回 JSON
  並在檔案層加 `reviewed_at` timestamp、保留 `uploaded` 等欄位。
- CLI：`--book <名稱>`（比對 `CardStore._slug` 前綴）、`--dry-run`（印分數分布不寫檔）、
  `--force`（已有 `reviewed_at` 的檔也重審；預設跳過已重審的檔）。
- 注意：230 張卡 × 本地 Gemma，一張約數十秒，全量跑要提醒使用者需時（log 進度 `i/N`）。

### Phase 3 驗收

- 煙霧測試：`_parse_review_response` 對「含 thinking 前綴」「含 code fence」「純 JSON」三種輸出都能解析。
- `python tools/rereview_cards.py --book 多巴胺國度 --dry-run` 跑通且分數有區分度（不再全 7）；
  正式跑一本書後 JSON 的 `quality_score`/`revision_notes` 有真實內容。
- 全量重審 14 本書（使用者在場時跑，Ollama 需啟動）。

---

## Phase 4：知識抽取精練（K）

> 改動檔案：`zettelkasten_generator.py`、`src/infrastructure/notion/zettelkasten_card_repository.py`、
> `src/application/use_cases/generate_book_cards_use_case.py`（K3 已傳 annotation，確認即可）。
> 只影響**未來新卡**，可與 Phase 3 並行。

### K1 主張式標題

- `_build_prompt` 與 `_build_batch_prompt` 的【標題】規則改為：
  「標題必須是一個可以獨立成立的完整論斷（主張句），讓人不看內容也知道這張卡主張什麼；不要用主題名」。
- 附正反例：✅「語言愈先進，謊言愈精美」／❌「語言的進化與欺騙藝術的關係」。
- 標題長度規則放寬為 5–20 字（主張句比主題名長）。

### K2 【延伸】段

- prompt（兩處）加第四段：`【延伸】一句話：這個概念可以應用在哪裡、與什麼概念相關、或它挑戰了什麼常見假設`。
- `ZettelkastenCard` 加 `extension: str = ""`（`to_dict`/`from_dict` 同步）。
- 解析：`_parse_response` 加 `【延伸】` pattern（參考 `_TAG_LINE` 的寫法；缺失容忍，回空字串，
  **不因缺延伸段而讓卡片作廢**）。批次解析同樣帶入。
- `_build_children()`：content 段之後加 💡 callout（有 extension 才加，截 2000 字）。
- 此欄位同時是未來 #3-2/#3-3 卡片橫向連結的文字素材（見 `ZETTELKASTEN_IMPROVEMENTS.md`）。

### K3 讀者註記上卡（= NOTION_OUTPUT_IMPROVEMENTS 的 B 項）

- `ZettelkastenCard` 加 `source_annotation: str = ""`（`to_dict`/`from_dict` 同步）。
- `generate_card()` 與 `_parse_batch_response()` 建卡時帶入 `highlight.get('annotation')`。
- `_build_children()`：原文 quote 之後、📖 章節 callout 之前，若有註記加「💭 我的註記」callout
  （截 2000 字）。
- 完成後把 `NOTION_OUTPUT_IMPROVEMENTS.md` 的 B 項打勾。

### K4 章節參照消毒

- `zettelkasten_generator.py` 加模組函式 `_clean_chapter_reference(raw: str) -> str`：
  - 空值回空；長度 > 25 字 → 視為污染回空；
  - 含內文特徵字元（`」`、`「`、`⋯`、`。`）→ 視為污染回空。
- 套用兩處:建卡時（`generate_card` / `_parse_batch_response` 的 `chapter_reference=`）與
  `_build_children()` 的 📖 callout（污染時 callout 只顯示進度百分比，或整個省略）。

### Phase 4 驗收

- 煙霧測試：舊 JSON（無 `extension`/`source_annotation` 欄位）過 `from_dict` 不炸；
  污染章名樣本（見「關鍵事實」#4）過 `_clean_chapter_reference` 回空。
- 對一本新書（或刪掉某書卡片後重產）跑 `python main.py`：新卡標題是主張句、
  頁面有 💡 延伸 callout、有註記的劃線出現 💭 callout、📖 callout 無污染章名。

---

## Phase 5：既有卡完整回填（BF）

> 依賴：Phase 1（欄位存在）、Phase 2（JSON 標籤已重切）、Phase 3（JSON 已重審）。
> 新增 `tools/backfill_cards.py`。

流程（對每個 `cards_output/*.json`）：

1. **解析書籍頁**：呼叫 repository 的 E4 策略鏈（把 `_find_book_page` 改成可從外部呼叫，
   或在 repository 上加一個公開方法）。backfill 沒有劃線頁 page_id 可反查 → 直接走書名比對分支。
2. **撈既有卡片**：有書籍頁 → 用 `來源` relation 過濾分頁撈該書卡片；沒有 → 分頁撈**整個卡片盒**
   （全庫只撈一次、快取在記憶體，供所有無 relation 的書共用）。
3. **標題比對認卡**：正規化（strip、全形空白→半形）後 JSON 卡標題 == Notion 卡標題。
   一對多（同標題多張卡）或比不中的**記進報告、不動它**——寧可漏填不可錯填。
4. **回寫 properties**（`pages.update`，走 `retry_with_backoff` + `NotionRateLimiter`）：
   - `來源劃線ID` ← `_card_source_id(card)`（讓未來增量去重對既有卡生效——這是回填最重要的產出）
   - `品質分數` ← 重審後分數（僅 > 0 時寫）
   - `狀態` ← `_status_name(card)`
   - `Key Word` ← 重切後 tags 以「、」join
   - `Tags` ← `categories`（若 Phase 1 E3 的批次分類已跑過該 JSON；沒有就跳過此欄）
5. **報告**：`--dry-run` 印比對報告（每本書：JSON N 張／認到 M 張／落單清單）不寫入；
   正式跑完印總結（更新張數、跳過張數、失敗清單）。

CLI：`--book <名稱>`、`--dry-run`、`--dir`（預設 `cards_output`）。

### Phase 5 驗收

- `--dry-run` 全量報告：認卡率合理（預期多數能以標題認到；落單的列清單給使用者手動處理）。
- 正式跑後抽查 Notion：既有卡的 來源劃線ID/品質分數/狀態/Key Word 已填；
  board view 按 Tags 分組不再全堆「無分組」（若 Tags 也回填）。
- 對某本已回填的書重跑 `python main.py` → 不重複建卡（增量去重生效）。

---

## Phase 6：分享貼文投影層（P）

> 素材全部來自 `cards_output/*.json`，**不動同步管線**。
> 新增 `tools/generate_posts.py` + `src/infrastructure/notion/book_page_publisher.py`。

### 共用底座

- `BookPagePublisher`（新的小 repository）：負責把貼文 blocks append 到 Books DB
  （Personal Reading List）書籍頁面。複用 `NotionRateLimiter` + `retry_with_backoff`；
  書籍頁解析複用 E4 的書名比對。
- 頁面結構：書頁下統一一個 **toggle heading「📣 分享草稿」**（不存在就建立；判斷方式：
  `blocks.children.list` 找同名 toggle heading）；每次執行在其下 append 一個帶日期＋型態的
  子 toggle（例：`2026-07-06 金句卡`），內容放貼文段落。**append-only，不覆蓋不刪除**。
- 書頁找不到時：貼文落地 `posts_output/<書名>_<型態>_<日期>.md`（目錄加進 `.gitignore`）+ log warning。
- 貼文生成用 `_ollama_generate()`（Phase 3 的 helper）。

### P1 金句卡

- 每本書挑品質分數最高的 1–3 張卡（需 Phase 3 重審後分數才有區分度；分數全 0 時 fallback
  用 `CardSelectionAlgorithm._calculate_score` 對 source_highlight 重算排序）。
- prompt：輸入卡片標題+內容+原文劃線+書名，要求輸出短貼文：原文金句（≤50 字節錄）＋
  30 字以內的個人洞見＋書名標註。繁體中文、台灣用語、社群語氣（適合 Threads/IG）。

### P2 讀畢書摘

- 輸入：整本書全部卡片（標題+內容）＋讀者註記（`source_annotation` 非空的優先呈現）。
- prompt：產 300–500 字讀後貼文草稿：一段鉤子開頭、2–3 個核心觀點（可條列）、一句個人收穫結尾。

### P3 跨書主題串（最後做）

- 用重切後的 Key Word tags 聚合：找出出現在 ≥ 2 本書的概念標籤，每個概念挑 2–3 本書各 1 張卡。
- prompt：產串文草稿（3–5 則，每則 ≤ 500 字），主軸是「同一概念在不同書的不同切面」。
- 輸出位置：append 到**貢獻卡數最多**那本書的「📣 分享草稿」區，文內列出全部來源書名。

### CLI

`python tools/generate_posts.py --book <名稱> --type quote|digest|thread [--dry-run]`
- `--type` 可省略（預設 `quote`）；`--book` 對 `thread` 型態無意義（掃全庫）。
- `--dry-run`：印 markdown 到 stdout，不上傳 Notion。

### Phase 6 驗收

- `--dry-run` 三種型態各跑一次，輸出可讀。
- `--book <一本在 Books DB 的書> --type quote` 正式跑 → 該書頁出現「📣 分享草稿」toggle
  與日期子 toggle；重跑一次 → 多一個子 toggle，不覆蓋。
- 挑一本不在 Books DB 的書 → 落地 `posts_output/*.md`。

---

## 文件同步（隨各 Phase 的 commit 一起）

- `NOTION_OUTPUT_IMPROVEMENTS.md`：E1–E5（Phase 1）、B 項（Phase 4 K3）進度打勾；
  A 節（劃線頁改版）**不在本計畫範圍**，維持未勾。
- `ZETTELKASTEN_IMPROVEMENTS.md`：補記「審核層已 Gemma 化」「既有卡已回填」。
- 本文件：各 Phase 完成時把「總進度」打勾。
- `CLAUDE.md`：新增 `tools/` 目錄說明、審核後端說明、新 env 變數。
- `.env.example` 新 env：`ZETTELKASTEN_REVIEWER`、`OLLAMA_REVIEW_MODEL`、
  `OLLAMA_REVIEW_TIMEOUT_SECONDS`、`ZETTELKASTEN_TAG_CATEGORIES`。

## Commit 規範

沿用專案 gitmoji 風格，每 Phase 一個 commit（工具與其煙霧驗證同 commit）：

1. `✨ feat: 卡片盒 schema 對齊（E1-E5：自動建欄/Key Word/Tags 分類/來源反查/dedup 兜底）`
2. `🐛 fix: 標籤分隔符解析修復 + 既有卡片 JSON 重切工具`
3. `✨ feat: 審核層 Gemma 化（Ollama reviewer + 移除假分數 + 重審 CLI）`
4. `✨ feat: 知識抽取精練（主張式標題/延伸段/註記上卡/章節消毒）`
5. `✨ feat: 既有 Notion 卡片回填工具（來源劃線ID/分數/狀態/Key Word）`
6. `✨ feat: 分享貼文投影層（金句卡/讀畢書摘/跨書主題串 → Personal Reading List）`

## 全域注意事項

- **無測試框架**：驗證用 `python -c` 煙霧測試 + 工具 `--dry-run` + 真實 Notion 端對端
  （`tests/` 是修過的舊測試，與本計畫改動面重疊不大，改完跑一次確認沒弄壞即可）。
- 所有 Notion 寫入走 `retry_with_backoff` + `NotionRateLimiter`（~3 req/s）。
- 所有 rich_text 寫入截 2000 字（`_RICH_TEXT_LIMIT`）。
- `ZettelkastenCard` 每加一個欄位，`to_dict`/`from_dict` 都要同步，且 `from_dict` 必須對
  舊 JSON（缺該欄位）向後相容。
- 需要真實環境的步驟（端對端、重審、回填、貼文上傳）需要 Ollama 啟動與 `.env` 配置，
  執行前先確認（`check_ollama_availability()`），不可用時明確報錯而非默默跳過。
- 全量重審/回填屬長時間操作，先 `--dry-run` 或單書驗證，再由使用者決定何時全量跑。
