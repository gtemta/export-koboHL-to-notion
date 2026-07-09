# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Primary entry (clean architecture)
- **Sync to Notion**: `python main.py`
- **Rebuild existing pages**: `RESYNC_HIGHLIGHTS=書名子字串 python main.py`（或 `all`）—
  已匯出書籍刪除同步產生的 block（heading_1/bullet/callout/divider）後以最新章節結構
  重建；使用者手動加的內容（paragraph 等）保留。可先搭 `DRY_RUN=true` 預覽。

### Legacy / specialized entries
- **Zettelkasten flow**: `python -m legacy.uploadToNotion`
- **USB auto-sync**: `python checkUSBandUpload.py` (delegates to `main.main()`)
- **Card backfill**: `python backfill_zettelkasten.py` — one-shot repair for 卡片盒
  cards missing 來源/Tags (resolves books via 來源劃線ID → KoboReader.sqlite /
  cards_output JSON, auto-creates Reading List pages, re-runs Tags classification).
  Supports `DRY_RUN=true`.

### Quality gates
- **Lint**: `python -m ruff check .` (config in `pyproject.toml`; `legacy/` + `analysis/` excluded)
- **Tests**: `python -m pytest` (all green, no external resources needed)
- **Dry-run verify**: `DRY_RUN=true python main.py` — full flow, reads only, writes logged as `[DRY RUN]`
- CI (`.github/workflows/ci.yml`) runs ruff + pytest on every push/PR.

## Engineering Standards（開發基礎規範）

所有開發（人或 AI agent）必須遵守本節。守門靠自動化與文件，不靠模型的聰明程度或當下記憶。

### 1. 硬基礎（一次性建設，已完成 2026-07-07）

- [x] `pyproject.toml` 集中工具設定：`ruff`（lint）＋ `pytest`。（`src/domain/` 型別檢查可日後漸進加上。）
- [x] 依賴鎖定：`requirements.txt`（執行）＋ `requirements-dev.txt`（pytest、ruff）。Ollama/Gemini 皆用 `requests` 直打 REST，無額外 SDK 依賴。
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
│   ├── entities/                        — Book, Chapter, Highlight dataclasses
│   ├── repositories/                    — BookRepository, NotionRepository (ABCs)
│   └── services/chapter_extractor.py    — Strategy-based chapter name fallback
├── application/
│   ├── use_cases/sync_books_use_case.py — SyncBooksUseCase.execute()
│   ├── use_cases/generate_book_cards_use_case.py — Zettelkasten card post-sync step
│   └── dtos/sync_result.py
└── infrastructure/                      — Adapters for external systems
    ├── persistence/
    │   ├── kobo_sqlite_repository.py    — implements BookRepository
    │   ├── toc_chapter_resolver.py      — deterministic chapter mapping from Kobo TOC
    │   ├── chapter_title_heuristics.py  — regex title guessing (fallback only)
    │   ├── highlight_organizer.py       — progress-based grouping (fallback only)
    │   └── card_store.py                — local JSON persistence / resume for cards
    ├── notion/
    │   ├── notion_api_repository.py     — implements NotionRepository
    │   ├── dry_run_notion_repository.py — DRY_RUN decorator: reads delegate, writes log-only
    │   ├── zettelkasten_card_repository.py — uploads cards to 卡片盒 DB (per-highlight dedup)
    │   ├── rate_limiter.py              — thread-safe ~3 req/s limiter
    │   └── retry_policy.py              — 409/429/404 exponential backoff
    ├── external/cover_fetcher.py        — Google Books + Open Library fallback
    └── container.py                     — composition root (build_use_case)
