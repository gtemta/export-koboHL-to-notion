# 卡片角色看板與相關卡片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓書頁「筆記圖」段變成依角色分欄、依閱讀順序排列的看板，卡片之間有「相關卡片」連結，並移除 📖 章名＋進度那行。

**Architecture:** 新工具 `tools/build_card_board.py` 從 Notion 讀卡片、用 Kobo 資料庫排書中順序、跑兩次本地模型取連結交集，算出「只填空白」的寫入計畫後才寫回 Notion。決策邏輯全在 domain（純函式）；Notion、Kobo、Ollama 各自是 infrastructure adapter；不進 `main.py` 同步流程。

**Tech Stack:** Python、notion-client 2.2.1（`Client.request` 打 Notion-Version `2026-03-11` 的 Views API）、sqlite3、Ollama REST、unittest／pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-11-03-card-role-board-design.md`（實作前先讀，尤其「反目標」與「尚未驗證」）

## Global Constraints

- 欄位名一字不差：`角色`（select，選項依序 `主軸`、`支柱`、`案例`）、`閱讀順序`（number）、`相關卡片`（self-relation，單一欄位）。view 名稱 `本書卡片`。
- `閱讀順序` 從 10 起、每次加 10；新卡從同書最大值往上加 10。
- 連結＝兩次模型回應的交集，視為不分方向的一對；角色不同取較低階（主軸 > 支柱 > 案例）。
- 定位到的卡少於 80% 視為失敗；每次模型呼叫最多試 2 次；任一次最終失敗，這本書這輪**什麼都不寫**。
- 少於 3 張卡的書不跑模型，角色填 `案例`，只排順序。
- 模型 `OLLAMA_CARD_MAP_MODEL` 預設 `gemma4:12b`，**不退回** `OLLAMA_MODEL`；逾時 `OLLAMA_CARD_MAP_TIMEOUT_SECONDS` 預設 `600`。
- 提示詞不改：沿用 `build_book_map_prompt`。
- 永不覆寫既有值、永不移除連結、永不動使用者手動建立的書頁與使用者自己的 view。
- 新欄位只由 `ensure_card_board_columns()` 建立，不放進 `_ensure_schema`／`_schema_additions`。
- domain 不得有 IO。隨機種子用 sha1，不可用內建 `hash()`。
- 開工基準：`python -m pytest` 713 passed、`python -m ruff check .` 乾淨；每個 task 結束都要維持全綠。
- Commit：gitmoji＋type，一個 commit 一個意圖，訊息結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。不要 `git add` `docs/KNOWLEDGE_SYSTEM_GAPS.md`（使用者尚未追蹤的檔）。

## Review Focus

1. **同一本書有兩張同名卡** → 連結與角色各自對到正確的頁面，不可因標題相同而串在一起。（Task 3 `test_same_titled_cards_stay_separate`）
2. **使用者改過欄位、刪過連結後重跑** → 全部保留，刪掉的舊連結不會被加回來。（Task 3 `test_existing_values_are_never_overwritten`、`test_removed_old_link_is_not_added_back`）
3. **上一輪在寫入途中中斷** → 只補還空白的卡；gallery 與看板同時存在時只刪 gallery，不多建一個看板。（Task 3 `test_partially_written_book_only_fills_blanks`、Task 6 `test_swap_after_interrupted_run_only_deletes_gallery`）
4. **筆記圖段裡是使用者自己的 view 或改過名的 gallery** → 完全不動，也不加看板。（Task 6 `test_other_views_are_left_alone`、Task 7 `test_manual_book_page_gets_fields_but_no_board`）
5. **這台電腦沒有 `KoboReader.sqlite`，或卡片的 ID 查不到** → 不失敗，這些卡排在最後。（Task 4 `test_missing_database_returns_empty`、Task 3 `test_unknown_positions_sort_last_by_created_time`）

---

## 實測結果（Task 1 完成後填寫，後續 task 以此為準）

| 問題 | 預設假設 | 實測 |
|---|---|---|
| 自我關聯的建立 body | `{"relation": {"database_id": DB, "type": "single_property", "single_property": {}}}` | |
| 單一欄位在 API 寫一邊，另一邊讀得到嗎 | 不確定（程式一律兩邊都寫） | |
| `group_by.property_id` 收欄位名嗎 | 收（文件對 `properties` 說可用名稱） | |
| 看板欄位順序 | `sort: {"type": "manual"}` 會照選項順序 | |
| 卡片顯示欄位 | `properties: [{"property_id": "閱讀順序", "visible": true}]` 其餘預設隱藏 | |
| 筆記圖段的 gallery 在 `list_blocks` 的樣子 | `type == "child_database"`，block id 即 linked database id | |
| linked database 能新增 view、刪 gallery | 能 | |

---

### Task 1: 開分支並在《主控力》實測 API

**Files:**
- Modify: `.gitignore`（加 `.superpowers/`）
- Modify: 本計畫的「實測結果」表
- 實測腳本放 scratchpad，不進 repo

**Interfaces:**
- Produces: 「實測結果」表，Task 5、6 的 body 以它為準。

- [ ] **Step 1: 開分支、把 `.superpowers/` 加進 `.gitignore`、提交文件**

```bash
git checkout -b feat/card-role-board
git add .gitignore docs/superpowers/specs/2026-11-03-card-role-board-design.md docs/superpowers/plans/2026-11-03-card-role-board.md
git commit -m "📝 docs: 卡片角色看板的設計與實作計畫"
```

- [ ] **Step 2: 寫一次性腳本並執行**

對卡片盒 `de21f50e0e1c4a6491c5d3e923d06e31`、書頁 `398f8b18-6b35-8183-9590-c5bdc3bccc4c`，依序：(1) `databases.update` 建三個欄位；(2) `list_blocks` 印出筆記圖段的 block 類型與 id；(3) `GET views?database_id=<該 id>` 列出既有 view；(4) `POST views` 帶 `database_id` 建看板（欄位見 Task 6 的 `card_board_body`）；(5) 只填三張卡的 `角色`：〈50%法則〉主軸、〈危機處理應對〉支柱、〈改變視角：將提議連結到對方利益點〉案例，其餘留空，順便確認空白卡會落在哪一欄；(6) 只在〈危機處理應對〉（`398f8b18-6b35-8113-ae59-ff7609639514`）的 `相關卡片` 寫入〈50%法則〉（`398f8b18-6b35-817f-8984-f37f9d0d3f0f`），再讀回 50%法則那一側；(7) `DELETE views/{gallery}`。每一步印出原始回應。

Expected：每步都有回應並把結果填進表。

**停止條件：** 看板建不出來，或 `相關卡片` 建不成單一欄位 → 停下回報使用者（spec 明定要重議）。

- [ ] **Step 3: 請使用者在 Notion 看一眼《主控力》書頁**

確認三欄順序、卡片顯示的欄位，以及把一張卡拖到別欄會不會改角色。把觀察填進表；欄位順序不對先試 `ascending`。

- [ ] **Step 4: 更新實測結果並提交**

```bash
git add docs/superpowers/plans/2026-11-03-card-role-board.md
git commit -m "📝 docs: 記錄看板 API 實測結果"
```

---

### Task 2: 修正 `normalize_book_map` 的兩個 bug

**Files:**
- Modify: `src/domain/services/infographic_rules.py`
- Test: `tests/unit/test_infographic_rules.py`、`tests/unit/test_infographic_spec_generator.py`

**Interfaces:**
- Produces: `MIN_MAP_COVERAGE = 0.8`；`clean_role(value: Any) -> str`；`is_card_number(value: Any, count: int) -> bool`（由 `_is_card_number` 改名公開，Task 3 要用）；`normalize_book_map(raw, titles, min_coverage: float = MIN_MAP_COVERAGE)`。

- [ ] **Step 1: 寫失敗的測試**

```python
def test_support_is_an_alias_of_pillar(self):
    raw = _map_raw(cards=[{"n": i, "role": "支撐", "neighbors": []} for i in range(1, 5)])
    _, entries = normalize_book_map(raw, TITLES)
    self.assertEqual({e.role for e in entries.values()}, {"支柱"})

