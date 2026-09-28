# Reading List 書頁補完 M1 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓同步自動建立的 📚 Personal Reading List 書頁（現有 26 頁與之後的新頁）補上與使用者手動頁一致的六段版面、書封、本書卡片 gallery 與書籍種類，並修好劃線頁 20/26 的透明封面。全程不用 LLM。

**Architecture:** Books DB 邏輯從卡片 repo 抽成 `ReadingListRepository`，再加上書頁讀寫；新的 `CoverFinder`（Kobo 圖床優先、每張驗證）由劃線頁與書頁共用；版面由純函式組裝；卡片 gallery 經全專案唯一使用新版 API 的 `NotionViewsClient` 建立。`SyncBooksUseCase` 在執行緒池結束後，依序對 `READING_LIST_PAGES` 命中的書執行 `CompleteReadingListPageUseCase`：只處理 integration 建的頁、只補空白處，所以重跑冪等。

**Tech Stack:** Python 3.13（語法需相容 3.8，ruff `target-version = "py38"`）、notion-client 2.2.1、requests、`unittest`（跑在 pytest 下）、ruff。

**Spec:** `docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md`（本計畫只做 M1；M2 AI 剖析在 M1 真跑驗收後另寫計畫）

## Global Constraints

- 繁體中文、台灣用語：log、註解、commit message。
- Commit 慣例：gitmoji + type，一個 commit 一個意圖；訊息結尾加上 harness 指定的 attribution trailer。
- 每個 task 結束前 `python -m ruff check .` 與 `python -m pytest` 都要綠燈。基準線：**353 passed**、ruff 乾淨；不得有既有測試轉紅。若 ruff 只報 `I001`（import 排序），執行 `python -m ruff check --fix .` 後重跑即可；其他規則的錯誤要手動修。
- 不新增任何依賴（`requirements.txt` 不動）。
- 型別標註用 `typing.List/Dict/Optional/Tuple`，不可用 `list[str]`、`X | None`。
- 所有 Notion 呼叫都走 `retry_with_backoff(fn, rate_limiter)` + `NotionRateLimiter`；rich_text 每段 ≤ 2000 字（用 `split_rich_text`）。
- **只有** `src/infrastructure/notion/notion_views_client.py` 可使用非預設的 Notion-Version，固定為 `"2026-03-11"`，並一律經 `Client.request()` 送出（notion-client 2.2.1 的 `pages.create`／`pages.update` 會用白名單靜默丟掉不認得的參數）。
- Reading List 書頁**永不寫入** `推薦分數/5`、`Status`、`Done Date`、`Blog Link`、`slug`（`Status` 只由既有的自動建頁寫入）。
- 只處理 `page["created_by"]["id"] == users.me()["id"]` 的頁；版面只寫在空白頁（沒有 block，或只有沒文字的 paragraph）；每一段、每個屬性都只在空白時寫。
- 段落標題為 `heading_2`，文字固定為：`書籍資料`、`筆記圖`、`概要`、`實際執行`、`心得`、`金句摘錄`。
- 書封 URL：Kobo `https://cdn.kobo.com/book-images/{image_id}/353/569/90/False/image.jpg`；Open Library `https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false`。有效圖片 = HTTP 200 且 `content-type` 以 `image/` 開頭且內容 > 2048 bytes。
- `READING_LIST_PAGES`：空＝關閉；`all`＝全部；否則為逗號分隔的書名子字串（與 `RESYNC_HIGHLIGHTS` 同一個 parser）。
- DRY_RUN：讀取照常，寫入只記 `[DRY RUN]` log。
- M1 範圍外（留給 M2）：LLM、`is_finished`、`get_toc_titles`、`analysis_store`、`reading_list_output/`、`Summary 一言以蔽之`、心得段。

## Review Focus

spec 隱含、但最容易在真實使用時出錯的五種輸入／狀況（最可能的在前）；每一條都已在所屬 task 加上對應測試：

1. **integration 建的頁、但使用者已經打了一行字** → 不得在它後面接版面；屬性仍可在空白時補。→ Task 9 `test_page_with_user_text_gets_no_skeleton`
2. **`users.me()` 失敗（離線、token 權限）** → 一律視為「不是我們的頁」，整輪不寫任何書頁（寧可不做也不誤寫）。→ Task 3 `test_identity_failure_fails_closed`
3. **沒有 `ImageId` 的書（側載）＋ Google Books 回 429** → 不得寫入任何無效封面；Google 本輪不再查；Open Library 404 → 無封面，版面照寫但不放圖。→ Task 4 `test_google_quota_exhausted_falls_back_and_stops_asking`、Task 9 `test_no_cover_means_no_image_and_no_cover_update`
4. **Google 書名搜尋回傳別本書**（第一筆書名對不上）→ 跳過，不拿別人的封面。→ Task 4 `test_title_search_rejects_other_books`
5. **使用者把 integration 頁的「筆記圖」標題改了名** → gallery 跳過並 WARNING，絕不插到別處。→ Task 9 `test_renamed_notes_heading_skips_gallery`

---

### Task 1: 實測 Views API（一次性 spike）

**Files:**
- Create（**不進 repo**，放在你的暫存目錄）：`spike_views_api.py`
- Modify: `docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md`（「外部服務與套件」表中 Views API 那一列的備註欄）

**Interfaces:**
- Consumes: `.env` 的 `NOTION_TOKEN`、`NOTION_BOOKS_DATABASE_ID`、`NOTION_ZETTELKASTEN_DATABASE_ID`
- Produces: 經實測確認的 `POST /v1/views` body——Task 8 的 `card_gallery_body()` 以此為準

- [ ] **Step 1: 寫 spike 腳本**

在暫存目錄（不是 repo）建立 `spike_views_api.py`：

```python
"""Throwaway spike (Task 1): verify Views API create_database + after_block + filter.

Run from the repo root:  python <scratch>/spike_views_api.py [--keep]
Creates a temporary 📚 Personal Reading List page「_spike_讀書頁」, writes the six
section headings, creates a filtered card gallery right after「筆記圖」, prints
what Notion stored, then archives the page (unless --keep). Not committed.
"""
import json
import os
import sys

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(".env")
TOKEN = os.environ["NOTION_TOKEN"]
BOOKS_DB = os.environ["NOTION_BOOKS_DATABASE_ID"]
CARDS_DB = os.environ["NOTION_ZETTELKASTEN_DATABASE_ID"]
KEEP = "--keep" in sys.argv

old = Client(auth=TOKEN)                               # the app's API version
new = Client(auth=TOKEN, notion_version="2026-03-11")  # Views API


def h2(text):
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def label(block):
    kind = block["type"]
    rich = (block.get(kind) or {}).get("rich_text") or []
    text = "".join(r.get("plain_text", "") for r in rich)
    return f"{kind}:{text}" if text else kind


target = old.databases.query(
    database_id=BOOKS_DB,
    filter={"property": "Name", "title": {"contains": "多巴胺國度"}},
)["results"][0]["id"]
print("filter target (多巴胺國度 Reading List page):", target)

page = old.pages.create(
    parent={"database_id": BOOKS_DB},
    properties={"Name": {"title": [{"text": {"content": "_spike_讀書頁"}}]}},
)
page_id = page["id"]
print("spike page:", page.get("url"))
try:
    sections = ["書籍資料", "筆記圖", "概要", "實際執行", "心得", "金句摘錄"]
    created = old.blocks.children.append(
        block_id=page_id, children=[h2(s) for s in sections])["results"]
    notes_heading = created[1]["id"]

    ds_id = new.request(path=f"databases/{CARDS_DB}", method="GET")["data_sources"][0]["id"]
    body = {
        "data_source_id": ds_id,
        "name": "本書卡片",
        "type": "gallery",
        "create_database": {
            "parent": {"type": "page_id", "page_id": page_id},
            "position": {"type": "after_block", "block_id": notes_heading},
        },
        "filter": {"property": "來源", "relation": {"contains": target}},
        "sorts": [{"property": "標題", "direction": "ascending"}],
        "configuration": {"type": "gallery", "cover": {"type": "page_cover"}},
    }
    view = new.request(path="views", method="POST", body=body)
    print("created view:", json.dumps(
        {k: view.get(k) for k in ("id", "type", "parent", "data_source_id")},
        ensure_ascii=False))

    stored = new.request(path=f"views/{view['id']}", method="GET")
    print("stored filter:", json.dumps(stored.get("filter"), ensure_ascii=False))
    print("stored configuration:", json.dumps(stored.get("configuration"), ensure_ascii=False))

    order = [label(b) for b in old.blocks.children.list(block_id=page_id)["results"]]
    print("block order:", order)
    placed_ok = order[1] == "heading_2:筆記圖" and not order[2].startswith("heading")
    print("gallery placed right after 筆記圖:", placed_ok)

    matched = new.request(path=f"data_sources/{ds_id}/query", method="POST",
                          body={"filter": body["filter"]})
    print("cards matching the filter:", len(matched.get("results", [])), "(expect 17)")
    if not placed_ok:
        sys.exit("FAIL: gallery not placed after 筆記圖")
finally:
    if KEEP:
        print("--keep: page left in place; archive it manually when done:", page_id)
    else:
        old.pages.update(page_id=page_id, archived=True)
        print("spike page archived")
```

- [ ] **Step 2: 在 repo 根目錄執行**

Run: `PYTHONIOENCODING=utf-8 python <暫存目錄>/spike_views_api.py`

Expected（重點行）：
```
created view: {"id": "...", "type": "gallery", ...}
stored filter: {"property": "來源", "relation": {"contains": "<多巴胺國度書頁 id>"}}   ← 欄位可能以 property id 呈現，但必須是 relation contains 同一個頁 id
block order: ['heading_2:書籍資料', 'heading_2:筆記圖', '<非 heading 的 block>', 'heading_2:概要', ...]
gallery placed right after 筆記圖: True
cards matching the filter: 17 (expect 17)
spike page archived
```

- [ ] **Step 3: 判斷結果**

- 全部符合 → 做 Step 4。
- `POST views` 回 400 且錯誤訊息指到 `configuration` → 把腳本 body 的 `"configuration"` 那一行刪掉再跑一次。若成功：**開始 Task 8 之前**，先把本計畫 Task 8 Step 3 `card_gallery_body()` 裡的 `"configuration"` 那一行刪掉，並把 Task 8 Step 1 測試中 expected body 的 `"configuration"` 那一行也刪掉；Step 4 的紀錄註明「configuration 不支援，gallery 用預設卡片預覽」。
- 其他任何失敗（請求拋錯、`gallery placed right after 筆記圖: False`、比對到的卡片數不是 17）→ **停止**，把完整輸出貼給使用者並等待決定；不要開始後續任務。

- [ ] **Step 4: 把實測結果記進 spec**

把 spec「外部服務與套件」表中 Views API 那一列的備註欄，從
`依官方 reference（/reference/create-view）；M1 第一個任務實測確認`
改成
`依官方 reference（/reference/create-view）；M1 Task 1 實測通過（<執行當天日期>）：after_block 放置、relation 篩選、gallery page_cover 設定皆如預期`
（若 Step 3 走了 configuration 分支，改寫成實際結果。）

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md
git commit -m "📝 docs: 記錄 Views API 實測結果（M1 Task 1 spike）"
```

---

### Task 2: Books DB 邏輯抽出為 `ReadingListRepository`（純搬移，行為不變）

**Files:**
- Create: `src/infrastructure/notion/reading_list_repository.py`
- Modify: `src/infrastructure/notion/zettelkasten_card_repository.py`（刪 `:47-56` 常數、`:100-103` 兩個快取欄位、`:310-527` 十一個方法；改 class docstring 與 `__init__`；新增委派用 `_find_book_page`）
- Test (rewrite): `tests/unit/test_book_page_autocreate.py`

**Interfaces:**
- Consumes: 無（本 task 只搬移）
- Produces:
  - `ReadingListRepository(token: str, database_id: Optional[str], rate_limiter: Optional[NotionRateLimiter] = None, client: Optional[Client] = None)`
  - `ReadingListRepository.resolve_or_create(book_title: str, source_page_id: Optional[str] = None, percent_read: Optional[float] = None) -> Optional[str]`
  - 私有方法沿用原名：`_find_book_page`、`_reverse_lookup_book`、`_match_book_by_name`、`_backfill_kobo_relation`、`_create_book_page`、`_book_status_name`（staticmethod）、`_books_wants`、`_all_books_pages`、`_page_name`、`_main_title`、`_normalize`；屬性 `_books_database_id`、`_client`、`_rate_limiter`、`_books_pages_cache`、`_books_schema_props`
  - `ZettelkastenCardRepository(..., reading_list: Optional[ReadingListRepository] = None)`；屬性 `_reading_list`（沒有 Books DB 時為 None）

- [ ] **Step 1: 改寫測試，改測新類別並加上委派測試**

以下列內容**整檔取代** `tests/unit/test_book_page_autocreate.py`：

```python
"""ReadingListRepository — 書不在 Reading List 時自動建頁：Status 推導、
建頁 payload、Kobo relation 回填；以及卡片 repo 對它的委派。"""
import unittest

from src.infrastructure.notion.reading_list_repository import ReadingListRepository
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)


class _FakeLimiter:
    def wait(self):
        pass


class _FakePages:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.created.append(kwargs)
        return {"id": "new-books-page"}

    def update(self, **kwargs):
        self._parent.updated.append(kwargs)
        return {}


class _FakeDatabases:
    def __init__(self, parent, books_schema):
        self._parent = parent
        self._books_schema = books_schema

    def retrieve(self, database_id):
        return {"properties": self._books_schema}

    def query(self, **kwargs):
        self._parent.queries.append(kwargs)
        return {"results": [], "has_more": False}


class _FakeClient:
    def __init__(self, books_schema):
        self.created = []
        self.updated = []
        self.queries = []
        self.pages = _FakePages(self)
        self.databases = _FakeDatabases(self, books_schema)


_FULL_BOOKS_SCHEMA = {
    "Name": {"type": "title"},
    "Kobo EReader": {"type": "relation"},
    "Status": {"type": "select"},
}


def _make_repo(books_schema=None):
    return ReadingListRepository(
        token="fake-token",
        database_id="books-db",
        rate_limiter=_FakeLimiter(),
        client=_FakeClient(
            _FULL_BOOKS_SCHEMA if books_schema is None else books_schema
        ),
    )


class TestBookStatusName(unittest.TestCase):
    def test_finished_book(self):
        self.assertEqual(ReadingListRepository._book_status_name(100), "🔖閱讀完畢")
        self.assertEqual(ReadingListRepository._book_status_name(99), "🔖閱讀完畢")

    def test_in_progress_book(self):
        self.assertEqual(ReadingListRepository._book_status_name(42), "📖 閱讀中")

    def test_unknown_progress_counts_as_reading(self):
        self.assertEqual(ReadingListRepository._book_status_name(None), "📖 閱讀中")


class TestCreateBookPage(unittest.TestCase):
    def test_full_payload(self):
        repo = _make_repo()
        page_id = repo._create_book_page("多巴胺國度：副標", "kobo-page-1", 100)
        self.assertEqual(page_id, "new-books-page")

        created = repo._client.created[0]
        self.assertEqual(created["parent"], {"database_id": "books-db"})
        props = created["properties"]
        self.assertEqual(
            props["Name"]["title"][0]["text"]["content"], "多巴胺國度：副標")
        self.assertEqual(
            props["Kobo EReader"]["relation"], [{"id": "kobo-page-1"}])
        self.assertEqual(props["Status"]["select"]["name"], "🔖閱讀完畢")

    def test_no_source_page_skips_relation(self):
        repo = _make_repo()
        repo._create_book_page("佛教入門", None, 50)
        props = repo._client.created[0]["properties"]
        self.assertNotIn("Kobo EReader", props)
        self.assertEqual(props["Status"]["select"]["name"], "📖 閱讀中")

    def test_missing_schema_columns_skipped(self):
        repo = _make_repo(books_schema={"Name": {"type": "title"}})
        repo._create_book_page("佛教入門", "kobo-page-1", 100)
        props = repo._client.created[0]["properties"]
        self.assertEqual(set(props.keys()), {"Name"})

    def test_no_books_database_returns_none(self):
        repo = ReadingListRepository(
            token="fake-token", database_id=None,
            rate_limiter=_FakeLimiter(), client=_FakeClient({}),
        )
        self.assertIsNone(repo._create_book_page("x", None, None))


class TestBackfillKoboRelation(unittest.TestCase):
    def _page(self, relation):
        return {
            "id": "books-page-1",
            "properties": {
                "Name": {"type": "title", "title": []},
                "Kobo EReader": {"type": "relation", "relation": relation},
            },
        }

    def test_fills_empty_relation(self):
        repo = _make_repo()
        repo._backfill_kobo_relation(self._page([]), "kobo-page-1")
        updated = repo._client.updated[0]
        self.assertEqual(updated["page_id"], "books-page-1")
        self.assertEqual(
            updated["properties"]["Kobo EReader"]["relation"],
            [{"id": "kobo-page-1"}],
        )

    def test_existing_relation_untouched(self):
        repo = _make_repo()
        repo._backfill_kobo_relation(
            self._page([{"id": "already-linked"}]), "kobo-page-1")
        self.assertEqual(repo._client.updated, [])

    def test_page_without_property_untouched(self):
        repo = _make_repo()
        repo._backfill_kobo_relation(
            {"id": "p", "properties": {"Name": {"type": "title"}}}, "kobo-page-1")
        self.assertEqual(repo._client.updated, [])


class TestResolveOrCreate(unittest.TestCase):
    def test_falls_through_to_create(self):
        repo = _make_repo()
        page_id = repo.resolve_or_create("完全不存在的書", "kobo-page-1", 100)
        self.assertEqual(page_id, "new-books-page")
        # reverse lookup + equals + contains queries all ran and found nothing
        self.assertGreaterEqual(len(repo._client.queries), 3)


class TestCardRepositoryDelegates(unittest.TestCase):
    def test_builds_reading_list_sharing_client_and_limiter(self):
        limiter = _FakeLimiter()
        repo = ZettelkastenCardRepository(
            token="t", database_id="cards-db",
            books_database_id="books-db", rate_limiter=limiter,
        )
        self.assertIsInstance(repo._reading_list, ReadingListRepository)
        self.assertIs(repo._reading_list._client, repo._client)
        self.assertIs(repo._reading_list._rate_limiter, limiter)

    def test_no_books_database_means_no_reading_list(self):
        repo = ZettelkastenCardRepository(token="t", database_id="cards-db")
        self.assertIsNone(repo._reading_list)
        self.assertIsNone(repo.resolve_book_page("任何書"))

    def test_resolve_book_page_delegates(self):
        class _Spy:
            def __init__(self):
                self.calls = []

            def resolve_or_create(self, *args):
                self.calls.append(args)
                return "books-page-9"

        spy = _Spy()
        repo = ZettelkastenCardRepository(
            token="t", database_id="cards-db",
            books_database_id="books-db", reading_list=spy,
        )
        self.assertEqual(repo.resolve_book_page("書", "kobo-1", 50), "books-page-9")
        self.assertEqual(spy.calls, [("書", "kobo-1", 50)])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_book_page_autocreate.py -v`
Expected: 收集階段失敗，`ModuleNotFoundError: No module named 'src.infrastructure.notion.reading_list_repository'`

- [ ] **Step 3a: 建立 `reading_list_repository.py` 的外殼**

建立 `src/infrastructure/notion/reading_list_repository.py`：

```python
"""Notion repository for 📚 Personal Reading List (the Books DB).

Everything that touches the Books DB lives here: resolving a book's page for
the card「來源」relation — reverse lookup via the `Kobo EReader` relation →
title match → auto-create — moved unchanged from ZettelkastenCardRepository,
which now delegates to this class.
"""
import logging
from typing import List, Optional

from notion_client import Client

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

