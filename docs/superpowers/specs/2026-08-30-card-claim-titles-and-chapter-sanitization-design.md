# 卡片主張式標題（K1）與章節參照消毒（K4）設計

> 記錄日期：2026-08-30
> 對應：`docs/KNOWLEDGE_REFINEMENT_PLAN.md` Phase 4 的 K1 / K4（K2 延伸段、K3 註記上卡不在本批）
> 分支：`feat/card-claim-titles`
> 狀態：設計已與使用者確認，待實作

## 背景

卡片盒的可掃讀性幾乎全靠標題，但目前產卡 prompt 要的是「概括核心概念」，產出的是**主題名**
（「語言的進化與欺騙藝術」）而非**主張**（「語言愈先進，謊言愈精美」）——不點進卡片就不知道
這張卡說了什麼。

同時 `chapter_reference` 會被劃線正文污染，例：
`"拮抗理論」：「任何長時間或反覆從享樂或情感中性狀態脫離的情況⋯⋯都是有其代價的。」50這種代價就是一種..."`，
直接印在卡片的 📖 callout 上。

## 關鍵事實（已在程式碼查證，實作時不需重查）

| 事實 | 位置 |
|------|------|
| 標題規則出現在**兩處** prompt，批次路徑才是 `main.py` 實際走的 | `zettelkasten_generator.py:494`（單卡）、`:900` format 範例、`:919` 規則 5（批次） |
| 建卡時 `chapter_reference=` 的賦值點有**兩處** | `zettelkasten_generator.py:463`（`generate_card`）、`:967`（`_parse_batch_response`） |
| 兩處都用 `highlight.get('chapter_name', 'Unknown')`，預設值 `'Unknown'` 會原封不動印成「📖 Unknown」 | 同上 |
| 章名 = `toc_label or _initial_chapter_name(...)`，所以 `Highlight.toc_chapter` 非 None ⟺ 章名來自 Kobo 目錄、可信 | `src/infrastructure/persistence/kobo_sqlite_repository.py:121,132` |
| 污染唯一來源：`extract_real_chapter_title(劃線正文)` — 容忍到 150 字，只要含「：」就給 3 分信心 | `src/infrastructure/persistence/chapter_title_heuristics.py:19,29` |
| 📖 callout 的守門是 `if card.chapter_reference:`，章名一空連進度也消失 | `src/infrastructure/notion/zettelkasten_card_repository.py:744` |
| 審核 `correctness` 面向明文禁止「加入原文沒說的因果、數據或結論」 | `zettelkasten_generator.py:1289` |
| TOC 章名格式為 `章 › 小節`，上限 60 字 | `toc_chapter_resolver.resolve()` |

## 使用者已定案的決策（不要再問）

1. **K1 忠於原文優先**：prompt 要主張句，但原文只是定義／描述時寫精準的概念陳述句，
   不得自行推論。**審核 prompt 一字不動**——不在唯一的品質關卡上開豁免口，也不加嚴到
   讓退卡率上升。
2. **K4 用來源分流**，不是純字串嗅探：TOC 來源直接信，只有 heuristic 猜的才套嗅探規則。
   純字串嗅探會誤殺合法的長章名（`章 › 小節` 可到 60 字）與含引號的真實章名。
3. **不動 `chapter_title_heuristics.py` 源頭**：收緊它會連帶改變無 TOC 書籍的劃線頁分章，
   超出 K4 範圍。
4. **污染時 📖 callout 只留進度百分比**：進度是 Kobo 硬數據、永遠可信，不該被章名的問題連坐。
5. **不回填既有卡片標題**：K1 只影響未來新卡。

## K1 — 標題規則

`zettelkasten_generator.py` 兩支 prompt 的【標題】規則同步改為（文字一致）：

```
【標題】5-20個字，寫成一句可以獨立成立的論斷，讓人不看內容也知道這張卡主張什麼。
✅「語言愈先進，謊言愈精美」／❌「語言的進化與欺騙藝術的關係」
若原文只是定義或描述、本身沒有論斷，就寫成精準的概念陳述句，不要自行推論出原文沒有的結論。
```

- 長度由 5-15 放寬為 5-20（主張句比主題名長）。
- `_build_batch_prompt` 的 format 範例（`:900`）與規則 5（`:919`）都要改，**只改一處等於沒改**。
- 審核 prompt、`_parse_response` 的解析規則都不動——標題仍是 `【標題】` 標記，格式契約沒變。

## K4 — 章節參照消毒

### 純函式

`zettelkasten_generator.py` 新增模組層函式：

