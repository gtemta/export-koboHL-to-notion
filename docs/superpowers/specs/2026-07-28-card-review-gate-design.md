# 卡片審核閘門：地端交叉審核模型把關後才進 Notion

> 記錄日期：2026-07-28
> 分支：`feat/card-review-gate`
> 取代四批計畫的「第 2 批：審核真實化」與 `KNOWLEDGE_REFINEMENT_PLAN.md` Phase 3。

## 問題

產卡後沒有任何實質審核。唯一的審核者 `GeminiReviewer` 需要 `GEMINI_API_KEY`
（使用者沒有），所以 7 處 fallback `quality_score = 7` 讓每張卡拿到假分數直接上
Notion。實測結果：230 張卡分數一律 7、`revision_notes` 一律空字串——審核層等於
不存在。卡片可能推論出原文沒說的因果、一張卡塞兩個概念、離開原書就讀不懂、
或與同書其他卡重複。

## 決策

1. **交叉審核**：產卡用 `OLLAMA_MODEL`，審核用**另一個**地端模型
   `OLLAMA_REVIEW_MODEL`（預設 `qwen3:8b`）。同一個模型改自己的考卷只會重新
   發現自己的盲點。兩者相同時 log WARNING。
2. **四面向各 1–5 分，全部達標才過**（門檻 `ZETTELKASTEN_REVIEW_MIN_SCORE`，
   預設 4）。不用平均：一張寫得漂亮但塞了三個概念的卡，平均分會把它救回來。
   門檻定 4 而非 3，是因為 e2e 實測 qwen3:8b 對「本來就寫得不錯」的卡一律給
   5 分，3 分門檻幾乎不會擋掉任何東西。
   - `consistency` 一致性：標題↔內容↔原文不矛盾，且與全書主軸同向、不與其他卡重複
   - `correctness` 正確性：忠於原文，沒有推論出原文沒說的因果／數據／結論
   - `shareability` 分享性：離開原書脈絡也讀得懂，可單獨分享
   - `atomicity` 知識最小片段性：只講一個概念（塞兩個以上最多 2 分）
3. **兩階段審核**：`summarize_book()` 每本書一次抽出全書主軸，再逐卡 `review()`
   帶著「原文＋卡片＋全書主軸＋同書其他卡標題」送審。理由：一整本書應該有統一
   方向，`一致性` 若只看卡內就抓不到離題與重複。主軸抽取回空字串時降級為只用
   標題清單（服務仍在 → 不算審核不可用）。
4. **沒過 → 帶審核意見重產一次 → 再不過就丟棄**（`ZETTELKASTEN_REVIEW_MAX_REGEN`
   預設 1）。重產的 prompt 帶 `book_theme` 與 `revision_hint`。
5. **硬閘門**：審核模型叫不到、模型沒 pull、回應解析不出 JSON → 該本書一張卡都
   不上傳，log ERROR。「無法解析」與「低分」必須分得開：`_parse_review` 回 `None`
   代表審核失敗，缺欄位或分數越界一律視為不可信。
6. **Notion 不留任何審核痕跡**：移除「品質分數」「狀態」欄與「🔍 AI 審稿修改說明」
   toggle。閘門已經決定卡片能不能進來，DB 裡每張卡都通過了，分數欄只是雜訊。
7. **刪除 Gemini 後端**：從未跑過、無 API key、單一總分契約與四維審核不相容。

## 架構

```
generate_cards_with_review(highlights, book_title) -> GenerationResult(passed, rejected)
  1. 門檻檢查 + select_highlights
  2. reviewer.is_available()  ── 不可用 → 回空，連草稿都不產（產卡是好幾分鐘的本地推論）
  3. enhancer.batch_generate  ── 草稿
  4. reviewer.summarize_book  ── 全書主軸
  5. 逐卡 reviewer.review     ── 過 → passed；不過 → 帶 notes 重產 → 再審 → 仍不過 → rejected
  6. enhancer.classify_cards  ── 只對 passed
```

- `generate_cards()` 保留為 thin wrapper 回 `.passed`（legacy entry 仍在用）。
- **並行安全**：書籍走 `ThreadPoolExecutor(max_workers=5)` 且共用同一個 generator
  實例，所以審核狀態一律走參數與回傳值，不放實例屬性。
