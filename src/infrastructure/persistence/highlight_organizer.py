"""Reorganize highlights into chapters based on reading-progress clustering.

Ported from DBReader.smart_sort_highlights_by_chapter / create_progress_based_chapters_with_real_titles.
Operates on Highlight entities (mutates chapter_name in-place) rather than dicts.
"""
import logging
from typing import List

from ...domain.entities.highlight import Highlight
from .chapter_title_heuristics import extract_real_chapter_title, title_confidence

logger = logging.getLogger(__name__)


def organize_by_progress(highlights: List[Highlight]) -> List[Highlight]:
    """Group highlights into progress-based chapters, labelling each with the best
    real title found in that chapter's range (or a fallback name)."""
    if not highlights:
        return []

    scored = [(h.chapter_progress, h) for h in highlights if h.chapter_progress and h.chapter_progress > 0]
    if not scored:
        # No progress info — keep existing chapter_name values, return sorted by content_id
        return sorted(highlights, key=lambda h: h.content_id or '')

    scored.sort(key=lambda t: t[0])

    # Discover real titles keyed by their progress position
    real_titles = {}
    for progress, h in scored:
        title = extract_real_chapter_title(h.text)
        if title:
            real_titles[progress] = title

    # Pick number of chapters adaptively
    total = len(scored)
    num_chapters = min(20, max(3, total // 2))
    if real_titles:
        num_chapters = min(num_chapters, min(15, max(len(real_titles), len(real_titles) * 2)))

    per_chapter = total / num_chapters
    chapters: List[List[Highlight]] = []
    current: List[Highlight] = []

    for i, (progress, h) in enumerate(scored):
        current.append(h)
        is_last = i == total - 1
        should_close = False
        if len(chapters) < num_chapters - 1:
            expected_end = (len(chapters) + 1) * per_chapter
            if i + 1 >= expected_end and i + 1 < total:
                next_progress = scored[i + 1][0]
                gap = next_progress - progress
                if (gap > 0.05
                        or len(current) >= per_chapter * 1.5
                        or next_progress in real_titles):
                    should_close = True
        if should_close or is_last:
            if current:
                chapters.append(current)
                current = []

    # Assign best title per chapter
    for idx, group in enumerate(chapters):
        chapter_num = idx + 1
        best_title = None
        best_score = 0
        for h in group:
            p = h.chapter_progress
            if p in real_titles:
                score = title_confidence(real_titles[p])
                if score > best_score:
                    best_score = score
                    best_title = real_titles[p]

        label = best_title if best_title else f"第{chapter_num}章"
        if len(label) > 60:
            label = label[:57] + "..."
        for h in group:
            h.chapter_name = label

    # Flatten, preserving chapter then progress order
    organized: List[Highlight] = []
    for group in chapters:
        organized.extend(sorted(group, key=lambda h: h.chapter_progress or 0))

    logger.info(f"組織 {total} 個高亮成 {len(chapters)} 個章節 (真實標題: {sum(1 for g in chapters if any(real_titles.get(h.chapter_progress) for h in g))})")
    return organized
