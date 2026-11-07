"""The only place that talks to Notion's newer API version (Views API).

notion-client 2.2.1 defaults to Notion-Version 2022-06-28 and its endpoint
helpers silently drop body fields they don't know, so this client pins a newer
version and sends raw requests through Client.request(). Everything else in the
project stays on the old version.
"""
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from notion_client import Client

from .rate_limiter import NotionRateLimiter
from .retry_policy import retry_with_backoff

logger = logging.getLogger(__name__)

NOTION_VIEWS_API_VERSION = "2026-03-11"
CARD_VIEW_NAME = "本書卡片"
# 卡片盒欄位名（見 zettelkasten_card_repository）
_CARD_SOURCE_PROPERTY = "來源"
_CARD_ROLE_PROPERTY = "角色"
_CARD_ORDER_PROPERTY = "閱讀順序"


def card_board_body(data_source_id: str, book_page_id: str, placement: Dict,
                    role_property_id: str, order_property_id: str) -> Dict:
    """POST /v1/views body: this book's cards as a board grouped by 角色, in
    reading order. `placement` is `{"database_id": …}` (add to an existing linked
    database) or `{"create_database": …}` (new one after the「筆記圖」heading).

    group_by / configuration.properties take the property *id* exactly as the
    API returned it (names → 400); filter and sorts take the property name."""
    return {
        "data_source_id": data_source_id,
        "name": CARD_VIEW_NAME,
        "type": "board",
        **placement,
        "filter": {"property": _CARD_SOURCE_PROPERTY,
                   "relation": {"contains": book_page_id}},
        "sorts": [{"property": _CARD_ORDER_PROPERTY, "direction": "ascending"}],
        "configuration": {
            "type": "board",
            "group_by": {"type": "select", "property_id": role_property_id,
                         "sort": {"type": "manual"}, "hide_empty_groups": False},
            "cover": {"type": "page_cover"},
            "properties": [{"property_id": order_property_id, "visible": True}],
        },
    }


@dataclass(frozen=True)
class ViewSwap:
    add_board: bool
    delete_gallery_id: Optional[str]


def plan_view_swap(views: Sequence[Dict]) -> ViewSwap:
    """What turns a book's old 本書卡片 gallery into the board. Matches on name AND
    type, so a renamed gallery or any of the user's other views is never touched."""
    gallery_id = next(
        (v["id"] for v in views
         if v.get("name") == CARD_VIEW_NAME and v.get("type") == "gallery"), None)
    has_board = any(
        v.get("name") == CARD_VIEW_NAME and v.get("type") == "board" for v in views)
    return ViewSwap(add_board=gallery_id is not None and not has_board,
                    delete_gallery_id=gallery_id)


class NotionViewsClient:
    def __init__(self, token: str, rate_limiter: Optional[NotionRateLimiter] = None,
                 client: Optional[Client] = None):
        self._client = client or Client(auth=token, notion_version=NOTION_VIEWS_API_VERSION)
        self._rate_limiter = rate_limiter or NotionRateLimiter()
        self._data_source_ids: Dict[str, str] = {}
        self._board_property_ids: Dict[str, Tuple[str, str]] = {}

    def _request(self, path: str, method: str, query: Optional[Dict] = None,
                 body: Optional[Dict] = None) -> Dict:
        return retry_with_backoff(
            lambda: self._client.request(path=path, method=method, query=query, body=body),
            self._rate_limiter,
        ) or {}

    def data_source_id(self, database_id: str) -> Optional[str]:
        """First data source of a database (cached per run)."""
        if database_id in self._data_source_ids:
            return self._data_source_ids[database_id]
        db = self._request(f"databases/{database_id}", "GET")
        sources = db.get("data_sources") or []
        if not sources:
            logger.warning(f"資料庫 {database_id} 沒有回傳 data source，無法建 view")
            return None
        self._data_source_ids[database_id] = sources[0]["id"]
        return sources[0]["id"]

    def board_property_ids(self, cards_database_id: str) -> Tuple[str, str]:
        """(角色 id, 閱讀順序 id), URL-encoded exactly as the API returns them
        (cached per database). Raises when a column is missing."""
        if cards_database_id in self._board_property_ids:
            return self._board_property_ids[cards_database_id]
        data_source_id = self.data_source_id(cards_database_id)
        if not data_source_id:
            raise RuntimeError(f"資料庫 {cards_database_id} 沒有 data source，讀不到欄位 id")
        properties = self._request(f"data_sources/{data_source_id}", "GET").get("properties") or {}
        ids = []
        for name in (_CARD_ROLE_PROPERTY, _CARD_ORDER_PROPERTY):
            prop_id = (properties.get(name) or {}).get("id")
            if not prop_id:
                raise RuntimeError(f"卡片盒缺少「{name}」欄，無法建看板")
            ids.append(prop_id)
        result = (ids[0], ids[1])
        self._board_property_ids[cards_database_id] = result
        return result

    def create_card_board(self, page_id: str, cards_database_id: str,
                          book_page_id: str, after_block_id: str) -> Optional[str]:
        data_source_id = self.data_source_id(cards_database_id)
        if not data_source_id:
            return None
        role_id, order_id = self.board_property_ids(cards_database_id)
        placement = {"create_database": {
            "parent": {"type": "page_id", "page_id": page_id},
            "position": {"type": "after_block", "block_id": after_block_id},
        }}
        body = card_board_body(data_source_id, book_page_id, placement, role_id, order_id)
        view = self._request("views", "POST", body=body)
        logger.info(f"已在書頁 {page_id} 建立卡片看板（view {view.get('id')}）")
        return view.get("id")

    def describe_swap(self, linked_database_id: str) -> ViewSwap:
        """Read-only: what swapping this book's gallery for the board would do."""
        refs = self._request("views", "GET", query={"database_id": linked_database_id})
        views = [self._request(f"views/{ref['id']}", "GET")
                 for ref in refs.get("results") or []]
        return plan_view_swap(views)

    def swap_gallery_for_board(self, linked_database_id: str, cards_database_id: str,
                               book_page_id: str) -> bool:
        """Add the board, then delete the old gallery (a database must always keep
        at least one view). True if anything was added or deleted."""
        swap = self.describe_swap(linked_database_id)
        if swap.add_board:
            data_source_id = self.data_source_id(cards_database_id)
            if not data_source_id:
                raise RuntimeError(f"資料庫 {cards_database_id} 沒有 data source，無法建看板")
            role_id, order_id = self.board_property_ids(cards_database_id)
            body = card_board_body(
                data_source_id, book_page_id, {"database_id": linked_database_id},
                role_id, order_id)
            view = self._request("views", "POST", body=body)
            logger.info(f"已在 {linked_database_id} 加入卡片看板（view {view.get('id')}）")
        if swap.delete_gallery_id:
            self._request(f"views/{swap.delete_gallery_id}", "DELETE")
            logger.info(f"已刪除舊的卡片 gallery（view {swap.delete_gallery_id}）")
        return swap.add_board or swap.delete_gallery_id is not None