def test_under_eighty_percent_placed_is_not_a_map(self):
    raw = _map_raw(cards=[{"n": i, "role": "支柱", "neighbors": []} for i in range(1, 4)])
    self.assertIsNone(normalize_book_map(raw, TITLES))      # 3/4 = 75%

def test_eighty_percent_placed_is_a_map_and_the_rest_default(self):
    raw = _map_raw(cards=[{"n": i, "role": "支柱", "neighbors": []} for i in range(1, 5)])
    _, entries = normalize_book_map(raw, TITLES + ["第五張"])
    self.assertEqual(entries["第五張"].role, "案例")
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/unit/test_infographic_rules.py -q`
Expected: 3 failed。

- [ ] **Step 3: 實作**

`clean_role`：合法值原樣回傳，`支撐` → `支柱`，其他 → `DEFAULT_ROLE`（別名表放模組層 `_ROLE_ALIASES`），`normalize_spec` 也改用它。`normalize_book_map` 在 `if not seen_cards` 處改為「`not seen_cards or len(seen_cards) < count * min_coverage` → None」。

- [ ] **Step 4: 調整既有測試**

這些改動是刻意的（spec 第 4 節）：
- `test_every_title_gets_an_entry…`、`test_out_of_range_numbers…`、`test_unknown_role…`、`test_neighbors_are_capped…` 改傳 `min_coverage=0.0`（它們測的不是覆蓋率）。
- 刪除 `test_one_placed_card_is_enough_to_count_as_a_map`。
- `test_infographic_spec_generator.py` 的 `test_valid_response_becomes_theme_and_entries`：改用 5 張卡、回應定位前 4 張，第 5 張斷言為 `案例`。

- [ ] **Step 5: 跑全部測試**

Run: `python -m pytest -q; python -m ruff check .`
Expected: 全過、ruff 乾淨。

- [ ] **Step 6: 提交**

```bash
git add src/domain/services/infographic_rules.py tests/unit/test_infographic_rules.py tests/unit/test_infographic_spec_generator.py
git commit -m "🐛 fix: 全書地圖接受「支撐」寫法，定位不到八成的卡視為失敗"
```

---

### Task 3: 看板的 domain 規則

**Files:**
- Create: `src/domain/entities/board_card.py`、`src/domain/services/card_board_rules.py`
- Test: `tests/unit/test_card_board_rules.py`

**Interfaces:**
- Consumes: Task 2 的 `clean_role`、`is_card_number`、`MIN_MAP_COVERAGE`；`DEFAULT_ROLE`、`ROLES`。
- Produces（`board_card.py`）：

```python
@dataclass(frozen=True)
class BoardCard:
    page_id: str
    book_page_id: str                  # 來源 relation 第一筆；"" = 沒有來源
    title: str
    source_id: str                     # 來源劃線ID，可能為空
    created_time: str
    role: str = ""                     # "" = 新卡
    reading_order: Optional[float] = None
    related_ids: Tuple[str, ...] = ()
    related_complete: bool = True      # False = API 截斷（has_more），不可重寫
    content: str = ""                  # 要跑模型時才填

