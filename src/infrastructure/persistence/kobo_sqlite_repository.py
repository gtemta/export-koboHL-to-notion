"""SQLite-backed implementation of BookRepository for Kobo's KoboReader.sqlite."""
import logging
import sqlite3
from contextlib import contextmanager
from typing import List

from ...domain.entities.book import Book
from ...domain.entities.highlight import Highlight
from ...domain.repositories.book_repository import BookRepository
from .chapter_title_heuristics import (
    chapter_name_from_container_path,
    chapter_name_from_content_id,
    extract_real_chapter_title,
)
from .highlight_organizer import organize_by_progress
from .toc_chapter_resolver import TocChapterResolver

logger = logging.getLogger(__name__)

# 只取真實劃線：dogear/markup 的 Text 皆空（實測 23+107 筆）、Hidden 防禦性排除
_BOOKMARK_FILTER = (
    "Bookmark.Type = 'highlight' "
    "AND IFNULL(Bookmark.Hidden, 'false') NOT IN ('true', '1')"
)

_BOOK_QUERY = (
    "SELECT DISTINCT content.ContentId, content.Title, content.Subtitle, "
    "content.Attribution, content.DateLastRead, content.TimeSpentReading, "
    "content.Description, content.Publisher, content.___PercentRead, "
    "content.LastTimeFinishedReading, content.ISBN "
    "FROM Bookmark "
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID "
    f"WHERE {_BOOKMARK_FILTER} "
    "ORDER BY content.Title"
)

# Kobo 內建目錄：ContentType=9 是 spine（檔案閱讀順序）、899 是 TOC 條目（真實章節標題）
_SPINE_QUERY = (
    "SELECT ContentID, VolumeIndex FROM content "
    "WHERE ContentType = 9 AND BookID = ?"
)

_TOC_QUERY = (
    "SELECT ContentID, Title, VolumeIndex, Depth FROM content "
    "WHERE ContentType = 899 AND BookID = ?"
)

_HIGHLIGHT_QUERY = (
    "SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress, "
    "Bookmark.StartContainerPath, Bookmark.EndContainerPath, "
    "content.ChapterIDBookmarked, content.CurrentChapterEstimate, "
    "content.CurrentChapterProgress, Bookmark.Annotation, Bookmark.BookmarkID "
    "FROM Bookmark "
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID "
    f"WHERE Bookmark.VolumeID = ? AND {_BOOKMARK_FILTER} "
    "ORDER BY Bookmark.ChapterProgress"
)


class KoboSqliteRepository(BookRepository):
    """Reads books and highlights from the Kobo e-reader SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
        finally:
            conn.close()

    def get_all_books(self) -> List[Book]:
        books: List[Book] = []
        try:
            with self._connect() as conn:
                for row in conn.execute(_BOOK_QUERY).fetchall():
                    (cid, title, subtitle, author, date_last_read,
                     time_spent, description, publisher, percent_read,
                     last_finished, isbn) = row
                    books.append(Book(
                        id=cid,
                        title=title or '',
                        subtitle=subtitle,
                        author=author,
                        publisher=publisher,
                        isbn=isbn,
                        description=description,
                        percent_read=percent_read,
                        date_last_read=date_last_read,
                        time_spent_reading=time_spent,
                        last_time_finished_reading=last_finished,
                    ))
        except sqlite3.Error as e:
            logger.error(f"讀取書籍列表失敗: {e}", exc_info=True)
            raise
        logger.info(f"從 Kobo 資料庫讀出 {len(books)} 本書")
        return books

    def get_highlights_with_chapters(self, book_id: str) -> List[Highlight]:
        raw: List[Highlight] = []
        resolved_count = 0
        sort_keys = {}
        try:
            with self._connect() as conn:
                resolver = TocChapterResolver(
                    conn.execute(_SPINE_QUERY, (book_id,)).fetchall(),
                    conn.execute(_TOC_QUERY, (book_id,)).fetchall(),
                )
                for row in conn.execute(_HIGHLIGHT_QUERY, (book_id,)).fetchall():
                    (text, content_id, chapter_progress, start_path, end_path,
                     chapter_id_bookmarked, cur_chapter_est, cur_chapter_prog,
                     annotation, bookmark_id) = row
                    toc_chapter = resolver.resolve(content_id or '')
                    if toc_chapter:
                        resolved_count += 1
                    highlight = Highlight(
                        text=text or '',
                        chapter_name=toc_chapter or self._initial_chapter_name(
                            text or '', content_id or '', start_path, chapter_id_bookmarked),
                        chapter_progress=chapter_progress or 0.0,
                        content_id=content_id or '',
                        start_container_path=start_path,
                        end_container_path=end_path,
                        chapter_id_bookmarked=chapter_id_bookmarked,
                        current_chapter_estimate=cur_chapter_est,
                        current_chapter_progress=cur_chapter_prog,
                        annotation=annotation,
                        bookmark_id=bookmark_id,
                    )
                    spine_pos = resolver.spine_position(content_id or '')
                    sort_keys[id(highlight)] = (
                        spine_pos if spine_pos is not None else float('inf'),
                        chapter_progress or 0.0,
                    )
                    raw.append(highlight)
        except sqlite3.Error as e:
            logger.error(f"讀取書籍 {book_id} 的高亮失敗: {e}", exc_info=True)
            raise

        if resolved_count:
            # TOC 命中：確定性章節 + spine 順序排序，不再用進度分群發明章節
            logger.info(
                f"TOC 精確章節解析: {resolved_count}/{len(raw)} 筆劃線命中")
            return sorted(raw, key=lambda h: sort_keys[id(h)])
        # 整本書無 TOC 資料（sideload 等）→ 維持原進度分群 pipeline
        return organize_by_progress(raw)

    @staticmethod
    def _initial_chapter_name(text: str, content_id: str,
                              container_path, chapter_id_bookmarked) -> str:
        """Best-effort chapter name from available signals.

        organize_by_progress may overwrite this during progress-based grouping,
        but we set a reasonable default so highlights without progress data
        still have a meaningful chapter label.
        """
        real = extract_real_chapter_title(text)
        if real:
            return real
        from_id = chapter_name_from_content_id(content_id)
        if from_id:
            return from_id
        if container_path:
            from_container = chapter_name_from_container_path(container_path)
            if from_container:
                return from_container
        if chapter_id_bookmarked:
            from_bookmark = chapter_name_from_content_id(chapter_id_bookmarked)
            if from_bookmark and not from_bookmark.startswith('OEBPS/Text/'):
                return from_bookmark
        return "未知章節"
