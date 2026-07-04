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

logger = logging.getLogger(__name__)


_BOOK_QUERY = (
    "SELECT DISTINCT content.ContentId, content.Title, content.Subtitle, "
    "content.Attribution, content.DateLastRead, content.TimeSpentReading, "
    "content.Description, content.Publisher, content.___PercentRead, "
    "content.LastTimeFinishedReading, content.ISBN "
    "FROM Bookmark "
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID "
    "ORDER BY content.Title"
)

_HIGHLIGHT_QUERY = (
    "SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress, "
    "Bookmark.StartContainerPath, Bookmark.EndContainerPath, "
    "content.ChapterIDBookmarked, content.CurrentChapterEstimate, "
    "content.CurrentChapterProgress, Bookmark.Annotation "
    "FROM Bookmark "
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID "
    "WHERE Bookmark.VolumeID = ? "
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
        try:
            with self._connect() as conn:
                for row in conn.execute(_HIGHLIGHT_QUERY, (book_id,)).fetchall():
                    (text, content_id, chapter_progress, start_path, end_path,
                     chapter_id_bookmarked, cur_chapter_est, cur_chapter_prog,
                     annotation) = row
                    raw.append(Highlight(
                        text=text or '',
                        chapter_name=self._initial_chapter_name(
                            text or '', content_id or '', start_path, chapter_id_bookmarked),
                        chapter_progress=chapter_progress or 0.0,
                        content_id=content_id or '',
                        start_container_path=start_path,
                        end_container_path=end_path,
                        chapter_id_bookmarked=chapter_id_bookmarked,
                        current_chapter_estimate=cur_chapter_est,
                        current_chapter_progress=cur_chapter_prog,
                        annotation=annotation,
                    ))
        except sqlite3.Error as e:
            logger.error(f"讀取書籍 {book_id} 的高亮失敗: {e}", exc_info=True)
            raise

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
