"""概念圖卡規格：把模型吐出的原始 JSON 整理成可信的 InfographicSpec（純函式）。"""
import unittest

from src.domain.services.infographic_rules import (
    DEFAULT_ICONS,
    ICON_NAMES,
    MAX_LABEL_CHARS,
    MAX_LINE_CHARS,
    normalize_book_map,
    normalize_spec,
)

SIBLINGS = ["習慣是複利", "改變身分", "環境設計", "兩分鐘法則"]


def _raw(**overrides):
    raw = {
        "lines": ["目標決定方向。", "身分決定行動。", "先問我是誰。"],
        "nodes": [
            {"icon": "target", "label": "設定目標"},
            {"icon": "lightbulb", "label": "認定身分"},
            {"icon": "repeat", "label": "自然重複"},
        ],
        "layout": "flow",
        "role": "支柱",
        "neighbors": [
            {"relation": "前提", "title": "習慣是複利"},
            {"relation": "導向", "title": "環境設計"},
        ],
    }
    raw.update(overrides)
    return raw


def _spec(raw=None, title="改變身分"):
    return normalize_spec(raw if raw is not None else _raw(), title, SIBLINGS)


def _icons(spec):
    return [n.icon for n in spec.nodes]


class TestNormalizeSpecPassThrough(unittest.TestCase):
    def test_valid_input_is_kept_as_is(self):
        spec = _spec()
        self.assertEqual(spec.card_title, "改變身分")
        self.assertEqual(spec.lines, ["目標決定方向。", "身分決定行動。", "先問我是誰。"])
        self.assertEqual(
            [(n.icon, n.label) for n in spec.nodes],
            [("target", "設定目標"), ("lightbulb", "認定身分"), ("repeat", "自然重複")],
        )
        self.assertEqual(spec.layout, "flow")
        self.assertEqual(spec.role, "支柱")
        self.assertEqual(
            [(n.relation, n.title) for n in spec.neighbors],
            [("前提", "習慣是複利"), ("導向", "環境設計")],
        )


class TestLines(unittest.TestCase):
    def test_keeps_only_first_three_lines(self):
        spec = _spec(_raw(lines=["一", "二", "三", "四"]))
        self.assertEqual(spec.lines, ["一", "二", "三"])

    def test_blank_lines_are_dropped_before_counting(self):
        spec = _spec(_raw(lines=["", "  ", "甲", "乙"]))
        self.assertEqual(spec.lines, ["甲", "乙"])

    def test_no_usable_line_means_no_spec(self):
        self.assertIsNone(_spec(_raw(lines=["", "   "])))
        self.assertIsNone(_spec(_raw(lines=[])))

    def test_lines_given_as_one_string_are_split_on_newlines(self):
        spec = _spec(_raw(lines="甲\n乙\n丙\n丁"))
        self.assertEqual(spec.lines, ["甲", "乙", "丙"])

    def test_overlong_line_is_cut_at_the_last_punctuation_within_the_limit(self):
        head = "甲" * (MAX_LINE_CHARS - 6)
        long_line = head + "，" + "乙" * 20
        spec = _spec(_raw(lines=[long_line]))
        self.assertEqual(spec.lines, [head + "，"])

    def test_overlong_line_without_punctuation_is_hard_cut_with_ellipsis(self):
        spec = _spec(_raw(lines=["甲" * (MAX_LINE_CHARS + 10)]))
        line = spec.lines[0]
        self.assertEqual(len(line), MAX_LINE_CHARS)
        self.assertTrue(line.endswith("…"))


