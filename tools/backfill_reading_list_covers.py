#!/usr/bin/env python
"""為 📚 Personal Reading List 裡「沒有封面」的書頁補上 cover。

手動建立的書頁多半沒有封面，在 gallery view 裡就是一格空白。本工具掃過整個
Books DB，對每一頁沒有 cover 的書：

  1. 頁名對得上 Kobo 書庫裡的書 → 用 Kobo 圖床的書封；
  2. 對不上（紙本書、英文書…）→ 依書名到 Open Library 搜尋，書名一致才採用
     （若設了 GOOGLE_BOOKS_API_KEY 也會先試 Google Books）；
  3. 找不到就只回報，不亂配。

書封一律「上傳到 Notion」再掛上去（不是寫外部網址）：Kobo 圖床會擋 Notion 的
伺服器，外部網址在 Notion 裡會是「Permission denied」。

只寫 cover：不碰 icon、屬性、內容。**已有 cover 的頁一律不動**（包含你手動換過的圖），
重跑冪等。舊版寫下、現在壞掉的 Kobo 圖床 cover 不算「沒有」，那一批由
`READING_LIST_PAGES=all python main.py` 一併修（它同時處理 icon 與書籍資料的圖片）。

    python tools/backfill_reading_list_covers.py --dry-run
    python tools/backfill_reading_list_covers.py
    python tools/backfill_reading_list_covers.py --only "過度努力,Clean Code"
"""
import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Sequence

# allow `python tools/backfill_reading_list_covers.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import Settings  # noqa: E402
from src.domain.entities.book import Book  # noqa: E402
from src.domain.services.reading_list_rules import match_library_book  # noqa: E402
from src.infrastructure.container import (  # noqa: E402
    setup_file_and_console_logging,
)
from src.infrastructure.external.cover_fetcher import CoverFinder  # noqa: E402
from src.infrastructure.notion.cover_uploader import CoverUploader  # noqa: E402
from src.infrastructure.notion.rate_limiter import NotionRateLimiter  # noqa: E402
from src.infrastructure.notion.reading_list_repository import (  # noqa: E402
    ReadingListRepository,
)
from src.infrastructure.persistence.kobo_sqlite_repository import (  # noqa: E402
    KoboSqliteRepository,
)

logger = logging.getLogger("backfill_reading_list_covers")


@dataclass
class Outcome:
    title: str
    page_id: str
    # set | would_set | not_found | failed | has_cover | no_title
    status: str
    source: str = ""    # 封面來源：kobo / google / openlibrary / openlibrary-search
    matched: str = ""   # 對上的 Kobo 書名（對不上為空）
    detail: str = ""    # 失敗原因


def filter_pages(pages: Sequence[dict], needles: Sequence[str], reading_list) -> List[dict]:
    """只留書名含任一子字串的頁（不分大小寫）；沒給子字串就全留。"""
    wanted = [n.strip().lower() for n in needles if n.strip()]
    if not wanted:
        return list(pages)
    return [p for p in pages
            if any(n in reading_list.page_title(p).lower() for n in wanted)]


def backfill_covers(pages, library, reading_list, uploader, dry_run: bool) -> List[Outcome]:
    """逐頁補封面；單頁失敗只記下來，不中斷。dry-run 照常查封面（讀取），不上傳不寫入。"""
    outcomes: List[Outcome] = []
    for page in pages:
        title = reading_list.page_title(page)
        if page.get("cover"):
            outcomes.append(Outcome(title, page["id"], "has_cover"))
            continue
        if not title:
            outcomes.append(Outcome(title, page["id"], "no_title"))
            continue
        kobo_book = match_library_book(title, library)
        book = kobo_book or Book(id=f"page:{page['id']}", title=title)
        matched = kobo_book.title if kobo_book else ""
        image = uploader.finder.find_image(book)
        if image is None:
            outcomes.append(Outcome(title, page["id"], "not_found"))
            continue
        if dry_run:
            outcomes.append(Outcome(title, page["id"], "would_set", image.source, matched))
            continue
        try:
            file_id = uploader.upload(book)
            reading_list.update_page(page["id"], cover_file_id=file_id)
        except Exception as e:  # noqa: BLE001 — 一頁失敗不中斷，重跑會補上
            logger.error(f"'{title}' 補封面失敗: {e}")
            outcomes.append(Outcome(title, page["id"], "failed", image.source, matched, str(e)))
            continue
        outcomes.append(Outcome(title, page["id"], "set", image.source, matched))
    return outcomes


