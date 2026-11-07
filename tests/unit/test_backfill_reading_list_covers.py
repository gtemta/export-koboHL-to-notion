"""tools/backfill_reading_list_covers.py — 只補「沒有封面」的 Reading List 頁，只寫 cover。"""
import unittest

from src.domain.entities.book import Book
from src.infrastructure.external.cover_fetcher import CoverImage
from tools.backfill_reading_list_covers import (
    backfill_covers,
    filter_pages,
    summarize,
)

FILE_ID = "file-1"


def _page(page_id, title, cover=None, icon=None):
    return {"id": page_id, "cover": cover, "icon": icon,
            "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}}}


def _image(source="kobo"):
    return CoverImage(url="https://x/c.jpg", content_type="image/jpeg",
                      data=b"x" * 5000, source=source)


class _Finder:
    """book.title → CoverImage；沒登記的書找不到。"""

    def __init__(self, images):
        self.images = images
        self.books = []

    def find_image(self, book):
        self.books.append(book)
        return self.images.get(book.title)


class _Uploader:
    def __init__(self, finder, fail_for=()):
        self.finder = finder
        self.fail_for = set(fail_for)
        self.uploaded = []

    def upload(self, book):
        if book.title in self.fail_for:
            raise RuntimeError("upload down")
        self.uploaded.append(book.title)
        return FILE_ID


class _ReadingList:
    def __init__(self, fail_for=()):
        self.updates = []
        self.fail_for = set(fail_for)

    @staticmethod
    def page_title(page):
        return page["properties"]["Name"]["title"][0]["plain_text"]

    def update_page(self, page_id, properties=None, cover_file_id=None, icon_file_id=None):
        if page_id in self.fail_for:
            raise RuntimeError("notion down")
        self.updates.append((page_id, properties, cover_file_id, icon_file_id))


LIBRARY = [Book(id="k1", title="過度努力：為什麼越拼命越焦慮", image_id="img-1")]


def _run(pages, images, dry_run=False, **kw):
    finder = _Finder(images)
    uploader = _Uploader(finder, fail_for=kw.get("upload_fail", ()))
    rl = _ReadingList(fail_for=kw.get("update_fail", ()))
    outcomes = backfill_covers(pages, LIBRARY, rl, uploader, dry_run=dry_run)
    return outcomes, rl, uploader, finder


class TestBackfillCovers(unittest.TestCase):
    def test_page_without_cover_gets_only_the_cover(self):
        outcomes, rl, uploader, _ = _run(
            [_page("p1", "過度努力")], {"過度努力：為什麼越拼命越焦慮": _image()})
        self.assertEqual(rl.updates, [("p1", None, FILE_ID, None)])
        self.assertEqual([o.status for o in outcomes], ["set"])
        self.assertEqual(outcomes[0].source, "kobo")
        self.assertEqual(outcomes[0].matched, "過度努力：為什麼越拼命越焦慮")

    def test_page_with_any_cover_is_never_touched(self):
        """使用者設的、或舊版寫的 Kobo 圖床網址都算「已有」——壞掉的那批交給書頁補完。"""
        kobo = {"type": "external", "external": {"url": "https://cdn.kobo.com/book-images/x/353/569/90/False/image.jpg"}}
        mine = {"type": "external", "external": {"url": "https://example.com/mine.jpg"}}
        outcomes, rl, uploader, finder = _run(
            [_page("p1", "過度努力", cover=kobo), _page("p2", "奇才", cover=mine)], {})
        self.assertEqual([o.status for o in outcomes], ["has_cover", "has_cover"])
        self.assertEqual((rl.updates, uploader.uploaded, finder.books), ([], [], []))

    def test_icon_is_never_written(self):
        _, rl, _, _ = _run([_page("p1", "過度努力", icon={"type": "emoji", "emoji": "📚"})],
                           {"過度努力：為什麼越拼命越焦慮": _image()})
        self.assertEqual([u[3] for u in rl.updates], [None])

    def test_book_not_on_kobo_is_looked_up_by_title_alone(self):
        outcomes, rl, _, finder = _run(
            [_page("p1", "Clean Code: A Handbook")],
            {"Clean Code: A Handbook": _image("openlibrary-search")})
        self.assertEqual(outcomes[0].status, "set")
        self.assertEqual(outcomes[0].source, "openlibrary-search")
        self.assertEqual(outcomes[0].matched, "")
        self.assertIsNone(finder.books[0].image_id)

    def test_no_cover_anywhere_is_reported_not_written(self):
        outcomes, rl, _, _ = _run([_page("p1", "大話設計模式")], {})
        self.assertEqual([o.status for o in outcomes], ["not_found"])
        self.assertEqual(rl.updates, [])

    def test_page_without_a_title_is_skipped(self):
        outcomes, rl, _, finder = _run([_page("p1", "")], {})
        self.assertEqual([o.status for o in outcomes], ["no_title"])
        self.assertEqual(finder.books, [])

    def test_dry_run_looks_up_but_never_uploads_or_writes(self):
        outcomes, rl, uploader, _ = _run(
            [_page("p1", "過度努力")], {"過度努力：為什麼越拼命越焦慮": _image()}, dry_run=True)
        self.assertEqual([o.status for o in outcomes], ["would_set"])
        self.assertEqual((rl.updates, uploader.uploaded), ([], []))

    def test_one_failure_does_not_stop_the_rest(self):
        pages = [_page("p1", "過度努力"), _page("p2", "Clean Code")]
        images = {"過度努力：為什麼越拼命越焦慮": _image(), "Clean Code": _image("openlibrary-search")}
        outcomes, rl, _, _ = _run(pages, images, upload_fail={"過度努力：為什麼越拼命越焦慮"})
        self.assertEqual([o.status for o in outcomes], ["failed", "set"])
        self.assertIn("upload down", outcomes[0].detail)
        self.assertEqual([u[0] for u in rl.updates], ["p2"])

    def test_notion_update_failure_is_reported(self):
        outcomes, _, _, _ = _run(
            [_page("p1", "Clean Code")], {"Clean Code": _image("openlibrary-search")},
            update_fail={"p1"})
        self.assertEqual([o.status for o in outcomes], ["failed"])

    def test_two_pages_for_the_same_kobo_book_both_get_the_cover(self):
        pages = [_page("p1", "過度努力"), _page("p2", "過度努力：為什麼越拼命越焦慮")]
        outcomes, rl, _, _ = _run(pages, {"過度努力：為什麼越拼命越焦慮": _image()})
        self.assertEqual([o.status for o in outcomes], ["set", "set"])
        self.assertEqual([u[0] for u in rl.updates], ["p1", "p2"])


class TestFilterPages(unittest.TestCase):
    def test_substrings_are_matched_on_the_title(self):
        rl = _ReadingList()
        pages = [_page("p1", "過度努力"), _page("p2", "Clean Code"), _page("p3", "奇才")]
        self.assertEqual([p["id"] for p in filter_pages(pages, ["clean", "奇"], rl)],
                         ["p2", "p3"])

    def test_empty_filter_keeps_everything(self):
        pages = [_page("p1", "過度努力")]
        self.assertEqual(filter_pages(pages, [], _ReadingList()), pages)


class TestSummarize(unittest.TestCase):
    def test_counts_and_not_found_list(self):
        outcomes, _, _, _ = _run(
            [_page("p1", "過度努力"), _page("p2", "大話設計模式"), _page("p3", "奇才", cover={"type": "file"})],
            {"過度努力：為什麼越拼命越焦慮": _image()})
        text = summarize(outcomes)
        self.assertIn("已補上封面：1", text)
        self.assertIn("找不到封面：1", text)
        self.assertIn("已有封面（略過）：1", text)
        self.assertIn("大話設計模式", text)

    def test_dry_run_wording(self):
        outcomes, _, _, _ = _run(
            [_page("p1", "過度努力")], {"過度努力：為什麼越拼命越焦慮": _image()}, dry_run=True)
        self.assertIn("將補上封面：1", summarize(outcomes))


if __name__ == "__main__":
    unittest.main()
