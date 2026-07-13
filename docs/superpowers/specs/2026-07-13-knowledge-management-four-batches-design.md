# 知識管理四批改善設計（劃線層 → 審核真實化 → 知識品質 → 連結性）

> 記錄日期：2026-07-13
> 背景：以「知識筆記管理與書籍劃線內容」為題全面檢視現有缺點，與使用者逐項討論後定案。
> 本設計整合三份既有計畫的剩餘項目（`ZETTELKASTEN_IMPROVEMENTS.md` #3-2/#3-3、
> `NOTION_OUTPUT_IMPROVEMENTS.md` A/B/D 項、`KNOWLEDGE_REFINEMENT_PLAN.md` Phase 2–4）
> 並新增本次定案的決策。四批依序執行，**每批獨立 feature branch + commit**，
> 每批完成即更新相關計畫文件進度與 CLAUDE.md。

## 已查證的資料事實（2026-07-13 實測 KoboReader.sqlite，開發時不需重查）

- 劃線共 2181 筆（Type=`highlight`），**最長僅 278 字**——超過 Notion 2000 字上限的劃線不存在。
- `dogear` 23 筆、`markup` 107 筆，**Text 全部為空**；`highlight` 全部非空。
- `Hidden` 為 true 的資料 0 筆。
- 程式碼現況：`zettelkasten_generator.py` 有 7 處 `quality_score = 7` 假分數 fallback；
  劃線頁無 quote/toggle/截斷保護（A 項未做）；`Bookmark.Type` 未過濾。

## 使用者本次定案的決策（不要再問）

1. **執行順序**：劃線層（誠實性＋閱讀體驗合併，一次 RESYNC）→ 審核真實化 → 知識品質 → 連結性。
2. **超長劃線**：不做複雜拆分。只加防禦性 helper：單段 rich_text 超 2000 字時切成
   同一 block 內多段 rich_text（視覺無縫、零資料遺失）。理由：實測資料不存在此情況，純保險。
3. **劃線頁版面**：**兩層巢狀 toggle**——章 toggle → 小節 toggle → 劃線 quote。
4. **舊卡處理**：先重審（第 2 批）取得真實分數，**低於門檻的卡才用新規格重產**並更新
   Notion 頁面；高分舊卡保留不動（不覆蓋可能的手動編輯）。
5. **橫向連結作法**：**Embedding 一步到位**（取代原 #3-2/#3-3 兩段式）——同書連結
   增量價值低（已被「來源」relation 分組），直接做跨書 embedding 相似度。

---

## 第 1 批：劃線層一次到位

> Branch：`feat/highlight-page-v2`。
> 改動檔案：`src/infrastructure/persistence/kobo_sqlite_repository.py`、
> `src/infrastructure/persistence/toc_chapter_resolver.py`、
> `src/infrastructure/notion/notion_api_repository.py`、相關單元測試。

### 1-1 資料純度過濾

- `_HIGHLIGHT_QUERY` 加 `AND Bookmark.Type = 'highlight'`；加 `Hidden` 排除條件
  （實測 0 筆，純保險；注意 Kobo 的 Hidden 欄可能是字串 `'true'`/`'false'`）。
- 效果：130 筆空白劃線不再混入 Notion 頁面，也不再灌水 `ZETTELKASTEN_MIN_HIGHLIGHTS` 計數。

### 1-2 rich_text 防禦性拆段

- 新 helper：文字超 2000 字時切成多段 rich_text（每段 ≤ 2000）放同一 block 的
  `rich_text` 陣列（Notion 單 block 上限 100 段，足夠）。
- 所有劃線/註記/標題文字寫入點統一走此 helper，消滅「單段過長 → 整批 append 失敗 →
  該章默默丟失且 Exported=true 後永不重傳」的故障類別。

### 1-3 劃線頁改版（兩層巢狀 toggle）

- 結構：章 toggle heading → 小節 toggle heading → 劃線 `quote` block；
  有註記（Annotation）時 💭 callout 作為該 quote 的 child（縮排從屬）。
- 只有章、無小節的劃線放章 toggle 直下；無 TOC 的書（fallback 路徑）維持單層。
- 頁首 `# Highlights` 改為「📌 劃線筆記」。
- Notion API 限制：單一 append 請求巢狀最多兩層、單 block children 上限 100——
  小節 children 超過 ~90 blocks 時拆「(續)」toggle；章層超量用後續
  `blocks.children.append`（對既有 block id）補掛。批次切割邏輯以 toggle 為單位，
  不得把一個 toggle 的 children 拆到兩個 request。

### 1-4 TocChapterResolver 結構化輸出

- 現況輸出合併字串「章 › 小節」；改為同時暴露結構化層級（章, 小節）供版面組裝。
  既有合併字串保留給 fallback／卡片章節參照等文字用途，避免大改下游。
- domain 純邏輯，附單元測試。

### 1-5 RESYNC 對齊與全庫重建

- `RESYNC_HIGHLIGHTS` 的同步 block 刪除清單補上新型別（toggle heading、quote）。
- 本批完成驗證後執行 `RESYNC_HIGHLIGHTS=all python main.py` 全庫重建一次
  （使用者手動加的 paragraph 等內容依現有機制保留）。

### 驗收

- 單元測試：resolver 結構化輸出、兩層 block builder、拆段 helper、SQL 過濾。
- `DRY_RUN=true` 全流程通過；挑一本多層 TOC 的書實跑，Notion 上目視：
  兩層收合、劃線為 quote、💭 縮排、無空白劃線。