_RICH_TEXT_LIMIT = 2000
# Books DB title property + the relation on it that points back at the Kobo DB.
_BOOKS_TITLE_PROPERTY = "Name"
_KOBO_RELATION_PROPERTY = "Kobo EReader"
# Books DB reading status (select). Option names must match the DB exactly —
# note the space in "📖 閱讀中".
_BOOKS_STATUS_PROPERTY = "Status"
_BOOK_STATUS_DONE = "🔖閱讀完畢"
_BOOK_STATUS_READING = "📖 閱讀中"
# Kobo ___PercentRead is 0-100; at/above this the book counts as finished.
_BOOK_DONE_PERCENT = 99

# sentinel: not yet fetched (distinct from "fetched, empty/unreadable").
_UNSET = object()


class ReadingListRepository:
    """Books-DB (Personal Reading List) access.

    `client` is injectable so ZettelkastenCardRepository can share its client
    and rate limiter, and so tests can pass a fake.
    """

    def __init__(
        self,
        token: str,
        database_id: Optional[str],
        rate_limiter: Optional[NotionRateLimiter] = None,
        client: Optional[Client] = None,
    ):
        self._books_database_id = database_id
        self._client = client or Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        # full Books-DB page list, fetched once for name-based matching
        self._books_pages_cache = _UNSET
        # Books-DB property names; _UNSET until fetched, None if unreadable
        self._books_schema_props = _UNSET

    def resolve_or_create(
        self,
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> Optional[str]:
        """Books-DB page id for a book, auto-creating the page when unlisted."""
        return self._find_book_page(book_title, source_page_id, percent_read)

    # ----- Internals (moved unchanged from ZettelkastenCardRepository) -----
```

- [ ] **Step 3b: 原樣搬移十一個方法**

在 `src/infrastructure/notion/zettelkasten_card_repository.py` 中，**剪下**第 310 行（`    def _find_book_page(`）到第 527 行（`_normalize` 的 `return " ".join(...)`）這一整段，**一字不改**貼到 `reading_list_repository.py` 檔尾（接在 `# ----- Internals ...` 註解之後，保持 4 格縮排）。這段依序包含：`_find_book_page`、`_reverse_lookup_book`、`_match_book_by_name`、`_backfill_kobo_relation`、`_create_book_page`、`_book_status_name`、`_books_wants`、`_all_books_pages`、`_page_name`、`_main_title`、`_normalize`。它們用到的常數（`_BOOKS_TITLE_PROPERTY`、`_KOBO_RELATION_PROPERTY`、`_BOOKS_STATUS_PROPERTY`、`_BOOK_STATUS_DONE`、`_BOOK_STATUS_READING`、`_BOOK_DONE_PERCENT`、`_RICH_TEXT_LIMIT`、`_UNSET`）與 import（`List`、`Optional`、`retry_with_backoff`）都已在 Step 3a 的外殼中定義。

- [ ] **Step 3c: 卡片 repo 改為委派**

在 `src/infrastructure/notion/zettelkasten_card_repository.py`：

1. 刪除第 47–56 行（`# Books DB title property + ...` 到 `_BOOK_DONE_PERCENT = 99`）。
2. 在 `from .rate_limiter import NotionRateLimiter` 與 `from .retry_policy import retry_with_backoff` 之間加入：

```python
from .reading_list_repository import ReadingListRepository
```

3. 把 class docstring 與整個 `__init__` 換成：

```python
class ZettelkastenCardRepository:
    """Uploads Zettelkasten cards to the Notion 卡片盒 database.

    The `來源` relation targets the Books DB (Personal Reading List), not the
    Kobo highlights DB. Resolving it (reverse lookup → title match →
    auto-create) is delegated to ReadingListRepository; only if that fails too
    is the card left unlinked.
    """

    def __init__(
        self,
        token: str,
        database_id: str,
        books_database_id: Optional[str] = None,
        rate_limiter: Optional[NotionRateLimiter] = None,
        tag_categories: Optional[List[str]] = None,
        reading_list: Optional[ReadingListRepository] = None,
    ):
        self._database_id = database_id
        self._books_database_id = books_database_id
        self._client = Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        # fixed Tags classification list (DI from settings); [] → don't seed/filter
        self._tag_categories = list(tag_categories or [])
        # cached card-DB property names; _UNSET until first fetched, None if unreadable
        self._schema_props = _UNSET
        # E1 auto-create-columns runs once per process
        self._schema_ensured = False
        # Books DB（Personal Reading List）的查找／自動建頁交給 ReadingListRepository；
        # 沒注入時自建一個，共用本 repo 的 client 與限速器。
        if reading_list is None and books_database_id:
            reading_list = ReadingListRepository(
                token=token,
                database_id=books_database_id,
                rate_limiter=self._rate_limiter,
                client=self._client,
            )
        self._reading_list = reading_list
```

4. 在原本 `_find_book_page` 所在的位置（`_build_visuals` 之後、`_existing_source_ids` 之前）放入委派方法：

```python
    def _find_book_page(
        self,
        book_title: str,
        source_page_id: Optional[str] = None,
        percent_read: Optional[float] = None,
    ) -> Optional[str]:
        """E4: Books-DB page for a card's 來源 relation — reverse lookup → title
        match → auto-create, implemented in ReadingListRepository."""
        if self._reading_list is None:
            return None
        return self._reading_list.resolve_or_create(
            book_title, source_page_id, percent_read
        )
```

`upload_cards` 與 `resolve_book_page` 都呼叫 `self._find_book_page(...)`，不用改。

- [ ] **Step 4: 驗證搬移完整、測試全綠**

Run: `grep -nE "def (_reverse_lookup_book|_match_book_by_name|_backfill_kobo_relation|_create_book_page|_book_status_name|_books_wants|_all_books_pages|_page_name|_main_title|_normalize)" src/infrastructure/notion/zettelkasten_card_repository.py`
Expected: 沒有輸出（這些方法已全部搬走）

Run: `python -m pytest tests/unit/test_book_page_autocreate.py -v`
Expected: 14 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 356 passed（353 − 11 舊 + 14 新）；`All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/reading_list_repository.py src/infrastructure/notion/zettelkasten_card_repository.py tests/unit/test_book_page_autocreate.py
git commit -m "♻️ refactor: Books DB 邏輯抽出為 ReadingListRepository（行為不變）"
```

---

### Task 3: `ReadingListRepository` 書頁讀寫

**Files:**
- Modify: `src/infrastructure/notion/reading_list_repository.py`
- Test: `tests/unit/test_reading_list_repository.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `ReadingListRepository`、`_match_book_by_name`
- Produces:
  - 模組常數 `BOOK_TYPE_PROPERTY = "Type 書籍種類"`
  - `find_page(title: str, source_page_id: Optional[str] = None) -> Optional[dict]`（反查 → 書名比對；**絕不建頁**；回傳完整 page 物件，含 `id`、`created_by`、`cover`、`icon`、`properties`）
  - `is_created_by_integration(page: dict) -> bool`
  - `list_blocks(page_id: str) -> List[dict]`
  - `append_blocks(page_id: str, blocks: List[dict], after: Optional[str] = None) -> List[dict]`（回傳建立的頂層 block）
  - `update_page(page_id: str, properties: Optional[dict] = None, cover_url: Optional[str] = None, icon_url: Optional[str] = None) -> None`
  - `type_page_ids(names: List[str]) -> Dict[str, str]`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_reading_list_repository.py`：

```python
"""ReadingListRepository — Reading List 書頁補完需要的讀寫（M1）。"""
import unittest
from types import SimpleNamespace

from src.infrastructure.notion.reading_list_repository import (
    BOOK_TYPE_PROPERTY,
    ReadingListRepository,
)


class _NoWait:
    def wait(self):
        pass


class _FakeClient:
    """記錄每次呼叫；回應由各測試設定。"""

    def __init__(self):
        self.me_calls = 0
        self.me_error = None
        self.queries = []          # (database_id, kwargs)
        self.query_results = {}    # database_id -> list of pages
        self.children = {}         # block_id -> list of blocks
        self.appends = []          # kwargs of each append
        self.updates = []          # kwargs of each pages.update
        self.dbs = {}              # database_id -> retrieve() result
        self.users = SimpleNamespace(me=self._me)
        self.blocks = SimpleNamespace(
            children=SimpleNamespace(list=self._list, append=self._append))
        self.pages = SimpleNamespace(update=self._update, create=self._create)
        self.databases = SimpleNamespace(query=self._query, retrieve=self._retrieve)

    def _me(self):
        self.me_calls += 1
        if self.me_error:
            raise self.me_error
        return {"object": "user", "id": "bot-1", "type": "bot"}

    def _list(self, block_id, page_size=100, start_cursor=None):
        items = self.children.get(block_id, [])
        start = int(start_cursor or 0)
        end = start + 2  # tiny pages so pagination is exercised
        more = end < len(items)
        return {"results": items[start:end], "has_more": more,
                "next_cursor": str(end) if more else None}

    def _append(self, block_id, children, after=None):
        self.appends.append({"block_id": block_id, "children": children, "after": after})
        n = len(self.appends)
        return {"results": [{"id": f"a{n}-{i}"} for i in range(len(children))]}

    def _update(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def _create(self, **kwargs):
        raise AssertionError("find_page must never create a page")

    def _query(self, database_id, **kwargs):
        self.queries.append((database_id, kwargs))
        return {"results": list(self.query_results.get(database_id, [])),
                "has_more": False}

    def _retrieve(self, database_id):
        return self.dbs.get(database_id, {"properties": {}})


def _repo(client=None, database_id="books-db"):
    return ReadingListRepository(
        token="t", database_id=database_id,
        rate_limiter=_NoWait(), client=client or _FakeClient(),
    )


def _type_page(page_id, name):
    return {"id": page_id, "properties": {
        "領域（標籤名）": {"type": "title", "title": [{"plain_text": name}]}}}


class TestFindPage(unittest.TestCase):
    def test_reverse_lookup_returns_full_page(self):
        client = _FakeClient()
        page = {"id": "rl-1", "created_by": {"id": "bot-1"}, "properties": {}}
        client.query_results["books-db"] = [page]
        self.assertIs(_repo(client).find_page("書", "kobo-1"), page)
        self.assertEqual(
            client.queries[0][1]["filter"]["relation"], {"contains": "kobo-1"})

    def test_not_found_never_creates(self):
        self.assertIsNone(_repo().find_page("完全不存在的書", "kobo-1"))

    def test_no_database_returns_none(self):
        self.assertIsNone(_repo(database_id=None).find_page("書", "kobo-1"))


class TestCreatedByIntegration(unittest.TestCase):
    def test_bot_created_page(self):
        self.assertTrue(
            _repo().is_created_by_integration({"created_by": {"id": "bot-1"}}))

    def test_user_created_page(self):
        self.assertFalse(
            _repo().is_created_by_integration({"created_by": {"id": "user-9"}}))

    def test_bot_identity_fetched_once(self):
        client = _FakeClient()
        repo = _repo(client)
        repo.is_created_by_integration({"created_by": {"id": "bot-1"}})
        repo.is_created_by_integration({"created_by": {"id": "bot-1"}})
        self.assertEqual(client.me_calls, 1)

    def test_identity_failure_fails_closed(self):
        client = _FakeClient()
        client.me_error = RuntimeError("offline")
        with self.assertLogs(
            "src.infrastructure.notion.reading_list_repository", level="WARNING"
        ):
            self.assertFalse(
                _repo(client).is_created_by_integration({"created_by": {"id": "bot-1"}}))


class TestListBlocks(unittest.TestCase):
    def test_paginates_in_order(self):
        client = _FakeClient()
        client.children["page-1"] = [{"id": f"b{i}"} for i in range(5)]
        blocks = _repo(client).list_blocks("page-1")
        self.assertEqual([b["id"] for b in blocks], ["b0", "b1", "b2", "b3", "b4"])


class TestAppendBlocks(unittest.TestCase):
    def test_single_batch_after_anchor(self):
        client = _FakeClient()
        created = _repo(client).append_blocks("page-1", [{"x": 1}] * 3, after="h-1")
        self.assertEqual(len(client.appends), 1)
        self.assertEqual(client.appends[0]["after"], "h-1")
        self.assertEqual(len(created), 3)

    def test_batches_chain_after_last_created(self):
        client = _FakeClient()
        created = _repo(client).append_blocks("page-1", [{"x": 1}] * 150)
        self.assertEqual(len(client.appends), 2)
        self.assertIsNone(client.appends[0]["after"])
        self.assertEqual(len(client.appends[0]["children"]), 100)
        self.assertEqual(client.appends[1]["after"], "a1-99")
        self.assertEqual(len(created), 150)


class TestUpdatePage(unittest.TestCase):
    def test_cover_icon_and_properties_in_one_call(self):
        client = _FakeClient()
        _repo(client).update_page(
            "page-1", properties={"P": {"x": 1}},
            cover_url="https://c/cover.jpg", icon_url="https://c/cover.jpg")
        self.assertEqual(client.updates, [{
            "page_id": "page-1",
            "properties": {"P": {"x": 1}},
            "cover": {"type": "external", "external": {"url": "https://c/cover.jpg"}},
            "icon": {"type": "external", "external": {"url": "https://c/cover.jpg"}},
        }])

    def test_nothing_to_update_skips_call(self):
        client = _FakeClient()
        _repo(client).update_page("page-1")
        self.assertEqual(client.updates, [])


class TestTypePageIds(unittest.TestCase):
    def _client(self):
        client = _FakeClient()
        client.dbs["books-db"] = {"properties": {BOOK_TYPE_PROPERTY: {
            "type": "relation", "relation": {"database_id": "types-db"}}}}
        client.query_results["types-db"] = [
            _type_page("t-psy", "Psychology"), _type_page("t-mkt", "Marketing")]
        return client

    def test_resolves_names_via_relation_target(self):
        repo = _repo(self._client())
        self.assertEqual(
            repo.type_page_ids(["Psychology", "Nope"]), {"Psychology": "t-psy"})

    def test_index_is_cached(self):
        client = self._client()
        repo = _repo(client)
        repo.type_page_ids(["Psychology"])
        repo.type_page_ids(["Marketing"])
        type_queries = [q for q in client.queries if q[0] == "types-db"]
        self.assertEqual(len(type_queries), 1)

    def test_books_db_without_type_property(self):
        with self.assertLogs(
            "src.infrastructure.notion.reading_list_repository", level="WARNING"
        ):
            self.assertEqual(_repo().type_page_ids(["Psychology"]), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_reading_list_repository.py -v`
Expected: `ImportError: cannot import name 'BOOK_TYPE_PROPERTY'`

- [ ] **Step 3: 實作**

在 `src/infrastructure/notion/reading_list_repository.py`：

1. `from typing import List, Optional` 改成 `from typing import Dict, List, Optional`。
2. 在 `_UNSET = object()` 之前加入：

```python
# Reading List 書頁補完
BOOK_TYPE_PROPERTY = "Type 書籍種類"
_MAX_CHILDREN_PER_REQUEST = 100
```

3. 在 `__init__` 結尾（`self._books_schema_props = _UNSET` 之後）加入：

```python
        # integration（bot）的 user id；_UNSET = 尚未查詢，None = 查詢失敗
        self._bot_id = _UNSET
        # 書籍種類名稱 → 種類庫頁 id；_UNSET = 尚未查詢
        self._type_index_cache = _UNSET
```

4. 在 `resolve_or_create` 之後、`# ----- Internals` 註解之前加入：

```python
    # ----- Reading List 書頁補完：讀寫書頁本身 -----

    def find_page(self, title: str, source_page_id: Optional[str] = None) -> Optional[dict]:
        """Books-DB page object — reverse lookup, then title match. Unlike
        resolve_or_create this never creates a page."""
        if not self._books_database_id:
            return None
        if source_page_id:
            page = self._reverse_lookup_page(source_page_id)
            if page is not None:
                return page
        return self._match_book_by_name(title)

    def is_created_by_integration(self, page: dict) -> bool:
        """Whether this integration created the page. Fails closed: if our own
        identity can't be read, nothing counts as ours (so nothing is written)."""
        creator = ((page or {}).get("created_by") or {}).get("id")
        bot_id = self._bot_user_id()
        return bool(creator) and creator == bot_id

    def list_blocks(self, page_id: str) -> List[dict]:
        """All top-level blocks of a page, in order."""
        blocks: List[dict] = []
        cursor: Optional[str] = None
        while True:
            kwargs = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = retry_with_backoff(
                lambda k=kwargs: self._client.blocks.children.list(**k),
                self._rate_limiter,
            ) or {}
            blocks.extend(response.get("results", []))
            if not response.get("has_more"):
                return blocks
            cursor = response.get("next_cursor")

    def append_blocks(
        self, page_id: str, blocks: List[dict], after: Optional[str] = None
    ) -> List[dict]:
        """Append (or insert after `after`) top-level blocks; returns the created
        blocks. Batches chain on the last created block so order is kept."""
        created: List[dict] = []
        for i in range(0, len(blocks), _MAX_CHILDREN_PER_REQUEST):
            kwargs = {
                "block_id": page_id,
                "children": blocks[i:i + _MAX_CHILDREN_PER_REQUEST],
            }
            anchor = created[-1]["id"] if created else after
            if anchor:
                kwargs["after"] = anchor
            response = retry_with_backoff(
                lambda k=kwargs: self._client.blocks.children.append(**k),
                self._rate_limiter,
            ) or {}
            created.extend(response.get("results", []))
        return created

    def update_page(
        self,
        page_id: str,
        properties: Optional[dict] = None,
        cover_url: Optional[str] = None,
        icon_url: Optional[str] = None,
    ) -> None:
        """One pages.update carrying whatever was given; no-op when empty."""
        kwargs: dict = {"page_id": page_id}
        if properties:
            kwargs["properties"] = properties
        if cover_url:
            kwargs["cover"] = {"type": "external", "external": {"url": cover_url}}
        if icon_url:
            kwargs["icon"] = {"type": "external", "external": {"url": icon_url}}
        if len(kwargs) == 1:
            return
        retry_with_backoff(
            lambda: self._client.pages.update(**kwargs), self._rate_limiter
        )

    def type_page_ids(self, names: List[str]) -> Dict[str, str]:
        """書籍種類名稱 → 種類庫的頁 id（只回傳找得到的名稱）。"""
        index = self._type_index()
        return {name: index[name] for name in names if name in index}

    def _bot_user_id(self) -> Optional[str]:
        if self._bot_id is _UNSET:
            try:
                me = retry_with_backoff(
                    lambda: self._client.users.me(), self._rate_limiter
                ) or {}
                self._bot_id = me.get("id")
            except Exception as e:
                logger.warning(f"讀取 integration 身分失敗，本輪不補任何書頁: {e}")
                self._bot_id = None
        return self._bot_id

    def _type_index(self) -> Dict[str, str]:
        """種類庫全部頁面的 名稱 → id。種類庫由 Books DB 的 relation 目標決定，
        名稱取該庫 type == "title" 的欄位——兩者都不寫死。每輪只查一次。"""
        if self._type_index_cache is not _UNSET:
            return self._type_index_cache
        index: Dict[str, str] = {}
        try:
            db = retry_with_backoff(
                lambda: self._client.databases.retrieve(self._books_database_id),
                self._rate_limiter,
            ) or {}
            prop = (db.get("properties") or {}).get(BOOK_TYPE_PROPERTY) or {}
            target = (prop.get("relation") or {}).get("database_id")
            if not target:
                logger.warning(f"Books DB 沒有「{BOOK_TYPE_PROPERTY}」relation，不填書籍種類")
            else:
                for page in self._query_all(target):
                    name = self._title_of(page)
                    if name:
                        index[name] = page.get("id")
        except Exception as e:
            logger.warning(f"讀取書籍種類庫失敗: {e}")
        self._type_index_cache = index
        return index

    def _query_all(self, database_id: str) -> List[dict]:
        pages: List[dict] = []
        cursor: Optional[str] = None
        while True:
            kwargs = {"database_id": database_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            result = retry_with_backoff(
                lambda k=kwargs: self._client.databases.query(**k),
                self._rate_limiter,
            ) or {}
            pages.extend(result.get("results", []))
            if not result.get("has_more"):
                return pages
            cursor = result.get("next_cursor")

    @staticmethod
    def _title_of(page: dict) -> str:
        for prop in (page.get("properties") or {}).values():
            if (prop or {}).get("type") == "title":
                return "".join(
                    t.get("plain_text", "") for t in prop.get("title") or []
                ).strip()
        return ""

    def _reverse_lookup_page(self, source_page_id: str) -> Optional[dict]:
        """Books page (full object) whose `Kobo EReader` relation contains the
        highlight page."""
        try:
            result = retry_with_backoff(
                lambda: self._client.databases.query(
                    database_id=self._books_database_id,
                    filter={
                        "property": _KOBO_RELATION_PROPERTY,
                        "relation": {"contains": source_page_id},
                    },
                    page_size=1,
                ),
                self._rate_limiter,
            ) or {}
            results = result.get("results") or []
            if results:
                return results[0]
        except Exception as e:
            logger.warning(f"Books DB 反查（{_KOBO_RELATION_PROPERTY}）失敗: {e}")
        return None
```

5. 把搬來的 `_reverse_lookup_book` 整個方法換成（共用上面的 `_reverse_lookup_page`，行為不變）：

```python
    def _reverse_lookup_book(self, source_page_id: str) -> Optional[str]:
        page = self._reverse_lookup_page(source_page_id)
        return page.get("id") if page else None
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_reading_list_repository.py tests/unit/test_book_page_autocreate.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/reading_list_repository.py tests/unit/test_reading_list_repository.py
git commit -m "✨ feat: ReadingListRepository 書頁讀寫（找頁不建頁、列／插入 block、更新屬性、書籍種類對照）"
```

---

### Task 4: `CoverFinder`（Kobo 圖床優先、逐張驗證）＋ `Book.image_id`

**Files:**
- Modify: `src/domain/entities/book.py`
- Modify: `src/infrastructure/persistence/kobo_sqlite_repository.py:26-35`（`_BOOK_QUERY`）、`:74-100`（`get_all_books`）
- Modify: `tests/unit/test_highlight_filter.py`（fixture schema 加 `ImageId`；新增一個測試）
- Rewrite: `src/infrastructure/external/cover_fetcher.py`（新程式＋暫留的舊介面區塊，Task 5 刪除）
- Test: `tests/unit/test_cover_finder.py`（新建）

**Interfaces:**
- Consumes: 無
- Produces:
  - `Book.image_id: Optional[str] = None`
  - `cover_fetcher.KOBO_CDN_URL`、`cover_fetcher.OPEN_LIBRARY_URL`（format 字串）
  - `is_real_isbn13(isbn: Optional[str]) -> bool`
  - `is_legacy_openlibrary_url(url: Optional[str]) -> bool`
  - `CoverFinder(google_api_key: Optional[str] = None, http_get: Optional[Callable] = None)`；`.find(book: Book) -> Optional[str]`；`.is_valid_image(url: Optional[str]) -> bool`
  - 舊函式 `get_google_books_cover`、`get_openlibrary_cover`、`get_best_book_cover` 本 task **原樣保留**在檔尾的「舊介面」區塊（`NotionApiRepository.add_book_cover` 還在用），Task 5 換掉唯一呼叫點時一併刪除；`legacy/` 有自己的副本，不受影響

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_cover_finder.py`：

```python
"""CoverFinder — Kobo 圖床優先、Google Books／Open Library 遞補、每張圖都驗證。"""
import unittest

import requests

from src.domain.entities.book import Book
from src.infrastructure.external.cover_fetcher import (
    KOBO_CDN_URL,
    CoverFinder,
    is_legacy_openlibrary_url,
    is_real_isbn13,
)

_GOOGLE = "https://www.googleapis.com/"


class _Resp:
    def __init__(self, status=200, ctype="image/jpeg", size=5000, payload=None):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.content = b"x" * size
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeHttp:
    """依序比對路由；沒對到的一律回 404 html。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        for match, resp in self.routes:
            if match(url, params or {}):
                return resp
        return _Resp(status=404, ctype="text/html", size=10)


def _book(**overrides):
    fields = dict(id="b1", title="多巴胺國度：在縱慾年代找到身心平衡",
                  isbn="9786267195185", image_id="img-1")
    fields.update(overrides)
    return Book(**fields)


def _google_calls(http):
    return [c for c in http.calls if c[0].startswith(_GOOGLE)]


class TestCoverFinder(unittest.TestCase):
    def test_kobo_cdn_is_first_and_enough(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://cdn.kobo.com/"), _Resp())])
        self.assertEqual(
            CoverFinder(http_get=http).find(_book()),
            KOBO_CDN_URL.format(image_id="img-1"))
        self.assertEqual(len(http.calls), 1)

    def test_google_isbn_when_no_image_id(self):
        payload = {"items": [{"volumeInfo": {
            "title": "多巴胺國度",
            "imageLinks": {"thumbnail": "http://books.google.com/x?id=1&zoom=1"}}}]}
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE) and p.get("q") == "isbn:9786267195185",
             _Resp(ctype="application/json", payload=payload)),
            (lambda u, p: u == "http://books.google.com/x?id=1&zoom=3", _Resp()),
        ])
        self.assertEqual(
            CoverFinder(http_get=http).find(_book(image_id=None)),
            "http://books.google.com/x?id=1&zoom=3")

    def test_google_quota_exhausted_falls_back_and_stops_asking(self):
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE), _Resp(status=429, ctype="application/json")),
            (lambda u, p: u.startswith("https://covers.openlibrary.org/"),
             _Resp(status=404, ctype="text/html", size=10)),
        ])
        finder = CoverFinder(http_get=http)
        with self.assertLogs("src.infrastructure.external.cover_fetcher", level="WARNING"):
            self.assertIsNone(finder.find(_book(image_id=None)))
        self.assertEqual(len(_google_calls(http)), 1)  # 429 後同一本書不再查書名
        self.assertIsNone(finder.find(_book(id="b2", image_id=None)))
        self.assertEqual(len(_google_calls(http)), 1)  # 第二本書完全不問 Google

    def test_title_search_rejects_other_books(self):
        payload = {"items": [
            {"volumeInfo": {"title": "多巴胺的秘密",
                            "imageLinks": {"thumbnail": "http://g/wrong&zoom=1"}}},
            {"volumeInfo": {"title": "多巴胺國度",
                            "imageLinks": {"thumbnail": "http://g/right&zoom=1"}}},
        ]}
        http = _FakeHttp([
            (lambda u, p: u.startswith(_GOOGLE) and p.get("q") == "intitle:多巴胺國度",
             _Resp(ctype="application/json", payload=payload)),
            (lambda u, p: u.startswith("http://g/"), _Resp()),
        ])
        url = CoverFinder(http_get=http).find(_book(image_id=None, isbn="7363579164627"))
        self.assertEqual(url, "http://g/right&zoom=3")
        self.assertNotIn("http://g/wrong&zoom=3", [c[0] for c in http.calls])

    def test_placeholder_gif_rejected(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://cdn.kobo.com/"),
                           _Resp(ctype="image/gif", size=43))])
        self.assertIsNone(CoverFinder(http_get=http).find(_book(isbn="7363579164627")))

    def test_open_library_used_for_real_isbn(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://covers.openlibrary.org/"),
                           _Resp())])
        url = CoverFinder(http_get=http).find(_book(image_id=None))
        self.assertEqual(
            url, "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg?default=false")

    def test_result_cached_per_book(self):
        http = _FakeHttp([(lambda u, p: u.startswith("https://cdn.kobo.com/"), _Resp())])
        finder = CoverFinder(http_get=http)
        finder.find(_book())
        finder.find(_book())
        self.assertEqual(len(http.calls), 1)

    def test_api_key_sent_to_google(self):
        http = _FakeHttp([])
        CoverFinder(google_api_key="k-1", http_get=http).find(_book(image_id=None))
        google = [p for u, p in _google_calls(http)]
        self.assertTrue(google)
        self.assertTrue(all(p.get("key") == "k-1" for p in google))

    def test_network_error_is_not_fatal(self):
        def boom(url, params=None, timeout=None):
            raise requests.ConnectionError("offline")

        self.assertIsNone(CoverFinder(http_get=boom).find(_book()))


class TestHelpers(unittest.TestCase):
    def test_real_isbn13(self):
        self.assertTrue(is_real_isbn13("9786267195185"))
        self.assertTrue(is_real_isbn13(" 9791234567890 "))
        self.assertFalse(is_real_isbn13("7363579164627"))  # Kobo 內部 id
        self.assertFalse(is_real_isbn13(None))

    def test_legacy_openlibrary_url(self):
        self.assertTrue(is_legacy_openlibrary_url(
            "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg"))
        self.assertFalse(is_legacy_openlibrary_url(
            "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg?default=false"))
        self.assertFalse(is_legacy_openlibrary_url(KOBO_CDN_URL.format(image_id="x")))
        self.assertFalse(is_legacy_openlibrary_url(None))


if __name__ == "__main__":
    unittest.main()
```

在 `tests/unit/test_highlight_filter.py`：

1. `_create_db` 的 `CREATE TABLE content` 欄位清單最後一段從 `"VolumeIndex INTEGER, Depth INTEGER)"` 改為 `"VolumeIndex INTEGER, Depth INTEGER, ImageId TEXT)"`。
2. 在 `TestBookmarkTypeFilter` 的 `test_book_with_only_dogears_not_listed` 之後加入：

```python
    def test_book_carries_kobo_image_id(self):
        """content.ImageId 帶進 Book.image_id（Kobo 圖床封面用）"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE content SET ImageId = 'img-123' WHERE ContentID = ?", (_BOOK,))
        conn.commit()
        conn.close()
        books = self.repo.get_all_books()
        self.assertEqual([b.image_id for b in books], ["img-123"])
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_cover_finder.py tests/unit/test_highlight_filter.py -v`
Expected: `test_cover_finder.py` 收集失敗 `ImportError: cannot import name 'KOBO_CDN_URL'`；`test_book_carries_kobo_image_id` 失敗 `AttributeError: 'Book' object has no attribute 'image_id'`

- [ ] **Step 3: 實作**

`src/domain/entities/book.py`：在 `last_time_finished_reading: Optional[datetime] = None` 之後加一行：

```python
    image_id: Optional[str] = None  # Kobo content.ImageId → Kobo 圖床書封
```

`src/infrastructure/persistence/kobo_sqlite_repository.py`：

1. `_BOOK_QUERY` 的 `"content.LastTimeFinishedReading, content.ISBN "` 改為 `"content.LastTimeFinishedReading, content.ISBN, content.ImageId "`。
2. `get_all_books` 的解包與建構改為：

```python
                for row in conn.execute(_BOOK_QUERY).fetchall():
                    (cid, title, subtitle, author, date_last_read,
                     time_spent, description, publisher, percent_read,
                     last_finished, isbn, image_id) = row
                    books.append(Book(
                        id=cid,
                        title=title or '',
                        subtitle=subtitle,
                        author=author,
                        publisher=publisher,
                        isbn=isbn,
                        description=description,
                        percent_read=percent_read,
                        date_last_read=date_last_read,
                        time_spent_reading=time_spent,
                        last_time_finished_reading=last_finished,
                        image_id=image_id,
                    ))
```

以下列內容**整檔取代** `src/infrastructure/external/cover_fetcher.py`：

```python
"""Book covers for Kobo highlight pages and Reading List pages.

Sources, first *validated* hit wins (spec 2026-09-28「封面」):
1. Kobo's own CDN via content.ImageId — exact edition, no quota
   (35/35 in the 2026-09-28 survey);
2. Google Books — real ISBN-13 first, then a main-title search whose result
   title must match; optional API key (keyless calls share one global daily
   quota and mostly return 429, which is how 20/26 covers went blank);
3. Open Library by real ISBN-13 with ?default=false (404 when no cover).

Every candidate is downloaded and checked, so a 1x1 placeholder can never be
written as a "cover" again.
"""
import logging
import re
import threading
import unicodedata
from typing import Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

KOBO_CDN_URL = "https://cdn.kobo.com/book-images/{image_id}/353/569/90/False/image.jpg"
OPEN_LIBRARY_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_MIN_IMAGE_BYTES = 2048
_TIMEOUT = 8.0
_ISBN13 = re.compile(r"^97[89]\d{10}$")


def is_real_isbn13(isbn: Optional[str]) -> bool:
    """Kobo's ISBN column often holds internal ids (e.g. 7363579164627)."""
    return bool(_ISBN13.match((isbn or "").strip()))


def is_legacy_openlibrary_url(url: Optional[str]) -> bool:
    """Open Library URLs written before validation existed: they answer with a
    1x1 placeholder instead of 404 when the book has no cover."""
    return bool(url) and "covers.openlibrary.org" in url and "default=false" not in url


def _title_core(text: str) -> str:
    """Letters/digits only — same idea as the card classifier's text core."""
    return "".join(
        ch for ch in (text or "") if unicodedata.category(ch)[0] in ("L", "N")
    ).lower()


def _main_title(title: str) -> str:
    return re.split(r"[:：]", title or "", maxsplit=1)[0].strip()


class CoverFinder:
    """Finds and validates one cover URL per book; cached for the whole run.

    Shared by the highlight-page cover step (runs in the sync thread pool) and
    Reading List page completion (runs afterwards), so each book is looked up
    once. `http_get` is injectable for tests (signature of requests.get).
    """

    def __init__(self, google_api_key: Optional[str] = None,
                 http_get: Optional[Callable] = None):
        self._google_api_key = google_api_key
        self._http_get = http_get or requests.get
        self._cache: Dict[str, Optional[str]] = {}
        self._lock = threading.Lock()
        self._google_exhausted = False

    def find(self, book) -> Optional[str]:
        key = book.id or book.title
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        url = (self._from_kobo(book) or self._from_google(book)
               or self._from_open_library(book))
        if url is None:
            logger.info(f"找不到 '{book.title}' 的封面")
        with self._lock:
            self._cache[key] = url
        return url

    def is_valid_image(self, url: Optional[str]) -> bool:
        if not url:
            return False
        try:
            response = self._http_get(url, timeout=_TIMEOUT)
        except requests.RequestException as e:
            logger.debug(f"封面驗證失敗 {url}: {e}")
            return False
        content_type = (response.headers or {}).get("content-type", "")
        return (response.status_code == 200
                and content_type.startswith("image/")
                and len(response.content or b"") > _MIN_IMAGE_BYTES)

    # ----- sources -----

    def _from_kobo(self, book) -> Optional[str]:
        image_id = (getattr(book, "image_id", None) or "").strip()
        if not image_id:
            return None
        url = KOBO_CDN_URL.format(image_id=image_id)
        return url if self.is_valid_image(url) else None

    def _from_google(self, book) -> Optional[str]:
        queries = []
        if is_real_isbn13(book.isbn):
            queries.append((f"isbn:{book.isbn.strip()}", 1, ""))
        main = _main_title(book.title)
        if main:
            queries.append((f"intitle:{main}", 5, _title_core(main)))
        for query, max_results, match_core in queries:
            if self._google_exhausted:
                return None
            for item in self._google_items(query, max_results):
                info = item.get("volumeInfo") or {}
                if match_core:
                    core = _title_core(info.get("title", ""))
                    if not core or (match_core not in core and core not in match_core):
                        continue
                thumb = (info.get("imageLinks") or {}).get("thumbnail")
                if not thumb:
                    continue
                url = thumb.replace("&zoom=1", "&zoom=3")
                if self.is_valid_image(url):
                    return url
        return None

    def _google_items(self, query: str, max_results: int) -> List[dict]:
        params = {"q": query, "maxResults": max_results}
        if self._google_api_key:
            params["key"] = self._google_api_key
        try:
            response = self._http_get(_GOOGLE_BOOKS_URL, params=params, timeout=_TIMEOUT)
        except requests.RequestException as e:
            logger.debug(f"Google Books 查詢失敗: {e}")
            return []
        if response.status_code == 429:
            if not self._google_exhausted:
                logger.warning(
                    "Google Books 配額用盡（429），本輪不再查詢；"
                    "可設定 GOOGLE_BOOKS_API_KEY 取得自己的配額")
            self._google_exhausted = True
            return []
        if response.status_code != 200:
            return []
        try:
            return response.json().get("items") or []
        except ValueError:
            return []

    def _from_open_library(self, book) -> Optional[str]:
        if not is_real_isbn13(book.isbn):
            return None
        url = OPEN_LIBRARY_URL.format(isbn=book.isbn.strip())
        return url if self.is_valid_image(url) else None


# ----- 舊介面：NotionApiRepository.add_book_cover 仍在用，Task 5 換成 CoverFinder 後整段刪除 -----
_LEGACY_OPEN_LIBRARY_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"


def get_google_books_cover(title: str) -> Optional[str]:
    """Query Google Books for a high-resolution cover URL."""
    try:
        response = requests.get(
            _GOOGLE_BOOKS_URL,
            params={"q": f"intitle:{title}", "maxResults": 1},
            timeout=_TIMEOUT,
        )
        if response.status_code != 200:
            logger.debug(f"Google Books non-200: {response.status_code}")
            return None
        items = response.json().get("items") or []
        if not items:
            return None
        links = items[0].get("volumeInfo", {}).get("imageLinks", {})
        thumb = links.get("thumbnail")
        if not thumb:
            return None
        return thumb.replace("&zoom=1", "&zoom=3")
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Google Books 查詢失敗: {e}")
        return None


def get_openlibrary_cover(isbn: str) -> str:
    return _LEGACY_OPEN_LIBRARY_URL.format(isbn=isbn)


def get_best_book_cover(title: str, isbn: Optional[str]) -> Optional[str]:
    """Google Books preferred; Open Library fallback if ISBN is present."""
    cover = get_google_books_cover(title)
    if cover:
        return cover
    if isbn:
        return get_openlibrary_cover(isbn)
    return None
```

（舊介面區塊與原檔的三個函式行為完全相同，只是把原本的 `_OPEN_LIBRARY_URL`／`_REQUEST_TIMEOUT` 改用 `_LEGACY_OPEN_LIBRARY_URL`／`_TIMEOUT`——兩者值相同。）

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_cover_finder.py tests/unit/test_highlight_filter.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠（`notion_api_repository.py` 仍透過舊介面運作，行為未變）

- [ ] **Step 5: Commit**

```bash
git add src/domain/entities/book.py src/infrastructure/persistence/kobo_sqlite_repository.py src/infrastructure/external/cover_fetcher.py tests/unit/test_cover_finder.py tests/unit/test_highlight_filter.py
git commit -m "✨ feat: CoverFinder——書封 Kobo 圖床優先、逐張驗證（尚未接上）"
```

---

### Task 5: 劃線頁透明封面修復（`add_book_cover(page_id, book)`）

**Files:**
- Modify: `src/infrastructure/external/cover_fetcher.py`（刪除檔尾「舊介面」區塊）
- Modify: `src/domain/repositories/notion_repository.py`（`add_book_cover` 簽名）
- Modify: `src/infrastructure/notion/notion_api_repository.py:13`（import）、`:44-48`（`__init__`）、`:126-142`（`add_book_cover`）、`:196-208`（`_has_existing_cover` 換成 `_existing_cover_url`）
- Modify: `src/infrastructure/notion/dry_run_notion_repository.py`（`add_book_cover`）
- Modify: `src/application/use_cases/sync_books_use_case.py:88`、`:141`（兩個呼叫點）
- Modify: `tests/unit/test_resync.py`、`tests/unit/test_dry_run_repository.py`（fake 簽名）
- Test: `tests/unit/test_book_cover_repair.py`（新建）

**Interfaces:**
- Consumes: Task 4 的 `CoverFinder`（`.find`、`.is_valid_image`）、`is_legacy_openlibrary_url`
- Produces:
  - `NotionRepository.add_book_cover(page_id: str, book: Book) -> None`（ABC、`NotionApiRepository`、`DryRunNotionRepository` 一致）
  - `NotionApiRepository(token, database_id, rate_limiter=None, cover_finder: Optional[CoverFinder] = None)`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_book_cover_repair.py`：

```python
"""劃線頁封面：沒封面就補；舊 Open Library 透明圖重驗不過就換掉或清掉；有效封面不重驗。"""
import unittest
from types import SimpleNamespace

from src.domain.entities.book import Book
from src.infrastructure.notion.notion_api_repository import NotionApiRepository

LEGACY = "https://covers.openlibrary.org/b/isbn/9786267195185-L.jpg"
KOBO = "https://cdn.kobo.com/book-images/img-1/353/569/90/False/image.jpg"
GOOGLE = "http://books.google.com/books/content?id=x&zoom=3"
BOOK = Book(id="b1", title="多巴胺國度", isbn="9786267195185", image_id="img-1")


class _NoWait:
    def wait(self):
        pass


class _FakeFinder:
    def __init__(self, found=None, valid=()):
        self.found = found
        self.valid = set(valid)
        self.find_calls = 0

    def find(self, book):
        self.find_calls += 1
        return self.found

    def is_valid_image(self, url):
        return url in self.valid


class _FakeClient:
    def __init__(self, page):
        self.page = page
        self.updates = []
        self.pages = SimpleNamespace(retrieve=lambda page_id: self.page,
                                     update=self._update)

    def _update(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def _ext(url):
    return {"type": "external", "external": {"url": url}}


def _repo(page, finder):
    repo = NotionApiRepository.__new__(NotionApiRepository)
    repo._client = _FakeClient(page)
    repo._rate_limiter = _NoWait()
    repo._database_id = "db"
    repo._cover_finder = finder
    return repo


class TestAddBookCover(unittest.TestCase):
    def test_page_without_cover_gets_one(self):
        repo = _repo({"icon": None, "cover": None}, _FakeFinder(found=KOBO))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": _ext(KOBO), "cover": _ext(KOBO)}])

    def test_valid_existing_cover_untouched(self):
        finder = _FakeFinder(found=KOBO)
        repo = _repo({"icon": _ext(GOOGLE), "cover": _ext(GOOGLE)}, finder)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(finder.find_calls, 0)

    def test_broken_legacy_cover_replaced(self):
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, _FakeFinder(found=KOBO))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": _ext(KOBO), "cover": _ext(KOBO)}])

    def test_broken_legacy_cover_cleared_when_nothing_found(self):
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, _FakeFinder(found=None))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [
            {"page_id": "page-1", "icon": None, "cover": None}])

    def test_legacy_url_that_still_works_is_kept(self):
        finder = _FakeFinder(found=KOBO, valid={LEGACY})
        repo = _repo({"icon": _ext(LEGACY), "cover": _ext(LEGACY)}, finder)
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])
        self.assertEqual(finder.find_calls, 0)

    def test_nothing_found_and_no_existing_cover(self):
        repo = _repo({"icon": None, "cover": None}, _FakeFinder(found=None))
        repo.add_book_cover("page-1", BOOK)
        self.assertEqual(repo._client.updates, [])


if __name__ == "__main__":
    unittest.main()
```

更新既有 fake 的簽名：

- `tests/unit/test_resync.py` 的 `_FakeNotionRepo.add_book_cover` 改為：

```python
    def add_book_cover(self, page_id, book):
        pass
```

- `tests/unit/test_dry_run_repository.py`：`FakeNotionRepository.add_book_cover` 改為：

```python
    def add_book_cover(self, page_id, book):
        self.write_calls.append(("cover", page_id))
```

  並把 `test_writes_never_reach_inner` 中的 `self.repo.add_book_cover("page-1", "測試書")` 改成 `self.repo.add_book_cover("page-1", book)`（`book` 已在該測試開頭定義為 `SimpleNamespace(title="測試書")`）。

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_book_cover_repair.py -v`
Expected: 多個 FAIL——舊的 `add_book_cover(page_id, title, isbn)` 不認得 `_cover_finder`，會把 `Book` 當成書名走舊流程（此時可能真的打一次 Google Books，屬預期），`updates` 與預期不符

- [ ] **Step 3: 實作**

`src/infrastructure/external/cover_fetcher.py`：刪除從 `# ----- 舊介面：` 那一行到檔尾的整段（`_LEGACY_OPEN_LIBRARY_URL` 與三個舊函式）。

`src/domain/repositories/notion_repository.py` 的 `add_book_cover` 抽象方法換成：

```python
    @abstractmethod
    def add_book_cover(self, page_id: str, book: Book) -> None:
        """補上書籍封面（icon＋cover）；無效的舊 Open Library 封面會被替換或清除"""
        pass
```

`src/infrastructure/notion/notion_api_repository.py`：

1. 第 13 行 `from ..external.cover_fetcher import get_best_book_cover` 換成：

```python
from ..external.cover_fetcher import CoverFinder, is_legacy_openlibrary_url
```

2. `__init__` 換成：

```python
    def __init__(self, token: str, database_id: str,
                 rate_limiter: Optional[NotionRateLimiter] = None,
                 cover_finder: Optional[CoverFinder] = None):
        self._database_id = database_id
        self._client = Client(auth=token)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        self._cover_finder = cover_finder or CoverFinder()
```

3. `add_book_cover` 整個方法換成：

```python
    def add_book_cover(self, page_id: str, book: Book) -> None:
        existing = self._existing_cover_url(page_id)
        if existing and not self._is_broken_cover(existing):
            logger.debug(f"page {page_id} 已有封面,跳過")
            return
        cover_url = self._cover_finder.find(book)
        if cover_url:
            retry_with_backoff(
                lambda: self._client.pages.update(
                    page_id=page_id,
                    icon={"type": "external", "external": {"url": cover_url}},
                    cover={"type": "external", "external": {"url": cover_url}},
                ),
                self._rate_limiter,
            )
            logger.info(f"已為 '{book.title}' 設定封面")
        elif existing:
            retry_with_backoff(
                lambda: self._client.pages.update(page_id=page_id, icon=None, cover=None),
                self._rate_limiter,
            )
            logger.info(f"'{book.title}' 的舊封面無效且找不到替代，已清除")
        else:
            logger.debug(f"找不到 '{book.title}' 的封面")
```

4. `_has_existing_cover` 整個方法換成下面兩個方法：

```python
    def _is_broken_cover(self, url: str) -> bool:
        """只重驗舊的 Open Library 網址（1x1 透明圖那批）；其他既有封面一律信任，
        避免每次同步對每本書多打一個 GET。"""
        return is_legacy_openlibrary_url(url) and not self._cover_finder.is_valid_image(url)

    def _existing_cover_url(self, page_id: str) -> Optional[str]:
        try:
            page = retry_with_backoff(
                lambda: self._client.pages.retrieve(page_id),
                self._rate_limiter,
            ) or {}
        except Exception as e:
            logger.warning(f"查詢封面狀態失敗: {e}")
            return None
        for key in ("icon", "cover"):
            value = page.get(key) or {}
            if isinstance(value, dict) and value.get("type") == "external":
                url = (value.get("external") or {}).get("url")
                if url:
                    return url
        return None
```

`src/infrastructure/notion/dry_run_notion_repository.py` 的 `add_book_cover` 換成：

```python
    def add_book_cover(self, page_id: str, book: Book) -> None:
        logger.info(f"{_PREFIX} 將檢查並補上 '{book.title}' 的封面 (page {page_id})")
```

`src/application/use_cases/sync_books_use_case.py` 兩處 `self.notion_repo.add_book_cover(page_id, book.title, book.isbn)` 都改成：

```python
self.notion_repo.add_book_cover(page_id, book)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_book_cover_repair.py tests/unit/test_cover_finder.py tests/unit/test_resync.py tests/unit/test_dry_run_repository.py tests/unit/test_highlight_filter.py -v`
Expected: 全部 passed

Run: `grep -n "get_best_book_cover\|_LEGACY_OPEN_LIBRARY_URL" -r src/`
Expected: 沒有輸出

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/external/cover_fetcher.py src/domain/repositories/notion_repository.py src/infrastructure/notion/notion_api_repository.py src/infrastructure/notion/dry_run_notion_repository.py src/application/use_cases/sync_books_use_case.py tests/unit/test_book_cover_repair.py tests/unit/test_resync.py tests/unit/test_dry_run_repository.py
git commit -m "🐛 fix: 劃線頁透明封面——add_book_cover 改用 CoverFinder，無效舊封面替換或清除"
```

---

### Task 6: 卡片 Tags 多數決推算書籍種類＋依來源讀回卡片

**Files:**
- Create: `src/domain/entities/book_card.py`
- Create: `src/domain/services/reading_list_rules.py`
- Modify: `src/config/settings.py`（新增 `DEFAULT_BOOK_TYPE_MAPPING`）
- Modify: `src/infrastructure/notion/zettelkasten_card_repository.py`（新增 `list_book_cards`、`_to_book_card`）
- Test: `tests/unit/test_reading_list_rules.py`、`tests/unit/test_list_book_cards.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `ZettelkastenCardRepository`
- Produces:
  - `BookCard(page_id: str, title: str, tags: List[str] = [], keywords: List[str] = [], content: str = "")`
  - `derive_book_types(cards: Sequence[BookCard], mapping: Dict[str, str], max_types: int = 2) -> List[str]`
  - `settings.DEFAULT_BOOK_TYPE_MAPPING: Dict[str, str]`
  - `ZettelkastenCardRepository.list_book_cards(books_page_id: str) -> List[BookCard]`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_reading_list_rules.py`：

```python
"""書籍種類推算：卡片 Tags 多數決（spec「書籍種類推算」）。"""
import unittest

from src.config.settings import DEFAULT_BOOK_TYPE_MAPPING
from src.domain.entities.book_card import BookCard
from src.domain.services.reading_list_rules import derive_book_types


def _cards(*tag_lists):
    return [BookCard(page_id=f"c{i}", title=f"卡{i}", tags=list(tags))
            for i, tags in enumerate(tag_lists)]


class TestDeriveBookTypes(unittest.TestCase):
    def test_dopamine_nation_example(self):
        # 《多巴胺國度》實際分布：心理學 15、人生觀點 2、哲學科學 2、商務 1、邏輯思考 1
        cards = _cards(
            *[["💞心理學"]] * 12,
            ["💼商務", "💞心理學"],
            ["🧘‍♂️人生觀點", "💞心理學"],
            ["🔬哲學科學"],
            ["🔬哲學科學", "🧘‍♂️人生觀點"],
            ["💞心理學", "🧩邏輯思考"],
        )
        self.assertEqual(derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING), ["Psychology"])

    def test_runner_up_with_half_the_votes_is_kept(self):
        cards = _cards(*[["💞心理學"]] * 4, *[["📈行銷"]] * 2)
        self.assertEqual(
            derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING), ["Psychology", "Marketing"])

    def test_tie_keeps_mapping_order(self):
        cards = _cards(*[["💼商務"]] * 3, *[["🧠學習技巧"]] * 3)
        self.assertEqual(
            derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING),
            ["Learning Skills", "Business & Finance"])

    def test_same_card_votes_once_per_type(self):
        cards = _cards(["💼商務", "💰理財投資"], ["💞心理學"], ["💞心理學"])
        self.assertEqual(
            derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING),
            ["Psychology", "Business & Finance"])

    def test_emoji_insensitive(self):
        self.assertEqual(
            derive_book_types(_cards(["心理學"]), DEFAULT_BOOK_TYPE_MAPPING), ["Psychology"])

    def test_at_most_two_types(self):
        cards = _cards(*[["💞心理學"]] * 2, *[["📈行銷"]] * 2, *[["💻軟體工程"]] * 2)
        self.assertEqual(len(derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING)), 2)

    def test_unmapped_or_no_cards(self):
        self.assertEqual(derive_book_types(_cards(["🍳料理"]), DEFAULT_BOOK_TYPE_MAPPING), [])
        self.assertEqual(derive_book_types([], DEFAULT_BOOK_TYPE_MAPPING), [])


