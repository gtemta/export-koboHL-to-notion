"""概念圖卡 HTML 渲染（純函式，字串進字串出）。"""
import re
import unittest

from src.domain.entities.infographic_spec import InfographicSpec, Neighbor, Node
from src.domain.services.infographic_rules import LAYOUTS
from src.infrastructure.infographic.html_renderer import render_infographic_html
from src.infrastructure.infographic.icon_library import icon_inner_svg

BOOK = "原子習慣"
TITLES = ["習慣是複利", "改變身分", "環境設計", "兩分鐘法則"]


def _spec(**overrides):
    fields = dict(
        card_title="改變身分",
        lines=["目標決定方向。", "身分決定行動。", "先問我是誰。"],
        nodes=[Node("target", "設定目標"), Node("lightbulb", "認定身分"), Node("repeat", "自然重複")],
        layout="flow",
        role="支柱",
        neighbors=[Neighbor("前提", "習慣是複利"), Neighbor("導向", "環境設計")],
    )
    fields.update(overrides)
    return InfographicSpec(**fields)


def _render(spec=None, book=BOOK, titles=TITLES):
    return render_infographic_html(spec or _spec(), book, titles)


class TestContent(unittest.TestCase):
    def test_is_a_complete_document_on_the_social_canvas(self):
        html = _render()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("1080px", html)
        self.assertIn("1350px", html)
        self.assertIn("Noto Sans TC", html)

    def test_shows_title_lines_labels_and_book(self):
        html = _render()
        for text in ("改變身分", "目標決定方向。", "先問我是誰。", "設定目標", "自然重複", "《原子習慣》"):
            self.assertIn(text, html)

    def test_role_tag_wording(self):
        self.assertIn("全書主軸", _render(_spec(role="主軸")))
        self.assertIn("支柱觀念", _render(_spec(role="支柱")))
        self.assertIn("案例", _render(_spec(role="案例")))

    def test_all_user_text_is_html_escaped(self):
        evil = "<script>alert(1)</script>"
        spec = _spec(
            card_title=evil,
            lines=[evil],
            nodes=[Node("target", evil), Node("lightbulb", "b"), Node("repeat", "c")],
            neighbors=[Neighbor("前提", evil)],
        )
        html = render_infographic_html(spec, evil, [evil, "x"])
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_node_without_label_renders_only_the_icon(self):
        spec = _spec(nodes=[Node("target"), Node("lightbulb", "乙"), Node("repeat")])
        html = _render(spec)
        self.assertEqual(html.count('class="node-label"'), 1)
        self.assertEqual(html.count('class="node"'), 3)

    def test_icon_markup_comes_from_the_icon_library(self):
        self.assertIn(icon_inner_svg("lightbulb"), _render())


class TestLayouts(unittest.TestCase):
    def test_every_layout_renders_every_node_once(self):
        for layout in LAYOUTS:
            for count in (3, 4):
                names = ("target", "lightbulb", "repeat", "compass")[:count]
                spec = _spec(layout=layout, nodes=[Node(n, f"標籤{n}") for n in names])
                html = _render(spec)
                self.assertIn(f"layout-{layout}", html)
                self.assertEqual(html.count('class="node"'), count, layout)
                for n in names:
                    self.assertEqual(html.count(f"標籤{n}"), 1, f"{layout}/{n}")

    def test_contrast_has_a_vs_divider_between_two_sides(self):
        html = _render(_spec(layout="contrast"))
        self.assertIn(">VS<", html)
        self.assertEqual(html.count('class="side"'), 2)

    def test_cycle_loops_back_to_the_start(self):
        self.assertIn("回到起點", _render(_spec(layout="cycle")))
        self.assertNotIn("回到起點", _render(_spec(layout="flow")))

    def test_cause_marks_cause_and_result(self):
        html = _render(_spec(layout="cause"))
        self.assertIn("起因", html)
        self.assertIn("結果", html)


class TestBookMap(unittest.TestCase):
    def test_one_dot_per_card_with_exactly_the_current_one_highlighted(self):
        html = _render()
        self.assertEqual(len(re.findall(r'class="dot"', html)) + html.count('class="dot on"'), 4)
        self.assertEqual(html.count('class="dot on"'), 1)
        self.assertIn("第 2 / 4 張", html)
        before = html.split('class="dot on"')[0]
        self.assertEqual(before.count('class="dot"'), 1)

    def test_neighbors_are_listed_with_their_relation(self):
        html = _render()
        self.assertIn("前提", html)
        self.assertIn("習慣是複利", html)
        self.assertIn("導向", html)
        self.assertIn("環境設計", html)

    def test_card_outside_the_book_gets_no_position_map(self):
        html = _render(titles=["別本書的卡"])
        self.assertNotIn("全書位置", html)
        self.assertNotIn('class="dot', html)

    def test_no_neighbors_means_no_neighbor_line(self):
        html = _render(_spec(neighbors=[]))
        self.assertNotIn('class="map-note"', html)

    def test_sixteen_card_book_still_has_one_dot_per_card(self):
        titles = [f"卡{i}" for i in range(16)]
        spec = _spec(card_title="卡7", neighbors=[])
        html = render_infographic_html(spec, BOOK, titles)
        self.assertEqual(html.count('class="dot on"'), 1)
        self.assertEqual(len(re.findall(r'class="dot"', html)), 15)
        self.assertIn("第 8 / 16 張", html)


if __name__ == "__main__":
    unittest.main()
