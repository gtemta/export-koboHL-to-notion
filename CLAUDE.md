# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Primary entry (clean architecture)
- **Sync to Notion**: `python main.py`
- **Rebuild existing pages**: `RESYNC_HIGHLIGHTS=書名子字串 python main.py`（或 `all`）—
  已匯出書籍刪除同步產生的 block（heading_1/bullet/callout/divider）後以最新章節結構
  重建；使用者手動加的內容（paragraph 等）保留。可先搭 `DRY_RUN=true` 預覽。
- **Complete Reading List pages**: `READING_LIST_PAGES=書名子字串 python main.py`（或 `all`）—
  只處理同步自動建立的 📚 Personal Reading List 頁：空白頁寫入「心得摘錄」六段版面、書封、
  本書卡片 gallery、書籍種類；只補空白的段落與屬性，重跑冪等。可先搭 `DRY_RUN=true` 預覽。

### Legacy / specialized entries
- **Zettelkasten flow**: `python -m legacy.uploadToNotion`
- **USB auto-sync**: `python checkUSBandUpload.py` (delegates to `main.main()`)
- **Card backfill**: `python backfill_zettelkasten.py` — one-shot repair for 卡片盒
  cards missing 來源/Tags (resolves books via 來源劃線ID → KoboReader.sqlite /
  cards_output JSON, auto-creates Reading List pages, re-runs Tags classification).
  Supports `DRY_RUN=true`.

### Maintenance tools (`tools/`)
- **Re-split glued tags**: `python tools/fix_card_tags.py --dry-run`（預覽「原標籤 →
  新標籤」）／不帶 `--dry-run` 正式寫回。掃 `cards_output/*.json`（`--dir` 可換），
  用 `_split_tags` 重切每張卡的 `tags`，其餘欄位一字不動；原子寫檔、重跑冪等。
  只改本地 JSON——Notion 上既有卡片的 `Key Word` 要靠 backfill 才會更新。
- **Backfill card visuals**: `python tools/backfill_card_visuals.py --dry-run`（預覽
  「卡片 → cover/icon」）／不帶 `--dry-run` 正式寫回。為卡片盒既有卡片補上 cover
  （依 Tags 純規則）、page icon（標題＋Key Word 批次送 Ollama 挑 emoji）與
  `加工狀態=🌱未加工`。**已有值一律不覆蓋** → 重跑冪等，也不會蓋掉手動換過的圖。
  Ollama 不可用時只補 cover，icon 留待下次重跑。**順序要求**：若卡片盒裡還有
  卡片缺 來源/Tags，先跑 `backfill_zettelkasten.py` 補齊分類，**再**跑這支工具
  ——cover 依 Tags 挑色且已有 cover 不覆蓋，若順序反過來，沒 Tags 的卡先拿到
  預設米色 cover，之後 Tags 補上了也不會回頭補色（不寫覆蓋邏輯是刻意的，避免
  蓋掉使用者手動換過的圖）。

### Quality gates
- **Lint**: `python -m ruff check .` (config in `pyproject.toml`; `legacy/` + `analysis/` excluded)
- **Tests**: `python -m pytest` (all green, no external resources needed)
- **Dry-run verify**: `DRY_RUN=true python main.py` — full flow, reads only, writes logged as `[DRY RUN]`
- CI (`.github/workflows/ci.yml`) runs ruff + pytest on every push/PR.

## Engineering Standards（開發基礎規範）

所有開發（人或 AI agent）必須遵守本節。守門靠自動化與文件，不靠模型的聰明程度或當下記憶。

### 1. 硬基礎（一次性建設，已完成 2026-07-07）

- [x] `pyproject.toml` 集中工具設定：`ruff`（lint）＋ `pytest`。（`src/domain/` 型別檢查可日後漸進加上。）
- [x] 依賴鎖定：`requirements.txt`（執行）＋ `requirements-dev.txt`（pytest、ruff）。Ollama 用 `requests` 直打 REST，無額外 SDK 依賴。
- [x] GitHub Actions 最小 CI：`ruff check` ＋ `pytest tests`（`.github/workflows/ci.yml`）。
- **不准留「已知是壞的」測試**：壞掉的測試要嘛修、要嘛刪。紅燈常駐會讓人和 AI 都學會忽略紅燈，比沒測試更糟。
- 秘密與資料檔邊界：`.env`、`KoboReader.sqlite`、`cards_output/`、`logs/` 永不進版控；`.env.example` 是唯一進版控的設定樣板。