if __name__ == "__main__":
    unittest.main()
```

建立 `tests/unit/test_list_book_cards.py`：

```python
"""ZettelkastenCardRepository.list_book_cards — 依「來源」讀回某本書的卡片（屬性）。"""
import unittest
from types import SimpleNamespace

from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)


class _NoWait:
    def wait(self):
        pass


def _card(pid, title, tags, keyword):
    return {"id": pid, "properties": {
        "標題": {"type": "title", "title": [{"plain_text": title}]},
        "Tags": {"type": "multi_select", "multi_select": [{"name": t} for t in tags]},
        "Key Word": {"type": "rich_text",
                     "rich_text": [{"plain_text": keyword}] if keyword else []},
    }}


class _FakeClient:
    def __init__(self, pages_by_cursor=None, error=None):
        self.queries = []
        self._pages = pages_by_cursor or {}
        self._error = error
        self.databases = SimpleNamespace(query=self._query)

    def _query(self, **kwargs):
        self.queries.append(kwargs)
        if self._error:
            raise self._error
        return self._pages[kwargs.get("start_cursor")]


def _repo(client):
    repo = ZettelkastenCardRepository(token="dummy", database_id="cards-db",
                                      rate_limiter=_NoWait())
    repo._client = client
    return repo


class TestListBookCards(unittest.TestCase):
    def test_paginates_and_parses(self):
        client = _FakeClient({
            None: {"results": [_card("c1", "卡一", ["💞心理學"], "成癮、延遲滿足")],
                   "has_more": True, "next_cursor": "p2"},
            "p2": {"results": [_card("c2", "卡二", [], "語言學・社會合作")],
                   "has_more": False},
        })
        cards = _repo(client).list_book_cards("rl-1")
        self.assertEqual([c.page_id for c in cards], ["c1", "c2"])
        self.assertEqual(cards[0].title, "卡一")
        self.assertEqual(cards[0].tags, ["💞心理學"])
        self.assertEqual(cards[0].keywords, ["成癮", "延遲滿足"])
        self.assertEqual(cards[1].keywords, ["語言學", "社會合作"])
        self.assertEqual(
            client.queries[0]["filter"], {"property": "來源", "relation": {"contains": "rl-1"}})
        self.assertEqual(client.queries[0]["database_id"], "cards-db")

    def test_query_failure_returns_empty(self):
        client = _FakeClient(error=RuntimeError("boom"))
        with self.assertLogs(
            "src.infrastructure.notion.zettelkasten_card_repository", level="WARNING"
        ):
            self.assertEqual(_repo(client).list_book_cards("rl-1"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_reading_list_rules.py tests/unit/test_list_book_cards.py -v`
Expected: `ImportError: cannot import name 'DEFAULT_BOOK_TYPE_MAPPING'`；`AttributeError: ... has no attribute 'list_book_cards'`

- [ ] **Step 3: 實作**

建立 `src/domain/entities/book_card.py`：

```python
from dataclasses import dataclass, field
from typing import List


@dataclass
class BookCard:
    """A 卡片盒 card as read back from Notion (Reading List page completion)."""
    page_id: str
    title: str
    tags: List[str] = field(default_factory=list)      # Tags multi_select（固定分類）
    keywords: List[str] = field(default_factory=list)  # Key Word（自由概念）
    content: str = ""                                   # 卡片內文；M2 才讀
```

建立 `src/domain/services/reading_list_rules.py`：

```python
"""Pure rules for Reading List page completion (no IO)."""
import unicodedata
from typing import Dict, List, Sequence

from ..entities.book_card import BookCard


def _core(name: str) -> str:
    """Letters/digits only — same convention as the card classifier's
    `_category_core`, so "💞心理學" and "心理學" are the same tag."""
    return "".join(
        ch for ch in (name or "") if unicodedata.category(ch)[0] in ("L", "N")
    )


def derive_book_types(
    cards: Sequence[BookCard], mapping: Dict[str, str], max_types: int = 2
) -> List[str]:
    """Majority vote of card Tags → 書籍種類 names (spec「書籍種類推算」).

    - each card votes at most once per type (💼商務 + 💰理財投資 → one vote);
    - ties keep the mapping's order;
    - the runner-up is kept only with at least half the winner's votes.
    """
    tag_to_type = {_core(tag): book_type for tag, book_type in mapping.items() if _core(tag)}
    type_order: List[str] = []
    for book_type in mapping.values():
        if book_type not in type_order:
            type_order.append(book_type)

    votes: Dict[str, int] = {}
    for card in cards:
        card_types = {tag_to_type[_core(t)] for t in card.tags if _core(t) in tag_to_type}
        for book_type in card_types:
            votes[book_type] = votes.get(book_type, 0) + 1
    if not votes:
        return []

    ranked = sorted(votes, key=lambda t: (-votes[t], type_order.index(t)))
    winner = ranked[0]
    picked = [winner]
    for runner_up in ranked[1:max_types]:
        if votes[runner_up] * 2 >= votes[winner]:
            picked.append(runner_up)
    return picked
```

`src/config/settings.py`：

1. `from typing import List, Optional` 改成 `from typing import Dict, List, Optional`。
2. 在 `DEFAULT_TAG_CATEGORIES` 定義之後加入：

```python
# 卡片 Tags（固定分類）→ 📚 Personal Reading List「Type 書籍種類」頁名。
# 補書頁時以卡片 Tags 多數決推算書籍種類；順序即同票時的優先序。
DEFAULT_BOOK_TYPE_MAPPING: Dict[str, str] = {
    "💞心理學": "Psychology",
    "🧠學習技巧": "Learning Skills",
    "💼商務": "Business & Finance",
    "💰理財投資": "Business & Finance",
    "🧘‍♂️人生觀點": "Spiritual Inspiration",
    "🧩邏輯思考": "Logical Thinking",
    "🔬哲學科學": "Philosophy & Science",
    "💻軟體工程": "Software Engineering",
    "📈行銷": "Marketing",
    "📋專案管理": "Project Management",
}
```

`src/infrastructure/notion/zettelkasten_card_repository.py`：

1. import 區加入 `import re`（在 `import logging` 之後）與 `from ...domain.entities.book_card import BookCard`（在 `from .card_visuals import cover_url_for` 之前）。
2. 在 `has_property` 方法之後（`# ----- Internals -----` 之前）加入：

```python
    def list_book_cards(self, books_page_id: str) -> List[BookCard]:
        """Cards whose 來源 relation points at a Books-DB page (properties only).

        Read-only; used by Reading List page completion to derive 書籍種類.
        """
        cards: List[BookCard] = []
        cursor: Optional[str] = None
        try:
            while True:
                kwargs = {
                    "database_id": self._database_id,
                    "filter": {
                        "property": "來源",
                        "relation": {"contains": books_page_id},
                    },
                    "page_size": 100,
                }
                if cursor:
                    kwargs["start_cursor"] = cursor
                result = retry_with_backoff(
                    lambda k=kwargs: self._client.databases.query(**k),
                    self._rate_limiter,
                ) or {}
                cards.extend(self._to_book_card(p) for p in result.get("results", []))
                if not result.get("has_more"):
                    break
                cursor = result.get("next_cursor")
        except Exception as e:
            logger.warning(f"讀取書頁 {books_page_id} 的卡片失敗: {e}")
            return []
        return cards

    @staticmethod
    def _to_book_card(page: dict) -> BookCard:
        props = (page or {}).get("properties") or {}

        def _plain(prop_name: str, kind: str) -> str:
            parts = (props.get(prop_name) or {}).get(kind) or []
            return "".join(p.get("plain_text", "") for p in parts).strip()

        tags = [
            o.get("name", "")
            for o in (props.get(_TAGS_PROPERTY) or {}).get("multi_select") or []
            if o.get("name")
        ]
        keywords = [
            k.strip() for k in re.split(r"[、・]", _plain(_KEYWORD_PROPERTY, "rich_text"))
            if k.strip()
        ]
        return BookCard(
            page_id=page.get("id", ""),
            title=_plain("標題", "title"),
            tags=tags,
            keywords=keywords,
        )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_reading_list_rules.py tests/unit/test_list_book_cards.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/domain/entities/book_card.py src/domain/services/reading_list_rules.py src/config/settings.py src/infrastructure/notion/zettelkasten_card_repository.py tests/unit/test_reading_list_rules.py tests/unit/test_list_book_cards.py
git commit -m "✨ feat: 卡片 Tags 多數決推算書籍種類，並依來源讀回書的卡片"
```

---

### Task 7: 書頁版面純函式＋共用 `clean_html`

**Files:**
- Create: `src/infrastructure/notion/text_utils.py`
- Modify: `src/infrastructure/notion/notion_api_repository.py`（改 import `clean_html`、刪 `_clean_html`）
- Create: `src/infrastructure/notion/reading_list_page_blocks.py`
- Test: `tests/unit/test_reading_list_page_blocks.py`（新建）

**Interfaces:**
- Consumes: `highlight_page_blocks.heading_block`、`split_rich_text`；Task 4 的 `is_real_isbn13`
- Produces:
  - `text_utils.clean_html(text: str) -> str`
  - 常數 `SECTION_BOOK_INFO`、`SECTION_NOTES`、`SECTION_OVERVIEW`、`SECTION_ACTIONS`、`SECTION_REFLECTION`、`SECTION_QUOTES`、`SECTIONS`、`DESCRIPTION_TOGGLE`、`HIGHLIGHTS_LINK_TEXT`
  - `skeleton_blocks(book: Book, cover_url: Optional[str], kobo_page_id: Optional[str]) -> List[dict]`
  - `book_info_blocks(book: Book, cover_url: Optional[str]) -> List[dict]`
  - `highlights_link_block(kobo_page_id: str) -> dict`
  - `block_text(block: dict) -> str`
  - `is_blank_page(blocks: List[dict]) -> bool`
  - `find_section(blocks: List[dict], name: str) -> Optional[Tuple[dict, List[dict]]]`（回傳 `(標題 block, 段落內 blocks)`）
  - `section_is_empty(body: List[dict]) -> bool`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_reading_list_page_blocks.py`：

```python
"""Reading List 書頁版面純函式：六段骨架、書籍資料、段落定位與空白判斷。"""
import unittest

from src.domain.entities.book import Book
from src.infrastructure.notion.reading_list_page_blocks import (
    DESCRIPTION_TOGGLE,
    SECTION_NOTES,
    SECTION_OVERVIEW,
    SECTIONS,
    block_text,
    find_section,
    is_blank_page,
    section_is_empty,
    skeleton_blocks,
)
from src.infrastructure.notion.text_utils import clean_html


def _heading(text, level=2):
    key = f"heading_{level}"
    return {"type": key, key: {"rich_text": [{"plain_text": text}]}}


def _para(text=""):
    return {"type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": text}] if text else []}}