```

Card generation (`zettelkasten_generator.py`, still at project root) is wired in as
an optional post-sync step: `GenerateBookCardsUseCase` bridges `Highlight` entities
to the generator, persists the batch via `CardStore`, then uploads through
`ZettelkastenCardRepository`. Enabled by `ENABLE_ZETTELKASTEN_CARDS=true`.

### Entry point flow

`main.py` → `Settings.from_env()` → `container.build_use_case(settings)` → `SyncBooksUseCase.execute()`.

Inside the use case: for each book, check Notion → create if missing → fetch highlights (with sophisticated chapter extraction already done by the repo) → upload in batched blocks → update metadata → attach cover.

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
   files). Labels are `章 › 小節`. Same-file anchored entries are ambiguous only when
   the file has multiple TOC entries; then the resolver falls back to the nearest
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
  - Zettelkasten card generation (used by both `main.py` and the legacy path):
    - `ENABLE_ZETTELKASTEN_CARDS`: `true`/`false` (default `false`)
    - `NOTION_ZETTELKASTEN_DATABASE_ID`: target 卡片盒 database (required when enabled)
    - `NOTION_BOOKS_DATABASE_ID`: Books DB the card `來源` relation points at (optional)
    - `ZETTELKASTEN_MIN_HIGHLIGHTS` (default `10`), `ZETTELKASTEN_MAX_CARDS` (default `16`)
    - `ZETTELKASTEN_TAG_CATEGORIES`: comma-separated fixed Tags list (default in `settings.DEFAULT_TAG_CATEGORIES`). LLM classifies each card into 1-2 of these; missing options are auto-seeded into the 卡片盒 Tags column on first upload.
    - `ZETTELKASTEN_CARDS_OUTPUT_DIR`: local card JSON dir (default `cards_output`, gitignored)
    - Ollama + Gemini vars (`OLLAMA_*`, `GEMINI_*`): see `.env.example`
- **KoboReader.sqlite**: Copy from Kobo device to project root (or set `KOBO_DB_PATH`)
- **Notion database** must have: Title (text), Exported (checkbox). Optional fields: Author, Publisher, Subtitle, Description, ISBN, SpendReadingTime, LastReadDate, LastFinishedReadTime, PercentageRead.
- **Notion 卡片盒 database** (when cards enabled): 標題 (title) is required. The
  repository reads the DB schema first and **auto-creates** the missing optional
  columns (`來源劃線ID`, `品質分數`, `狀態`) + seeds missing `Tags` options on the
  first upload (`_ensure_schema`). Columns written when present:
  `來源` (relation → Books DB), `Key Word` (rich_text — free concept tags, 、-joined),
  `Tags` (multi_select — fixed-category classification, only values in the allowed
  list), `來源劃線ID` (rich_text, enables per-highlight dedup), `品質分數` (number),
  `狀態` (select: 草稿/已審/永久筆記). The old `主題` column is no longer used.
- **Notion DB 三層關係**: 卡片盒 `來源` relation → 📚 Personal Reading List (Books
  DB, title 欄叫 `Name`)，Reading List 的 `Kobo EReader` relation → Kobo highlights
  DB。書不在 Reading List 時 repository **自動建頁**（Name=完整書名、Kobo EReader
  relation、Status 依 Kobo 進度：≥99% → `🔖閱讀完畢`，否則 `📖 閱讀中`——注意
  option 名稱須與 DB 完全一致，📖 後有空格）；名稱比對命中但 relation 空時會順手
  補上，讓下次反查直接命中。
- **Tags 分類比對是 emoji-insensitive**：分類選項帶 emoji 前綴（`💞心理學`），但
  本地 LLM 幾乎不會照抄 emoji，故 prompt 給純文字名、parser 以 text core
  （只留字母/數字/CJK）比回 canonical 名稱寫入 Notion。改分類清單時維持這個約定。

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
- **資料純度**：`_HIGHLIGHT_QUERY`/`_BOOK_QUERY` 未過濾 `Bookmark.Type`——實際資料有
  23 筆 `dogear` 與 107 筆 `markup`（Text 皆空）混入為空白劃線；`Hidden` 也未過濾。
- **Kobo 未匯出資訊**（2026-07-10 調查，候選功能）：劃線 `DateCreated`/`Color`、
  `content.Series`/`Language`、Shelf 收藏、Reviews 個人書評、Event/Activity 閱讀行為。
