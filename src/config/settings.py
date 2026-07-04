import os
import logging
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv


@dataclass
class Settings:
    """應用程式設定"""
    notion_token: str
    notion_database_id: str
    kobo_db_path: str = "KoboReader.sqlite"
    max_workers: int = 5
    batch_size: int = 90
    log_level: str = "INFO"
    enable_zettelkasten_cards: bool = False
    notion_zettelkasten_database_id: Optional[str] = None
    notion_books_database_id: Optional[str] = None
    zettelkasten_min_highlights: int = 10
    zettelkasten_max_cards: int = 16

    @classmethod
    def from_env(cls) -> 'Settings':
        """從環境變數載入設定"""
        load_dotenv()

        notion_token = os.getenv("NOTION_TOKEN")
        notion_database_id = os.getenv("NOTION_DATABASE_ID")

        if not notion_token:
            raise ValueError("NOTION_TOKEN 環境變數必須設定")
        if not notion_database_id:
            raise ValueError("NOTION_DATABASE_ID 環境變數必須設定")

        return cls(
            notion_token=notion_token,
            notion_database_id=notion_database_id,
            kobo_db_path=os.getenv("KOBO_DB_PATH", "KoboReader.sqlite"),
            max_workers=int(os.getenv("MAX_WORKERS", "5")),
            batch_size=int(os.getenv("BATCH_SIZE", "90")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            enable_zettelkasten_cards=os.getenv("ENABLE_ZETTELKASTEN_CARDS", "false").lower() == "true",
            notion_zettelkasten_database_id=os.getenv("NOTION_ZETTELKASTEN_DATABASE_ID"),
            notion_books_database_id=os.getenv("NOTION_BOOKS_DATABASE_ID"),
            zettelkasten_min_highlights=int(os.getenv("ZETTELKASTEN_MIN_HIGHLIGHTS", "10")),
            zettelkasten_max_cards=int(os.getenv("ZETTELKASTEN_MAX_CARDS", "16")),
        )
    
    def setup_logging(self) -> logging.Logger:
        """設定日誌記錄"""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
            ]
        )
        return logging.getLogger(__name__)