def _full_book():
    return Book(id="b1", title="多巴胺國度", author="安娜．蘭布克", publisher="方舟文化",
                isbn="9786267195185", description="<p><strong>成癮</strong>&amp;平衡</p>",
                image_id="img-1")


class TestSkeleton(unittest.TestCase):
    def test_sections_in_template_order(self):
        blocks = skeleton_blocks(_full_book(), "https://cdn/x.jpg", "kobo-1")
        headings = [block_text(b) for b in blocks if b["type"] == "heading_2"]
        self.assertEqual(headings, list(SECTIONS))

    def test_book_info_contents(self):
        blocks = skeleton_blocks(_full_book(), "https://cdn/x.jpg", "kobo-1")
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["image"]["external"]["url"], "https://cdn/x.jpg")
        bullets = [block_text(b) for b in blocks if b["type"] == "bulleted_list_item"]
        self.assertEqual(bullets, ["作者：安娜．蘭布克", "出版社：方舟文化", "ISBN：9786267195185"])
        toggle = next(b for b in blocks if b["type"] == "toggle")
        self.assertEqual(block_text(toggle), DESCRIPTION_TOGGLE)
        self.assertEqual(block_text(toggle["toggle"]["children"][0]), "成癮&平衡")

    def test_highlights_link_is_a_page_mention(self):
        last = skeleton_blocks(_full_book(), None, "kobo-1")[-1]
        rich = last["paragraph"]["rich_text"]
        self.assertEqual(rich[1]["mention"], {"type": "page", "page": {"id": "kobo-1"}})

    def test_missing_fields_are_omitted(self):
        blocks = skeleton_blocks(Book(id="b2", title="側載書", isbn="7363579164627"), None, None)
        self.assertEqual([b["type"] for b in blocks], ["heading_2"] * 6)

    def test_long_description_is_split(self):
        book = Book(id="b3", title="書", description="字" * 4500)
        toggle = next(b for b in skeleton_blocks(book, None, None) if b["type"] == "toggle")
        rich = toggle["toggle"]["children"][0]["paragraph"]["rich_text"]
        self.assertEqual([len(r["text"]["content"]) for r in rich], [2000, 2000, 500])


