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
