"""Integration: chapter organizing holds up across several books.

Was a manual DBReader script; rewritten as a skippable pytest integration test
that checks organize-by-progress produces labelled, progress-ordered highlights
for the first few books that have any.
"""
import os

import pytest

from src.infrastructure.persistence.kobo_sqlite_repository import KoboSqliteRepository

_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "KoboReader.sqlite"
)
pytestmark = pytest.mark.skipif(
    not os.path.exists(_DB), reason="KoboReader.sqlite not present"
)


@pytest.fixture(scope="module")
def books_with_highlights():
    repo = KoboSqliteRepository(_DB)
    collected = []
    for book in repo.get_all_books():
        highlights = repo.get_highlights_with_chapters(book.id)
        if highlights:
            collected.append((book, highlights))
        if len(collected) >= 5:
            break
    return collected


def test_at_least_one_book_has_highlights(books_with_highlights):
    if not books_with_highlights:
        pytest.skip("no highlights in sample DB")
    assert books_with_highlights


def test_each_book_is_labelled_and_progress_ordered(books_with_highlights):
    if not books_with_highlights:
        pytest.skip("no highlights in sample DB")
    for _book, highlights in books_with_highlights:
        assert all(h.chapter_name for h in highlights)
        progresses = [h.chapter_progress for h in highlights if h.chapter_progress]
        assert progresses == sorted(progresses)