@dataclass(frozen=True)
class CardUpdate:
    page_id: str
    role: Optional[str] = None
    reading_order: Optional[int] = None
    related_ids: Optional[Tuple[str, ...]] = None   # 寫入後的完整清單

@dataclass(frozen=True)
class MapRun:
    roles: Dict[str, str]              # page_id -> 角色
    links: FrozenSet[FrozenSet[str]]   # 不分方向的一對 page_id
```

- Produces（`card_board_rules.py`）：
  - `READING_ORDER_STEP = 10`、`MIN_CARDS_FOR_MAP = 3`
  - `needs_map(cards: Sequence[BoardCard]) -> bool`：有任何卡 `role` 空白。
  - `sort_by_book_order(cards, positions: Mapping[str, Tuple[int, float]]) -> List[BoardCard]`：以 `source_id` 查位置；查不到的排最後，彼此依 `created_time`。
  - `shuffled_listing(cards, book_title: str) -> List[BoardCard]`：`random.Random(sha1(書名) 轉 int).shuffle` 的副本。
  - `parse_map_run(raw: Any, page_ids: Sequence[str]) -> Optional[MapRun]`：`n` 依 `page_ids` 順序 1 起算；覆蓋率不足回 None；鄰居只看 `n`（不看 relation），自己與超出範圍的丟棄。
  - `merge_map_runs(first: MapRun, second: MapRun) -> MapRun`：見 Global Constraints；只出現在一次的卡用那次的角色。
  - `plan_book_updates(cards, merged: Optional[MapRun], positions) -> List[CardUpdate]`：`merged is None` 代表不跑模型（角色填 `DEFAULT_ROLE`、無連結）。沒有要改的卡不產生 `CardUpdate`。

- [ ] **Step 1: 寫失敗的測試**

用輔助函式 `_card(id, **kw)` 建 `BoardCard`，`_run(roles, *pairs)` 建 `MapRun`。

```python
def test_first_run_numbers_in_book_order_from_ten(self):
    cards = [_card("b", source_id="B"), _card("a", source_id="A")]
    updates = {u.page_id: u for u in plan_book_updates(cards, _run({}), {"A": (1, 0.1), "B": (2, 0.5)})}
    self.assertEqual((updates["a"].reading_order, updates["b"].reading_order), (10, 20))

def test_new_cards_go_after_the_largest_existing_number(self):
    cards = [_card("old", role="主軸", reading_order=25.5), _card("n1"), _card("n2")]
    orders = {u.page_id: u.reading_order for u in plan_book_updates(cards, _run({}), {})}
    self.assertEqual(sorted(v for v in orders.values() if v), [35, 45])

def test_existing_values_are_never_overwritten(self):
    cards = [_card("old", role="主軸", reading_order=15, related_ids=("x",)), _card("x", role="案例", reading_order=20), _card("new")]
    updates = plan_book_updates(cards, _run({"old": "案例", "new": "支柱"}, ("old", "new")), {})
    old = next(u for u in updates if u.page_id == "old")
    self.assertIsNone(old.role); self.assertIsNone(old.reading_order)
    self.assertEqual(set(old.related_ids), {"x", "new"})

def test_removed_old_link_is_not_added_back(self):
    cards = [_card("a", role="主軸", reading_order=10), _card("b", role="案例", reading_order=20), _card("n")]
    updates = plan_book_updates(cards, _run({}, ("a", "b")), {})
    self.assertFalse([u for u in updates if u.page_id in ("a", "b") and u.related_ids])

def test_links_are_written_on_both_ends(self):
    updates = {u.page_id: u for u in plan_book_updates([_card("a"), _card("b")], _run({}, ("a", "b")), {})}
    self.assertEqual((updates["a"].related_ids, updates["b"].related_ids), (("b",), ("a",)))

def test_truncated_relation_is_not_rewritten(self):
    cards = [_card("a", role="主軸", reading_order=10, related_complete=False), _card("n")]
    updates = {u.page_id: u for u in plan_book_updates(cards, _run({}, ("a", "n")), {})}
    self.assertNotIn("a", updates); self.assertEqual(updates["n"].related_ids, ("a",))

def test_partially_written_book_only_fills_blanks(self):
    cards = [_card("done", role="支柱", reading_order=10), _card("todo")]
    updates = plan_book_updates(cards, _run({"done": "主軸", "todo": "案例"}), {})
    self.assertEqual([(u.page_id, u.role, u.reading_order) for u in updates], [("todo", "案例", 20)])

def test_no_map_means_default_role_and_no_links(self):
    updates = plan_book_updates([_card("a")], None, {})
    self.assertEqual((updates[0].role, updates[0].related_ids), ("案例", None))

def test_links_keep_only_pairs_seen_in_both_runs_regardless_of_direction(self):
    merged = merge_map_runs(_run({}, ("a", "b"), ("b", "c")), _run({}, ("b", "a"), ("c", "d")))
    self.assertEqual(merged.links, {frozenset({"a", "b"})})

def test_role_disagreement_takes_the_lower_rank(self):
    merged = merge_map_runs(_run({"a": "主軸", "b": "支柱"}), _run({"a": "支柱", "b": "案例"}))
    self.assertEqual(merged.roles, {"a": "支柱", "b": "案例"})

def test_parse_drops_self_and_out_of_range_links_and_reads_support_alias(self):
    raw = {"cards": [{"n": 1, "role": "支撐", "neighbors": [{"n": 1}, {"n": 9}, {"n": 2}]}, {"n": 2, "role": "主軸"}]}
    run = parse_map_run(raw, ["a", "b"])
    self.assertEqual(run.roles, {"a": "支柱", "b": "主軸"}); self.assertEqual(run.links, {frozenset({"a", "b"})})

