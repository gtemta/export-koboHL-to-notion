import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv

# 卡片盒 Tags multi_select 的固定分類清單。LLM 只能從此清單挑，不可自由新增；
# 歸不進任何分類時回空，留給使用者手動處理。可用 ZETTELKASTEN_TAG_CATEGORIES 覆寫。
DEFAULT_TAG_CATEGORIES: List[str] = [
    "💞心理學", "🧠學習技巧", "💼商務", "🧘‍♂️人生觀點", "🧩邏輯思考",
    "🔬哲學科學", "💻軟體工程", "📈行銷", "📋專案管理", "💰理財投資",
]


@dataclass
class Settings:
    """應用程式設定"""
    notion_token: str
    notion_database_id: str
    kobo_db_path: str = "KoboReader.sqlite"
    max_workers: int = 5
    batch_size: int = 90
    log_level: str = "INFO"
    dry_run: bool = False
    enable_zettelkasten_cards: bool = False
    notion_zettelkasten_database_id: Optional[str] = None
    notion_books_database_id: Optional[str] = None
    zettelkasten_min_highlights: int = 10
    zettelkasten_max_cards: int = 16
    zettelkasten_cards_output_dir: str = "cards_output"
    zettelkasten_tag_categories: List[str] = field(
        default_factory=lambda: list(DEFAULT_TAG_CATEGORIES)
    )
    # RESYNC_HIGHLIGHTS：空=停用；"all"=全部；否則為書名子字串清單。
    # 符合的已匯出書籍會刪除同步產生的 block 後重建劃線內容。
    resync_highlights: List[str] = field(default_factory=list)

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
            dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
            enable_zettelkasten_cards=os.getenv("ENABLE_ZETTELKASTEN_CARDS", "false").lower() == "true",
            notion_zettelkasten_database_id=os.getenv("NOTION_ZETTELKASTEN_DATABASE_ID"),
            notion_books_database_id=os.getenv("NOTION_BOOKS_DATABASE_ID"),
            zettelkasten_min_highlights=int(os.getenv("ZETTELKASTEN_MIN_HIGHLIGHTS", "10")),
            zettelkasten_max_cards=int(os.getenv("ZETTELKASTEN_MAX_CARDS", "16")),
            zettelkasten_cards_output_dir=os.getenv("ZETTELKASTEN_CARDS_OUTPUT_DIR", "cards_output"),
            zettelkasten_tag_categories=cls._parse_tag_categories(
                os.getenv("ZETTELKASTEN_TAG_CATEGORIES")
            ),
            resync_highlights=cls._parse_resync(os.getenv("RESYNC_HIGHLIGHTS")),
        )

    @staticmethod
    def _parse_resync(raw: Optional[str]) -> List[str]:
        """逗號分隔的書名子字串清單；未設定或全空 → 停用。"""
        if not raw or not raw.strip():
            return []
        return [t.strip() for t in raw.split(",") if t.strip()]

    def resync_matches(self, title: str) -> bool:
        """此書是否需要重建劃線內容（"all" 或書名含任一子字串）。"""
        if not self.resync_highlights:
            return False
        return any(t == "all" or t in title for t in self.resync_highlights)

    @staticmethod
    def _parse_tag_categories(raw: Optional[str]) -> List[str]:
        """逗號分隔的分類清單；未設定或全空則用 DEFAULT_TAG_CATEGORIES。"""
        if not raw or not raw.strip():
            return list(DEFAULT_TAG_CATEGORIES)
        parsed = [c.strip() for c in raw.split(",") if c.strip()]
        return parsed or list(DEFAULT_TAG_CATEGORIES)
    
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