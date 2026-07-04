# Zettelkasten / 劃線知識管理改善計畫

> ⏭️ 後續計畫：Notion 輸出結構 review 後的修正（Tags/Key Word/來源 relation、劃線頁改版等）
> 記錄在 [`NOTION_OUTPUT_IMPROVEMENTS.md`](NOTION_OUTPUT_IMPROVEMENTS.md)。

> 記錄日期：2026-07-04
> 背景：Zettelkasten 卡片產生已從 legacy 移植到 `src/`（`GenerateBookCardsUseCase` + `ZettelkastenCardRepository`），
> 本文件記錄後續讓「匯出後的劃線內容」更好管理的改善方向，按優先順序排列。

## 實作進度（2026-07-04）

- ✅ #1 Annotation 匯出 — Highlight/SQL/Notion callout/選卡評分/prompt
- ✅ #2 劃線粒度去重 — BookmarkID → `來源劃線ID` 屬性，續傳 + 增量
- ✅ #3-1 主題標籤 — LLM 產 `【標籤】`，寫入 `主題` multi_select
- ✅ #4 品質分數/狀態寫回 — `品質分數`/`狀態` 屬性 + 修改說明 toggle + schema guard
- ✅ #5 產卡本地留存 — `CardStore` JSON 落地 + 上傳失敗續傳
- ⬜ #3-2 / #3-3 卡片間橫向連結（同批 / 跨書 embedding）— 未做
- ✅ #6 文件同步更新 — CLAUDE.md / .env.example

---

## 1. 匯出 Kobo 個人註記（Annotation）— 最高優先

**現況**：Kobo `Bookmark` 表除了 `Text`（劃線）之外還有 `Annotation` 欄位（讀者在閱讀器上手寫的筆記），
目前整個專案沒有任何地方讀取它（`kobo_sqlite_repository.py`、`legacy/DBReader.py` 都沒有）。

**問題**：
- 使用者自己寫的想法沒有匯出到 Notion——這比劃線本身更接近「永久筆記」。
- 選卡演算法（`zettelkasten_generator.py` 的 `CardSelectionAlgorithm._calculate_score`）
  只靠關鍵字清單與長度評分，但「使用者有寫註記的劃線」才是最強的重要性訊號。

**實作方向**：
1. `Highlight` entity 加 `annotation: Optional[str]` 欄位。
2. `KoboSqliteRepository` 的 SQL 加選 `Annotation` 欄位。
3. Notion 上傳時：有註記的劃線在 quote block 後面附一個 callout（💭 我的註記）。
4. 選卡評分：有 annotation 的劃線加重權重（例如 +5 分）或直接保證入選；
   annotation 內容一併餵給 LLM 當產卡 context。

---

## 2. 卡片去重改為「劃線粒度」— 修正資料遺漏

**現況**：`ZettelkastenCardRepository._has_existing_cards()` 只查「這本書是否已有任何卡片」，
有就整本略過（`zettelkasten_card_repository.py:56`）。

**問題**：
- 部分上傳失敗（16 張傳到第 5 張斷線）→ 下次同步整本被跳過，剩下的卡永遠不會補上。
- 重讀書籍新增的劃線，也因整本略過而永遠不會產新卡。

**實作方向**：
1. 卡片頁面加一個 rich_text 屬性（如 `來源劃線ID`）存 Kobo `BookmarkID`，
   或退而求其次存劃線文字的 hash（如 sha1 前 12 碼）。
2. 去重查詢改成：撈出該書既有卡片的來源劃線 ID 集合，只為「還沒有卡片的劃線」產卡。
3. `Highlight` entity 需要帶出 `BookmarkID`（目前 SQL 有 `BookmarkID` 可用）。
4. 這同時解決「斷點續傳」與「增量同步」兩個問題。

---

## 3. 卡片之間的橫向連結 — Zettelkasten 的核心

**現況**：每張卡只有「來源 → 書」relation，卡與卡之間完全孤立。

