# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Python Environment (Primary Implementation)
- **Main sync command**: `python3 uploadToNotion.py`
- **Test chapter extraction**: `python3 test_chapter_extraction.py`
- **Demo hierarchical output**: `python3 demo_hierarchical_output.py`
- **Demo simple markdown**: `python3 demo_simple_markdown_output.py`
- **Test different books**: `python3 test_different_book.py`

### Node.js Environment (Legacy)
- **Install dependencies**: `npm install`
- **Run legacy sync**: `npm start` (runs `node index.js`)

### No standard linting/testing tools are configured in this project.

## Project Architecture

This is a dual-language tool for exporting Kobo e-reader highlights to Notion databases. The project has evolved from a Node.js implementation to a more sophisticated Python implementation with intelligent chapter extraction capabilities.

### Core Components

1. **DBReader.py**: SQLite database operations and chapter extraction logic
   - `getBookInfoFromDB()`: Retrieves book metadata from KoboReader.sqlite
   - `getHLWithChapterFromDB()`: Extracts highlights with intelligent chapter mapping
   - `extract_real_chapter_title()`: Extracts actual chapter titles from text content using multiple patterns
   - `extract_chapter_name()`: Fallback chapter name extraction from ContentID paths

2. **uploadToNotion.py**: Notion API integration and sync orchestration
   - `sync_book_highlights_with_chapter()`: Syncs highlights with hierarchical chapter organization
   - `process_single_book()`: Handles individual book processing with error handling
   - `export_highlights()`: Main orchestration with thread pool execution
   - Book cover fetching from Google Books API and Open Library

3. **index.js**: Legacy Node.js implementation (simpler, no chapter extraction)

### Data Flow Architecture

```
KoboReader.sqlite → DBReader.py → Chapter Extraction → uploadToNotion.py → Notion API
```

1. **SQLite Reading**: Extracts from `content` and `Bookmark` tables
2. **Chapter Intelligence**: Multiple extraction strategies prioritized by accuracy
3. **Notion Formatting**: Clean markdown with hierarchical chapter organization
4. **Parallel Processing**: ThreadPoolExecutor for concurrent book processing

### Chapter Extraction Logic (Key Innovation)

The system uses a sophisticated multi-tier approach:

1. **Text Content Analysis**: Extracts real chapter titles from highlight text using regex patterns
2. **ContentID Parsing**: Fallback to file path analysis (`book_id!OEBPS!Text/chapter.xhtml`)
3. **Section Optimization**: Converts `Section0008` → `第8章` for better readability
4. **Hierarchical Sorting**: Orders chapters by reading progress for logical flow

### Configuration Requirements

- **.env file** with:
  - `NOTION_TOKEN`: Notion integration token
  - `NOTION_DATABASE_ID`: Target database identifier
- **KoboReader.sqlite**: Must be copied from Kobo device to project root
- **Notion database** must have: Title (text), Exported (checkbox), plus optional fields for metadata

### Key Database Schema Understanding

- **content table**: Book metadata (Title, Author, ISBN, reading progress)
- **Bookmark table**: Highlights with chapter references
  - `Text`: The actual highlighted content
  - `ContentID`: Chapter file path for extraction
  - `ChapterProgress`: Reading position for sorting

### Error Handling Patterns

The codebase uses comprehensive logging via Python's logging module with file rotation. Thread-safe database connections prevent SQLite locking issues. Notion API failures are logged but don't stop batch processing.

### Deployment Notes

This tool requires direct file system access to the Kobo device's SQLite database and stable internet connectivity for Notion API calls. The Python implementation is recommended over Node.js for its advanced chapter extraction capabilities.