class TestNodes(unittest.TestCase):
    def test_unknown_icon_names_are_dropped_with_their_label(self):
        spec = _spec(_raw(nodes=[
            {"icon": "target", "label": "甲"},
            {"icon": "no-such-icon", "label": "乙"},
            {"icon": "lightbulb", "label": "丙"},
            {"icon": "repeat", "label": "丁"},
        ]))
        self.assertEqual(
            [(n.icon, n.label) for n in spec.nodes],
            [("target", "甲"), ("lightbulb", "丙"), ("repeat", "丁")],
        )

    def test_duplicate_icons_are_dropped(self):
        spec = _spec(_raw(nodes=[
            {"icon": "target", "label": "甲"},
            {"icon": "target", "label": "乙"},
            {"icon": "lightbulb", "label": "丙"},
            {"icon": "repeat", "label": "丁"},
        ]))
        self.assertEqual(_icons(spec), ["target", "lightbulb", "repeat"])

    def test_too_few_nodes_are_padded_with_unlabeled_default_icons(self):
        spec = _spec(_raw(nodes=[{"icon": "target", "label": "甲"}]))
        self.assertEqual(len(spec.nodes), 3)
        self.assertEqual((spec.nodes[0].icon, spec.nodes[0].label), ("target", "甲"))
        self.assertEqual(len(set(_icons(spec))), 3)
        self.assertEqual([n.label for n in spec.nodes[1:]], ["", ""])

    def test_missing_nodes_fall_back_to_defaults(self):
        spec = _spec(_raw(nodes=None))
        self.assertEqual(len(spec.nodes), 3)
        self.assertTrue(set(_icons(spec)) <= set(ICON_NAMES))

    def test_at_most_four_nodes(self):
        nodes = [{"icon": name, "label": name} for name in ICON_NAMES[:6]]
        spec = _spec(_raw(nodes=nodes))
        self.assertEqual(_icons(spec), list(ICON_NAMES[:4]))

    def test_a_bare_icon_name_is_accepted_as_an_unlabeled_node(self):
        spec = _spec(_raw(nodes=["target", {"icon": "lightbulb", "label": "乙"}, "repeat"]))
        self.assertEqual(
            [(n.icon, n.label) for n in spec.nodes],
            [("target", ""), ("lightbulb", "乙"), ("repeat", "")],
        )

    def test_label_is_trimmed_and_hard_cut_to_the_limit(self):
        spec = _spec(_raw(nodes=[
            {"icon": "target", "label": "  " + "甲" * (MAX_LABEL_CHARS + 5) + " "},
            {"icon": "lightbulb", "label": "乙"},
            {"icon": "repeat", "label": "丙"},
        ]))
        self.assertEqual(spec.nodes[0].label, "甲" * (MAX_LABEL_CHARS - 1) + "…")

    def test_non_string_label_becomes_empty(self):
        spec = _spec(_raw(nodes=[
            {"icon": "target", "label": 42},
            {"icon": "lightbulb", "label": None},
            {"icon": "repeat"},
        ]))
        self.assertEqual([n.label for n in spec.nodes], ["", "", ""])

    def test_garbage_node_entries_do_not_crash(self):
        spec = _spec(_raw(nodes=[None, 7, ["target"], {"icon": ["target"]}]))
        self.assertEqual(len(spec.nodes), 3)

    def test_default_icons_are_all_in_the_whitelist_and_distinct(self):
        self.assertTrue(set(DEFAULT_ICONS) <= set(ICON_NAMES))
        self.assertEqual(len(set(DEFAULT_ICONS)), len(DEFAULT_ICONS))
        self.assertGreaterEqual(len(DEFAULT_ICONS), 4)

    def test_whitelist_has_no_duplicates(self):
        self.assertEqual(len(set(ICON_NAMES)), len(ICON_NAMES))


class TestLayoutAndRole(unittest.TestCase):
    def test_unknown_layout_falls_back_to_flow(self):
        self.assertEqual(_spec(_raw(layout="spiral")).layout, "flow")

    def test_unknown_role_falls_back_to_case(self):
        self.assertEqual(_spec(_raw(role="配角")).role, "案例")

    def test_every_known_layout_is_accepted(self):
        for layout in ("flow", "contrast", "cause", "hierarchy", "cycle"):
            self.assertEqual(_spec(_raw(layout=layout)).layout, layout)

    def test_non_dict_input_means_no_spec(self):
        self.assertIsNone(normalize_spec("lines", "改變身分", SIBLINGS))
        self.assertIsNone(normalize_spec(None, "改變身分", SIBLINGS))


class TestNeighbors(unittest.TestCase):
    def test_title_not_in_the_book_is_dropped(self):
        spec = _spec(_raw(neighbors=[{"relation": "前提", "title": "全書沒有這張"}]))
        self.assertEqual(spec.neighbors, [])

    def test_the_card_itself_is_not_its_own_neighbor(self):
        spec = _spec(_raw(neighbors=[{"relation": "對照", "title": "改變身分"}]))
        self.assertEqual(spec.neighbors, [])

    def test_unknown_relation_is_dropped(self):
        spec = _spec(_raw(neighbors=[{"relation": "喜歡", "title": "環境設計"}]))
        self.assertEqual(spec.neighbors, [])

    def test_duplicates_are_dropped_and_count_is_capped_at_three(self):
        neighbors = [
            {"relation": "前提", "title": "習慣是複利"},
            {"relation": "前提", "title": "習慣是複利"},
            {"relation": "導向", "title": "環境設計"},
            {"relation": "對照", "title": "兩分鐘法則"},
            {"relation": "導向", "title": "兩分鐘法則"},
        ]
        spec = _spec(_raw(neighbors=neighbors))
        self.assertEqual(len(spec.neighbors), 3)
        self.assertEqual(
            [(n.relation, n.title) for n in spec.neighbors],
            [("前提", "習慣是複利"), ("導向", "環境設計"), ("對照", "兩分鐘法則")],
        )

    def test_garbage_neighbor_entries_do_not_crash(self):
        spec = _spec(_raw(neighbors=["環境設計", None, {"title": "環境設計"}]))
        self.assertEqual(spec.neighbors, [])

    def test_unhashable_title_does_not_crash(self):
        spec = _spec(_raw(neighbors=[{"relation": "前提", "title": ["環境設計"]}]))
        self.assertEqual(spec.neighbors, [])


