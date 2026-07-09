"""One-shot backfill for 卡片盒 cards that are missing 來源 / Tags.

Usage:
    DRY_RUN=true python backfill_zettelkasten.py   # read + report only
    python backfill_zettelkasten.py                # apply the writes

Scope: cards whose 來源 relation is empty, plus cards that have a 來源劃線ID
but still no Tags (e.g. a previous pass linked 來源 while classification was
broken). For each card:
  1. resolve the source book — 來源劃線ID is a Kobo BookmarkID (looked up in
     KoboReader.sqlite) or a sha1 fallback id (looked up in cards_output/*.json);
  2. resolve / auto-create the 📚 Personal Reading List page via
     ZettelkastenCardRepository.resolve_book_page (also backfills the page's
     Kobo EReader relation when a Kobo highlights page is found);
  3. classify cards with empty Tags through the fixed Ollama flow (needs a
     running Ollama; skipped card-by-card when no content is available);
  4. patch 來源 + Tags in a single pages.update per card.
"""
import json
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from notion_client import Client

from src.config.settings import Settings
from src.infrastructure.container import setup_file_and_console_logging
from src.infrastructure.notion.rate_limiter import NotionRateLimiter
from src.infrastructure.notion.retry_policy import retry_with_backoff
from src.infrastructure.notion.zettelkasten_card_repository import (
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard, ZettelkastenLLMEnhancer

logger = logging.getLogger("backfill_zettelkasten")

_SOURCE_PROP = "來源"
_SOURCE_ID_PROP = "來源劃線ID"
_TAGS_PROP = "Tags"
_KOBO_TITLE_PROP = "Title"  # Kobo EReader DB title property

_BOOK_BY_BOOKMARK_SQL = (
    "SELECT c.Title, c.___PercentRead FROM Bookmark b "
    "INNER JOIN content c ON b.VolumeID = c.ContentID "
    "WHERE b.BookmarkID = ? LIMIT 1"
)
_PERCENT_BY_TITLE_SQL = (
    "SELECT ___PercentRead FROM content WHERE Title = ? LIMIT 1"
)


def fetch_incomplete_cards(client, db_id: str, limiter) -> List[dict]:
    """卡片盒 pages missing 來源, or missing Tags but carrying a 來源劃線ID."""
    cards: List[dict] = []
    cursor: Optional[str] = None
    while True:
        kwargs = {
            "database_id": db_id,
            "filter": {"or": [
                {"property": _SOURCE_PROP, "relation": {"is_empty": True}},
                {"and": [
                    {"property": _TAGS_PROP, "multi_select": {"is_empty": True}},
                    {"property": _SOURCE_ID_PROP,
                     "rich_text": {"is_not_empty": True}},
                ]},
            ]},
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        result = retry_with_backoff(
            lambda k=kwargs: client.databases.query(**k), limiter
        ) or {}
        for page in result.get("results", []):
            props = page.get("properties") or {}
            sid_rich = (props.get(_SOURCE_ID_PROP) or {}).get("rich_text") or []
            sid = sid_rich[0].get("plain_text", "").strip() if sid_rich else ""
            title_rich = (props.get("標題") or {}).get("title") or []
            title = "".join(t.get("plain_text", "") for t in title_rich).strip()
            tags = (props.get(_TAGS_PROP) or {}).get("multi_select") or []
            relation = (props.get(_SOURCE_PROP) or {}).get("relation") or []
            cards.append({
                "page_id": page["id"],
                "source_id": sid,
                "title": title,
                "has_tags": bool(tags),
                "has_source": bool(relation),
            })
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return cards


def build_json_index(cards_dir: str) -> Dict[str, dict]:
    """source-highlight id → {book_title, card} from local cards_output JSONs."""
    index: Dict[str, dict] = {}
    for path in sorted(Path(cards_dir).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"讀取 {path.name} 失敗: {e}")
            continue
        book_title = payload.get("book_title", "")
        for raw in payload.get("cards", []):
            card = ZettelkastenCard.from_dict(raw)
            sid = ZettelkastenCardRepository._card_source_id(card)
            if sid:
                index[sid] = {"book_title": book_title, "card": card}
    return index


def lookup_book_by_bookmark(
    kobo_db: str, bookmark_id: str
) -> Optional[Tuple[str, Optional[float]]]:
    try:
        with sqlite3.connect(kobo_db) as conn:
            row = conn.execute(_BOOK_BY_BOOKMARK_SQL, (bookmark_id,)).fetchone()
        return (row[0] or "", row[1]) if row else None
    except sqlite3.Error as e:
        logger.warning(f"KoboReader.sqlite 查 BookmarkID 失敗: {e}")
        return None


def lookup_percent_by_title(kobo_db: str, title: str) -> Optional[float]:
    try:
        with sqlite3.connect(kobo_db) as conn:
            row = conn.execute(_PERCENT_BY_TITLE_SQL, (title,)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def find_kobo_page_id(client, kobo_db_id: str, book_title: str, limiter) -> Optional[str]:
    """Kobo highlights page for a book (sync creates pages by clean title)."""
    clean = book_title.split(":")[0].strip()  # mirrors Book.get_clean_title()
    try:
        result = retry_with_backoff(
            lambda: client.databases.query(
                database_id=kobo_db_id,
                filter={"property": _KOBO_TITLE_PROP, "title": {"equals": clean}},
                page_size=1,
            ),
            limiter,
        ) or {}
        results = result.get("results") or []
        return results[0]["id"] if results else None
    except Exception as e:
        logger.warning(f"Kobo DB 查 '{clean}' 失敗: {e}")
        return None


def main() -> None:
    settings = Settings.from_env()
    setup_file_and_console_logging(settings.log_level)
    dry_run = settings.dry_run
    if dry_run:
        logger.warning("=== DRY RUN：只讀取與報告，不會寫入 Notion ===")

    if not settings.notion_zettelkasten_database_id:
        raise SystemExit("NOTION_ZETTELKASTEN_DATABASE_ID 未設定")

    limiter = NotionRateLimiter()
    client = Client(auth=settings.notion_token)
    card_repo = ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
        books_database_id=settings.notion_books_database_id,
        rate_limiter=limiter,
        tag_categories=settings.zettelkasten_tag_categories,
    )
    enhancer = ZettelkastenLLMEnhancer()

    cards = fetch_incomplete_cards(
        client, settings.notion_zettelkasten_database_id, limiter
    )
    logger.info(f"卡片盒中 {len(cards)} 張卡片缺「{_SOURCE_PROP}」或「{_TAGS_PROP}」")
    if not cards:
        return

    json_index = build_json_index(settings.zettelkasten_cards_output_dir)
    logger.info(f"cards_output 索引 {len(json_index)} 個來源劃線ID")

    # ----- resolve each card to a book -----
    by_book: Dict[str, List[dict]] = defaultdict(list)
    unresolved: List[dict] = []
    for card in cards:
        sid = card["source_id"]
        entry = json_index.get(sid)
        if entry:
            card["book_title"] = entry["book_title"]
            card["json_card"] = entry["card"]
            by_book[entry["book_title"]].append(card)
            continue
        found = (
            lookup_book_by_bookmark(settings.kobo_db_path, sid)
            if sid and not sid.startswith("sha1:") else None
        )
        if found and found[0]:
            card["book_title"] = found[0]
            card["json_card"] = None
            by_book[found[0]].append(card)
        else:
            unresolved.append(card)
    if unresolved:
        logger.warning(
            f"{len(unresolved)} 張卡片無法反查書籍（需手動處理）: "
            + "、".join(c["title"][:20] for c in unresolved[:10])
        )

    # ----- per book: resolve Reading List page, classify, patch -----
    linked = tagged = failed = 0
    for book_title, book_cards in by_book.items():
        need_source = [c for c in book_cards if not c["has_source"]]
        need_tags = [
            c for c in book_cards
            if not c["has_tags"] and c.get("json_card") is not None
        ]

        if dry_run:
            logger.info(
                f"[DRY RUN] '{book_title}'：補來源 {len(need_source)} 張、"
                f"補 Tags {len(need_tags)} 張"
            )
            continue

        books_page_id = None
        if need_source:
            percent = lookup_percent_by_title(settings.kobo_db_path, book_title)
            kobo_page_id = find_kobo_page_id(
                client, settings.notion_database_id, book_title, limiter
            )
            books_page_id = card_repo.resolve_book_page(
                book_title, kobo_page_id, percent
            )
            if not books_page_id:
                logger.warning(f"'{book_title}' 無法取得 Reading List 頁面，來源不補")

        # classify the cards that still have no Tags (one Ollama call per book)
        if need_tags:
            enhancer.classify_cards(
                [c["json_card"] for c in need_tags],
                settings.zettelkasten_tag_categories, book_title,
            )

        for c in book_cards:
            props: dict = {}
            if not c["has_source"] and books_page_id:
                props[_SOURCE_PROP] = {"relation": [{"id": books_page_id}]}
            jc = c.get("json_card")
            if not c["has_tags"] and jc is not None and jc.categories:
                props[_TAGS_PROP] = {
                    "multi_select": [{"name": n} for n in jc.categories]
                }
            if not props:
                continue
            try:
                retry_with_backoff(
                    lambda pid=c["page_id"], p=props: client.pages.update(
                        page_id=pid, properties=p
                    ),
                    limiter,
                )
                if _SOURCE_PROP in props:
                    linked += 1
                if _TAGS_PROP in props:
                    tagged += 1
            except Exception as e:
                failed += 1
                logger.error(f"卡片 '{c['title']}' 回填失敗: {e}")
        logger.info(f"'{book_title}'：回填完成 {len(book_cards)} 張")

    if dry_run:
        logger.info(
            f"[DRY RUN] 共 {len(cards)} 張待回填、"
            f"{len(by_book)} 本書、{len(unresolved)} 張無法反查"
        )
    else:
        logger.info(
            f"回填完成：來源 {linked} 張、Tags {tagged} 張、失敗 {failed} 張、"
            f"無法反查 {len(unresolved)} 張"
        )


if __name__ == "__main__":
    main()
