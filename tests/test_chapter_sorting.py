"""Progress-based chapter grouping (highlight_organizer.organize_by_progress).

Was a manual DBReader script; rewritten as a self-contained pytest test that
exercises the ported organizer with synthetic highlights (no DB required).
"""
from src.domain.entities.highlight import Highlight
from src.infrastructure.persistence.highlight_organizer import organize_by_progress


def _h(progress, text="一段普通的劃線內容", content_id="c"):
    return Highlight(text=text, chapter_name="", chapter_progress=progress,
                     content_id=content_id)


def test_empty_returns_empty():
    assert organize_by_progress([]) == []


def test_progressed_highlights_are_kept_and_ascending():
    hs = [_h(0.9), _h(0.1), _h(0.5), _h(0.3)]
    out = organize_by_progress(hs)
    assert len(out) == len(hs)
    progresses = [h.chapter_progress for h in out]
    assert progresses == sorted(progresses)


def test_every_output_highlight_gets_a_chapter_label():
    hs = [_h(i / 20) for i in range(1, 20)]
    out = organize_by_progress(hs)
    assert out
    assert all(h.chapter_name for h in out)


def test_no_progress_falls_back_to_content_id_order():
    hs = [_h(0, content_id="b"), _h(0, content_id="a")]
    out = organize_by_progress(hs)
    assert [h.content_id for h in out] == ["a", "b"]


def test_real_chapter_title_used_as_label():
    # A highlight whose text is a chapter heading should label its cluster.
    hs = [_h(0.1, text="第一章：開始的地方")] + [_h(0.1 + i / 100) for i in range(1, 6)]
    out = organize_by_progress(hs)
    assert any("第一章" in h.chapter_name for h in out)