### 2. Definition of Done（每次改動，四條同時滿足才算完成）

1. **分支開工**：`main` 永遠可跑，改動走 feature branch。
2. **domain 層改動必附單元測試**；infrastructure 層（Notion API）不強求測試，但改動需可用 dry-run 驗證：`DRY_RUN=true python main.py` 讀取照常、寫入只印 log（`DryRunNotionRepository`），卡片流程整個跳過（避免打 Ollama 及汙染 `cards_output/` 續傳狀態）。
3. **跑過真實流程再收工**：不是「測試過了」，而是 `python main.py` 對至少一本書實際跑通、在 Notion 上看到預期結果。
4. **Commit 慣例**：gitmoji + type（維持現有風格），一個 commit 一個意圖。

### 3. Loop Engineer 規範（與 AI 協作的迭代紀律)

1. **一圈一意圖**：每個 session 只推進一件事。任務必須有可驗證的結束條件（「上傳後 Notion 欄位 X 有值」），沒有結束條件的任務不開工。
2. **以觀察收尾，不以宣稱收尾**：AI 說「完成了」不算數；每圈結束前必須有可觀察證據 — 測試輸出、實際執行 log、Notion 上的真實頁面。
3. **每圈更新地圖**：架構或慣例改變時，同一圈內更新 CLAUDE.md，不留到「之後整理」。CLAUDE.md 是下一個 session 的全部世界觀，過期等於下一圈從錯誤地圖出發。
4. **計畫文件有生命週期**：`docs/*_PLAN.md` 執行完 48 小時內，有價值的決策濃縮進 CLAUDE.md 或 `docs/DECISIONS.md`（輕量 ADR：日期／決定了什麼／為什麼），其餘刪除。一次性 SUMMARY 文件同樣適用——過期文件會污染未來 AI 的檢索。
5. **技術債登記制**：新增債務必登記在下方 Known Cleanup Debt；每完成幾個功能就消一筆。債只進不出，AI 每次修改的成本會單調上升。
6. **換模型不換規範**：所有規則活在 repo 裡（本節、pyproject、CI、DECISIONS.md），不活在任何模型的記憶或單次對話裡。規範的目標是讓較弱的模型也能安全做事。

## Project Architecture

Kobo e-reader highlight sync to Notion databases. The codebase was refactored from a monolithic Python script into clean architecture. Monolithic files remain in `legacy/` for features not yet ported (Zettelkasten card generation, USB automation).

### Layered structure (`src/`)

```
src/
├── config/settings.py                   — Settings.from_env() loads .env
├── domain/                              — Pure: no IO, no external deps
│   ├── entities/                        — Book, Chapter, Highlight, BookCard dataclasses
│   ├── repositories/                    — BookRepository, NotionRepository (ABCs)
│   ├── services/chapter_extractor.py    — Strategy-based chapter name fallback
│   └── services/reading_list_rules.py   — 卡片 Tags 多數決 → 書籍種類（純函式）
├── application/
│   ├── use_cases/sync_books_use_case.py — SyncBooksUseCase.execute()
│   ├── use_cases/generate_book_cards_use_case.py — Zettelkasten card post-sync step
│   ├── use_cases/complete_reading_list_page_use_case.py — Reading List 書頁補完（M1）
│   └── dtos/sync_result.py
└── infrastructure/                      — Adapters for external systems
    ├── persistence/
    │   ├── kobo_sqlite_repository.py    — implements BookRepository
    │   ├── toc_chapter_resolver.py      — deterministic chapter mapping from Kobo TOC
    │   ├── chapter_title_heuristics.py  — regex title guessing (fallback only)
    │   ├── highlight_organizer.py       — progress-based grouping (fallback only)
    │   └── card_store.py                — local JSON persistence / resume for cards
    ├── notion/
    │   ├── notion_api_repository.py     — implements NotionRepository (API orchestration)
    │   ├── highlight_page_blocks.py     — pure block builders: 劃線頁 v2 兩層 toggle 版面
    │   ├── dry_run_notion_repository.py — DRY_RUN decorator: reads delegate, writes log-only
    │   ├── zettelkasten_card_repository.py — uploads cards to 卡片盒 DB (per-highlight dedup;
    │   │                                     刻意不寫任何審核痕跡，見「卡片審核閘門」)
    │   ├── reading_list_repository.py   — Books DB：來源解析／自動建頁＋書頁讀寫
    │   ├── reading_list_page_blocks.py  — pure block builders: Reading List 書頁六段版面、段落定位
    │   ├── notion_views_client.py       — 唯一使用新版 API（2026-03-11）：建卡片 gallery
    │   ├── dry_run_reading_list_repository.py — 書頁補完的 DRY_RUN decorator
    │   ├── text_utils.py                — clean_html
    │   ├── rate_limiter.py              — thread-safe ~3 req/s limiter
    │   └── retry_policy.py              — 409/429/404 exponential backoff
    ├── external/cover_fetcher.py        — CoverFinder：Kobo 圖床 → Google Books → Open Library，逐張驗證
    └── container.py                     — composition root (build_use_case)
```

