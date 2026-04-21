# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Primary entry (clean architecture)
- **Sync to Notion**: `python main.py`

### Legacy / specialized entries
- **Zettelkasten flow**: `python -m legacy.uploadToNotion`
- **USB auto-sync**: `python checkUSBandUpload.py` (delegates to `main.main()`)

### No standard linting/testing tools are configured in this project.
(Tests in `tests/` are in mixed state — see Project Architecture below.)

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
│   └── dtos/sync_result.py
└── infrastructure/                      — Adapters for external systems
    ├── persistence/
    │   ├── kobo_sqlite_repository.py    — implements BookRepository
    │   ├── chapter_title_heuristics.py  — extract_real_chapter_title regex patterns
    │   └── highlight_organizer.py       — progress-based chapter grouping
    ├── notion/
    │   ├── notion_api_repository.py     — implements NotionRepository
    │   ├── rate_limiter.py              — thread-safe ~3 req/s limiter
    │   └── retry_policy.py              — 409/429 exponential backoff
    ├── external/cover_fetcher.py        — Google Books + Open Library fallback
    └── container.py                     — composition root (build_use_case)
```

### Entry point flow

`main.py` → `Settings.from_env()` → `container.build_use_case(settings)` → `SyncBooksUseCase.execute()`.

Inside the use case: for each book, check Notion → create if missing → fetch highlights (with sophisticated chapter extraction already done by the repo) → upload in batched blocks → update metadata → attach cover.

### Legacy code (`legacy/`)

- `legacy/uploadToNotion.py` (1070 lines): original monolithic sync. Integrates with `zettelkasten_generator.py` at root. Preserved because Zettelkasten card generation is not yet ported into `src/`.
- `legacy/DBReader.py` (662 lines): original SQLite reader. Still imported by `summarize_with_gemma.py`, `tests/`, and `analysis/` scripts — those modules haven't been migrated.

Run legacy via `python -m legacy.uploadToNotion` (the module adjusts `sys.path` to locate root-level siblings).

### Chapter Extraction Logic (Key Innovation)

Two-level extraction in the new architecture:

1. **Per-highlight** (`KoboSqliteRepository._initial_chapter_name`): tries text-based real title → ContentID path → StartContainerPath → ChapterIDBookmarked.
2. **Progress-based re-grouping** (`highlight_organizer.organize_by_progress`): clusters highlights into N chapters using reading progress, then picks the highest-confidence real title found in each cluster's range.

The simpler `ChapterExtractor` in `src/domain/services/` is used only as a fallback when the repo returns a highlight without a chapter name.

### Configuration Requirements

- **.env file** with:
  - `NOTION_TOKEN`: Notion integration token (required)
  - `NOTION_DATABASE_ID`: Target database identifier (required)
  - `KOBO_DB_PATH`: default `KoboReader.sqlite`
  - `MAX_WORKERS`: thread pool size, default `5`
  - `LOG_LEVEL`: default `INFO`
  - Zettelkasten vars (legacy path only): see `.env.example`
- **KoboReader.sqlite**: Copy from Kobo device to project root (or set `KOBO_DB_PATH`)
- **Notion database** must have: Title (text), Exported (checkbox). Optional fields: Author, Publisher, Subtitle, Description, ISBN, SpendReadingTime, LastReadDate, LastFinishedReadTime, PercentageRead.

### Key Database Schema

- **content table**: Book metadata (Title, Author, ISBN, reading progress)
- **Bookmark table**: Highlights with chapter references
  - `Text`: the highlighted content
  - `ContentID`: chapter file path for extraction
  - `ChapterProgress`: reading position for sorting

### Error Handling Patterns

- Logging: `src/infrastructure/container.setup_file_and_console_logging()` configures a rotating file handler (`logs/kobo_notion_sync.log`, 2MB × 3) plus console output.
- Thread-safety: SQLite connections opened per call via context manager; Notion rate limiter uses a Lock.
- Retry: 409 conflicts and 429 rate-limits get exponential backoff in `retry_with_backoff`. Other Notion errors bubble up.
- Failure isolation: per-book failures are caught in the use case and recorded in `SyncResult.errors`; sync continues.

### Known Cleanup Debt

- `tests/` has a duplicated `test_chapter_extraction.py` (both root-level and `tests/unit/`). They import `legacy.DBReader` via old paths and are partially broken.
- `analysis/` contains one-shot debug scripts; candidates for deletion.
- `docs/` is full of past refactor plans (REFACTOR_PLAN.md etc.) that could be archived.
- `summarize_with_gemma.py` still depends on legacy.DBReader — port or retire later.
- Zettelkasten path is duplicated work waiting to be ported into `src/` as a post-sync step.