class TestSections(unittest.TestCase):
    def test_blank_page(self):
        self.assertTrue(is_blank_page([]))
        self.assertTrue(is_blank_page([_para(), _para("   ")]))
        self.assertFalse(is_blank_page([_para("我先寫了一行")]))
        self.assertFalse(is_blank_page([_heading("書籍資料")]))

    def test_subheadings_belong_to_the_section(self):
        blocks = [_heading(SECTION_OVERVIEW), _heading("1. 路線圖", level=3),
                  _para("人行道、慢車道、快車道"), _heading("實際執行")]
        heading, body = find_section(blocks, SECTION_OVERVIEW)
        self.assertIs(heading, blocks[0])
        self.assertEqual(len(body), 2)
        self.assertFalse(section_is_empty(body))

    def test_higher_level_section_spans_lower_headings(self):
        blocks = [_heading(SECTION_NOTES, level=1), _heading("小標"), _heading("下一章", level=1)]
        _, body = find_section(blocks, SECTION_NOTES)
        self.assertEqual(len(body), 1)

    def test_empty_section_and_non_text_blocks(self):
        blocks = [_heading(SECTION_NOTES), _para(), _heading(SECTION_OVERVIEW)]
        _, body = find_section(blocks, SECTION_NOTES)
        self.assertTrue(section_is_empty(body))
        self.assertFalse(section_is_empty([{"type": "child_database"}]))
        self.assertFalse(section_is_empty([{"type": "unsupported"}]))

    def test_missing_section(self):
        self.assertIsNone(find_section([_heading("卡片")], SECTION_NOTES))


class TestCleanHtml(unittest.TestCase):
    def test_strips_tags_and_entities(self):
        self.assertEqual(clean_html("<p>A&amp;B</p>\n\n<p>C</p>"), "A&B C")
        self.assertEqual(clean_html(None), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_reading_list_page_blocks.py -v`
Expected: `ModuleNotFoundError: No module named 'src.infrastructure.notion.reading_list_page_blocks'`

- [ ] **Step 3: 實作**

建立 `src/infrastructure/notion/text_utils.py`：

```python
"""Small text helpers shared by Notion writers."""
import re


def clean_html(text: str) -> str:
    """Strip tags, collapse whitespace, unescape the few entities Kobo uses."""
    clean = re.sub(r'<[^>]+>', '', text or '')
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'"))
```

`src/infrastructure/notion/notion_api_repository.py`：

1. 在 `from .retry_policy import retry_with_backoff` 之後加入 `from .text_utils import clean_html`。
2. `_build_properties` 中的 `_clean_html(book.description)` 改為 `clean_html(book.description)`。
3. 刪除檔尾的 `def _clean_html(...)` 整個函式，並刪除第 4 行 `import re`（`re` 只有 `_clean_html` 在用，留著 ruff 會報 F401）。

建立 `src/infrastructure/notion/reading_list_page_blocks.py`：

```python
"""Pure block builders for Reading List book pages (M1 layout).

Mirrors the user's「心得摘錄」template: six heading_2 sections. No Notion client
here — CompleteReadingListPageUseCase orchestrates the writes, this module owns
block construction and section lookup so both stay unit-testable.
"""
from typing import Any, Dict, List, Optional, Tuple

from ...domain.entities.book import Book
from ..external.cover_fetcher import is_real_isbn13
from .highlight_page_blocks import heading_block, split_rich_text
from .text_utils import clean_html

SECTION_BOOK_INFO = "書籍資料"
SECTION_NOTES = "筆記圖"
SECTION_OVERVIEW = "概要"
SECTION_ACTIONS = "實際執行"
SECTION_REFLECTION = "心得"
SECTION_QUOTES = "金句摘錄"
SECTIONS = (SECTION_BOOK_INFO, SECTION_NOTES, SECTION_OVERVIEW,
            SECTION_ACTIONS, SECTION_REFLECTION, SECTION_QUOTES)

DESCRIPTION_TOGGLE = "出版社簡介"
HIGHLIGHTS_LINK_TEXT = "畫線重點 → "

_HEADING_LEVELS = {"heading_1": 1, "heading_2": 2, "heading_3": 3}


def skeleton_blocks(book: Book, cover_url: Optional[str],
                    kobo_page_id: Optional[str]) -> List[Dict[str, Any]]:
    """The whole six-section layout, written once onto a blank page."""
    blocks: List[Dict[str, Any]] = [heading_block(SECTION_BOOK_INFO, level=2)]
    blocks += book_info_blocks(book, cover_url)
    blocks += [heading_block(name, level=2) for name in SECTIONS[1:]]
    if kobo_page_id:
        blocks.append(highlights_link_block(kobo_page_id))
    return blocks


def book_info_blocks(book: Book, cover_url: Optional[str]) -> List[Dict[str, Any]]:
    """書籍資料段：書封圖（gallery 預覽靠它）、作者／出版社／ISBN、出版社簡介。"""
    blocks: List[Dict[str, Any]] = []
    if cover_url:
        blocks.append({"object": "block", "type": "image",
                       "image": {"type": "external", "external": {"url": cover_url}}})
    facts = [("作者", book.author), ("出版社", book.publisher)]
    if is_real_isbn13(book.isbn):
        facts.append(("ISBN", book.isbn.strip()))
    for label, value in facts:
        if value and value.strip():
            blocks.append(_bullet(f"{label}：{value.strip()}"))
    description = clean_html(book.description or "")
    if description:
        blocks.append({"object": "block", "type": "toggle", "toggle": {
            "rich_text": split_rich_text(DESCRIPTION_TOGGLE),
            "children": [_paragraph(description)],
        }})
    return blocks


def highlights_link_block(kobo_page_id: str) -> Dict[str, Any]:
    """「畫線重點 → @劃線頁」——與使用者手動頁的金句摘錄寫法一致。"""
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content": HIGHLIGHTS_LINK_TEXT}},
        {"type": "mention", "mention": {"type": "page", "page": {"id": kobo_page_id}}},
    ]}}


def block_text(block: Dict[str, Any]) -> str:
    """Plain text of a block — works for API responses (plain_text) and for
    blocks built here (text.content)."""
    payload = block.get(block.get("type", ""), {}) or {}
    return "".join(
        rt.get("plain_text") or (rt.get("text") or {}).get("content") or ""
        for rt in payload.get("rich_text") or []
    )


def is_blank_page(blocks: List[Dict[str, Any]]) -> bool:
    """No blocks, or only paragraphs without text."""
    return all(b.get("type") == "paragraph" and not block_text(b).strip() for b in blocks)


def find_section(blocks: List[Dict[str, Any]], name: str
                 ) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """(heading, body) of the section whose heading text equals `name`.

    The body runs until the next heading of the same or a higher level, so a
    `###` inside a `##` section is content — the user's own 概要 uses that.
    """
    for i, block in enumerate(blocks):
        level = _HEADING_LEVELS.get(block.get("type"))
        if level is None or block_text(block).strip() != name:
            continue
        body: List[Dict[str, Any]] = []
        for following in blocks[i + 1:]:
            other = _HEADING_LEVELS.get(following.get("type"))
            if other is not None and other <= level:
                break
            body.append(following)
        return block, body
    return None


def section_is_empty(body: List[Dict[str, Any]]) -> bool:
    return is_blank_page(body)


