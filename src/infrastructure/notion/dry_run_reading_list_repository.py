"""DRY_RUN decorators for Reading List page completion.

Reads go to the real repository; writes are logged only. Blocks "written" in
this run are remembered per page, so the follow-up step (finding「筆記圖」to
place the gallery) behaves as in a real run and the log shows the full plan.
"""
import logging
import threading
from typing import Dict, List, Optional

from .dry_run_notion_repository import DRY_RUN_PAGE_ID_PREFIX

logger = logging.getLogger(__name__)

_PREFIX = "[DRY RUN]"


class DryRunReadingListRepository:
    def __init__(self, inner):
        self._inner = inner
        self._pending: Dict[str, List[dict]] = {}
        self._lock = threading.Lock()

    def find_page(self, title: str, source_page_id: Optional[str] = None) -> Optional[dict]:
        """本輪 dry-run 配發的假 page id（見 DRY_RUN_PAGE_ID_PREFIX）只在記憶體內
        有意義，絕不是真實的劃線頁 id——流入反查只會查到不相干的結果，所以在這
        裡攔下，退回只用書名比對。"""
        if source_page_id and source_page_id.startswith(DRY_RUN_PAGE_ID_PREFIX):
            source_page_id = None
        return self._inner.find_page(title, source_page_id)

    def is_created_by_integration(self, page: dict) -> bool:
        return self._inner.is_created_by_integration(page)

    def type_page_ids(self, names: List[str]) -> Dict[str, str]:
        return self._inner.type_page_ids(names)

    def book_types_available(self) -> bool:
        return self._inner.book_types_available()

    def list_blocks(self, page_id: str) -> List[dict]:
        with self._lock:
            pending = list(self._pending.get(page_id, []))
        return self._inner.list_blocks(page_id) + pending

    def append_blocks(self, page_id: str, blocks: List[dict],
                      after: Optional[str] = None) -> List[dict]:
        created: List[dict] = []
        with self._lock:
            pending = self._pending.setdefault(page_id, [])
            for block in blocks:
                fake = dict(block)
                fake["id"] = f"dry-run-block-{len(pending)}"
                pending.append(fake)
                created.append(fake)
        where = f"（插在 {after} 之後）" if after else ""
        logger.info(f"{_PREFIX} 將在書頁 {page_id} 寫入 {len(blocks)} 個 block{where}")
        return created

    def update_page(self, page_id: str, properties: Optional[dict] = None,
                    cover_url: Optional[str] = None, icon_url: Optional[str] = None) -> None:
        parts = []
        if properties:
            parts.append(f"屬性 {'、'.join(properties)}")
        if cover_url:
            parts.append("cover")
        if icon_url:
            parts.append("icon")
        if parts:
            logger.info(f"{_PREFIX} 將更新書頁 {page_id}：{'、'.join(parts)}")


class DryRunNotionViewsClient:
    def __init__(self, inner):
        self._inner = inner

    def data_source_id(self, database_id: str) -> Optional[str]:
        return self._inner.data_source_id(database_id)

    def create_card_gallery(self, page_id: str, cards_database_id: str,
                            book_page_id: str, after_block_id: str) -> Optional[str]:
        logger.info(
            f"{_PREFIX} 將在書頁 {page_id} 的「筆記圖」後建立卡片 gallery"
            f"（篩選 來源＝{book_page_id}）")
        return None