def test_parse_rejects_low_coverage(self):
    self.assertIsNone(parse_map_run({"cards": [{"n": 1, "role": "主軸"}]}, list("abcdefghij")))

def test_same_titled_cards_stay_separate(self):
    run = parse_map_run({"cards": [{"n": 1, "role": "主軸", "neighbors": [{"n": 3}]}, {"n": 2, "role": "案例"}, {"n": 3, "role": "支柱"}]}, ["same-1", "same-2", "other"])
    self.assertEqual(run.links, {frozenset({"same-1", "other"})}); self.assertEqual(run.roles["same-2"], "案例")

def test_unknown_positions_sort_last_by_created_time(self):
    cards = [_card("late", created_time="2026-02"), _card("known", source_id="K"), _card("early", created_time="2026-01")]
    self.assertEqual([c.page_id for c in sort_by_book_order(cards, {"K": (1, 0.0)})], ["known", "early", "late"])

def test_shuffle_is_stable_for_a_title_and_keeps_every_card(self):
    cards = [_card(str(i)) for i in range(8)]
    self.assertEqual(shuffled_listing(cards, "書"), shuffled_listing(cards, "書"))
    self.assertEqual({c.page_id for c in shuffled_listing(cards, "書")}, {c.page_id for c in cards})
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/unit/test_card_board_rules.py -q`
Expected: 匯入錯誤。

- [ ] **Step 3: 實作兩個檔案**

新起始值：同書既有最大值的 `int(floor)` 加 10；沒有既有值從 10 起。`related_ids` 順序：既有值在前，新加的依 page id 排序。

- [ ] **Step 4: 確認通過**

Run: `python -m pytest tests/unit/test_card_board_rules.py -q; python -m ruff check .`
Expected: 全過。

- [ ] **Step 5: 提交**

```bash
git add src/domain/entities/board_card.py src/domain/services/card_board_rules.py tests/unit/test_card_board_rules.py
git commit -m "✨ feat: 看板的 domain 規則（閱讀順序、連結交集、只填空白）"
```

---

### Task 4: 讀取 Kobo 位置與模型原始回應

**Files:**
- Create: `src/infrastructure/persistence/kobo_book_positions.py`
- Modify: `src/infrastructure/infographic/spec_generator.py`
- Test: `tests/unit/test_kobo_book_positions.py`、`tests/unit/test_infographic_spec_generator.py`

**Interfaces:**
- Produces:
  - `KoboBookPositions(db_path: str).positions_for(source_ids: Sequence[str]) -> Dict[str, Tuple[int, float]]`
  - `InfographicSpecGenerator.ask_book_map(book_title, cards) -> Optional[dict]`：只回解析後的原始 JSON，`build_book_map` 改為呼叫它再 normalize。`cards` 只需有 `.title`、`.content`（`BoardCard` 也可傳）。
  - `InfographicSpecGenerator.is_available() -> bool`：只打 `/api/tags` 不載入模型，比對 `model` 與 `f"{model}:latest"`，服務沒開與沒安裝各記一條清楚的 ERROR。

- [ ] **Step 1: 寫失敗的測試**

`test_kobo_book_positions.py` 用 tmp 目錄建最小 SQLite（`Bookmark(BookmarkID, VolumeID, ContentID, ChapterProgress)`、`content(ContentID, BookID, ContentType, VolumeIndex)`）：

```python
def test_position_is_spine_index_and_progress(self):
    self.assertEqual(KoboBookPositions(self.db).positions_for(["bm-1"]), {"bm-1": (10, 0.2)})

def test_unknown_id_is_omitted(self):
    self.assertEqual(KoboBookPositions(self.db).positions_for(["nope"]), {})

def test_null_progress_counts_as_zero(self):
    self.assertEqual(KoboBookPositions(self.db).positions_for(["bm-null"])["bm-null"][1], 0.0)

def test_missing_database_returns_empty(self):
    with self.assertLogs(level="WARNING"):
        self.assertEqual(KoboBookPositions("no-such.sqlite").positions_for(["bm-1"]), {})
```

`test_infographic_spec_generator.py`：

```python
def test_ask_book_map_returns_raw_json_without_normalizing(self):
    gen, _, patcher = _generator('{"cards": [{"n": 1, "role": "支撐"}]}')
    self.addCleanup(patcher.stop)
    self.assertEqual(gen.ask_book_map("書", CARDS)["cards"][0]["role"], "支撐")