def _bullet(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": split_rich_text(text)}}


def _paragraph(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": split_rich_text(text)}}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_reading_list_page_blocks.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/text_utils.py src/infrastructure/notion/notion_api_repository.py src/infrastructure/notion/reading_list_page_blocks.py tests/unit/test_reading_list_page_blocks.py
git commit -m "✨ feat: Reading List 書頁版面純函式（六段骨架、書籍資料、段落定位）"
```

---

### Task 8: `NotionViewsClient`（建本書卡片 gallery）

**Files:**
- Create: `src/infrastructure/notion/notion_views_client.py`
- Test: `tests/unit/test_notion_views_client.py`（新建）

**Interfaces:**
- Consumes: Task 1 實測確認的 body（若 Task 1 走了 configuration 分支，先依 Task 1 Step 3 修改本 task 的程式與測試）
- Produces:
  - 常數 `NOTION_VIEWS_API_VERSION = "2026-03-11"`、`CARD_GALLERY_NAME = "本書卡片"`
  - `card_gallery_body(data_source_id: str, page_id: str, book_page_id: str, after_block_id: str) -> dict`
  - `NotionViewsClient(token: str, rate_limiter: Optional[NotionRateLimiter] = None, client: Optional[Client] = None)`
  - `.data_source_id(database_id: str) -> Optional[str]`
  - `.create_card_gallery(page_id: str, cards_database_id: str, book_page_id: str, after_block_id: str) -> Optional[str]`（回傳 view id；API 錯誤會拋出，由呼叫端處理）

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_notion_views_client.py`：

```python
"""NotionViewsClient — 全專案唯一使用新版 API 的地方（Views API）。"""
import unittest

from src.infrastructure.notion.notion_views_client import (
    NOTION_VIEWS_API_VERSION,
    NotionViewsClient,
    card_gallery_body,
)


class _NoWait:
    def wait(self):
        pass


class _FakeClient:
    def __init__(self, data_sources=None):
        self.requests = []
        self._data_sources = [{"id": "ds-1"}] if data_sources is None else data_sources

    def request(self, path, method, query=None, body=None, auth=None):
        self.requests.append((method, path, body))
        if path.startswith("databases/"):
            return {"object": "database", "data_sources": self._data_sources}
        if path == "views":
            return {"object": "view", "id": "view-1"}
        raise AssertionError(f"unexpected request {method} {path}")


def _client(fake):
    return NotionViewsClient(token="t", rate_limiter=_NoWait(), client=fake)


class TestCardGalleryBody(unittest.TestCase):
    def test_body_shape(self):
        self.assertEqual(card_gallery_body("ds-1", "page-1", "page-1", "h-notes"), {
            "data_source_id": "ds-1",
            "name": "本書卡片",
            "type": "gallery",
            "create_database": {
                "parent": {"type": "page_id", "page_id": "page-1"},
                "position": {"type": "after_block", "block_id": "h-notes"},
            },
            "filter": {"property": "來源", "relation": {"contains": "page-1"}},
            "sorts": [{"property": "標題", "direction": "ascending"}],
            "configuration": {"type": "gallery", "cover": {"type": "page_cover"}},
        })


class TestNotionViewsClient(unittest.TestCase):
    def test_creates_gallery_after_heading(self):
        fake = _FakeClient()
        view_id = _client(fake).create_card_gallery("page-1", "cards-db", "page-1", "h-notes")
        self.assertEqual(view_id, "view-1")
        self.assertEqual(fake.requests[0][:2], ("GET", "databases/cards-db"))
        method, path, body = fake.requests[1]
        self.assertEqual((method, path), ("POST", "views"))
        self.assertEqual(body, card_gallery_body("ds-1", "page-1", "page-1", "h-notes"))

    def test_data_source_id_cached(self):
        fake = _FakeClient()
        client = _client(fake)
        client.create_card_gallery("p1", "cards-db", "p1", "h1")
        client.create_card_gallery("p2", "cards-db", "p2", "h2")
        db_gets = [r for r in fake.requests if r[1] == "databases/cards-db"]
        self.assertEqual(len(db_gets), 1)

    def test_no_data_source_creates_nothing(self):
        fake = _FakeClient(data_sources=[])
        with self.assertLogs(
            "src.infrastructure.notion.notion_views_client", level="WARNING"
        ):
            self.assertIsNone(_client(fake).create_card_gallery("p1", "cards-db", "p1", "h1"))
        self.assertFalse([r for r in fake.requests if r[1] == "views"])

    def test_default_client_pins_new_api_version(self):
        self.assertEqual(
            NotionViewsClient(token="t")._client.options.notion_version,
            NOTION_VIEWS_API_VERSION)
        self.assertEqual(NOTION_VIEWS_API_VERSION, "2026-03-11")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_notion_views_client.py -v`
Expected: `ModuleNotFoundError: No module named 'src.infrastructure.notion.notion_views_client'`

- [ ] **Step 3: 實作**

建立 `src/infrastructure/notion/notion_views_client.py`：

```python
"""The only place that talks to Notion's newer API version (Views API).

notion-client 2.2.1 defaults to Notion-Version 2022-06-28 and its endpoint
helpers silently drop body fields they don't know, so this client pins a newer
version and sends raw requests through Client.request(). Everything else in the
project stays on the old version.
"""
import logging
from typing import Dict, Optional

from notion_client import Client

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

NOTION_VIEWS_API_VERSION = "2026-03-11"
CARD_GALLERY_NAME = "本書卡片"
# 卡片盒欄位名（見 zettelkasten_card_repository）
_CARD_SOURCE_PROPERTY = "來源"
_CARD_TITLE_PROPERTY = "標題"


def card_gallery_body(data_source_id: str, page_id: str, book_page_id: str,
                      after_block_id: str) -> Dict:
    """POST /v1/views body: a gallery of this book's cards, placed right after
    the「筆記圖」heading (verified in M1 Task 1)."""
    return {
        "data_source_id": data_source_id,
        "name": CARD_GALLERY_NAME,
        "type": "gallery",
        "create_database": {
            "parent": {"type": "page_id", "page_id": page_id},
            "position": {"type": "after_block", "block_id": after_block_id},
        },
        "filter": {"property": _CARD_SOURCE_PROPERTY,
                   "relation": {"contains": book_page_id}},
        "sorts": [{"property": _CARD_TITLE_PROPERTY, "direction": "ascending"}],
        "configuration": {"type": "gallery", "cover": {"type": "page_cover"}},
    }


class NotionViewsClient:
    def __init__(self, token: str, rate_limiter: Optional[NotionRateLimiter] = None,
                 client: Optional[Client] = None):
        self._client = client or Client(auth=token, notion_version=NOTION_VIEWS_API_VERSION)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        self._data_source_ids: Dict[str, str] = {}

    def data_source_id(self, database_id: str) -> Optional[str]:
        """First data source of a database (cached per run)."""
        if database_id in self._data_source_ids:
            return self._data_source_ids[database_id]
        db = retry_with_backoff(
            lambda: self._client.request(path=f"databases/{database_id}", method="GET"),
            self._rate_limiter,
        ) or {}
        sources = db.get("data_sources") or []
        if not sources:
            logger.warning(f"資料庫 {database_id} 沒有回傳 data source，無法建 view")
            return None
        self._data_source_ids[database_id] = sources[0]["id"]
        return sources[0]["id"]

    def create_card_gallery(self, page_id: str, cards_database_id: str,
                            book_page_id: str, after_block_id: str) -> Optional[str]:
        data_source_id = self.data_source_id(cards_database_id)
        if not data_source_id:
            return None
        body = card_gallery_body(data_source_id, page_id, book_page_id, after_block_id)
        view = retry_with_backoff(
            lambda: self._client.request(path="views", method="POST", body=body),
            self._rate_limiter,
        ) or {}
        logger.info(f"已在書頁 {page_id} 建立卡片 gallery（view {view.get('id')}）")
        return view.get("id")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_notion_views_client.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/notion_views_client.py tests/unit/test_notion_views_client.py
git commit -m "✨ feat: Views API client——在書頁「筆記圖」後建本書卡片 gallery"
```

---

### Task 9: `CompleteReadingListPageUseCase`（M1 補頁流程）

**Files:**
- Create: `src/application/use_cases/complete_reading_list_page_use_case.py`
- Test: `tests/unit/test_complete_reading_list_page.py`（新建）

**Interfaces:**
- Consumes: Task 3 `ReadingListRepository`（`find_page`、`is_created_by_integration`、`list_blocks`、`append_blocks`、`update_page`、`type_page_ids`）與 `BOOK_TYPE_PROPERTY`；Task 4 `CoverFinder.find`；Task 6 `list_book_cards`、`derive_book_types`；Task 7 `skeleton_blocks`、`is_blank_page`、`find_section`、`section_is_empty`、`SECTION_NOTES`；Task 8 `create_card_gallery`
- Produces:
  - `CompleteReadingListPageUseCase(reading_list, card_repo, views, cover_finder, cards_database_id: Optional[str], type_mapping: Dict[str, str])`
  - `.execute(book: Book, kobo_page_id: str) -> None`（gallery 失敗不拋出；其他例外往上拋，由 Task 10 的 `SyncBooksUseCase` 記成錯誤）

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_complete_reading_list_page.py`：

```python
"""CompleteReadingListPageUseCase — 只補 integration 建的頁、只補空白處、重跑冪等。"""
import unittest

from src.application.use_cases.complete_reading_list_page_use_case import (
    CompleteReadingListPageUseCase,
)
from src.config.settings import DEFAULT_BOOK_TYPE_MAPPING
from src.domain.entities.book import Book
from src.domain.entities.book_card import BookCard
from src.infrastructure.notion.reading_list_page_blocks import (
    SECTION_NOTES,
    SECTIONS,
    block_text,
)
from src.infrastructure.notion.reading_list_repository import BOOK_TYPE_PROPERTY

COVER = "https://cdn.kobo.com/book-images/img-1/353/569/90/False/image.jpg"
BOOK = Book(id="b1", title="多巴胺國度", author="安娜．蘭布克", image_id="img-1")


def _page(cover=None, icon=None, types=None, with_type_prop=True):
    props = {}
    if with_type_prop:
        props[BOOK_TYPE_PROPERTY] = {"type": "relation", "relation": list(types or [])}
    return {"id": "rl-1", "cover": cover, "icon": icon,
            "created_by": {"id": "bot"}, "properties": props}


class _FakeReadingList:
    def __init__(self, page, blocks=None, bot=True, type_ids=None):
        self.page = page
        self.blocks = list(blocks or [])
        self.bot = bot
        self.type_ids = type_ids if type_ids is not None else {"Psychology": "t-psy"}
        self.appended = []
        self.updates = []

    def find_page(self, title, source_page_id=None):
        return self.page

    def is_created_by_integration(self, page):
        return self.bot

    def list_blocks(self, page_id):
        return list(self.blocks)

    def append_blocks(self, page_id, blocks, after=None):
        self.appended.append(blocks)
        created = []
        for block in blocks:
            new = dict(block)
            new["id"] = f"blk-{len(self.blocks)}"
            self.blocks.append(new)
            created.append(new)
        return created

    def update_page(self, page_id, properties=None, cover_url=None, icon_url=None):
        self.updates.append({"properties": properties, "cover_url": cover_url,
                             "icon_url": icon_url})
        if cover_url:
            self.page["cover"] = {"type": "external"}
        if icon_url:
            self.page["icon"] = {"type": "external"}
        if properties:
            self.page["properties"].update(
                {k: {"type": "relation", "relation": v["relation"]}
                 for k, v in properties.items()})

    def type_page_ids(self, names):
        return {n: self.type_ids[n] for n in names if n in self.type_ids}


class _FakeViews:
    """建立成功時在「筆記圖」標題後插入一個 child_database block，模擬真實頁面。"""

    def __init__(self, reading_list, fail=False):
        self.rl = reading_list
        self.fail = fail
        self.calls = []

    def create_card_gallery(self, page_id, cards_database_id, book_page_id, after_block_id):
        self.calls.append((page_id, cards_database_id, book_page_id, after_block_id))
        if self.fail:
            raise RuntimeError("views api down")
        index = next(i for i, b in enumerate(self.rl.blocks) if b.get("id") == after_block_id)
        self.rl.blocks.insert(index + 1, {"type": "child_database", "id": "db-1"})
        return "view-1"


class _FakeCards:
    def __init__(self, cards):
        self.cards = cards
        self.calls = 0

    def list_book_cards(self, books_page_id):
        self.calls += 1
        return list(self.cards)


class _FakeCover:
    def __init__(self, url=COVER):
        self.url = url

    def find(self, book):
        return self.url


def _psych_cards():
    return [BookCard(page_id=f"c{i}", title="卡", tags=["💞心理學"]) for i in range(3)]


def _use_case(rl, views=None, cards=None, cover=COVER, cards_db="cards-db"):
    return CompleteReadingListPageUseCase(
        reading_list=rl,
        card_repo=cards if cards is not None else _FakeCards(_psych_cards()),
        views=views,
        cover_finder=_FakeCover(cover),
        cards_database_id=cards_db,
        type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING),
    )


def _heading(text):
    return {"type": "heading_2", "id": f"h-{text}", "heading_2": {"rich_text": [{"plain_text": text}]}}


class TestCompleteReadingListPage(unittest.TestCase):
    def test_blank_page_gets_skeleton_gallery_cover_and_type(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        _use_case(rl, views).execute(BOOK, "kobo-1")

        self.assertEqual(len(rl.appended), 1)
        headings = [block_text(b) for b in rl.appended[0] if b["type"] == "heading_2"]
        self.assertEqual(headings, list(SECTIONS))
        notes_id = next(b["id"] for b in rl.blocks if block_text(b) == SECTION_NOTES)
        self.assertEqual(views.calls, [("rl-1", "cards-db", "rl-1", notes_id)])
        self.assertIn({"properties": None, "cover_url": COVER, "icon_url": COVER}, rl.updates)
        self.assertIn(
            {"properties": {BOOK_TYPE_PROPERTY: {"relation": [{"id": "t-psy"}]}},
             "cover_url": None, "icon_url": None},
            rl.updates)

    def test_second_run_is_a_no_op(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        use_case = _use_case(rl, views)
        use_case.execute(BOOK, "kobo-1")
        appended, calls, updates = len(rl.appended), len(views.calls), len(rl.updates)
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(
            (len(rl.appended), len(views.calls), len(rl.updates)), (appended, calls, updates))

    def test_manual_page_is_never_touched(self):
        rl = _FakeReadingList(_page(), bot=False)
        views = _FakeViews(rl)
        cards = _FakeCards(_psych_cards())
        _use_case(rl, views, cards).execute(BOOK, "kobo-1")
        self.assertEqual((rl.appended, views.calls, rl.updates, cards.calls), ([], [], [], 0))

    def test_page_not_found(self):
        rl = _FakeReadingList(None)
        _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertEqual((rl.appended, rl.updates), ([], []))

    def test_page_with_user_text_gets_no_skeleton(self):
        user_line = {"type": "paragraph", "id": "u1",
                     "paragraph": {"rich_text": [{"plain_text": "我先寫的一行"}]}}
        rl = _FakeReadingList(_page(), blocks=[user_line])
        views = _FakeViews(rl)
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ):
            _use_case(rl, views).execute(BOOK, "kobo-1")
        self.assertEqual(rl.appended, [])
        self.assertEqual(views.calls, [])
        self.assertIn({"properties": None, "cover_url": COVER, "icon_url": COVER}, rl.updates)

    def test_renamed_notes_heading_skips_gallery(self):
        rl = _FakeReadingList(_page(), blocks=[_heading("書籍資料"), _heading("卡片")])
        views = _FakeViews(rl)
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ) as logs:
            _use_case(rl, views).execute(BOOK, "kobo-1")
        self.assertEqual(views.calls, [])
        self.assertEqual(rl.appended, [])
        self.assertTrue(any(SECTION_NOTES in line for line in logs.output))

    def test_gallery_failure_does_not_raise_and_is_retried(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl, fail=True)
        use_case = _use_case(rl, views)
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ):
            use_case.execute(BOOK, "kobo-1")
        views.fail = False
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(views.calls), 2)
        self.assertEqual(len(rl.appended), 1)

    def test_existing_cover_only_icon_added(self):
        rl = _FakeReadingList(_page(cover={"type": "external"}))
        _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertIn({"properties": None, "cover_url": None, "icon_url": COVER}, rl.updates)

    def test_no_cover_means_no_image_and_no_cover_update(self):
        rl = _FakeReadingList(_page())
        _use_case(rl, _FakeViews(rl), cover=None).execute(BOOK, "kobo-1")
        self.assertNotIn("image", [b["type"] for b in rl.appended[0]])
        self.assertFalse([u for u in rl.updates if u["cover_url"] or u["icon_url"]])

    def test_existing_type_untouched(self):
        rl = _FakeReadingList(_page(types=[{"id": "t-mkt"}]))
        cards = _FakeCards(_psych_cards())
        _use_case(rl, _FakeViews(rl), cards).execute(BOOK, "kobo-1")
        self.assertEqual(cards.calls, 0)
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_type_name_missing_from_type_db_warns(self):
        rl = _FakeReadingList(_page(), type_ids={})
        with self.assertLogs(
            "src.application.use_cases.complete_reading_list_page_use_case", level="WARNING"
        ):
            _use_case(rl, _FakeViews(rl)).execute(BOOK, "kobo-1")
        self.assertFalse([u for u in rl.updates if u["properties"]])

    def test_without_cards_db_no_gallery_and_no_type(self):
        rl = _FakeReadingList(_page())
        views = _FakeViews(rl)
        use_case = CompleteReadingListPageUseCase(
            reading_list=rl, card_repo=None, views=None, cover_finder=_FakeCover(),
            cards_database_id=None, type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING))
        use_case.execute(BOOK, "kobo-1")
        self.assertEqual(len(rl.appended), 1)
        self.assertEqual(views.calls, [])
        self.assertFalse([u for u in rl.updates if u["properties"]])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_complete_reading_list_page.py -v`
Expected: `ModuleNotFoundError: No module named 'src.application.use_cases.complete_reading_list_page_use_case'`

- [ ] **Step 3: 實作**

建立 `src/application/use_cases/complete_reading_list_page_use_case.py`：

```python
"""Complete a sync-created 📚 Personal Reading List page (M1: no LLM).

Spec: docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md
Only pages created by this integration are touched, and only what is still
empty is written — so re-running is a no-op and nothing a person typed is ever
overwritten.
"""
import logging
from typing import Dict, Optional

from ...domain.entities.book import Book
from ...domain.services.reading_list_rules import derive_book_types
from ...infrastructure.external.cover_fetcher import CoverFinder
from ...infrastructure.notion.notion_views_client import NotionViewsClient
from ...infrastructure.notion.reading_list_page_blocks import (
    SECTION_NOTES,
    find_section,
    is_blank_page,
    section_is_empty,
    skeleton_blocks,
)
from ...infrastructure.notion.reading_list_repository import (
    BOOK_TYPE_PROPERTY,
    ReadingListRepository,
)
from ...infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)

logger = logging.getLogger(__name__)


class CompleteReadingListPageUseCase:
    def __init__(
        self,
        reading_list: ReadingListRepository,
        card_repo: Optional[ZettelkastenCardRepository],
        views: Optional[NotionViewsClient],
        cover_finder: CoverFinder,
        cards_database_id: Optional[str],
        type_mapping: Dict[str, str],
    ):
        self._reading_list = reading_list
        self._card_repo = card_repo
        self._views = views
        self._cover_finder = cover_finder
        self._cards_database_id = cards_database_id
        self._type_mapping = type_mapping

    def execute(self, book: Book, kobo_page_id: str) -> None:
        page = self._reading_list.find_page(book.title, kobo_page_id)
        if page is None:
            logger.debug(f"'{book.title}' 沒有 Reading List 頁，跳過補頁")
            return
        if not self._reading_list.is_created_by_integration(page):
            logger.debug(f"'{book.title}' 的 Reading List 頁是手動建立的，不補")
            return

        page_id = page["id"]
        cover_url = self._cover_finder.find(book)
        blocks = self._reading_list.list_blocks(page_id)
        if is_blank_page(blocks):
            self._reading_list.append_blocks(
                page_id, skeleton_blocks(book, cover_url, kobo_page_id))
            logger.info(f"'{book.title}' 書頁已建立版面（{page_id}）")
            blocks = self._reading_list.list_blocks(page_id)

        self._ensure_card_gallery(book, page_id, blocks)
        self._ensure_cover(page, cover_url)
        self._ensure_book_types(book, page)

    def _ensure_card_gallery(self, book: Book, page_id: str, blocks) -> None:
        if self._views is None or not self._cards_database_id:
            return
        section = find_section(blocks, SECTION_NOTES)
        if section is None:
            logger.warning(f"'{book.title}' 書頁找不到「{SECTION_NOTES}」段，跳過卡片 gallery")
            return
        heading, body = section
        if not section_is_empty(body):
            return
        try:
            self._views.create_card_gallery(
                page_id, self._cards_database_id, page_id, heading["id"])
        except Exception as e:  # noqa: BLE001 — 下次同步段落仍空白，會自動重試
            logger.warning(f"'{book.title}' 卡片 gallery 建立失敗（下次同步重試）: {e}")

    def _ensure_cover(self, page: dict, cover_url: Optional[str]) -> None:
        if not cover_url:
            return
        need_cover = not page.get("cover")
        need_icon = not page.get("icon")
        if not (need_cover or need_icon):
            return
        self._reading_list.update_page(
            page["id"],
            cover_url=cover_url if need_cover else None,
            icon_url=cover_url if need_icon else None,
        )

    def _ensure_book_types(self, book: Book, page: dict) -> None:
        if self._card_repo is None:
            return
        prop = (page.get("properties") or {}).get(BOOK_TYPE_PROPERTY)
        if prop is None or prop.get("relation"):
            return
        cards = self._card_repo.list_book_cards(page["id"])
        names = derive_book_types(cards, self._type_mapping)
        if not names:
            return
        ids = self._reading_list.type_page_ids(names)
        missing = [name for name in names if name not in ids]
        if missing:
            logger.warning(f"書籍種類庫找不到：{'、'.join(missing)}（'{book.title}'）")
        found = [ids[name] for name in names if name in ids]
        if found:
            self._reading_list.update_page(
                page["id"],
                properties={BOOK_TYPE_PROPERTY: {"relation": [{"id": i} for i in found]}},
            )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_complete_reading_list_page.py -v`
Expected: 12 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/application/use_cases/complete_reading_list_page_use_case.py tests/unit/test_complete_reading_list_page.py
git commit -m "✨ feat: CompleteReadingListPageUseCase——只補同步建的書頁、只補空白處"
```

---

### Task 10: `READING_LIST_PAGES` 設定＋同步後依序補頁

**Files:**
- Modify: `src/config/settings.py`
- Rewrite: `src/application/use_cases/sync_books_use_case.py`
- Test: `tests/unit/test_reading_list_sync_wiring.py`（新建）

**Interfaces:**
- Consumes: Task 9 `CompleteReadingListPageUseCase.execute(book, kobo_page_id)`
- Produces:
  - `Settings.reading_list_pages: List[str]`、`Settings.google_books_api_key: Optional[str]`、`Settings.reading_list_matches(title: str) -> bool`
  - `SyncBooksUseCase(..., page_use_case: Optional[CompleteReadingListPageUseCase] = None, should_complete_page: Optional[Callable[[str], bool]] = None)`；`.page_use_case`、`.should_complete_page` 為公開屬性（Task 11 的測試會讀）
  - `_process_single_book(book) -> Optional[str]`（成功回傳劃線頁 id）

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_reading_list_sync_wiring.py`：

```python
"""READING_LIST_PAGES 設定，以及 SyncBooksUseCase 在執行緒池結束後依序補頁。"""
import os
import unittest
from unittest import mock

from src.application.use_cases.sync_books_use_case import SyncBooksUseCase
from src.config.settings import Settings
from src.domain.entities.book import Book
from src.domain.services.chapter_extractor import ChapterExtractor


class TestReadingListSettings(unittest.TestCase):
    def test_disabled_when_unset(self):
        s = Settings(notion_token="t", notion_database_id="d")
        self.assertEqual(s.reading_list_pages, [])
        self.assertFalse(s.reading_list_matches("任何書"))

    def test_substrings_and_all(self):
        s = Settings(notion_token="t", notion_database_id="d",
                     reading_list_pages=Settings._parse_resync("多巴胺, 重要事"))
        self.assertTrue(s.reading_list_matches("多巴胺國度：在縱慾年代找到身心平衡"))
        self.assertFalse(s.reading_list_matches("異數"))
        s_all = Settings(notion_token="t", notion_database_id="d", reading_list_pages=["all"])
        self.assertTrue(s_all.reading_list_matches("異數"))

    def test_resync_matching_unchanged(self):
        s = Settings(notion_token="t", notion_database_id="d",
                     resync_highlights=["物哀"])
        self.assertTrue(s.resync_matches("日本美學1：物哀：櫻花落下後"))
        self.assertFalse(s.resync_matches("迷因"))

    def test_from_env_plumbing(self):
        env = {"NOTION_TOKEN": "t", "NOTION_DATABASE_ID": "d",
               "READING_LIST_PAGES": "all", "GOOGLE_BOOKS_API_KEY": "k-1"}
        with mock.patch.dict(os.environ, env):
            s = Settings.from_env()
        self.assertEqual(s.reading_list_pages, ["all"])
        self.assertEqual(s.google_books_api_key, "k-1")


class _FakeBookRepo:
    def __init__(self, titles):
        self._books = [Book(id=f"id-{t}", title=t) for t in titles]

    def get_all_books(self):
        return list(self._books)

    def get_highlights_with_chapters(self, book_id):
        return []


class _FakeNotionRepo:
    """已匯出的書：走更新元數據分支；劃線頁 id = kobo-<書名>。"""

    def check_book_exists(self, title, is_exported=True):
        return {"is_target_valid": is_exported, "pageId": f"kobo-{title}"}

    def update_book_metadata(self, page_id, book):
        pass

    def add_book_cover(self, page_id, book):
        pass

    def replace_book_highlights(self, page_id, highlights):
        pass


class _FakePageUseCase:
    def __init__(self, fail_on=None):
        self.calls = []
        self._fail_on = fail_on

    def execute(self, book, kobo_page_id):
        if book.title == self._fail_on:
            raise RuntimeError("boom")
        self.calls.append((book.title, kobo_page_id))


def _use_case(page_use_case, should_complete_page=lambda _t: True):
    return SyncBooksUseCase(
        book_repo=_FakeBookRepo(["B-book", "A-book"]),
        notion_repo=_FakeNotionRepo(),
        chapter_extractor=ChapterExtractor(),
        max_workers=2,
        page_use_case=page_use_case,
        should_complete_page=should_complete_page,
    )