Card generation (`zettelkasten_generator.py`, still at project root) is wired in as
an optional post-sync step: `GenerateBookCardsUseCase` bridges `Highlight` entities
to the generator, persists the batch via `CardStore`, then uploads through
`ZettelkastenCardRepository`. Enabled by `ENABLE_ZETTELKASTEN_CARDS=true`.

### 卡片審核閘門（2026-07-28）

產卡與上傳之間有一道**地端交叉審核**：產卡用 `OLLAMA_MODEL`，審核用
**另一個**模型 `OLLAMA_REVIEW_MODEL`（預設 `qwen3:8b`）——同一個模型改自己的考卷
只會重新發現自己的盲點。實作全在 `zettelkasten_generator.py`（`CardReview`、
`CardReviewer`、`GenerationResult`、`generate_cards_with_review`）。

- **兩階段**：先 `summarize_book()` 一次呼叫抽出全書主軸，再逐卡 `review()`，
  把「原文劃線＋卡片＋全書主軸＋同書其他卡標題」一起送審。全書脈絡是為了讓
  `一致性` 能判斷離題與重複，不只是卡內矛盾。
- **四面向各 1–5 分**（`consistency`/`correctness`/`shareability`/`atomicity`），
  **全部 ≥ `ZETTELKASTEN_REVIEW_MIN_SCORE`（預設 4）才通過**——不用平均，否則
  「寫得漂亮但塞了三個概念」會被高分項救回來。
- **沒過**：帶審核意見（`revision_hint`）重產一次，再不過就丟棄，不上傳。
- **審核不可用**（Ollama 沒開／模型沒 pull／回應解析不出 JSON）→ 該本書
  **一張卡都不上傳**，log ERROR。`CardReviewer.is_available()` 會檢查模型是否
  真的 pull 過，才能區分「服務沒開」與「模型沒下載」。
- **Notion 不留任何審核痕跡**：沒有品質分數欄、沒有狀態欄、沒有審稿 toggle。
  分數只在 `cards_output/*.json`（`review_scores`/`review_status`/`review_model`/
  `regenerated`）與 log 裡。被退的卡存進同一份 JSON 的 `rejected` 頂層鍵，
  `CardStore.load_pending` 只讀 `cards`，所以續傳絕不會誤傳被退的卡。
- **並行安全**：書籍走 `ThreadPoolExecutor` 且共用同一個 generator 實例，審核狀態
  一律走參數與回傳值，不放實例屬性。
- `_ollama_generate()` 是產卡／分類／審核共用的串流 POST helper（`think: false`
  ＋ 400 退回重試、in-stream error、`done_reason=length` 空輸出警告、timeout 撿殘句）。
- **DRY_RUN 驗不到這個功能**（`container.py` 在 dry-run 一律跳過卡片流程），
  必須真跑。
- **並行與模型換入換出**：書籍走 `ThreadPoolExecutor`，A 書產卡時 B 書可能正在
  審核，兩個模型會在 Ollama 互相擠掉（實測 VRAM 只放得下一個）。真跑很慢時先看
  log 時間戳，再考慮設 `OLLAMA_MAX_LOADED_MODELS=2` 或調低 `MAX_WORKERS`。