- 全庫 RESYNC 後抽查 3 本書（含一本無 TOC 的 sideload）。

---

## 第 2 批：審核真實化

> Branch：`feat/real-review`。
> 規格沿用 `KNOWLEDGE_REFINEMENT_PLAN.md` Phase 3（R1/R2/R3），已核准，此處只記差異與提醒：

- R1 `OllamaReviewer` 的請求**必須帶 `think: false`**（gemma4:e4b 陷阱，同 Tags 分類的教訓；
  400 時自動退回不帶參數重試）。
- R2 刪除全部 7 處 `quality_score = 7`；未審核 = 0 分 = 「草稿」。
- R3 `tools/rereview_cards.py` 重審 230 張舊卡：先 `--dry-run` 看分數分布，
  全量跑為長時操作，由使用者決定時點（需 Ollama 啟動）。R3 只更新本地 JSON。
- 回寫 Notion 走既有 `backfill_zettelkasten.py`：擴充它回填「品質分數」「狀態」兩欄
  （認卡機制沿用其現有實作），重審完跑一次。

### 驗收

- 煙霧測試三種輸出格式解析（thinking 前綴／code fence／純 JSON）。
- 單書 dry-run 分數有區分度（不再全 7）；全量重審後 Notion 分數欄為真實值。

---

## 第 3 批：知識品質

> Branch：`feat/card-quality`。
> 規格沿用 `KNOWLEDGE_REFINEMENT_PLAN.md` Phase 2（T1/T2 標籤重切）與 Phase 4
> （K1 主張式標題／K2 延伸段／K3 註記上卡／K4 章節消毒），已核准。新增：

### 3-1 低分舊卡重產（本次新定案）

- 前置：第 2 批重審完成、真實分數已回寫。
- 新工具 `tools/regenerate_low_cards.py`：對 `quality_score` 低於門檻
  （沿用 `GEMINI_REVIEW_THRESHOLD`，預設 6）的舊卡，以來源劃線為輸入用新 prompt 重產，
  **透過 `來源劃線ID` 認卡**（backfill 已填妥，比標題比對可靠）更新 Notion 頁面
  properties 與內文 blocks；高分卡不動。
- CLI：`--book`、`--dry-run`（印「將重產清單」）、進度 log `i/N`。
- 更新後同步寫回 `cards_output/*.json`（維持 `from_dict` 向後相容欄位慣例）。

### 驗收

- Phase 2/4 各自驗收沿用原計畫。
- 重產工具：dry-run 清單合理；單書實跑後 Notion 卡片標題為主張句、有 💡 延伸 callout、
  💭 註記 callout、📖 無污染章名；高分卡未被觸碰（spot check）。

---

## 第 4 批：連結性

> Branch：`feat/card-linking`。
> 取代 `ZETTELKASTEN_IMPROVEMENTS.md` #3-2/#3-3 的兩段式規劃。

### 4-1 Embedding 索引與「相關卡片」self-relation

- Embedding 後端：Ollama 本地 embedding model，預設 **`bge-m3`**（中文表現佳），
  env `OLLAMA_EMBEDDING_MODEL` 可覆寫；沿用 REST 直打、無新 SDK 依賴。
- 索引儲存：本地 sqlite 檔（如 `card_embeddings.sqlite`，gitignored），
  記 `來源劃線ID`、Notion page_id、embedding 向量、模型名、內容 hash
  （內容變更時重算）。
- 相似度：cosine；每張卡取 top-k（k=3）且相似度 ≥ 門檻才建立連結。門檻 env
  `CARD_LINK_MIN_SIMILARITY`，預設 `0.75`；`build_card_links.py --dry-run` 會印
  相似度分布，供使用者據實際資料調整後再正式跑。
- Notion 寫入：卡片盒 self-relation 欄「相關卡片」（`_ensure_schema` 自動建欄，
  single_property 自關聯）；關聯雙向回寫（A 連 B 時 B 也補 A）。
- 全量建索引工具 `tools/build_card_links.py`（`--dry-run` 印連結預覽）；
  新卡上傳成功後增量：算 embedding → 查 top-k → 寫 relation → 更新索引。
- 產卡流程在 Ollama 不可用時明確報錯跳過連結步驟（不默默失敗）。

### 4-2 劃線頁 ↔ 卡片盒互連（D 項，沿用原規格）

- 上傳卡片成功且本次有新卡時，劃線頁尾 append callout：
  「🗃️ 本書已產生 N 張知識卡片」+ 卡片盒 DB URL。0 新卡不 append。

### 驗收

- 煙霧測試：cosine/top-k 純函式、索引存取。
- `tools/build_card_links.py --dry-run` 連結預覽人工抽查語意合理（跨書連結出現）；
  正式跑後 Notion 卡片頁「相關卡片」雙向可點；重跑不重複建關聯（冪等）。
- 新書產卡後劃線頁尾出現 🗃️ callout。

---

## 全域注意事項

- 每批遵守 DoD：feature branch、domain 改動附單元測試、`DRY_RUN` 驗證、
  真實跑通至少一本書、gitmoji commit。
- 所有 Notion 寫入走 `retry_with_backoff` + `NotionRateLimiter`；rich_text 一律過拆段 helper。
- `ZettelkastenCard` 新欄位維持 `to_dict`/`from_dict` 同步＋`.get` 向後相容。
- 文件生命週期：各批完成時勾稽三份計畫文件進度；全部完成後把三份計畫的定案濃縮進
  `docs/DECISIONS.md`，過期計畫文件歸檔或刪除。
