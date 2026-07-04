"""Local JSON persistence for generated Zettelkasten cards.

Cards are expensive to generate (a local Ollama run for a dozen-plus cards), and
LLM output is non-deterministic, so we persist each batch to disk *before*
uploading. If an upload fails partway, the next run resumes from the saved JSON
instead of regenerating — the LLM never has to redo work it already did.
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

# zettelkasten_generator lives at project root (not yet ported into src/)
from zettelkasten_generator import ZettelkastenCard

logger = logging.getLogger(__name__)


class CardStore:
    def __init__(self, output_dir: str = "cards_output"):
        self._dir = output_dir

    def save(self, book_title: str, cards: List[ZettelkastenCard]) -> Optional[str]:
        """Write a batch of cards as an un-uploaded JSON; return its path."""
        if not cards:
            return None
        path = os.path.join(self._dir, self._filename(book_title))
        payload = {
            "book_title": book_title,
            "created_at": datetime.now().isoformat(),
            "uploaded": False,
            "cards": [c.to_dict() for c in cards],
        }
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"卡片已本地留存: {path} ({len(cards)} 張)")
            return path
        except OSError as e:
            logger.warning(f"卡片本地留存失敗 ({path}): {e}")
            return None

    def mark_uploaded(self, path: Optional[str]) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["uploaded"] = True
            data["uploaded_at"] = datetime.now().isoformat()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, ValueError) as e:
            logger.warning(f"標記卡片已上傳失敗 ({path}): {e}")

    def load_pending(
        self, book_title: str
    ) -> Optional[Tuple[str, List[ZettelkastenCard]]]:
        """Most recent saved-but-not-uploaded batch for this book, if any."""
        if not os.path.isdir(self._dir):
            return None
        prefix = self._slug(book_title) + "_"
        candidates = sorted(
            (fn for fn in os.listdir(self._dir)
             if fn.startswith(prefix) and fn.endswith(".json")),
            reverse=True,
        )
        for fn in candidates:
            path = os.path.join(self._dir, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            if data.get("uploaded"):
                continue
            cards = [ZettelkastenCard.from_dict(d) for d in data.get("cards", [])]
            if cards:
                logger.info(f"發現未上傳的卡片批次，續傳: {path} ({len(cards)} 張)")
                return path, cards
        return None

    def _filename(self, book_title: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self._slug(book_title)}_{ts}.json"

    @staticmethod
    def _slug(book_title: str) -> str:
        slug = re.sub(r'[\\/:*?"<>|]+', "_", (book_title or "untitled")).strip()
        return slug[:80] or "untitled"