**標籤分隔（Phase 2 T1/T2，2026-07-28）**：模型幾乎不照 prompt 用頓號，實測會用
全形冒號／破折號／中點／句號／連字號把標籤串成一整條。`_TAG_SPLIT` 因此涵蓋
全部這些分隔符，切完再修邊（去 `#`、括號、引號）、丟棄空值與 >15 字的句子、
去重。兩處 prompt 也加了負面規則。切分規則抽在
`ZettelkastenLLMEnhancer._split_tags()`，`_extract_tags` 與 `tools/fix_card_tags.py`
共用同一份，避免兩邊漂移。既有 JSON 用該工具重切（T2）；**已上傳 Notion 的卡片
`Key Word` 欄仍是舊值**，要等 backfill 才會更新。

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
  本地小模型；模型沒挑或挑了清單外的值時由關鍵字表／分類預設遞補，保證
  `main.py`／`GenerateBookCardsUseCase` 這條路徑產的卡永不空白。**這個保證不涵蓋
  `legacy/uploadToNotion.py`**：該路徑的 `ZettelkastenCardGenerator(...)` 建構時
  不帶 `tag_categories`，`generate_cards_with_review` 只在 `self.tag_categories`
  非空時才呼叫 `classify_cards`（icon 由它搭便車產生），所以 legacy 產的卡
  `icon` 全空；`sync_zettelkasten_cards()` 的 `pages.create` 也完全沒有
  `cover`/`icon`/`加工狀態` 三個 kwargs（甚至 properties 欄名都跟新 schema 不同，
  如 `Title` 而非 `標題`）。經 legacy 入口建立的卡片一律沒有 cover/icon/加工狀態，
  要靠 `tools/backfill_card_visuals.py` 事後補齊。
- **`classify_cards(..., apply_icon_fallback=False)`**：預設 `True` 時保底邏輯內建
  在 `classify_cards` 裡執行；回填工具傳 `False` 跳過它，只拿模型的原始挑選結果
  （可能是空字串），再自己對照卡片在 Notion 上**真實**的 Tags 補保底——因為
  `classify_cards` 同時會用模型當下解析出的（可能是幻覺）分類覆寫
  `card.categories`，內建保底若在那之後就地執行，吃到的會是這份幻覺分類而非
  卡片的真實分類。

### 卡片標題與章節參照（2026-08-30）

- **標題是主張句**：兩支產卡 prompt（`_build_prompt` 與 `_build_batch_prompt`）都要求
  5-20 字的獨立論斷，**兩處必須同步改**——`main.py` 實際走的是批次那支。原文只是定義或
  描述時退回精準的概念陳述句，不得自行推論；這是為了與審核 `correctness` 面向
  （禁止加入原文沒說的結論）共存，**審核 prompt 因此一字未動**。
- **章名消毒**：`_clean_chapter_reference(raw, *, from_toc)` 在**建卡當下**套用於兩個
  `chapter_reference=` 賦值點，讓 `cards_output/*.json` 落地的就是可信值（不在 Notion
  層 render 時才清——那樣 JSON 會留髒值，續傳與未來取材都會吃到）。
  `from_toc` 由 `GenerateBookCardsUseCase._to_dict()` 從
  `bool(Highlight.toc_chapter or Highlight.toc_section)` 帶入（非單純 `is not None`——
  TOC 條目標題可能是空字串，此時目錄沒給到真實章名，落回不信任），**缺鍵預設
  False**（legacy 入口走保守路線）。污染唯一來源是
  `chapter_title_heuristics.extract_real_chapter_title()`——它拿劃線正文猜章名、容忍到
  150 字；該檔案刻意未收緊，收緊它會連帶改變無 TOC 書籍的劃線頁分章。
- 章名被清成空字串時，📖 callout 仍會保留閱讀進度（守門條件是
  `chapter_reference or chapter_progress`）——進度是 Kobo 硬數據，不受章名判定連坐。

### Reading List 書頁補完（2026-09-29，M1）

設計：`docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md`。

