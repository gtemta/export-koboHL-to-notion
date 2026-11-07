"""Local persistence for a book's concept map (card roles + inter-card relations).

One file per book under `<cards_output>/maps/`, kept apart from the card batch
files: a book can have several batches (incremental card generation), so a
single batch file is the wrong owner for something that spans all of them. The
subfolder also keeps `CardStore.load_pending` and `tools/fix_card_tags.py`
(which only look at `cards_output/*.json`) from ever seeing it.

The map is an LLM product, so it is cached: `load` returns it only while the
book's card set is exactly the one it was built from.
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Sequence, Tuple

from ...domain.entities.infographic_spec import MapEntry, Neighbor
from .card_store import book_slug

logger = logging.getLogger(__name__)


class BookMapStore:
    def __init__(self, output_dir: str = "cards_output"):
        self._dir = os.path.join(output_dir, "maps")

    def _path(self, book_title: str) -> str:
        return os.path.join(self._dir, f"{book_slug(book_title)}.json")

    def save(
        self,
        book_title: str,
        titles: Sequence[str],
        theme: str,
        entries: Dict[str, MapEntry],
    ) -> Optional[str]:
        payload = {
            "book_title": book_title,
            "created_at": datetime.now().isoformat(),
            "titles": list(titles),
            "theme": theme,
            "entries": {
                title: {
                    "role": entry.role,
                    "neighbors": [
                        {"relation": n.relation, "title": n.title} for n in entry.neighbors
                    ],
                }
                for title, entry in entries.items()
            },
        }
        path = self._path(book_title)
        tmp = path + ".tmp"
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return path
        except OSError as e:
            logger.warning(f"全書概念地圖本地留存失敗 ({path}): {e}")
            return None

    def load(
        self, book_title: str, titles: Sequence[str]
    ) -> Optional[Tuple[str, Dict[str, MapEntry]]]:
        """The cached (theme, entries), or None when absent, unreadable, or built
        for a different set of cards (a new batch added or removed cards)."""
        try:
            with open(self._path(book_title), encoding="utf-8") as f:
                data = json.load(f)
            if set(data["titles"]) != set(titles):
                return None
            entries = {
                title: MapEntry(
                    role=raw["role"],
                    neighbors=[Neighbor(n["relation"], n["title"]) for n in raw["neighbors"]],
                )
                for title, raw in data["entries"].items()
            }
            if not set(titles) <= set(entries):
                return None
            return str(data.get("theme") or ""), entries
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            return None