def test_is_available_checks_the_model_is_installed(self):
    # requests.get 以 mock 回 {"models": [{"name": "gemma4:12b"}]}；model="gemma4:12b" → True，model="x" → False
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/unit/test_kobo_book_positions.py tests/unit/test_infographic_spec_generator.py -q`
Expected: FAIL。

- [ ] **Step 3: 實作**

唯讀連線：`sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)`，開檔或查詢失敗（`sqlite3.Error`）記 WARNING 回 `{}`。spine 每個 `VolumeID` 查一次 `_SPINE_QUERY`，用 `TocChapterResolver(rows, []).spine_position(content_id)`，spine 查不到的省略。

- [ ] **Step 4: 確認通過並提交**

Run: `python -m pytest -q; python -m ruff check .`
Expected: 全過。

```bash
git add src/infrastructure/persistence/kobo_book_positions.py src/infrastructure/infographic/spec_generator.py tests/unit/test_kobo_book_positions.py tests/unit/test_infographic_spec_generator.py
git commit -m "✨ feat: 用來源劃線ID 查書中位置，模型回應可取原始 JSON"
```

---

### Task 5: 卡片盒的讀寫

**Files:**
- Modify: `src/infrastructure/notion/zettelkasten_card_repository.py`
- Test: `tests/unit/test_card_board_repository.py`

**Interfaces:**
- Consumes: `BoardCard`、`CardUpdate`；「實測結果」表的關聯 body。
- Produces（`ZettelkastenCardRepository` 方法）：
  - `ensure_card_board_columns() -> List[str]`：回傳這次建立的欄名；schema 讀不到時不寫、回 `[]`（比照 `ensure_infographic_column`）。
  - `list_board_cards() -> List[BoardCard]`：全部卡片（`_query_all` 帶 `{"property": "標題", "title": {"is_not_empty": True}}`），欄位不存在視為空白；`related_complete = not relation_prop.get("has_more")`。
  - `card_text(page_id: str) -> str`：頂層 paragraph 的 `plain_text`，以空格串接。
  - `update_board_fields(update: CardUpdate) -> None`：一次 `pages.update`，只送非 None 的欄位。

- [ ] **Step 1: 寫失敗的測試**

```python
def test_columns_are_created_once_in_option_order(self):
    fake.db_properties = {"標題": {}}
    self.assertEqual(set(repo.ensure_card_board_columns()), {"角色", "閱讀順序", "相關卡片"})
    props = fake.db_updates[0]["properties"]
    self.assertEqual([o["name"] for o in props["角色"]["select"]["options"]], ["主軸", "支柱", "案例"])
    self.assertEqual(props["相關卡片"]["relation"]["database_id"], "db")

def test_existing_columns_are_left_alone(self):
    fake.db_properties = {"角色": {}, "閱讀順序": {}, "相關卡片": {}}
    self.assertEqual(repo.ensure_card_board_columns(), [])
    self.assertEqual(fake.db_updates, [])

def test_ordinary_sync_does_not_create_board_columns(self):
    repo.ensure_schema()
    self.assertNotIn("角色", (fake.db_updates or [{"properties": {}}])[0]["properties"])

def test_list_reads_all_fields_and_treats_missing_columns_as_blank(self):
    # 一頁有全部欄位、一頁只有 標題：斷言 role/reading_order/related_ids/book_page_id/source_id

def test_truncated_relation_is_marked_incomplete(self):
    # 相關卡片 帶 has_more: true → related_complete is False

def test_update_sends_only_given_fields(self):
    repo.update_board_fields(CardUpdate(page_id="p", reading_order=30))
    self.assertEqual(fake.page_updates, [("p", {"閱讀順序": {"number": 30}})])

def test_update_writes_full_relation_list(self):
    repo.update_board_fields(CardUpdate(page_id="p", related_ids=("a", "b")))
    self.assertEqual(fake.page_updates[0][1], {"相關卡片": {"relation": [{"id": "a"}, {"id": "b"}]}})
```

- [ ] **Step 2: 確認失敗，實作，確認通過**

Run: `python -m pytest tests/unit/test_card_board_repository.py -q`
Expected：先 FAIL，實作後全過。常數放模組層 `_ROLE_PROPERTY`、`_ORDER_PROPERTY`、`_RELATED_PROPERTY`。

- [ ] **Step 3: 提交**

```bash
git add src/infrastructure/notion/zettelkasten_card_repository.py tests/unit/test_card_board_repository.py
git commit -m "✨ feat: 卡片盒補上看板欄位並支援讀寫"
```

---

### Task 6: 看板 view 與書頁補完改用看板

**Files:**
- Modify: `src/infrastructure/notion/notion_views_client.py`、`src/infrastructure/notion/dry_run_reading_list_repository.py`、`src/application/use_cases/complete_reading_list_page_use_case.py`、`src/infrastructure/container.py`
- Test: `tests/unit/test_notion_views_client.py`、`tests/unit/test_complete_reading_list_page.py`、`tests/unit/test_reading_list_dry_run.py`

**Interfaces:**
- Consumes: `ensure_card_board_columns()`；「實測結果」表。
- Produces（`notion_views_client.py`；原 `CARD_GALLERY_NAME`、`card_gallery_body`、`create_card_gallery` 全部改名，不留舊名）：
  - `CARD_VIEW_NAME = "本書卡片"`
  - `card_board_body(data_source_id, book_page_id, placement: Dict) -> Dict`
  - `ViewSwap(add_board: bool, delete_gallery_id: Optional[str])`（frozen dataclass）
  - `plan_view_swap(views: Sequence[Dict]) -> ViewSwap`（純函式）
  - `NotionViewsClient.create_card_board(page_id, cards_database_id, book_page_id, after_block_id) -> Optional[str]`
  - `NotionViewsClient.describe_swap(linked_database_id) -> ViewSwap`：`GET views?database_id=…`，再逐一 `GET views/{id}`，唯讀。
  - `NotionViewsClient.swap_gallery_for_board(linked_database_id, cards_database_id, book_page_id) -> bool`：先加後刪（資料庫至少要留一個 view）。
- `CompleteReadingListPageUseCase.__init__` 新增 `dry_run: bool = False`；`container.py` 傳 `dry_run=settings.dry_run`。

- [ ] **Step 1: 寫失敗的測試**

```python
def test_board_body_shape(self):
    placement = {"database_id": "linked"}
    self.assertEqual(card_board_body("ds-1", "page-1", placement), {
        "data_source_id": "ds-1", "name": "本書卡片", "type": "board", "database_id": "linked",
        "filter": {"property": "來源", "relation": {"contains": "page-1"}},
        "sorts": [{"property": "閱讀順序", "direction": "ascending"}],
        "configuration": {
            "type": "board",
            "group_by": {"type": "select", "property_id": "角色", "sort": {"type": "manual"}, "hide_empty_groups": False},
            "cover": {"type": "page_cover"},
            "properties": [{"property_id": "閱讀順序", "visible": True}],
        },
    })

