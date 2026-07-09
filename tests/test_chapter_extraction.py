"""Integration: KoboSqliteRepository reads books + highlights from a real DB.

Was a manual DBReader script printing results; rewritten as a proper pytest
integration test that asserts behaviour and skips when no KoboReader.sqlite is
present, so the suite stays runnable anywhere.
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
def repo():
    return KoboSqliteRepository(_DB)


def test_books_load(repo):
    books = repo.get_all_books()
    assert isinstance(books, list)
    assert books, "expected at least one book in the sample DB"
    for book in books[:5]:
        assert book.id
        assert book.title


def test_highlights_have_text_chapter_and_new_fields(repo):
    for book in repo.get_all_books():
        highlights = repo.get_highlights_with_chapters(book.id)
        if not highlights:
            continue
        for h in highlights[:20]:
            assert h.text.strip()
            assert h.chapter_name  # organizer always assigns a label
            # fields wired in by improvements #1 / #2
            assert hasattr(h, "annotation")
            assert hasattr(h, "bookmark_id")
        # reading order: each chapter's highlights form one contiguous run
        # (ChapterProgress is per-file, so it is NOT globally monotonic)
        seen = set()
        previous = None
        for h in highlights:
            if h.chapter_name != previous:
                assert h.chapter_name not in seen, "chapter split into separate runs"
                seen.add(h.chapter_name)
                previous = h.chapter_name
        return
    pytest.skip("no highlights found in sample DB")