```python
def _clean_chapter_reference(raw: str, *, from_toc: bool) -> str
```

判斷順序：

1. `raw` 去空白後為空、或等於 `'Unknown'` → 回 `''`。**這一步不看 `from_toc`**——
   `'Unknown'` 是兩處 `highlight.get('chapter_name', 'Unknown')` 的哨兵預設值，
   不是任何真實章名，來自哪裡都該清掉。
2. `from_toc=True` → 原樣回傳（Kobo 目錄的真實標題，不做任何內容判斷）
3. 長度 > 25 字（以字元計）→ 回 `''`
4. 含 `」`、`「`、`⋯`、`。` 任一 → 回 `''`
5. 其餘原樣回傳

**只有第 3、4 步**（真正判定為污染）log 一則 **DEBUG**（帶原值前 30 字），
第 1 步的空值／哨兵不 log。不用 WARNING——無 TOC 的書會刷版。

### 套用點

`generate_card:463` 與 `_parse_batch_response:967` 兩個 `chapter_reference=` 賦值點，
在**建卡當下**套用，讓 `cards_output/*.json` 落地的就是乾淨值。

考慮過並否決的另外兩個位置：
- **Notion repository 的 render 階段**：JSON 會留著髒值，續傳與未來 Phase 6 取材都吃到污染。
- **兩層都套**：邏輯跨層重複，且 Notion 層被迫理解內容啟發式。

### 資料流

`src/application/use_cases/generate_book_cards_use_case.py` 的 `_to_dict()` 加一個鍵：

```python
"chapter_from_toc": h.toc_chapter is not None,
```

兩個建卡點以 `highlight.get('chapter_from_toc', False)` 取值。

**預設 `False` 是刻意的**：legacy 入口與舊測試傳的 dict 沒有這個鍵，會落到「不信任、套嗅探」
那一邊——寧可過度清洗也不要漏放污染。已知代價：legacy 路徑產的卡若章名超過 25 字會被清空。
該路徑產的卡本來就沒有 cover/icon/加工狀態，且已排定退役，接受此代價。

## 📖 callout 守門

`src/infrastructure/notion/zettelkasten_card_repository.py:744`：

```python
if card.chapter_reference or card.chapter_progress:
```

內文組法不變——章名為空字串時自然只剩「（進度 42%）」。這是本批唯一動到 Notion 層的改動。

## 錯誤處理

清洗函式無 IO、不拋例外；`raw` 為 `None` 以 `(raw or '')` 兜住。
K1 純屬 prompt 文字，不改變 `【標題】` 解析契約，模型不照做時的既有行為（`_parse_response`
回 `(None, None)` → 該卡放棄）維持不變。

## 測試

新增 `tests/unit/test_chapter_reference.py`：

| 案例 | 期望 |
|------|------|
| 計畫書記錄的真實污染樣本（`"拮抗理論」：「任何長時間⋯"`，`from_toc=False`） | `''` |
| `from_toc=True` 的長章名（`章 › 小節`，>25 字、含 `›`） | 原樣保留 |
| `第三章「習慣的力量」`，`from_toc=True` | 保留 |
| `第三章「習慣的力量」`，`from_toc=False` | `''`（記錄這個已知取捨） |
| `'Unknown'`、`''`、`None` | `''` |
| `generate_card` / `_parse_batch_response` 收到污染章名且 dict 無 `chapter_from_toc` 鍵 | `card.chapter_reference == ''` |
| repository：章名空 + 進度 0.42 | callout 存在，文字為「（進度 42%）」 |
| repository：章名空 + 進度 0 | 無 callout |

K1 依 `tests/unit/test_annotation.py` 的既有慣例，對兩支 prompt 各一則最小斷言
（輸出含「主張」與 `5-20`）。

## 真跑驗收（DoD 第 3 條）

`ENABLE_ZETTELKASTEN_CARDS=true python main.py`。

- **K1**：任一本新書即可，檢查新卡標題是主張句。
- **K4**：需要**一本無 TOC 的書**（有 TOC 的書走 `from_toc=True`、行為完全不變）。
  若手上 `KoboReader.sqlite` 沒有這種書，退而求其次以單元測試 + 一次重產的卡片檢查
  📖 callout 無污染，並在收工說明中**明確註記未取得無-TOC 書籍的實跑證據**，不得含混帶過。

## 不做

- 不動 `chapter_title_heuristics.py`（源頭收緊）
- 不動審核 prompt 的四面向與評分規則
- 不回填既有 ~230 張卡的標題
- K2（【延伸】段）、K3（註記上卡）不在本批