_MARKS = {"set": "✓", "would_set": "→", "not_found": "✗", "failed": "!",
          "has_cover": "·", "no_title": "?"}


def format_outcome(outcome: Outcome) -> str:
    detail = {
        "set": f"[{outcome.source}]",
        "would_set": f"[{outcome.source}]",
        "not_found": "找不到封面",
        "failed": f"失敗：{outcome.detail}",
        "has_cover": "已有封面，略過",
        "no_title": "沒有書名，略過",
    }[outcome.status]
    kobo = f"  ≈ Kobo《{outcome.matched}》" if outcome.matched else ""
    return f"{_MARKS[outcome.status]} {detail} {outcome.title.strip()}{kobo}"


def summarize(outcomes: Sequence[Outcome]) -> str:
    def count(status):
        return sum(1 for o in outcomes if o.status == status)

    lines = ["=== 總結 ===", f"掃描 {len(outcomes)} 頁"]
    if count("would_set"):
        lines.append(f"將補上封面：{count('would_set')}")
    lines.append(f"已補上封面：{count('set')}")
    lines.append(f"已有封面（略過）：{count('has_cover')}")
    lines.append(f"找不到封面：{count('not_found')}")
    if count("failed"):
        lines.append(f"失敗：{count('failed')}（重跑即可補上）")
    missing = [o.title.strip() for o in outcomes if o.status == "not_found"]
    if missing:
        lines.append("\n找不到封面的書（Open Library 查不到；設定 GOOGLE_BOOKS_API_KEY 後重跑可能補上）：")
        lines += [f"  - {title}" for title in missing]
    return "\n".join(lines)


def run(dry_run: bool, only: Sequence[str]) -> List[Outcome]:
    settings = Settings.from_env()
    if not settings.notion_books_database_id:
        print("未設定 NOTION_BOOKS_DATABASE_ID，無事可做")
        return []
    limiter = NotionRateLimiter()
    reading_list = ReadingListRepository(
        token=settings.notion_token, database_id=settings.notion_books_database_id,
        rate_limiter=limiter)
    finder = CoverFinder(google_api_key=settings.google_books_api_key)
    uploader = CoverUploader(token=settings.notion_token, cover_finder=finder,
                             rate_limiter=limiter)
    library = KoboSqliteRepository(db_path=settings.kobo_db_path).get_library_books()
    pages = filter_pages(reading_list.list_pages(), only, reading_list)
    print(f"Books DB {len(pages)} 頁；Kobo 書庫 {len(library)} 本")

    outcomes = backfill_covers(pages, library, reading_list, uploader, dry_run=dry_run)
    for outcome in outcomes:
        if outcome.status != "has_cover":
            print(format_outcome(outcome))
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description="為沒有封面的 Reading List 書頁補上封面")
    parser.add_argument("--dry-run", action="store_true",
                        help="只印出每一頁會用哪個來源的封面，不上傳、不寫回")
    parser.add_argument("--only", default="",
                        help="只處理書名含這些子字串的頁（逗號分隔，不分大小寫）")
    args = parser.parse_args()

    setup_file_and_console_logging()
    mode = "DRY RUN（不寫入）" if args.dry_run else "正式執行"
    print(f"=== Reading List 補封面 — {mode} ===")
    outcomes = run(args.dry_run, [s for s in args.only.split(",")])
    print("\n" + summarize(outcomes))
    if args.dry_run and any(o.status == "would_set" for o in outcomes):
        print("\n確認無誤後拿掉 --dry-run 正式執行。")
    return 1 if any(o.status == "failed" for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
