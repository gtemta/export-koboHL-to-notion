"""Local JSON persistence for generated Zettelkasten cards.

Cards are expensive to generate (a local Ollama run for a dozen-plus cards), and
LLM output is non-deterministic, so we persist each batch to disk *before*
uploading. If an upload fails partway, the next run resumes from the saved JSON
instead of regenerating — the LLM never has to redo work it already did.
"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# zettelkasten_generator lives at project root (not yet ported into src/)
from zettelkasten_generator import ZettelkastenCard

logger = logging.getLogger(__name__)


# Windows 保留的裝置名：連 `CON.txt` 這種帶副檔名的也算，不能當資料夾或檔案的主檔名。
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def book_slug(book_title: str) -> str:
    """Filesystem-safe name for a book (or a card title), shared by every per-book
    file we write. The result is used as a folder / file name, so it must never be
    able to leave its parent folder or be something Windows cannot create:

    - path separators and `:*?"<>|` become `_`;
    - leading/trailing dots and spaces are dropped (`..` would climb out of the
      folder; Windows silently strips trailing ones, so the file written is not the
      one asked for) — re-done after the 80-char cut, which can expose a new space;
    - reserved device names (`NUL`, `CON.txt`, ...) get a `_` suffix.
    """
    slug = re.sub(r'[\\/:*?"<>|]+', "_", (book_title or "untitled")).strip(" .")
    slug = slug[:80].strip(" .") or "untitled"
    if slug.split(".")[0].upper() in _RESERVED_NAMES:
        stem, dot, rest = slug.partition(".")
        slug = f"{stem}_{dot}{rest}"
    return slug


def card_source_id(card: ZettelkastenCard) -> str:
    """Stable id for the source highlight a card came from.

    Prefers the Kobo BookmarkID; falls back to a hash of the highlight text so
    cards still dedup even when no BookmarkID is available. This is exactly the
    value written to the 卡片盒 `來源劃線ID` column.
    """
    bookmark_id = getattr(card, "source_bookmark_id", "") or ""
    if bookmark_id.strip():
        return bookmark_id.strip()
    basis = (card.source_highlight or card.title or "").encode("utf-8")
    return "sha1:" + hashlib.sha1(basis).hexdigest()[:12]


@dataclass(frozen=True)
class SavedCard:
    """A card as persisted in some cards_output batch, with where it came from."""
    book_title: str
    card: ZettelkastenCard
    path: str


class CardStore:
    def __init__(self, output_dir: str = "cards_output"):
        self._dir = output_dir

    def save(
        self,
        book_title: str,
        cards: List[ZettelkastenCard],
        rejected: Optional[List[ZettelkastenCard]] = None,
    ) -> Optional[str]:
        """Write a batch of cards as an un-uploaded JSON; return its path.

        `rejected` holds the cards the review gate threw away. They are recorded
        under a separate key so there is a trace of what was dropped and why —
        `load_pending` only ever reads `cards`, so they can never be uploaded.
        """
        if not cards and not rejected:
            return None
        path = os.path.join(self._dir, self._filename(book_title))
        payload = {
            "book_title": book_title,
            "created_at": datetime.now().isoformat(),
            "uploaded": False,
            "cards": [c.to_dict() for c in cards],
            "rejected": [c.to_dict() for c in (rejected or [])],
        }
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(
                f"卡片已本地留存: {path} (通過 {len(cards)} 張"
                f"／退回 {len(rejected or [])} 張)"
            )
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
        return book_slug(book_title)

    # ----- read-only lookup (every batch, uploaded or not) -----

    def saved_cards(self) -> List[SavedCard]:
        """Every card in every batch file, oldest batch first.

        Unlike `load_pending` this includes already-uploaded batches — callers
        here work on cards that are long since in Notion. `rejected` cards are
        never returned. When a newer batch re-generated the same source highlight
        the newer card replaces the older one in place, so a book's cards keep
        the order of their first appearance (≈ reading order).
        """
        if not os.path.isdir(self._dir):
            return []
        found: Dict[Tuple[str, str], SavedCard] = {}
        for fn in sorted(os.listdir(self._dir)):
            path = os.path.join(self._dir, fn)
            if not (fn.endswith(".json") and os.path.isfile(path)):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError, RecursionError):
                continue
            if not isinstance(data, dict):
                continue
            # 手動改壞的檔案只該害到自己：整檔或單張卡的結構不對就略過，不連累其他卡。
            book_title = data.get("book_title") or ""
            cards = data.get("cards") or []
            if not isinstance(book_title, str) or not isinstance(cards, list):
                logger.warning(f"略過結構不符的卡片批次: {path}")
                continue
            for raw in cards:
                try:
                    card = ZettelkastenCard.from_dict(raw)
                    found[(book_title, card_source_id(card))] = SavedCard(book_title, card, path)
                except Exception as e:  # noqa: BLE001 — 壞掉的單張卡不該使整批查找失敗
                    logger.warning(f"略過格式錯誤的卡片 ({path}): {e}")
        return list(found.values())

    def book_cards(self, book_title: str) -> List[ZettelkastenCard]:
        return [s.card for s in self.saved_cards() if s.book_title == book_title]

    def find_by_source_id(self, source_id: str) -> Optional[SavedCard]:
        for saved in self.saved_cards():
            if card_source_id(saved.card) == source_id:
                return saved
        return None