**問題**：卡片盒方法的價值在跨書、跨主題的橫向連結；目前的卡片盒只是「按書分類的摘要」。

**實作方向（由低成本到高成本）**：
1. **主題標籤（先做這個）**：卡片盒 DB 加 multi_select「主題」屬性；
   產卡 prompt 讓 LLM 順便輸出 2–3 個概念標籤（`【標籤】` 段），
   `_build_properties` 寫入。這是讓卡片盒能以「概念」瀏覽的最低成本起點。
2. **同批連結**：卡片盒 DB 加 self-relation「相關卡片」；同一本書產卡完成後，
   多一次 LLM 呼叫，把 N 張卡的標題+內容丟進去，請它提議卡片間的關聯 pairs，再回寫 relation。
3. **跨書連結（長期）**：對既有卡片建 embedding index（可用本地 Ollama embedding model），
   新卡產生時找 top-k 相似卡片提議連結。需要本地儲存 embedding（sqlite 即可）。

---

## 4. 品質資訊寫回 Notion

**現況**：Gemini 審稿產生的 `quality_score`、`revision_notes` 只留在 log，
`_build_properties()` 沒寫進 Notion 頁面。

**實作方向**：
1. 卡片盒 DB 加 number 屬性「品質分數」+ select 屬性「狀態」（草稿 / 已審 / 永久筆記）。
2. `_build_properties` 寫入分數；狀態預設「草稿」（Gemini 審過且 >= threshold 可設「已審」）。
3. `revision_notes` 非空時附加為頁面底部的 toggle block。
4. 使用者即可在 Notion 篩出低分卡片手動改寫——對應「文獻筆記 → 永久筆記」的加工流程。

---

## 5. 產卡結果本地留存（可重試 / 產卡歷史）

**現況**：卡片只存在記憶體，上傳失敗就得重跑 LLM，且重跑結果不一致。
`ZettelkastenCard.to_dict()` 已寫好但沒人用。

**實作方向**：
1. `GenerateBookCardsUseCase.execute()` 在上傳前先把 cards 落地：
   `cards_output/<book_title>_<date>.json`（用 `to_dict()`）。
2. 上傳流程支援從 JSON 恢復：偵測到既有未完成的 JSON（可加 `uploaded: bool` 欄位）先續傳再產新卡。
3. 目錄加進 `.gitignore`。

---

## 6. 文件同步更新

**現況**：CLAUDE.md 還寫「Zettelkasten path is duplicated work waiting to be ported」，
但移植已動工（`generate_book_cards_use_case.py`、`zettelkasten_card_repository.py`）。

**實作方向**（隨本批改動 commit 一起做）：
1. 更新 CLAUDE.md 架構圖，加入新 use case 與 repository。
2. Configuration Requirements 補上：`ENABLE_ZETTELKASTEN_CARDS`、
   `NOTION_ZETTELKASTEN_DATABASE_ID`、`NOTION_BOOKS_DATABASE_ID`、
   `ZETTELKASTEN_MIN_HIGHLIGHTS`、`ZETTELKASTEN_MAX_CARDS`。
3. Known Cleanup Debt 的 Zettelkasten 條目改為「已移植，legacy 版待退役」。

---

## 建議執行順序

| 順位 | 項目 | 理由 |
|------|------|------|
| 1 | #1 Annotation 匯出 | 資料層面的根本遺漏，影響所有下游功能 |
| 2 | #2 劃線粒度去重 | 會默默丟資料的正確性問題 |
| 3 | #3-1 主題標籤 | 最少力氣讓卡片盒變成跨書知識庫 |
| 4 | #4 品質分數寫回 | 小改動，打通人工加工流程 |
| 5 | #5 本地留存 | 提升可靠性與可重試性 |
| 6 | #3-2/3-3 卡片連結 | 價值高但成本也高，放最後 |

（#6 文件更新不排序，隨當前未 commit 的改動一起進版。）