class TestSyncThenCompletePages(unittest.TestCase):
    def test_pages_completed_after_sync_in_title_order(self):
        pages = _FakePageUseCase()
        result = _use_case(pages).execute()
        self.assertEqual(result.successful_syncs, 2)
        self.assertEqual(pages.calls, [("A-book", "kobo-A-book"), ("B-book", "kobo-B-book")])

    def test_only_matching_titles_completed(self):
        pages = _FakePageUseCase()
        _use_case(pages, should_complete_page=lambda t: t == "B-book").execute()
        self.assertEqual(pages.calls, [("B-book", "kobo-B-book")])

    def test_page_failure_recorded_but_sync_counts(self):
        pages = _FakePageUseCase(fail_on="A-book")
        result = _use_case(pages).execute()
        self.assertEqual(result.successful_syncs, 2)
        self.assertEqual(result.failed_syncs, 0)
        self.assertTrue(any("補頁失敗: A-book" in e for e in result.errors))
        self.assertEqual(pages.calls, [("B-book", "kobo-B-book")])

    def test_without_page_use_case_nothing_happens(self):
        result = _use_case(None).execute()
        self.assertEqual(result.successful_syncs, 2)
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_reading_list_sync_wiring.py -v`
Expected: `TypeError: Settings.__init__() got an unexpected keyword argument 'reading_list_pages'` 與 `TypeError: SyncBooksUseCase.__init__() got an unexpected keyword argument 'page_use_case'`

- [ ] **Step 3: 實作**

`src/config/settings.py`：

1. 在 `resync_highlights: List[str] = field(default_factory=list)` 之後加入：

```python
    # READING_LIST_PAGES：空=停用；"all"=全部；否則為書名子字串清單（語法同 RESYNC_HIGHLIGHTS）。
    # 命中的書會在同步後補完「同步自動建立」的 Reading List 書頁。
    reading_list_pages: List[str] = field(default_factory=list)
    # 選填：Google Books API key（書封的第二來源；不帶 key 會吃全球共用配額）
    google_books_api_key: Optional[str] = None
```

2. `from_env()` 的 `cls(...)` 最後（`resync_highlights=...` 之後）加入：

```python
            reading_list_pages=cls._parse_resync(os.getenv("READING_LIST_PAGES")),
            google_books_api_key=os.getenv("GOOGLE_BOOKS_API_KEY") or None,
```

3. 把 `resync_matches` 換成下面三個方法：

```python
    @staticmethod
    def _title_filter_matches(filters: List[str], title: str) -> bool:
        """書名子字串清單比對；"all" 命中全部，空清單一律不命中。"""
        return any(t == "all" or t in title for t in filters)

    def resync_matches(self, title: str) -> bool:
        """此書是否需要重建劃線內容（"all" 或書名含任一子字串）。"""
        return self._title_filter_matches(self.resync_highlights, title)

    def reading_list_matches(self, title: str) -> bool:
        """此書是否要補完 Reading List 書頁（語法同 resync_matches）。"""
        return self._title_filter_matches(self.reading_list_pages, title)
```

以下列內容**整檔取代** `src/application/use_cases/sync_books_use_case.py`（已含 Task 5 的 `add_book_cover(page_id, book)`）：

```python
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from ...domain.entities.book import Book
from ...domain.repositories.book_repository import BookRepository
from ...domain.repositories.notion_repository import NotionRepository
from ...domain.services.chapter_extractor import ChapterExtractor
from ..dtos.sync_result import SyncResult
from .complete_reading_list_page_use_case import CompleteReadingListPageUseCase
from .generate_book_cards_use_case import GenerateBookCardsUseCase


class SyncBooksUseCase:
    """同步書籍用例"""

    def __init__(self,
                 book_repo: BookRepository,
                 notion_repo: NotionRepository,
                 chapter_extractor: ChapterExtractor,
                 max_workers: int = 5,
                 card_use_case: Optional[GenerateBookCardsUseCase] = None,
                 should_resync: Optional[Callable[[str], bool]] = None,
                 page_use_case: Optional[CompleteReadingListPageUseCase] = None,
                 should_complete_page: Optional[Callable[[str], bool]] = None):
        self.book_repo = book_repo
        self.notion_repo = notion_repo
        self.chapter_extractor = chapter_extractor
        self.max_workers = max_workers
        self.card_use_case = card_use_case
        # 書名 → 是否重建已匯出頁面的劃線內容（RESYNC_HIGHLIGHTS）
        self.should_resync = should_resync or (lambda _title: False)
        # 同步後補完 Reading List 書頁（READING_LIST_PAGES）；None = 功能關閉
        self.page_use_case = page_use_case
        self.should_complete_page = should_complete_page or (lambda _title: False)
        self.logger = logging.getLogger(__name__)

    def execute(self) -> SyncResult:
        """執行同步流程"""
        self.logger.info("開始同步書籍到Notion")

        books = self.book_repo.get_all_books()
        self.logger.info(f"找到 {len(books)} 本書籍待處理")

        if not books:
            return SyncResult(total_books=0, successful_syncs=0)

        result = SyncResult(total_books=len(books), successful_syncs=0)
        # (書, 劃線頁 id)：as_completed 迴圈跑在主執行緒，append 不需要鎖
        synced: List[Tuple[Book, str]] = []

        # 使用線程池並行處理
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(books))) as executor:
            future_to_book = {
                executor.submit(self._process_single_book, book): book
                for book in books
            }

            for future in as_completed(future_to_book):
                book = future_to_book[future]
                try:
                    page_id = future.result()
                    if page_id:
                        result.successful_syncs += 1
                        synced.append((book, page_id))
                        self.logger.info(f"成功處理書籍: {book.title}")
                    else:
                        result.add_error(f"處理失敗: {book.title}")
                except Exception as e:
                    error_msg = f"處理書籍 {book.title} 時發生錯誤: {str(e)}"
                    result.add_error(error_msg)
                    self.logger.error(error_msg, exc_info=True)

        self._complete_reading_list_pages(synced, result)

        self.logger.info(
            f"同步完成。成功: {result.successful_syncs}/{result.total_books} "
            f"({result.success_rate:.1f}%)")
        return result

    def _complete_reading_list_pages(self, synced: List[Tuple[Book, str]],
                                     result: SyncResult) -> None:
        """執行緒池結束後，依書名順序逐本補 Reading List 書頁。

        刻意不並行：M2 會用地端 LLM，VRAM 一次只放得下一個模型；依序也讓 log 可讀。
        單本失敗只記進錯誤清單，不算劃線同步失敗、不影響 exit code。
        """
        if self.page_use_case is None:
            return
        for book, page_id in sorted(synced, key=lambda pair: pair[0].title):
            if not self.should_complete_page(book.title):
                continue
            try:
                self.page_use_case.execute(book, page_id)
            except Exception as e:
                error_msg = f"補頁失敗: {book.title}: {e}"
                result.add_error(error_msg)
                self.logger.error(error_msg, exc_info=True)

    def _process_single_book(self, book) -> Optional[str]:
        """處理單本書籍；成功回傳劃線頁 id，失敗回傳 None"""
        try:
            clean_title = book.get_clean_title()

            # 檢查書籍是否已存在且已導出
            book_status = self.notion_repo.check_book_exists(clean_title, is_exported=True)

            if book_status["is_target_valid"]:
                # 書籍已存在且已導出，更新元數據
                self.logger.info(f"書籍 {clean_title} 已導出，更新元數據")
                page_id = book_status["pageId"]
                highlights = None
                if self.should_resync(clean_title):
                    # RESYNC_HIGHLIGHTS 命中：刪除同步產生的 block 後重建劃線
                    self.logger.info(f"重建 {clean_title} 的劃線內容 (resync)")
                    highlights = self.book_repo.get_highlights_with_chapters(book.id)
                    self.notion_repo.replace_book_highlights(page_id, highlights)
                self.notion_repo.update_book_metadata(page_id, book)
                self.notion_repo.add_book_cover(page_id, book)
                # 補齊卡片：若卡片盒尚無此書關聯卡片，repo 內 dedup 會控制是否實際新增
                if self.card_use_case is not None:
                    if highlights is None:
                        highlights = self.book_repo.get_highlights_with_chapters(book.id)
                    self.card_use_case.execute(book, highlights, source_page_id=page_id)
                return page_id

            # 檢查書籍是否存在但未導出
            book_status = self.notion_repo.check_book_exists(clean_title, is_exported=False)
            page_id = book_status.get("pageId")

            if not book_status["is_target_valid"]:
                # 書籍不存在，創建新條目
                self.logger.info(f"創建新書籍條目: {clean_title}")
                if not self.notion_repo.create_book_entry(clean_title):
                    return None

                # 重新獲取頁面ID
                new_book_status = self.notion_repo.check_book_exists(clean_title, is_exported=False)
                page_id = new_book_status.get("pageId")

            if not page_id:
                self.logger.error(f"無法獲取書籍 {clean_title} 的頁面ID")
                return None

            # 獲取並處理高亮內容
            highlights = self.book_repo.get_highlights_with_chapters(book.id)

            # Repo 已做完整章節提取;extractor 僅在章節名稱仍為預設值時作 fallback
            for highlight in highlights:
                if highlight.chapter_name in (None, '', '未知章節', '未知章节'):
                    highlight_data = {
                        'text': highlight.text,
                        'content_id': highlight.content_id,
                        'start_container_path': highlight.start_container_path
                    }
                    highlight.chapter_name = self.chapter_extractor.extract_chapter_name(highlight_data)

            self.logger.info(f"找到 {len(highlights)} 個高亮內容，開始同步")

            # 同步高亮內容到Notion
            self.notion_repo.sync_book_highlights(page_id, highlights)

            # 產生 Zettelkasten 卡片並上傳卡片盒（若已啟用）
            if self.card_use_case is not None:
                self.card_use_case.execute(book, highlights, source_page_id=page_id)

            # 更新書籍元數據
            self.notion_repo.update_book_metadata(page_id, book)

            # 添加書籍封面
            self.notion_repo.add_book_cover(page_id, book)

            return page_id

        except Exception as e:
            self.logger.error(f"處理書籍 {book.title} 時發生錯誤: {str(e)}", exc_info=True)
            return None
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_reading_list_sync_wiring.py tests/unit/test_resync.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/config/settings.py src/application/use_cases/sync_books_use_case.py tests/unit/test_reading_list_sync_wiring.py
git commit -m "✨ feat: READING_LIST_PAGES 設定，同步結束後依序補完 Reading List 書頁"
```

---

### Task 11: DRY_RUN decorator＋組裝＋`.env.example`

**Files:**
- Create: `src/infrastructure/notion/dry_run_reading_list_repository.py`
- Rewrite: `src/infrastructure/container.py`
- Modify: `.env.example`
- Test: `tests/unit/test_reading_list_dry_run.py`（新建）

**Interfaces:**
- Consumes: Task 3 `ReadingListRepository`、Task 4 `CoverFinder`、Task 5 `NotionApiRepository(cover_finder=...)`、Task 6 `DEFAULT_BOOK_TYPE_MAPPING`、Task 8 `NotionViewsClient`、Task 9 `CompleteReadingListPageUseCase`、Task 10 `Settings.reading_list_pages`／`google_books_api_key`／`reading_list_matches`、`SyncBooksUseCase(page_use_case=..., should_complete_page=...)`
- Produces:
  - `DryRunReadingListRepository(inner)`：`find_page`、`is_created_by_integration`、`type_page_ids` 委派；`list_blocks` 回傳 inner 的結果加上本輪「寫入」的 blocks；`append_blocks`、`update_page` 只記 log
  - `DryRunNotionViewsClient(inner)`：`data_source_id` 委派；`create_card_gallery` 只記 log、回傳 None
  - `build_use_case(settings)` 在 `READING_LIST_PAGES` 有值且有 `NOTION_BOOKS_DATABASE_ID` 時組出 `page_use_case`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/unit/test_reading_list_dry_run.py`：

```python
"""Reading List 補頁的 DRY_RUN decorator 與 container 組裝。"""
import unittest

from src.application.use_cases.complete_reading_list_page_use_case import (
    CompleteReadingListPageUseCase,
)
from src.config.settings import Settings
from src.infrastructure.container import build_use_case
from src.infrastructure.notion.dry_run_reading_list_repository import (
    DryRunNotionViewsClient,
    DryRunReadingListRepository,
)


class _Inner:
    def __init__(self):
        self.writes = []

    def find_page(self, title, source_page_id=None):
        return {"id": "rl-1"}

    def is_created_by_integration(self, page):
        return True

    def type_page_ids(self, names):
        return {"Psychology": "t-psy"}

    def list_blocks(self, page_id):
        return [{"type": "paragraph", "id": "real-1"}]

    def append_blocks(self, page_id, blocks, after=None):
        self.writes.append("append")
        return []

    def update_page(self, page_id, properties=None, cover_url=None, icon_url=None):
        self.writes.append("update")

    def data_source_id(self, database_id):
        return "ds-1"

    def create_card_gallery(self, page_id, cards_database_id, book_page_id, after_block_id):
        self.writes.append("gallery")
        return "view-1"


class TestDryRunReadingList(unittest.TestCase):
    def test_writes_never_reach_inner(self):
        inner = _Inner()
        repo = DryRunReadingListRepository(inner)
        with self.assertLogs(
            "src.infrastructure.notion.dry_run_reading_list_repository", level="INFO"
        ):
            created = repo.append_blocks("rl-1", [{"type": "heading_2"}])
            repo.update_page("rl-1", cover_url="https://c/x.jpg")
        self.assertEqual(inner.writes, [])
        self.assertEqual(created[0]["type"], "heading_2")
        self.assertTrue(created[0]["id"].startswith("dry-run-"))

    def test_list_blocks_includes_blocks_written_this_run(self):
        repo = DryRunReadingListRepository(_Inner())
        repo.append_blocks("rl-1", [{"type": "heading_2"}])
        self.assertEqual([b["id"] for b in repo.list_blocks("rl-1")][0], "real-1")
        self.assertEqual(len(repo.list_blocks("rl-1")), 2)
        self.assertEqual(len(repo.list_blocks("other-page")), 1)

    def test_reads_delegate(self):
        repo = DryRunReadingListRepository(_Inner())
        self.assertEqual(repo.find_page("書", "kobo-1"), {"id": "rl-1"})
        self.assertTrue(repo.is_created_by_integration({}))
        self.assertEqual(repo.type_page_ids(["Psychology"]), {"Psychology": "t-psy"})

    def test_views_create_is_logged_only(self):
        inner = _Inner()
        views = DryRunNotionViewsClient(inner)
        with self.assertLogs(
            "src.infrastructure.notion.dry_run_reading_list_repository", level="INFO"
        ):
            self.assertIsNone(views.create_card_gallery("rl-1", "cards", "rl-1", "h-1"))
        self.assertEqual(inner.writes, [])
        self.assertEqual(views.data_source_id("cards"), "ds-1")


class TestContainerWiring(unittest.TestCase):
    def _settings(self, **overrides):
        fields = dict(notion_token="t", notion_database_id="d",
                      notion_books_database_id="books", notion_zettelkasten_database_id="cards",
                      reading_list_pages=["all"], dry_run=False)
        fields.update(overrides)
        return Settings(**fields)

    def test_page_use_case_built_when_enabled(self):
        uc = build_use_case(self._settings())
        self.assertIsInstance(uc.page_use_case, CompleteReadingListPageUseCase)
        self.assertTrue(uc.should_complete_page("任何書"))

    def test_dry_run_wraps_writes(self):
        uc = build_use_case(self._settings(dry_run=True))
        self.assertIsInstance(uc.page_use_case._reading_list, DryRunReadingListRepository)
        self.assertIsInstance(uc.page_use_case._views, DryRunNotionViewsClient)

    def test_disabled_by_default(self):
        uc = build_use_case(self._settings(reading_list_pages=[]))
        self.assertIsNone(uc.page_use_case)
        self.assertFalse(uc.should_complete_page("任何書"))

    def test_missing_books_database_disables(self):
        uc = build_use_case(self._settings(notion_books_database_id=None))
        self.assertIsNone(uc.page_use_case)

    def test_missing_cards_database_keeps_layout_only(self):
        uc = build_use_case(self._settings(notion_zettelkasten_database_id=None))
        self.assertIsNone(uc.page_use_case._views)
        self.assertIsNone(uc.page_use_case._card_repo)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/unit/test_reading_list_dry_run.py -v`
Expected: `ModuleNotFoundError: No module named 'src.infrastructure.notion.dry_run_reading_list_repository'`

- [ ] **Step 3: 實作**

建立 `src/infrastructure/notion/dry_run_reading_list_repository.py`：

```python
"""DRY_RUN decorators for Reading List page completion.

Reads go to the real repository; writes are logged only. Blocks "written" in
this run are remembered per page, so the follow-up step (finding「筆記圖」to
place the gallery) behaves as in a real run and the log shows the full plan.
"""
import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_PREFIX = "[DRY RUN]"


class DryRunReadingListRepository:
    def __init__(self, inner):
        self._inner = inner
        self._pending: Dict[str, List[dict]] = {}
        self._lock = threading.Lock()

    def find_page(self, title: str, source_page_id: Optional[str] = None) -> Optional[dict]:
        return self._inner.find_page(title, source_page_id)

    def is_created_by_integration(self, page: dict) -> bool:
        return self._inner.is_created_by_integration(page)

    def type_page_ids(self, names: List[str]) -> Dict[str, str]:
        return self._inner.type_page_ids(names)

    def list_blocks(self, page_id: str) -> List[dict]:
        with self._lock:
            pending = list(self._pending.get(page_id, []))
        return self._inner.list_blocks(page_id) + pending

    def append_blocks(self, page_id: str, blocks: List[dict],
                      after: Optional[str] = None) -> List[dict]:
        created: List[dict] = []
        with self._lock:
            pending = self._pending.setdefault(page_id, [])
            for block in blocks:
                fake = dict(block)
                fake["id"] = f"dry-run-block-{len(pending)}"
                pending.append(fake)
                created.append(fake)
        where = f"（插在 {after} 之後）" if after else ""
        logger.info(f"{_PREFIX} 將在書頁 {page_id} 寫入 {len(blocks)} 個 block{where}")
        return created

    def update_page(self, page_id: str, properties: Optional[dict] = None,
                    cover_url: Optional[str] = None, icon_url: Optional[str] = None) -> None:
        parts = []
        if properties:
            parts.append(f"屬性 {'、'.join(properties)}")
        if cover_url:
            parts.append("cover")
        if icon_url:
            parts.append("icon")
        if parts:
            logger.info(f"{_PREFIX} 將更新書頁 {page_id}：{'、'.join(parts)}")


class DryRunNotionViewsClient:
    def __init__(self, inner):
        self._inner = inner

    def data_source_id(self, database_id: str) -> Optional[str]:
        return self._inner.data_source_id(database_id)

    def create_card_gallery(self, page_id: str, cards_database_id: str,
                            book_page_id: str, after_block_id: str) -> Optional[str]:
        logger.info(
            f"{_PREFIX} 將在書頁 {page_id} 的「筆記圖」後建立卡片 gallery"
            f"（篩選 來源＝{book_page_id}）")
        return None
```

以下列內容**整檔取代** `src/infrastructure/container.py`：

