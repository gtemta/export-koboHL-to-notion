"""Composition root — wires settings and repositories into a SyncBooksUseCase."""
import logging
import os
from logging.handlers import RotatingFileHandler

from ..application.use_cases.generate_book_cards_use_case import GenerateBookCardsUseCase
from ..application.use_cases.sync_books_use_case import SyncBooksUseCase
from ..config.settings import Settings
from ..domain.services.chapter_extractor import ChapterExtractor
from .notion.notion_api_repository import NotionApiRepository
from .notion.zettelkasten_card_repository import ZettelkastenCardRepository
from .persistence.card_store import CardStore
from .persistence.kobo_sqlite_repository import KoboSqliteRepository


def build_use_case(settings: Settings) -> SyncBooksUseCase:
    book_repo = KoboSqliteRepository(db_path=settings.kobo_db_path)
    notion_repo = NotionApiRepository(
        token=settings.notion_token,
        database_id=settings.notion_database_id,
    )
    extractor = ChapterExtractor()
    card_use_case = _build_card_use_case(settings)
    return SyncBooksUseCase(
        book_repo=book_repo,
        notion_repo=notion_repo,
        chapter_extractor=extractor,
        max_workers=settings.max_workers,
        card_use_case=card_use_case,
    )


def _build_card_use_case(settings: Settings):
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
    )
    card_repo = ZettelkastenCardRepository(
        token=settings.notion_token,
        database_id=settings.notion_zettelkasten_database_id,
        books_database_id=settings.notion_books_database_id,
    )
    card_store = CardStore(output_dir=settings.zettelkasten_cards_output_dir)
    return GenerateBookCardsUseCase(
        generator=generator, card_repo=card_repo, card_store=card_store
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