- `enhancer` / `reviewer` 改為可注入，讓閘門編排能在沒有 Ollama 的情況下被測試。
- **卡片→劃線的反查**用 `bookmark_id`（`batch_generate` 會丟掉解析失敗的卡，
  位置索引對不上），退回以 `source_highlight` 文字比對。

### 共用 helper

`_ollama_generate()` 收攏產卡／分類／審核三處重複的串流 POST：`think: false`
＋ 400 退回重試、in-stream `error` chunk、`done_reason=length` 空輸出警告、
timeout 撿殘句（`salvage_partial`，只給解析器能安全處理截斷輸出的呼叫端——
產卡路徑不撿，否則 `_parse_response` 的 fallback 會用原文捏造一張假卡）。

### 資料落地

`ZettelkastenCard` 新增 `review_status`／`review_scores`／`review_notes`／
`review_model`／`regenerated`，移除 `quality_score`／`revision_notes`。
`CardStore.save(book_title, cards, rejected)` 把被退的卡寫進同一份 JSON 的
`rejected` 頂層鍵；`load_pending` 只讀 `cards`，續傳絕不會誤傳被退的卡。
續傳路徑**不再過閘門**（留存的卡當初就通過了，否則 Ollama 沒開時已付出代價的
卡就永遠傳不出去）。

## 驗證結果

- `python -m ruff check .` 通過；`python -m pytest` 185 passed / 4 skipped。
- 新測試：`tests/unit/test_card_review.py`（解析三種輸出格式、缺欄位／越界／
  布林／純散文一律回 None、`passed()` 邊界、模型安裝比對）、
  `tests/unit/test_review_gate.py`（全過／重產後過／兩次都不過／重產失敗／
  審核不可用時連 `batch_generate` 都不呼叫／脈絡與 notes 有傳到／只分類存活的卡）。
- **反向煙霧測試（qwen3:8b 實跑）**：同一段劃線餵兩張卡——忠實版得
  5/5/5/5 通過；刻意捏造數據與因果、又混入第二個概念的版本得 2/2/3/2 未通過，
  `notes` 準確指出「加入了原文未提及的數據與因果關係」「混入與主軸無關的論點」。
  閘門確實會擋，不是形同虛設。

## 一併修掉的既有缺陷：標籤黏連（Phase 2 T1）

e2e 實跑再次確認 `_TAG_SPLIT` 的老問題：模型幾乎不照 prompt 用頓號，實測輸出
`學習方法-內在動力-知識轉化`、`環境心理學。習慣建立。行動科學`、
`身份認同・習慣建立・系統思考`，整條原封不動存進 Notion 的 Key Word 欄。
修法：分隔符集合擴充到全形/半形冒號、分號、句號、各種破折號與連字號、中點、
波浪號；切完修邊（去 `#`、括號、引號）、丟棄空值與超過 15 字的句子（那是模型
在標籤行寫散文）、去重；兩處 prompt 加負面規則與正反例。
T2：`tools/fix_card_tags.py` 重切既有 `cards_output/*.json`。切分規則抽成
`ZettelkastenLLMEnhancer._split_tags()` 由 T1/T2 共用——兩份分隔符清單第一次修改
就會漂移。工具只動 `tags`，其餘欄位（含 `uploaded`/`uploaded_at`/舊的
`quality_score`）一字不動；原子寫檔（temp + `os.replace`）、重跑冪等；
`--dry-run` 印「原標籤 → 新標籤」，標籤被清空的卡另外標記提醒人工確認。
**只改本地 JSON**——已上傳 Notion 的卡片 `Key Word` 欄仍是舊值，要等 Phase 5 backfill。

## 注意事項

- 時間成本：單書 1（主軸）+ N（逐卡）+ 重產次數 ≈ 17–25 次本地模型呼叫。
- **並行**：書籍走 `ThreadPoolExecutor(max_workers=5)`，產卡與審核都在該書自己的
  worker thread 內，所以 A 書產卡時 B 書可能正在審核。實測 `ollama ps` 顯示兩個
  模型無法同時常駐（VRAM 不足），會互相擠掉 → 交錯執行有換模型成本。真跑偏慢時
  可設 `OLLAMA_MAX_LOADED_MODELS=2` 或調低 `MAX_WORKERS`。
- `DRY_RUN` 會整個跳過卡片流程（`container.py`），本功能無法用 dry-run 驗收。
- 既有 Notion 卡片上的「品質分數」「狀態」欄不會被刪除，只是不再寫入。