```python
"""Composition root — wires settings and repositories into a SyncBooksUseCase."""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

from ..application.use_cases.complete_reading_list_page_use_case import (
    CompleteReadingListPageUseCase,
)
from ..application.use_cases.generate_book_cards_use_case import GenerateBookCardsUseCase
from ..application.use_cases.sync_books_use_case import SyncBooksUseCase
from ..config.settings import DEFAULT_BOOK_TYPE_MAPPING, Settings
from ..domain.services.chapter_extractor import ChapterExtractor
from .external.cover_fetcher import CoverFinder
from .notion.dry_run_notion_repository import DryRunNotionRepository
from .notion.dry_run_reading_list_repository import (
    DryRunNotionViewsClient,
    DryRunReadingListRepository,
)
from .notion.notion_api_repository import NotionApiRepository
from .notion.notion_views_client import NotionViewsClient
from .notion.rate_limiter import NotionRateLimiter
from .notion.reading_list_repository import ReadingListRepository
from .notion.zettelkasten_card_repository import ZettelkastenCardRepository
from .persistence.card_store import CardStore
from .persistence.kobo_sqlite_repository import KoboSqliteRepository


def build_use_case(settings: Settings) -> SyncBooksUseCase:
    logger = logging.getLogger(__name__)
    book_repo = KoboSqliteRepository(db_path=settings.kobo_db_path)
    # 劃線頁與 Reading List 書頁共用一個 CoverFinder：同一本書本輪只查一次封面
    cover_finder = CoverFinder(google_api_key=settings.google_books_api_key)
    notion_repo = NotionApiRepository(
        token=settings.notion_token,
        database_id=settings.notion_database_id,
        cover_finder=cover_finder,
    )
    if settings.dry_run:
        logger.warning("=== DRY RUN 模式：只讀取與記錄，不會寫入 Notion ===")
        notion_repo = DryRunNotionRepository(notion_repo)
    extractor = ChapterExtractor()
    # Books DB（Reading List）：卡片「來源」與書頁補完共用同一個實例與限速器
    books_limiter = NotionRateLimiter()
    reading_list = (
        ReadingListRepository(
            token=settings.notion_token,
            database_id=settings.notion_books_database_id,
            rate_limiter=books_limiter,
        )
        if settings.notion_books_database_id else None
    )
    if settings.dry_run:
        # 卡片流程會呼叫 Ollama 並改寫 cards_output/ 的續傳狀態，dry-run 一律跳過
        if settings.enable_zettelkasten_cards:
            logger.warning("DRY RUN 模式：跳過 Zettelkasten 卡片產生與上傳")
        card_use_case = None
    else:
        card_use_case = _build_card_use_case(settings, reading_list)
    if settings.resync_highlights:
        logger.warning(
            f"RESYNC_HIGHLIGHTS 啟用：{settings.resync_highlights} — "
            "符合的已匯出書籍會重建劃線內容"
        )
    page_use_case = _build_page_use_case(settings, reading_list, cover_finder, books_limiter)
    return SyncBooksUseCase(
        book_repo=book_repo,
        notion_repo=notion_repo,
        chapter_extractor=extractor,
        max_workers=settings.max_workers,
        card_use_case=card_use_case,
        should_resync=settings.resync_matches,
        page_use_case=page_use_case,
        should_complete_page=settings.reading_list_matches,
    )


def _build_card_use_case(settings: Settings,
                         reading_list: Optional[ReadingListRepository]):
    if not settings.enable_zettelkasten_cards:
        return None
    if not settings.notion_zettelkasten_database_id:
        logging.getLogger(__name__).warning(
            "ENABLE_ZETTELKASTEN_CARDS=true 但 NOTION_ZETTELKASTEN_DATABASE_ID 未設定，跳過卡片功能"
        )
        return None

    from zettelkasten_generator import ZettelkastenCardGenerator

    generator = ZettelkastenCardGenerator(
        max_cards=settings.zettelkasten_max_cards,
        min_highlights=settings.zettelkasten_min_highlights,
        tag_categories=settings.zettelkasten_tag_categories,
    )
    card_repo = ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
        books_database_id=settings.notion_books_database_id,
        tag_categories=settings.zettelkasten_tag_categories,
        reading_list=reading_list,
    )
    card_store = CardStore(output_dir=settings.zettelkasten_cards_output_dir)
    return GenerateBookCardsUseCase(
        generator=generator, card_repo=card_repo, card_store=card_store
    )


def _build_page_use_case(
    settings: Settings,
    reading_list: Optional[ReadingListRepository],
    cover_finder: CoverFinder,
    limiter: NotionRateLimiter,
) -> Optional[CompleteReadingListPageUseCase]:
    if not settings.reading_list_pages:
        return None
    logger = logging.getLogger(__name__)
    if reading_list is None:
        logger.warning(
            "READING_LIST_PAGES 已設定但 NOTION_BOOKS_DATABASE_ID 未設定，跳過 Reading List 書頁補完")
        return None
    card_repo = None
    views = None
    if settings.notion_zettelkasten_database_id:
        # 只用來讀卡片（推算書籍種類）；與是否產卡（ENABLE_ZETTELKASTEN_CARDS）無關
        card_repo = ZettelkastenCardRepository(
            token=settings.notion_token,
            database_id=settings.notion_zettelkasten_database_id,
            books_database_id=settings.notion_books_database_id,
            rate_limiter=limiter,
            tag_categories=settings.zettelkasten_tag_categories,
            reading_list=reading_list,
        )
        views = NotionViewsClient(token=settings.notion_token, rate_limiter=limiter)
    else:
        logger.warning(
            "NOTION_ZETTELKASTEN_DATABASE_ID 未設定：書頁不建卡片 gallery、不推算書籍種類")
    page_reading_list = reading_list
    if settings.dry_run:
        page_reading_list = DryRunReadingListRepository(reading_list)
        views = DryRunNotionViewsClient(views) if views is not None else None
    logger.warning(f"Reading List 書頁補完啟用：{', '.join(settings.reading_list_pages)}")
    return CompleteReadingListPageUseCase(
        reading_list=page_reading_list,
        card_repo=card_repo,
        views=views,
        cover_finder=cover_finder,
        cards_database_id=settings.notion_zettelkasten_database_id,
        type_mapping=dict(DEFAULT_BOOK_TYPE_MAPPING),
    )


def setup_file_and_console_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger with rotating file + console output.

    Mirrors the legacy setup: file DEBUG in logs/kobo_notion_sync.log, console INFO.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return root

    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join("logs", "kobo_notion_sync.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8',
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    ))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return root
```

`.env.example`：在 `RESYNC_HIGHLIGHTS=` 那一行之後加入：

```
# Reading List 書頁補完：空=停用；all=全部；否則為逗號分隔的書名子字串（語法同 RESYNC_HIGHLIGHTS）。
# 只處理同步自動建立的 📚 Personal Reading List 頁，且只補空白的段落與屬性：
# 「心得摘錄」六段版面、書封、本書卡片 gallery、書籍種類。需要 NOTION_BOOKS_DATABASE_ID；
# 卡片 gallery 與書籍種類另需 NOTION_ZETTELKASTEN_DATABASE_ID。可搭配 DRY_RUN 預覽。
READING_LIST_PAGES=

# 選填：Google Books API key。書封優先取自 Kobo 圖床；沒有 Kobo 圖的書才查 Google Books，
# 不帶 key 時與全球共用每日配額，常回 429。
GOOGLE_BOOKS_API_KEY=
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/unit/test_reading_list_dry_run.py -v`
Expected: 全部 passed

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/notion/dry_run_reading_list_repository.py src/infrastructure/container.py .env.example tests/unit/test_reading_list_dry_run.py
git commit -m "🔧 chore: Reading List 書頁補完的 DRY_RUN decorator 與組裝"
```

---

### Task 12: 真跑驗收（DoD 第 3 條）＋文件

**Files:**
- Create（**不進 repo**，放在暫存目錄）：`check_reading_list_pages.py`
- Modify: `CLAUDE.md`
- Modify: `docs/DECISIONS.md`

**Interfaces:**
- Consumes: Task 1–11 的全部成果；`.env`；`KoboReader.sqlite`（repo 根目錄，gitignored）
- Produces: Notion 上可觀察的證據（log 片段、唯讀檢查輸出、使用者目視確認）與更新後的地圖文件

- [ ] **Step 1: 品質閘門**

Run: `python -m pytest -q && python -m ruff check .`
Expected: 全綠

- [ ] **Step 2: DRY_RUN 預覽（不寫入）**

Git Bash：
```bash
PYTHONIOENCODING=utf-8 DRY_RUN=true READING_LIST_PAGES=all python main.py
```
PowerShell：
```powershell
$env:PYTHONIOENCODING='utf-8'; $env:DRY_RUN='true'; $env:READING_LIST_PAGES='all'; python main.py; Remove-Item Env:DRY_RUN, Env:READING_LIST_PAGES
```

Expected（在 `logs/kobo_notion_sync.log` 與終端機）：
- `Reading List 書頁補完啟用：all`
- 26 次 `[DRY RUN] 將在書頁 … 寫入 N 個 block`（每頁一次）
- 26 次 `[DRY RUN] 將在書頁 … 的「筆記圖」後建立卡片 gallery`
- `[DRY RUN] 將更新書頁 …：cover、icon`、`[DRY RUN] 將更新書頁 …：屬性 Type 書籍種類`
- 沒有任何非 `[DRY RUN]` 的寫入 log

Run: `grep -c "將在書頁 .* 寫入" logs/kobo_notion_sync.log`
Expected: 26（若日誌有舊內容，只看本次執行時間之後的行）

- [ ] **Step 3: 兩本書真跑（一本閱讀中、一本已讀完）**

```bash
PYTHONIOENCODING=utf-8 READING_LIST_PAGES=重要事,多巴胺國度 python main.py
```
（PowerShell 用 `$env:READING_LIST_PAGES='重要事,多巴胺國度'`，跑完 `Remove-Item Env:READING_LIST_PAGES`。）

注意：這次同步也會對**所有**書執行既有的劃線頁封面步驟，那 20 張透明封面會在這一輪被換掉——這是 Task 5 的預期行為。

Expected log：
- `'重要事，明天做：…' 書頁已建立版面（<page id>）`、`'多巴胺國度：…' 書頁已建立版面（<page id>）`
- 兩次 `已在書頁 … 建立卡片 gallery（view …）`
- 多次 `已為 '…' 設定封面`（劃線頁的透明封面被替換）

用 Notion MCP `notion-fetch` 打開兩個書頁，確認：
- 段落依序為 書籍資料（書封圖、作者、出版社、出版社簡介）→ 筆記圖（下方有 inline 卡片 gallery）→ 概要 → 實際執行 → 心得 → 金句摘錄（「畫線重點 → @劃線頁」）
- 頁面有 cover 與 icon（Kobo 圖床網址）
- 《多巴胺國度》的 `Type 書籍種類` = Psychology；《重要事，明天做》依卡片 Tags 推出 1–2 個種類
- `Status`、`推薦分數/5`、`Done Date` 未被改動

- [ ] **Step 4: 冪等檢查**

再跑一次同一個指令。
Expected：log 中**沒有** `書頁已建立版面`、`建立卡片 gallery`；兩個書頁內容不變。

- [ ] **Step 5: 全部 26 頁真跑＋唯讀檢查**

```bash
PYTHONIOENCODING=utf-8 READING_LIST_PAGES=all python main.py
```

在暫存目錄建立 `check_reading_list_pages.py`（唯讀）：

```python
"""Read-only check after the M1 real run: the sync-created Reading List pages."""
import os

from dotenv import load_dotenv
from notion_client import Client

load_dotenv(".env")
client = Client(auth=os.environ["NOTION_TOKEN"])
books_db = os.environ["NOTION_BOOKS_DATABASE_ID"]
bot = client.users.me()["id"]

pages, cursor = [], None
while True:
    kwargs = {"database_id": books_db, "page_size": 100}
    if cursor:
        kwargs["start_cursor"] = cursor
    result = client.databases.query(**kwargs)
    pages += result["results"]
    if not result.get("has_more"):
        break
    cursor = result["next_cursor"]

mine = [p for p in pages if p["created_by"]["id"] == bot]
stats = {"pages": len(mine), "cover": 0, "icon": 0, "type": 0, "skeleton": 0, "gallery": 0}
for page in mine:
    stats["cover"] += bool(page.get("cover"))
    stats["icon"] += bool(page.get("icon"))
    stats["type"] += bool(page["properties"].get("Type 書籍種類", {}).get("relation"))
    kids = client.blocks.children.list(block_id=page["id"], page_size=100)["results"]
    texts = ["".join(t.get("plain_text", "")
                     for t in (k.get(k["type"]) or {}).get("rich_text", [])) for k in kids]
    if "筆記圖" in texts:
        stats["skeleton"] += 1
        i = texts.index("筆記圖")
        stats["gallery"] += int(i + 1 < len(kids) and not kids[i + 1]["type"].startswith("heading"))
print(stats)
```

Run: `PYTHONIOENCODING=utf-8 python <暫存目錄>/check_reading_list_pages.py`
Expected: `{'pages': 26, 'cover': 26, 'icon': 26, 'type': 26, 'skeleton': 26, 'gallery': 26}`（`type` 若少於 26，逐一確認缺的那幾本是否真的沒有可對應的 Tags，並記下書名回報）

再請使用者打開 📚 Personal Reading List 的「閱讀完成」gallery view，**目視確認**這批書出現書封（這是本功能對使用者最直接的可見成果）。

- [ ] **Step 6: 更新 CLAUDE.md**

1. 在 `## Development Commands` → `### Primary entry (clean architecture)` 的 **Rebuild existing pages** 項目之後加入：

```markdown
- **Complete Reading List pages**: `READING_LIST_PAGES=書名子字串 python main.py`（或 `all`）—
  只處理同步自動建立的 📚 Personal Reading List 頁：空白頁寫入「心得摘錄」六段版面、書封、
  本書卡片 gallery、書籍種類；只補空白的段落與屬性，重跑冪等。可先搭 `DRY_RUN=true` 預覽。
```

2. 把 `### Layered structure (src/)` 底下整個 code block（從 `src/` 到 `└── container.py ...`）換成：

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

3. 在 `### 卡片標題與章節參照（2026-08-30）` 整節之後、`### Entry point flow` 之前加入：

```markdown
### Reading List 書頁補完（2026-09-29，M1）

設計：`docs/superpowers/specs/2026-09-28-reading-list-book-pages-design.md`。

- **只補同步建的頁**：`page.created_by.id == users.me().id` 才處理（查不到自己的身分時一律不處理）；
  使用者手動建的頁完全不碰。版面只寫在空白頁，每一段、每個屬性都只在空白時寫——重跑是 no-op，
  所以**不需要回填工具**，開啟後跑一次同步就會補完既有頁。
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
- **永不寫入**：`推薦分數/5`、`Status`、`Done Date`、`Blog Link`、`slug`。
- **M2（未做）**：讀完才寫的 🤖 AI 剖析。心得段原定放 Kobo 打字註記，但使用者的打字註記是 0 筆、
  手寫 markup 有 121 筆——M2 計畫前需重議。
```

4. 在 `### Configuration Requirements` 的 `RESYNC_HIGHLIGHTS` 項目之後加入：

```markdown
  - `READING_LIST_PAGES`: empty = off; `all` or comma-separated title substrings — complete
    sync-created 📚 Personal Reading List pages (layout, cover, card gallery, 書籍種類; only
    empty parts are written). Needs `NOTION_BOOKS_DATABASE_ID`; gallery + 書籍種類 also need
    `NOTION_ZETTELKASTEN_DATABASE_ID`.
  - `GOOGLE_BOOKS_API_KEY`: optional; only for books without a Kobo `ImageId`.
```

5. `### Known Cleanup Debt` 中以 `**Kobo 未匯出資訊**` 開頭的那一項整段換成：

```markdown
- **Kobo 未匯出資訊**：完整盤點見 spec `2026-09-28-reading-list-book-pages-design.md` 的附錄
  （原文書名 `Subtitle`、書系 `Series`、Kobo 讀完時間、劃線 `DateCreated` 時間戳、Wishlist…）。
  更正：`Reviews` 表是**其他讀者**的商店書評，不是使用者自己的書評。使用者的 121 筆手寫
  `markup` 目前被 `_BOOKMARK_FILTER` 當空白排除，圖檔在裝置 `.kobo/markups/`（未驗證）。
```

- [ ] **Step 7: 更新 docs/DECISIONS.md**

在第一個 `## ` 標題（目前是 `## 2026-08-05 — 卡片視覺用…`）之前插入：

```markdown
## 2026-09-29 — Reading List 書頁版面由程式自建＋Views API，不套 Notion 模板

使用者的「心得摘錄」模板裡，卡片盒 view 是**沒有篩選**的 table（手動頁的「來源＝本頁」篩選是
事後手加的），直接套模板每頁都會看到整個卡片盒；以 API 套模板又是非同步、需要兩個新 API。
改由程式一次寫六段版面，再用 Views API（`create_database` + `after_block`）在「筆記圖」後建本書
卡片 gallery。代價：沒有模板裡的按鈕，改模板不會連動到自動頁。新版 API（`2026-03-11`）只用在
`notion_views_client.py`，因為 notion-client 2.2.1 會靜默丟掉不認得的參數。

## 2026-09-29 — 書封改 Kobo 圖床優先，每張圖先下載驗證

劃線頁 20/26 的封面是 Open Library 回的 1×1 透明圖：不帶 key 的 Google Books 與全球共用每日配額
（實測 429），失敗後退回的 Open Library 網址又沒驗證。`content.ImageId` 組成的 Kobo 圖床網址在
35/35 本書命中且版本正確，改為首選；Google Books 與 Open Library 只給沒有 ImageId 的書。所有候選
都下載驗證；舊 Open Library 封面重驗不過就替換，找不到替代就清除。

## 2026-09-28 — Reading List AI 剖析：讀完才寫、與心得分開、每本最多一次（M2）

AI 剖析寫在「概要」並以 🤖 標註，「心得」只放使用者自己的文字——手動頁的心得是個人經驗，模型寫
不出來。閱讀中不寫：卡片不齊、剖析又不覆蓋，會永遠停在半本的理解。已寫入的剖析不自動重寫。
心得段的來源（打字註記 0 筆、手寫 markup 121 筆）待 M2 計畫前重議。
```

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md docs/DECISIONS.md
git commit -m "📝 docs: Reading List 書頁補完（M1）架構說明與 ADR"
```

- [ ] **Step 9: 回報**

向使用者回報：Step 5 的檢查輸出、兩本書的 Notion 觀察結果、目視確認結果、所有 WARNING（例如找不到的種類名稱）。M1 到此完成；M2 計畫要先與使用者重議心得段的來源。

---

## Self-Review

**1. Spec coverage（M1 範圍）**

| spec 要求 | Task |
|---|---|
| 只處理 integration 建的頁、fail closed | 3、9 |
| 空白頁才寫版面；每段／每屬性只在空白時寫；重跑冪等 | 7、9 |
| 六段 `heading_2` 版面、書籍資料（書封圖、作者／出版社／真 ISBN、出版社簡介）、金句摘錄 mention | 7 |
| 卡片 gallery：`after_block` 放在「筆記圖」後、失敗留白且下次重試 | 1、8、9 |
| cover／icon 各自判斷 | 9 |
| 書籍種類：多數決、同卡同種類一票、同票依對照表、第二名 ≥ 一半、最多 2 個；種類庫動態取得 | 3、6、9 |
| 封面來源串接、驗證、快取；Google 429 本輪停查 | 4 |
| 劃線頁舊 Open Library 封面重驗、替換或清除；不受開關影響 | 5 |
| Books DB 邏輯抽出、卡片 repo 委派、介面不變 | 2 |
| `READING_LIST_PAGES`、`GOOGLE_BOOKS_API_KEY`、依賴檢查、卡片 repo 一律建立供讀取 | 10、11 |
| 執行緒池後依序補頁、單本失敗不影響 exit code | 10 |
| DRY_RUN：讀取照常、寫入只記 log、流程可預覽 | 11、12 |
| 永不寫入的屬性 | 9（只寫 cover／icon／Type），12 Step 3 目視確認 |
| 真跑驗收、冪等檢查、文件與 ADR | 12 |

M2 的項目（`is_finished`、TOC、分析、審核、本地留存、`Summary 一言以蔽之`、心得段）刻意不在本計畫。

**2. Placeholder scan**：無 TBD／TODO；Task 1 Step 4 的「<執行當天日期>」與 Task 12 的 page id 是執行時才知道的觀察值，不是待補的設計。

**3. Type consistency**：`find_page`／`is_created_by_integration`／`list_blocks`／`append_blocks`／`update_page`／`type_page_ids`（Task 3）與 Task 9、11 的 fake 和 decorator 簽名一致；`create_card_gallery(page_id, cards_database_id, book_page_id, after_block_id)`（Task 8）與 Task 9、11 一致；`add_book_cover(page_id, book)`（Task 5）與 Task 10 的整檔取代一致；`CompleteReadingListPageUseCase(reading_list, card_repo, views, cover_finder, cards_database_id, type_mapping)`（Task 9）與 Task 11 的組裝一致。

**4. Review Focus**：五條皆已在所屬 task 加上具名測試（見文件開頭）。
