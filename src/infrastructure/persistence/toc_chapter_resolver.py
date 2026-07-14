"""Deterministic chapter resolution from Kobo's embedded table of contents.

KoboReader.sqlite already stores each epub's real TOC:

- ``content.ContentType=9``   — spine: file reading order (``VolumeIndex``)
- ``content.ContentType=899`` — TOC entries: real ``Title``, ``VolumeIndex``
  (TOC order), ``Depth`` (1–4). ``ContentID`` is ``{file}-{depth}`` or
  ``{file}#{anchor}-{depth}``.

A bookmark's ContentID names the file it lives in. The chapter is the nearest
preceding TOC entry in spine order ("spine interval" method) — no guessing.

Sub-file precision caveat: when several anchored TOC entries share the
bookmark's own file, the DB gives no way to tell which anchor region the
bookmark falls in, so we drop the section and keep the chapter-level label.
"""
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

_MAX_LABEL_LEN = 60
_TRAILING_DEPTH_SUFFIX = re.compile(r"-\d+$")


def _bookmark_file(content_id: str) -> str:
    """File part of a Bookmark.ContentID: after the last '!', before any '#'."""
    tail = (content_id or "").rsplit("!", 1)[-1]
    return tail.split("#", 1)[0]


def _toc_file_and_anchor(content_id: str) -> Tuple[str, bool]:
    """File part of a TOC ContentID and whether it points at an in-file anchor.

    ``Text/Ch1.xhtml-1`` → (``Text/Ch1.xhtml``, False)
    ``Text/Ch1.xhtml#sigil_toc_id_1-2`` → (``Text/Ch1.xhtml``, True)
    """
    tail = (content_id or "").rsplit("!", 1)[-1]
    tail = _TRAILING_DEPTH_SUFFIX.sub("", tail)
    file, sep, _anchor = tail.partition("#")
    return file, bool(sep)


@dataclass(frozen=True)
class _TocEntry:
    title: str
    depth: int
    file: str
    ambiguous: bool  # 同檔有多個 TOC 條目且本條目帶 anchor → 檔內落點不可判定
    spine_pos: int
    toc_index: int


class TocChapterResolver:
    """Per-book resolver mapping a bookmark's ContentID to its real chapter."""

    def __init__(self,
                 spine_rows: Iterable[Tuple[str, int]],
                 toc_rows: Iterable[Tuple[str, str, int, int]]):
        """spine_rows: (ContentID, VolumeIndex) from content WHERE ContentType=9.
        toc_rows: (ContentID, Title, VolumeIndex, Depth) from ContentType=899."""
        self._spine = {}
        for content_id, volume_index in spine_rows:
            self._spine[_bookmark_file(content_id)] = volume_index

        parsed = []
        entries_per_file: dict = {}
        for content_id, title, volume_index, depth in toc_rows:
            file, anchored = _toc_file_and_anchor(content_id)
            spine_pos = self._spine.get(file)
            if spine_pos is None:  # 檔案不在 spine 的幽靈條目，防禦性跳過
                continue
            parsed.append((file, anchored, spine_pos, title, volume_index, depth))
            entries_per_file[file] = entries_per_file.get(file, 0) + 1

        entries: List[_TocEntry] = []
        for file, anchored, spine_pos, title, volume_index, depth in parsed:
            # anchor 只有在同檔還有其他條目時才造成模糊；檔案唯一條目的
            # anchor（出版社把章標題 anchor 放檔首的常見模式）視同檔首
            entries.append(_TocEntry(
                title=(title or "").strip(),
                depth=depth or 1,
                file=file,
                ambiguous=anchored and entries_per_file[file] > 1,
                spine_pos=spine_pos,
                toc_index=volume_index,
            ))
        entries.sort(key=lambda e: (e.spine_pos, e.toc_index))
        self._entries = entries

    def has_toc(self) -> bool:
        return bool(self._entries)

    def spine_position(self, content_id: str) -> Optional[int]:
        return self._spine.get(_bookmark_file(content_id))

    def resolve_parts(self, content_id: str) -> Optional[Tuple[str, Optional[str]]]:
        """Return (chapter, section-or-None) for a bookmark, else None.

        Titles are returned untruncated — display truncation is resolve()'s job.
        """
        pos = self.spine_position(content_id)
        if pos is None or not self._entries:
            return None
        file = _bookmark_file(content_id)

        preceding = [e for e in self._entries if e.spine_pos <= pos]
        if not preceding:
            return None  # 劃線在第一個 TOC 條目之前（封面/前言），交給 fallback

        chapter: Optional[_TocEntry] = None
        for entry in reversed(preceding):
            if entry.depth <= 1:
                chapter = entry
                break

        section: Optional[_TocEntry] = None
        min_skipped_depth = float("inf")
        for entry in reversed(preceding):
            if entry.depth <= 1:
                break  # 回溯到章的起點為止，前一章的小節不算
            # 同檔模糊 anchor 無法判斷劃線在該 anchor 之前或之後 → 跳過，
            # 但記下深度：更早的候選只有在嚴格更淺（被跳過者必為其子層、
            # 不會終結其範圍）時才確定包含劃線
            if entry.ambiguous and entry.file == file:
                min_skipped_depth = min(min_skipped_depth, entry.depth)
                continue
            if entry.depth < min_skipped_depth:
                section = entry
            break

        if chapter and section:
            return chapter.title, section.title
        if chapter or section:
            return (chapter or section).title, None
        return None

    def resolve(self, content_id: str) -> Optional[str]:
        """Return "章 › 小節" (or just the chapter) for a bookmark, else None."""
        parts = self.resolve_parts(content_id)
        if parts is None:
            return None
        chapter, section = parts
        label = f"{chapter} › {section}" if section else chapter
        if len(label) > _MAX_LABEL_LEN:
            label = label[:_MAX_LABEL_LEN - 3] + "..."
        return label