TITLES = ["習慣是複利", "改變身分", "環境設計", "兩分鐘法則"]


def _map_raw(**overrides):
    raw = {
        "theme": "習慣靠系統與身分而非意志力",
        "cards": [
            {"n": 1, "role": "主軸", "neighbors": [{"relation": "導向", "n": 2}]},
            {"n": 2, "role": "支柱",
             "neighbors": [{"relation": "前提", "n": 1}, {"relation": "導向", "n": 3}]},
            {"n": 3, "role": "支柱", "neighbors": []},
            {"n": 4, "role": "案例", "neighbors": [{"relation": "對照", "n": 3}]},
        ],
    }
    raw.update(overrides)
    return raw


class TestNormalizeBookMap(unittest.TestCase):
    def test_numbers_are_resolved_to_titles(self):
        theme, entries = normalize_book_map(_map_raw(), TITLES)
        self.assertEqual(theme, "習慣靠系統與身分而非意志力")
        self.assertEqual(entries["習慣是複利"].role, "主軸")
        self.assertEqual(
            [(n.relation, n.title) for n in entries["改變身分"].neighbors],
            [("前提", "習慣是複利"), ("導向", "環境設計")],
        )
        self.assertEqual(
            [(n.relation, n.title) for n in entries["兩分鐘法則"].neighbors],
            [("對照", "環境設計")],
        )

    def test_every_title_gets_an_entry_even_if_the_model_skipped_it(self):
        raw = _map_raw(cards=[{"n": 1, "role": "主軸", "neighbors": []}])
        _, entries = normalize_book_map(raw, TITLES)
        self.assertEqual(set(entries), set(TITLES))
        self.assertEqual(entries["環境設計"].role, "案例")
        self.assertEqual(entries["環境設計"].neighbors, [])

    def test_out_of_range_numbers_and_self_links_are_dropped(self):
        raw = _map_raw(cards=[{"n": 2, "role": "支柱", "neighbors": [
            {"relation": "前提", "n": 99},
            {"relation": "前提", "n": 0},
            {"relation": "導向", "n": 2},
            {"relation": "導向", "n": "3"},
            {"relation": "導向", "n": True},
        ]}])
        _, entries = normalize_book_map(raw, TITLES)
        self.assertEqual(entries["改變身分"].neighbors, [])

    def test_unknown_role_falls_back_to_case(self):
        raw = _map_raw(cards=[{"n": 1, "role": "配角", "neighbors": []}])
        _, entries = normalize_book_map(raw, TITLES)
        self.assertEqual(entries["習慣是複利"].role, "案例")

    def test_neighbors_are_capped_and_deduped(self):
        raw = _map_raw(cards=[{"n": 1, "role": "主軸", "neighbors": [
            {"relation": "導向", "n": 2}, {"relation": "導向", "n": 2},
            {"relation": "對照", "n": 3}, {"relation": "前提", "n": 4},
            {"relation": "導向", "n": 4},
        ]}])
        _, entries = normalize_book_map(raw, TITLES)
        self.assertEqual(
            [n.title for n in entries["習慣是複利"].neighbors],
            ["改變身分", "環境設計", "兩分鐘法則"],
        )

    def test_garbage_input_still_yields_default_entries(self):
        for raw in (None, "text", {"cards": "oops"}, {"cards": [None, 3, {"n": "x"}]}):
            theme, entries = normalize_book_map(raw, TITLES)
            self.assertEqual(theme, "")
            self.assertEqual(set(entries), set(TITLES))
            self.assertTrue(all(e.role == "案例" and not e.neighbors for e in entries.values()))

    def test_non_string_theme_becomes_empty(self):
        theme, _ = normalize_book_map(_map_raw(theme=["x"]), TITLES)
        self.assertEqual(theme, "")


if __name__ == "__main__":
    unittest.main()
