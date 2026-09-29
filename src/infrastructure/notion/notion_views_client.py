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