def test_gallery_alone_is_swapped(self):
    self.assertEqual(plan_view_swap([_view("g", "本書卡片", "gallery")]), ViewSwap(True, "g"))

def test_swap_after_interrupted_run_only_deletes_gallery(self):
    views = [_view("g", "本書卡片", "gallery"), _view("b", "本書卡片", "board")]
    self.assertEqual(plan_view_swap(views), ViewSwap(False, "g"))

def test_board_already_there_needs_nothing(self):
    self.assertEqual(plan_view_swap([_view("b", "本書卡片", "board")]), ViewSwap(False, None))

def test_other_views_are_left_alone(self):
    for views in ([_view("t", "我的表格", "table")], [_view("r", "改過名", "gallery")]):
        self.assertEqual(plan_view_swap(views), ViewSwap(False, None))

def test_swap_adds_before_deleting(self):
    # fake 回傳單一 gallery；斷言 requests 順序為 POST views（body 帶 database_id）→ DELETE views/g

def test_blank_notes_section_gets_a_board_after_columns_exist(self):
    # 既有 test_blank_page_gets_skeleton_gallery_cover_and_type 改名：_FakeCards 記錄 ensure 呼叫，
    # 斷言先 ensure 再 create_card_board

def test_dry_run_never_creates_columns(self):
    # dry_run=True：_FakeCards.ensure_calls == 0，create_card_board 仍被呼叫（decorator 只記 log）
```

`_view(id, name, type)` 回傳 `{"id": id, "name": name, "type": type}`。若「實測結果」表與上面的 body 不同，以表為準並同步改測試。

把 `test_notion_views_client.py`、`test_complete_reading_list_page.py`（`_FakeViews`）、`test_reading_list_dry_run.py` 裡的舊名全部換新。

- [ ] **Step 2: 確認失敗，實作，確認通過**

Run: `python -m pytest tests/unit/test_notion_views_client.py tests/unit/test_complete_reading_list_page.py tests/unit/test_reading_list_dry_run.py -q`
Expected：先 FAIL，實作後全過。`_ensure_card_gallery` 改名 `_ensure_card_board`，段落空白才建；非空白不動（取代 gallery 是 Task 7 工具的事）。

- [ ] **Step 3: 跑全部並提交**

Run: `python -m pytest -q; python -m ruff check .`
Expected: 全過。

```bash
git add src/infrastructure/notion/notion_views_client.py src/infrastructure/notion/dry_run_reading_list_repository.py src/application/use_cases/complete_reading_list_page_use_case.py src/infrastructure/container.py tests/unit/test_notion_views_client.py tests/unit/test_complete_reading_list_page.py tests/unit/test_reading_list_dry_run.py
git commit -m "✨ feat: 書頁筆記圖改用依角色分欄的看板"
```

---

### Task 7: `BuildCardBoardUseCase` 與工具入口

**Files:**
- Create: `src/application/use_cases/build_card_board_use_case.py`、`src/application/dtos/card_board_report.py`、`tools/build_card_board.py`
- Modify: `.env.example`
- Test: `tests/unit/test_build_card_board.py`

**Interfaces:**
- Consumes: Task 3～6 全部介面；`ReadingListRepository.list_pages/page_title/is_created_by_integration/list_blocks`；`find_section`、`section_is_empty`、`SECTION_NOTES`。
- Produces:
  - `CardBoardReport`（dataclass）：`planned: List[str]`、`processed: List[Tuple[str, int]]`（書名、更新幾張卡）、`untouched: List[str]`、`failed: List[Tuple[str, str]]`、`no_source_cards: int`、`aborted: str`。
  - `BuildCardBoardUseCase(cards, reading_list, views, positions, generator, cards_database_id).execute(book_filter: Optional[str] = None, dry_run: bool = False) -> CardBoardReport`
  - 工具：`format_report(report, dry_run) -> str`；`run(dry_run, book, *, use_case=None) -> Tuple[str, int]`（有失敗或 aborted 時 exit code 1）；`card_map_model() -> str`。

`execute` 的流程（順序是需求的一部分）：

1. `list_board_cards()`、`list_pages()`，依 `book_page_id` 分組；空來源只計數；`book_filter` 比對書名子字串；來源頁不在 Reading List 的書記入 `failed`。
2. `dry_run`：每本書列出一行（卡數、新卡數、會跑模型與否、書頁會建看板／取代 gallery／不動），不呼叫模型、不寫入，回傳。
3. 有書需要模型（`needs_map` 且卡數 ≥ `MIN_CARDS_FOR_MAP`）但 `generator.is_available()` 為 False → 設 `aborted`，回傳，**不建欄位**。
4. `ensure_card_board_columns()`。
5. 逐本處理，單本例外記入 `failed` 後繼續：
   - 不需要模型的書不呼叫 `card_text`、`positions_for`、`ask_book_map`。
   - 需要時：填 `content`、依書中順序排序，第一次用書中順序、第二次用 `shuffled_listing`；每次最多試 2 次（`ask_book_map` ＋ `parse_map_run`）。任一次最終失敗 → 記入 `failed`、這本書不寫也不動書頁。
   - `plan_book_updates` 後逐張 `update_board_fields`。
   - 只有 `is_created_by_integration` 的書頁才處理看板：段落空白 → `create_card_board`；有 `child_database` → 各自 `swap_gallery_for_board`；找不到段落 → WARNING。

- [ ] **Step 1: 寫失敗的測試**

以 `_FakeCards`、`_FakeReadingList`、`_FakeViews`、`_FakePositions`、`_FakeGenerator(replies)` 測，其中 `_FakeCards` 與 `_FakeViews` 的寫入方法在 `dry_run` 測試裡一律 raise。`_FakeGenerator.ask_book_map` 記下每次收到的 page id 順序（`listings`），`reply(links=[("a", "b")])` 依該順序把 page id 轉成編號、產生涵蓋全部卡的 JSON；`None` 代表這次呼叫失敗。

```python
def test_two_runs_write_only_links_seen_twice(self):
    report = use_case(replies=[reply(links=[("a", "b"), ("b", "c")]), reply(links=[("a", "b")])]).execute()
    self.assertEqual(fake_cards.written["a"].related_ids, ("b",))
    self.assertEqual(fake_cards.written["c"].related_ids, None)
    self.assertEqual(report.failed, [])