- **只補同步建的頁**：`page.created_by.id == users.me().id` 才處理（查不到自己的身分時一律不處理）；
  使用者手動建的頁完全不碰。版面只寫在空白頁，每一段、每個屬性都只在空白時寫——重跑是 no-op，
  所以**不需要回填工具**，開啟後跑一次同步就會補完既有頁。
- **書頁由卡片流程建立**：Reading List 頁只由卡片流程（`ENABLE_ZETTELKASTEN_CARDS=true` 且劃線數
  ≥ `ZETTELKASTEN_MIN_HIGHLIGHTS`）自動建立；卡片關閉或劃線太少的新書沒有書頁，補頁步驟只記
  DEBUG 並跳過（`find_page` 永不建頁）。
- **`find_page` 如何分辨書**：先以 `Kobo EReader` relation 反查；反查不到才用書名比對，且書名
  命中的頁若已關聯到**別的**劃線頁就視為別本書、不處理（relation 空白的頁照收）。
- **流程**：`SyncBooksUseCase` 執行緒池結束後，依書名順序逐本呼叫 `CompleteReadingListPageUseCase`
  （只對 `READING_LIST_PAGES` 命中的書）。刻意不並行：M2 會用地端 LLM。單本失敗只記進錯誤清單，
  不影響 exit code。
- **版面**：六段 `heading_2`（書籍資料／筆記圖／概要／實際執行／心得／金句摘錄）一次寫入；
  卡片 gallery 用 Views API 的 `create_database.position = after_block` 插在「筆記圖」標題後。
  gallery 建失敗時段落留白，下次同步自動重試（不改放靜態清單——那會讓段落變非空白、永遠升級不了）。
- **新版 API 只在一個檔案**：`notion_views_client.py` 固定 Notion-Version `2026-03-11` 並走
  `Client.request()`；notion-client 2.2.1 的 `pages.create`／`pages.update` 會靜默丟掉不認得的參數。
