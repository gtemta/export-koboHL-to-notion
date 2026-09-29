"""Reading List 書頁版面純函式：六段骨架、書籍資料、段落定位與空白判斷。"""
import unittest

from src.domain.entities.book import Book
from src.infrastructure.notion.reading_list_page_blocks import (
    DESCRIPTION_TOGGLE,
    SECTION_NOTES,
    SECTION_OVERVIEW,
    SECTIONS,
    block_text,
    find_section,
    is_blank_page,
    section_is_empty,
    skeleton_blocks,
)
from src.infrastructure.notion.text_utils import clean_html


def _heading(text, level=2):
    key = f"heading_{level}"
    return {"type": key, key: {"rich_text": [{"plain_text": text}]}}


def _para(text=""):
    return {"type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": text}] if text else []}}


def _full_book():
    return Book(id="b1", title="多巴胺國度", author="安娜．蘭布克", publisher="方舟文化",
                isbn="9786267195185", description="<p><strong>成癮</strong>&amp;平衡</p>",
                image_id="img-1")


class TestSkeleton(unittest.TestCase):
    def test_sections_in_template_order(self):
        blocks = skeleton_blocks(_full_book(), "https://cdn/x.jpg", "kobo-1")
        headings = [block_text(b) for b in blocks if b["type"] == "heading_2"]
        self.assertEqual(headings, list(SECTIONS))

    def test_book_info_contents(self):
        blocks = skeleton_blocks(_full_book(), "https://cdn/x.jpg", "kobo-1")
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["image"]["external"]["url"], "https://cdn/x.jpg")
        bullets = [block_text(b) for b in blocks if b["type"] == "bulleted_list_item"]
        self.assertEqual(bullets, ["作者：安娜．蘭布克", "出版社：方舟文化", "ISBN：9786267195185"])
        toggle = next(b for b in blocks if b["type"] == "toggle")
        self.assertEqual(block_text(toggle), DESCRIPTION_TOGGLE)
        self.assertEqual(block_text(toggle["toggle"]["children"][0]), "成癮&平衡")

    def test_highlights_link_is_a_page_mention(self):
        last = skeleton_blocks(_full_book(), None, "kobo-1")[-1]
        rich = last["paragraph"]["rich_text"]
        self.assertEqual(rich[1]["mention"], {"type": "page", "page": {"id": "kobo-1"}})

    def test_missing_fields_are_omitted(self):
        blocks = skeleton_blocks(Book(id="b2", title="側載書", isbn="7363579164627"), None, None)
        self.assertEqual([b["type"] for b in blocks], ["heading_2"] * 6)

    def test_long_description_is_split(self):
        book = Book(id="b3", title="書", description="字" * 4500)
        toggle = next(b for b in skeleton_blocks(book, None, None) if b["type"] == "toggle")
        rich = toggle["toggle"]["children"][0]["paragraph"]["rich_text"]
        self.assertEqual([len(r["text"]["content"]) for r in rich], [2000, 2000, 500])


class TestSections(unittest.TestCase):
    def test_blank_page(self):
        self.assertTrue(is_blank_page([]))
        self.assertTrue(is_blank_page([_para(), _para("   ")]))
        self.assertFalse(is_blank_page([_para("我先寫了一行")]))
        self.assertFalse(is_blank_page([_heading("書籍資料")]))

    def test_subheadings_belong_to_the_section(self):
        blocks = [_heading(SECTION_OVERVIEW), _heading("1. 路線圖", level=3),
                  _para("人行道、慢車道、快車道"), _heading("實際執行")]
        heading, body = find_section(blocks, SECTION_OVERVIEW)
        self.assertIs(heading, blocks[0])
        self.assertEqual(len(body), 2)
        self.assertFalse(section_is_empty(body))

    def test_higher_level_section_spans_lower_headings(self):
        blocks = [_heading(SECTION_NOTES, level=1), _heading("小標"), _heading("下一章", level=1)]
        _, body = find_section(blocks, SECTION_NOTES)
        self.assertEqual(len(body), 1)

    def test_empty_section_and_non_text_blocks(self):
        blocks = [_heading(SECTION_NOTES), _para(), _heading(SECTION_OVERVIEW)]
        _, body = find_section(blocks, SECTION_NOTES)
        self.assertTrue(section_is_empty(body))
        self.assertFalse(section_is_empty([{"type": "child_database"}]))
        self.assertFalse(section_is_empty([{"type": "unsupported"}]))

    def test_missing_section(self):
        self.assertIsNone(find_section([_heading("卡片")], SECTION_NOTES))


class TestCleanHtml(unittest.TestCase):
    def test_strips_tags_and_entities(self):
        self.assertEqual(clean_html("<p>A&amp;B</p>\n\n<p>C</p>"), "A&B C")
        self.assertEqual(clean_html(None), "")


if __name__ == "__main__":
    unittest.main()