def test_second_listing_is_shuffled_and_first_is_book_order(self):
    use_case().execute()
    first, second = fake_generator.listings
    self.assertEqual(first, BOOK_ORDER_IDS)
    self.assertNotEqual(second, BOOK_ORDER_IDS); self.assertEqual(set(second), set(BOOK_ORDER_IDS))

def test_rerun_on_a_filled_book_never_touches_the_model(self):
    report = use_case(all_filled=True).execute()
    self.assertEqual(fake_generator.calls, 0); self.assertEqual(fake_cards.text_calls, 0)
    self.assertEqual(fake_cards.written, {})

def test_filled_books_do_not_need_ollama_running(self):
    report = use_case(all_filled=True, available=False).execute()
    self.assertEqual(report.aborted, "")

def test_model_unavailable_aborts_before_any_write(self):
    report = use_case(available=False).execute()
    self.assertIn("gemma4", report.aborted)
    self.assertEqual(fake_cards.ensure_calls, 0); self.assertEqual(fake_cards.written, {})

def test_each_model_call_gets_a_second_attempt(self):
    use_case(replies=[None, good(), good()]).execute()
    self.assertEqual(fake_generator.calls, 3)

def test_failed_map_writes_nothing_and_other_books_continue(self):
    report = two_book_use_case(first_book_replies=[None, None]).execute()
    self.assertEqual([t for t, _ in report.failed], ["書一"])
    self.assertEqual(set(fake_cards.written), {"書二的卡"})
    self.assertEqual(fake_views.calls_for("書一頁"), [])

def test_small_book_skips_the_model(self):
    use_case(cards=2).execute()
    self.assertEqual(fake_generator.calls, 0)
    self.assertEqual({u.role for u in fake_cards.written.values()}, {"案例"})

def test_manual_book_page_gets_fields_but_no_board(self):
    use_case(page_by_integration=False).execute()
    self.assertTrue(fake_cards.written); self.assertEqual(fake_views.calls, [])

def test_blank_section_creates_board_and_gallery_is_swapped(self):
    use_case(section_body=[]).execute()
    self.assertEqual(fake_views.calls[-1][0], "create_card_board")
    use_case(section_body=[{"type": "child_database", "id": "linked"}]).execute()
    self.assertEqual(fake_views.calls[-1][:2], ("swap_gallery_for_board", "linked"))

def test_dry_run_is_read_only(self):
    report = use_case().execute(dry_run=True)
    self.assertTrue(report.planned); self.assertEqual(fake_generator.calls, 0)

def test_book_filter_limits_processing(self):
    report = two_book_use_case().execute(book_filter="書二")
    self.assertEqual([title for title, _ in report.processed], ["書二"])

def test_cards_without_source_are_counted_and_skipped(self):
    report = use_case(extra_cards_without_source=2).execute()
    self.assertEqual(report.no_source_cards, 2)

def test_card_map_model_ignores_ollama_model(self):
    with mock.patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:4b"}, clear=False):
        os.environ.pop("OLLAMA_CARD_MAP_MODEL", None)
        self.assertEqual(card_map_model(), "gemma4:12b")

def test_tool_exit_code_reflects_failures(self):
    self.assertEqual(run(False, None, use_case=_Stub(CardBoardReport()))[1], 0)
    self.assertEqual(run(False, None, use_case=_Stub(CardBoardReport(failed=[("書", "x")])))[1], 1)
    self.assertEqual(run(False, None, use_case=_Stub(CardBoardReport(aborted="模型沒開")))[1], 1)
