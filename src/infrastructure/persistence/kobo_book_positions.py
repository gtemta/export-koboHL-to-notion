"""來源劃線ID（Kobo `BookmarkID`）→ 這則劃線在書中的位置。

位置 = (spine 序號, 檔內進度)：spine 序號是檔案的閱讀順序，`ChapterProgress` 只在單一檔案內
單調（不是全書單調），所以兩者要一起比。唯讀開啟、查不到的一律省略，不拋例外——
資料庫不在這台機器上時，呼叫端照樣能降級運作。
"""
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .kobo_sqlite_repository import _SPINE_QUERY
from .toc_chapter_resolver import TocChapterResolver

logger = logging.getLogger(__name__)

# SQLite 預設最多 999 個變數（舊版）；分批查，避免卡片多時超限
_ID_CHUNK = 500


class KoboBookPositions:
    def __init__(self, db_path: str):
        self._db_path = db_path

    def positions_for(self, source_ids: Sequence[str]) -> Dict[str, Tuple[int, float]]:
        """{BookmarkID: (spine 序號, 檔內進度)}；不在資料庫、或檔案不在 spine 的 id 省略。"""
        ids = list(dict.fromkeys(source_ids))
        if not ids:
            return {}
        try:
            conn = sqlite3.connect(Path(self._db_path).resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error as e:
            logger.warning(f"打不開 Kobo 資料庫 {self._db_path}，無法取得書中位置：{e}")
            return {}
        try:
            return self._query(conn, ids)
        except sqlite3.Error as e:
            logger.warning(f"讀取 Kobo 書中位置失敗：{e}")
            return {}
        finally:
            conn.close()

    @staticmethod
    def _query(conn: sqlite3.Connection, ids: List[str]) -> Dict[str, Tuple[int, float]]:
        by_volume: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
        for start in range(0, len(ids), _ID_CHUNK):
            chunk = ids[start:start + _ID_CHUNK]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                "SELECT BookmarkID, VolumeID, ContentID, ChapterProgress "
                f"FROM Bookmark WHERE BookmarkID IN ({marks})",
                chunk,
            ).fetchall()
            for bookmark_id, volume_id, content_id, progress in rows:
                by_volume[volume_id].append((bookmark_id, content_id or "", progress or 0.0))

        positions: Dict[str, Tuple[int, float]] = {}
        for volume_id, marks_in_volume in by_volume.items():
            resolver = TocChapterResolver(conn.execute(_SPINE_QUERY, (volume_id,)).fetchall(), [])
            for bookmark_id, content_id, progress in marks_in_volume:
                spine = resolver.spine_position(content_id)
                if spine is not None:
                    positions[bookmark_id] = (spine, progress)
        return positions