- **書封**：`CoverFinder` 依序試 Kobo 圖床（`content.ImageId` → `cdn.kobo.com/book-images/…`，
  2026-09-28 實測 35/35）→ Google Books（真 ISBN-13、書名比對；`GOOGLE_BOOKS_API_KEY` 選填）→
  Open Library（`?default=false`），每張都下載驗證（200、image/*、>2 KB）。劃線頁的
  `add_book_cover` 共用它，並會重驗舊的 Open Library 網址——那批 1×1 透明圖（20/26）因此被換掉。
- **書籍種類**：卡片 Tags 多數決（每張卡對每種類一票、同票依對照表順序、第二名需達第一名一半），
  對照表為 `settings.DEFAULT_BOOK_TYPE_MAPPING`；種類庫與其 title 欄都從 Books DB schema 動態取得。
  **種類庫必須分享給 integration**：Notion API 不回傳「目標 DB 未分享給 integration」的 relation 欄；
  此時整輪只記一次 WARNING（附分享提示）並跳過書籍種類（2026-10-01 實測：「Dante 閱讀標籤分類庫」
  未分享 → 26 本都沒填）。
- **永不寫入**：`推薦分數/5`、`Status`、`Done Date`、`Blog Link`、`slug`。
- **M2（未做）**：讀完才寫的 🤖 AI 剖析。心得段原定放 Kobo 打字註記，但使用者的打字註記是 0 筆、
  手寫 markup 有 121 筆——M2 計畫前需重議。
  M2 注意：`find_section` 不看 toggle heading 內的內容、`is_blank_page` 不看 `has_children`
  ——M1 只在自己建的頁做附加寫入所以無害，M2 判斷「概要」是否空白前要先補。

### Entry point flow

`main.py` → `Settings.from_env()` → `container.build_use_case(settings)` → `SyncBooksUseCase.execute()`.

Inside the use case: for each book, check Notion → create if missing → fetch highlights (with sophisticated chapter extraction already done by the repo) → upload in batched blocks → update metadata → attach cover.

**劃線頁版面（v2, 2026-07-14）**：頁首「📌 劃線筆記」＋兩層巢狀 toggle——章
（toggle heading_1）→ 小節（toggle heading_2）→ 劃線 `quote`；💭 註記 callout 是
quote 的 child。純 block 建構在 `highlight_page_blocks.py`（rich_text >2000 字無損
拆段、小節 >90 條拆「(續)」toggle、`chapter_tree` 依 `toc_chapter/toc_section` 分組），
`NotionApiRepository.sync_book_highlights` 先 append 章 toggle 取 id、再對每章 append
巢狀 children（以 toggle 為單位切批，不拆散單一 toggle）。RESYNC 刪除清單維持頂層
heading_1/bullet/callout/divider——v2 的 quote/heading_2 巢狀在章 toggle 內隨父塊刪除，
頂層 quote/heading_2 視為使用者內容（勿加入刪除清單）。

### Legacy code (`legacy/`)

- `legacy/uploadToNotion.py` (1070 lines): original monolithic sync. Integrates with `zettelkasten_generator.py` at root. Card generation is now also available in `src/` (see below); this legacy entry is kept for its USB-automation glue.
- `legacy/DBReader.py` (662 lines): original SQLite reader. Still imported by `summarize_with_gemma.py`, `tests/`, and `analysis/` scripts — those modules haven't been migrated.

Run legacy via `python -m legacy.uploadToNotion` (the module adjusts `sys.path` to locate root-level siblings).

### Chapter Extraction Logic (Key Innovation)

**Deterministic since 2026-07-10**: KoboReader.sqlite contains each book's real TOC —
`content.ContentType=899` are TOC entries (real `Title`, `VolumeIndex` order,
`Depth` 1–4), `ContentType=9` is the spine (file reading order). See
`docs/superpowers/specs/2026-07-10-toc-chapter-extraction-design.md`.

1. **TOC resolution** (`toc_chapter_resolver.TocChapterResolver`, pure logic + unit
   tests): a bookmark's file is located in the spine; its chapter = nearest preceding
   TOC entry ("spine interval" method — handles chapters spanning multiple xhtml
   files). `resolve_parts()` returns structured `(章, 小節)` (untruncated, drives the
   two-level toggle layout via `Highlight.toc_chapter/toc_section`); `resolve()` is a
   thin wrapper returning the joined `章 › 小節` label (60-char cap, feeds
   `chapter_name` for cards/fallback). Same-file anchored entries are ambiguous only
   when the file has multiple TOC entries; then the resolver falls back to the nearest
   strictly-shallower certain entry, or chapter level.
2. **Sorting** is `(spine_position, ChapterProgress)` — ChapterProgress is per-file,
   NOT globally monotonic; sorting by it alone interleaves chapters (old bug).
3. **Fallbacks** (books without TOC data, e.g. sideloads): per-highlight
   `_initial_chapter_name` heuristics + `organize_by_progress` clustering, and the
   domain `ChapterExtractor` when a chapter name is still missing.

### Configuration Requirements

- **.env file** with:
  - `NOTION_TOKEN`: Notion integration token (required)
  - `NOTION_DATABASE_ID`: Target database identifier (required)
  - `KOBO_DB_PATH`: default `KoboReader.sqlite`
  - `MAX_WORKERS`: thread pool size, default `5`
  - `LOG_LEVEL`: default `INFO`
  - `DRY_RUN`: `true` = reads as normal, Notion writes logged only, card flow skipped (default `false`)
  - `RESYNC_HIGHLIGHTS`: empty = off; `all` or comma-separated title substrings —
    matching already-exported books get their sync-generated blocks deleted and
    highlights re-uploaded (user-added blocks preserved; page id/relations stable)
  - `READING_LIST_PAGES`: empty = off; `all` or comma-separated title substrings — complete
    sync-created 📚 Personal Reading List pages (layout, cover, card gallery, 書籍種類; only
    empty parts are written). Needs `NOTION_BOOKS_DATABASE_ID`; gallery + 書籍種類 also need
    `NOTION_ZETTELKASTEN_DATABASE_ID`.
    書籍種類 also needs the type DB (「Dante 閱讀標籤分類庫」) shared with the integration —
    the API omits relation properties whose target DB is not shared.
  - `GOOGLE_BOOKS_API_KEY`: optional; only for books without a Kobo `ImageId`.
  - Zettelkasten card generation (used by both `main.py` and the legacy path):
    - `ENABLE_ZETTELKASTEN_CARDS`: `true`/`false` (default `false`)
    - `NOTION_ZETTELKASTEN_DATABASE_ID`: target 卡片盒 database (required when enabled)
    - `NOTION_BOOKS_DATABASE_ID`: Books DB the card `來源` relation points at (optional)
    - `ZETTELKASTEN_MIN_HIGHLIGHTS` (default `10`), `ZETTELKASTEN_MAX_CARDS` (default `16`)
    - `ZETTELKASTEN_TAG_CATEGORIES`: comma-separated fixed Tags list (default in `settings.DEFAULT_TAG_CATEGORIES`). LLM classifies each card into 1-2 of these; missing options are auto-seeded into the 卡片盒 Tags column on first upload.
    - `ZETTELKASTEN_CARDS_OUTPUT_DIR`: local card JSON dir (default `cards_output`, gitignored)
    - Review gate: `OLLAMA_REVIEW_MODEL` (default `qwen3:8b`, must differ from
      `OLLAMA_MODEL`), `OLLAMA_REVIEW_TIMEOUT_SECONDS`, `ZETTELKASTEN_REVIEW_MIN_SCORE`
      (default `4`), `ZETTELKASTEN_REVIEW_MAX_REGEN` (default `1`)
    - Other Ollama vars (`OLLAMA_*`): see `.env.example`
- **KoboReader.sqlite**: Copy from Kobo device to project root (or set `KOBO_DB_PATH`)
- **Notion database** must have: Title (text), Exported (checkbox). Optional fields: Author, Publisher, Subtitle, Description, ISBN, SpendReadingTime, LastReadDate, LastFinishedReadTime, PercentageRead.
- **Notion 卡片盒 database** (when cards enabled): 標題 (title) is required. The
  repository reads the DB schema first and **auto-creates** the missing optional
  column `來源劃線ID` + seeds missing `Tags` options on the first upload
  (`_ensure_schema`). Columns written when present:
  `來源` (relation → Books DB), `Key Word` (rich_text — free concept tags, 、-joined),
  `Tags` (multi_select — fixed-category classification, only values in the allowed
  list), `來源劃線ID` (rich_text, enables per-highlight dedup). The old `主題`,
  `品質分數` and `狀態` columns are no longer written — review results stay local
  (see 卡片審核閘門). Existing columns in the user's DB are left alone, just unused.
  回訪／視覺欄位（同樣由 `_ensure_schema` 自動建立）：`加工狀態` (select：
  🌱未加工/🌿已重寫/🌳永久筆記，建卡時一律寫 🌱)、`建立日期` (created_time，值由
  Notion 自算)、`上次回顧` (date，純手動)。每張卡另有 page **cover**（依 Tags 分類
  對應 Notion 內建漸層，`card_visuals.cover_url_for`）與 page **icon**（emoji）。
  ⚠️ **gallery view 需手動把 Card preview 設為 Page cover**，色卡才會顯示 ——
  Notion API 無法修改 view 設定。
- **Notion DB 三層關係**: 卡片盒 `來源` relation → 📚 Personal Reading List (Books
  DB, title 欄叫 `Name`)，Reading List 的 `Kobo EReader` relation → Kobo highlights
  DB。書不在 Reading List 時 repository **自動建頁**（Name=完整書名、Kobo EReader
  relation、Status 依 Kobo 進度：≥99% → `🔖閱讀完畢`，否則 `📖 閱讀中`——注意
  option 名稱須與 DB 完全一致，📖 後有空格）；名稱比對命中但 relation 空時會順手
  補上，讓下次反查直接命中。
- **Tags 分類比對是 emoji-insensitive**：分類選項帶 emoji 前綴（`💞心理學`），但
  本地 LLM 幾乎不會照抄 emoji，故 prompt 給純文字名、parser 以 text core
  （只留字母/數字/CJK）比回 canonical 名稱寫入 Notion。改分類清單時維持這個約定。
  另外分類呼叫帶 `think: false`——gemma4:e4b 這類 thinking model 否則會把
  `num_predict` 全部燒在隱藏推理上（done_reason=length、輸出空字串）；400 時
  自動退回不帶參數重試。

### Key Database Schema

- **content table**: rows are typed by `ContentType`:
  - `6` = books (Title, Author, ISBN, reading progress)
  - `9` = spine — epub file reading order (`VolumeIndex`)
  - `899` = TOC entries — real chapter titles + `Depth` (used by TocChapterResolver)
- **Bookmark table**: Highlights with chapter references
  - `Text`: the highlighted content
  - `Annotation`: the reader's own handwritten note (exported as a 💭 callout)
  - `BookmarkID`: stable id used for per-highlight card dedup
  - `ContentID`: file the highlight lives in (`{book}!{prefix}!{file}`)
  - `ChapterProgress`: position within the file (per-file, not global)
  - `Type`: `highlight` / `dogear` / `markup` — currently NOT filtered (see debt)
  - Unexported extras: `DateCreated`, `Color`; also Shelf/Reviews/Event tables

### Error Handling Patterns

- Logging: `src/infrastructure/container.setup_file_and_console_logging()` configures a rotating file handler (`logs/kobo_notion_sync.log`, 2MB × 3) plus console output.
- Thread-safety: SQLite connections opened per call via context manager; Notion rate limiter uses a Lock.
- Retry: 409 conflicts and 429 rate-limits get exponential backoff in `retry_with_backoff`. Other Notion errors bubble up.
- Failure isolation: per-book failures are caught in the use case and recorded in `SyncResult.errors`; sync continues.

### Known Cleanup Debt

- `tests/` still has overlapping `test_chapter_extraction.py` at root-level and in `tests/unit/` (both green and importing `src.*` since d998391) — merge into one. `tests/integration/` is empty.
- `analysis/` contains one-shot debug scripts; candidates for deletion. (Excluded from ruff along with `legacy/`.)
- `docs/` is full of past refactor plans (REFACTOR_PLAN.md etc.) that could be archived.
- `summarize_with_gemma.py` still depends on legacy.DBReader — port or retire later.
- Zettelkasten card generation is now ported into `src/` (use case + repository +
  card store, wired in `container.build_use_case`). `zettelkasten_generator.py`
  still lives at project root and the `legacy/` copy remains for the legacy entry —
  the legacy version can be retired once no longer used.
- See `docs/ZETTELKASTEN_IMPROVEMENTS.md` for the remaining roadmap (cross-card
  linking #3-2/#3-3 not yet done).
- ~~**資料純度**~~：已解（2026-07-14，劃線頁 v2 第 1 批）——`_BOOKMARK_FILTER` 過濾
  `Bookmark.Type='highlight'` 與 `Hidden`，130 筆空白 dogear/markup 不再混入。
- **Kobo 未匯出資訊**：完整盤點見 spec `2026-09-28-reading-list-book-pages-design.md` 的附錄
  （原文書名 `Subtitle`、書系 `Series`、Kobo 讀完時間、劃線 `DateCreated` 時間戳、Wishlist…）。
  更正：`Reviews` 表是**其他讀者**的商店書評，不是使用者自己的書評。使用者的 121 筆手寫
  `markup` 目前被 `_BOOKMARK_FILTER` 當空白排除，圖檔在裝置 `.kobo/markups/`（未驗證）。
- **劃線頁重複上傳的競態（2026-10-01 真跑發現，既有問題）**：`check_book_exists` 靠
  `databases.query`，其索引對 `Exported` checkbox 可延遲約 2 分鐘；新書匯出後 2 分鐘內再跑同步，
  同一本書的劃線會被再上傳一次（實測《如何改變一個人》，已用 `RESYNC_HIGHLIGHTS` 修復）。
  修法候選：query 回報「存在但未匯出」時，先 `pages.retrieve` 確認 `Exported` 再上傳。
- **Reading List 相關重複碼**（M1 刻意保留）：文字核心正規化 helper 三份、Notion 分頁迴圈 3–4 份
  （`list_blocks`、`_query_all`、`_cards_linked_to` 等）、`_RICH_TEXT_LIMIT` 定義三次。
- **卡片流程的書名比對沒有「別本書」防護**：`ReadingListRepository.resolve_or_create` 的書名
  比對仍會接受已關聯到其他劃線頁的頁（`find_page` 已加防護，見上）；目前 35 本書名無互相包含，
  尚未發生。
- **非冪等寫入的重試**：`retry_with_backoff` 對 append blocks、`POST /views` 逾時重試，若第一次其實
  已成功會重複寫入（gallery 至多重複一次：下次同步「筆記圖」段已非空白）。