```

- [ ] **Step 2: 確認失敗，實作，確認通過**

Run: `python -m pytest tests/unit/test_build_card_board.py -q`
Expected：先 FAIL，實作後全過。工具比照 `tools/make_card_infographic.py` 的結構（`setup_file_and_console_logging`、`--dry-run`、`--book`）；限速器共用一個 `NotionRateLimiter`。

- [ ] **Step 3: 更新 `.env.example`**

在「卡片概念圖卡」段落後加 `OLLAMA_CARD_MAP_MODEL`、`OLLAMA_CARD_MAP_TIMEOUT_SECONDS` 的註解行，說明預設值與不退回 `OLLAMA_MODEL` 的原因。

- [ ] **Step 4: 跑全部並提交**

Run: `python -m pytest -q; python -m ruff check .; python tools/build_card_board.py --dry-run --book 主控力`
Expected: 全過；工具印出《主控力》一行，Notion 無任何變動。

```bash
git add src/application/use_cases/build_card_board_use_case.py src/application/dtos/card_board_report.py tools/build_card_board.py tests/unit/test_build_card_board.py .env.example
git commit -m "✨ feat: 新增 build_card_board 工具產生角色看板與相關卡片"
```

---

### Task 8: 移除 📖 那行

**Files:**
- Modify: `src/infrastructure/notion/zettelkasten_card_repository.py`
- Create: `tools/remove_card_chapter_callouts.py`
- Test: `tests/unit/test_chapter_reference.py`、`tests/unit/test_remove_card_chapter_callouts.py`

**Interfaces:**
- Produces：
  - `is_chapter_callout(block: dict) -> bool`（模組層）：`type == "callout"` 且 icon emoji 為 `📖`。
  - `ZettelkastenCardRepository.list_chapter_callouts() -> List[Tuple[str, str, str]]`（卡片標題、block id、文字），只看頂層 block；`delete_block(block_id: str) -> None`。
  - 工具 `run(dry_run, *, repo=None) -> Tuple[str, int]`：`--dry-run` 列出每張卡與 callout 文字；正式刪除時單筆失敗記下繼續，有失敗時 exit code 1。

- [ ] **Step 1: 改寫測試**

把 `test_chapter_reference.py` 的 `TestChapterCalloutFallsBackToProgress` 換成：

```python
class TestCardBodyHasNoChapterCallout(unittest.TestCase):
    def test_no_callout_even_with_chapter_and_progress(self):
        blocks = _repo()._build_children(_card(chapter_reference="第一章", chapter_progress=0.42))
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "quote"])
```

`test_remove_card_chapter_callouts.py`：

```python
def test_only_book_emoji_callouts_match(self):
    self.assertTrue(is_chapter_callout(_callout("📖")))
    self.assertFalse(is_chapter_callout(_callout("💡")))
    self.assertFalse(is_chapter_callout({"type": "quote", "quote": {}}))
    self.assertFalse(is_chapter_callout({"type": "callout", "callout": {"icon": None}}))

def test_dry_run_lists_text_and_deletes_nothing(self):
    report, code = run(True, repo=fake)
    self.assertIn("第一章（進度 42%）", report); self.assertEqual(fake.deleted, []); self.assertEqual(code, 0)

def test_real_run_deletes_each_callout_and_rerun_finds_none(self):
    run(False, repo=fake)
    self.assertEqual(fake.deleted, ["c1", "c2"]); self.assertEqual(fake.list_chapter_callouts(), [])

def test_one_failed_delete_is_reported_and_the_rest_continue(self):
    fake.fail_on = "c1"
    report, code = run(False, repo=fake)
    self.assertEqual(fake.deleted, ["c2"]); self.assertEqual(code, 1); self.assertIn("c1", report)
```

- [ ] **Step 2: 確認失敗，實作，確認通過**

Run: `python -m pytest tests/unit/test_chapter_reference.py tests/unit/test_remove_card_chapter_callouts.py -q`
Expected：先 FAIL，實作後全過。`chapter_reference`、`chapter_progress`、`_clean_chapter_reference` 保留不動。

- [ ] **Step 3: 跑全部並提交**

Run: `python -m pytest -q; python -m ruff check .`
Expected: 全過。

```bash
git add src/infrastructure/notion/zettelkasten_card_repository.py tools/remove_card_chapter_callouts.py tests/unit/test_chapter_reference.py tests/unit/test_remove_card_chapter_callouts.py
git commit -m "✨ feat: 新卡不再寫 📖 那行，並提供清除既有卡片的工具"
```

---

### Task 9: 在《主控力》跑真實流程並更新文件

**Files:**
- Modify: `CLAUDE.md`
- 真實流程需要 Ollama 開著

- [ ] **Step 1: 真跑**

Run: `python tools/build_card_board.py --book 主控力`
Expected: `processed` 有這本書，`failed` 空白。若 Task 1 已填過角色，先把這本書的 `角色`、`閱讀順序` 清空，才測得到「新卡」流程（`相關卡片` 保留 Task 1 寫的那條即可）。

- [ ] **Step 2: 驗證成功標準 1、2**

用 Notion 讀回：《主控力》筆記圖段是看板、沒有 gallery；18 張卡都有角色與閱讀順序；〈危機處理應對〉與〈50%法則〉出現在彼此的 `相關卡片`。兩次模型回應若沒連到這兩張，**如實回報**，不要手動補上假裝通過。

- [ ] **Step 3: 驗證成功標準 4（使用者改過的不被蓋掉）**

透過 API 模擬手動改動：改一張的 `閱讀順序`、改一張的 `角色`、移除一條連結。重跑工具後讀回：三項都沒變，log 顯示沒有呼叫模型。驗證完把改動還原。

- [ ] **Step 4: 驗證成功標準 3 的預覽，然後停下來**

Run: `python tools/remove_card_chapter_callouts.py --dry-run`
Expected: 列出全部仍有 📖 的卡。**把清單交給使用者，使用者確認前不跑正式刪除。**

- [ ] **Step 5: 更新 `CLAUDE.md`**

依 spec「文件更新」：新增「卡片角色看板」一節（流程、兩次取交集的理由與試跑數據、只填空白規則、Task 1 實測結果）、`tools/` 兩支工具、環境變數、卡片盒欄位與實際欄位現況；更新「卡片標題與章節參照」的 📖 說明與「卡片概念圖卡」的 `normalize_book_map` 語意；Known Cleanup Debt 註記 #3-2 同書連結已完成（`docs/KNOWLEDGE_SYSTEM_GAPS.md` 未追蹤，不動）。

- [ ] **Step 6: 提交**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-11-03-card-role-board.md
git commit -m "📝 docs: CLAUDE.md 補上卡片角色看板的流程與實測"
```

- [ ] **Step 7: 交還使用者決定的事**

回報：全部書何時跑（約 2 到 4 小時）、📖 正式清除、隱藏 `來源劃線ID`。分支整合走 `superpowers:finishing-a-development-branch`。
