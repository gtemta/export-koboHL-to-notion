"""卡片角色看板的 domain 規則：只填空白、連結取交集、位置查不到排最後。"""
import unittest

from src.domain.entities.board_card import BoardCard, MapRun
from src.domain.services.card_board_rules import (
    merge_map_runs,
    needs_map,
    parse_map_run,
    plan_book_updates,
    shuffled_listing,
    sort_by_book_order,
)


def _card(page_id, **kw):
    fields = dict(book_page_id="book", title=page_id, source_id="", created_time="")
    fields.update(kw)
    return BoardCard(page_id=page_id, **fields)


def _run(roles, *pairs):
    return MapRun(roles=dict(roles), links=frozenset(frozenset(p) for p in pairs))


class PlanBookUpdatesTest(unittest.TestCase):
    def test_first_run_numbers_in_book_order_from_ten(self):
        cards = [_card("b", source_id="B"), _card("a", source_id="A")]
        updates = {u.page_id: u for u in plan_book_updates(cards, _run({}), {"A": (1, 0.1), "B": (2, 0.5)})}
        self.assertEqual((updates["a"].reading_order, updates["b"].reading_order), (10, 20))

    def test_new_cards_go_after_the_largest_existing_number(self):
        cards = [_card("old", role="主軸", reading_order=25.5), _card("n1"), _card("n2")]
        orders = {u.page_id: u.reading_order for u in plan_book_updates(cards, _run({}), {})}
        self.assertEqual(sorted(v for v in orders.values() if v), [35, 45])

    def test_existing_values_are_never_overwritten(self):
        cards = [
            _card("old", role="主軸", reading_order=15, related_ids=("x",)),
            _card("x", role="案例", reading_order=20),
            _card("new"),
        ]
        updates = plan_book_updates(cards, _run({"old": "案例", "new": "支柱"}, ("old", "new")), {})
        old = next(u for u in updates if u.page_id == "old")
        self.assertIsNone(old.role)
        self.assertIsNone(old.reading_order)
        self.assertEqual(set(old.related_ids), {"x", "new"})
        self.assertEqual(old.related_ids[0], "x")  # 既有的在前
        new = next(u for u in updates if u.page_id == "new")
        self.assertEqual(new.role, "支柱")

    def test_removed_old_link_is_not_added_back(self):
        cards = [
            _card("a", role="主軸", reading_order=10),
            _card("b", role="案例", reading_order=20),
            _card("n"),
        ]
        updates = plan_book_updates(cards, _run({}, ("a", "b")), {})
        self.assertFalse([u for u in updates if u.page_id in ("a", "b") and u.related_ids])

    def test_links_are_written_on_both_ends(self):
        updates = {u.page_id: u for u in plan_book_updates([_card("a"), _card("b")], _run({}, ("a", "b")), {})}
        self.assertEqual((updates["a"].related_ids, updates["b"].related_ids), (("b",), ("a",)))

    def test_truncated_relation_is_not_rewritten(self):
        cards = [_card("a", role="主軸", reading_order=10, related_complete=False), _card("n")]
        updates = {u.page_id: u for u in plan_book_updates(cards, _run({}, ("a", "n")), {})}
        self.assertNotIn("a", updates)
        self.assertEqual(updates["n"].related_ids, ("a",))

    def test_partially_written_book_only_fills_blanks(self):
        cards = [_card("done", role="支柱", reading_order=10), _card("todo")]
        updates = plan_book_updates(cards, _run({"done": "主軸", "todo": "案例"}), {})
        self.assertEqual([(u.page_id, u.role, u.reading_order) for u in updates], [("todo", "案例", 20)])

    def test_no_map_means_default_role_and_no_links(self):
        updates = plan_book_updates([_card("a")], None, {})
        self.assertEqual((updates[0].role, updates[0].related_ids), ("案例", None))

    def test_nothing_to_fill_produces_no_updates(self):
        cards = [_card("a", role="主軸", reading_order=10)]
        self.assertEqual(plan_book_updates(cards, _run({}), {}), [])

    def test_order_filled_for_card_that_already_has_a_role(self):
        cards = [_card("a", role="主軸", reading_order=10), _card("b", role="案例")]
        updates = plan_book_updates(cards, _run({}), {})
        self.assertEqual([(u.page_id, u.role, u.reading_order) for u in updates], [("b", None, 20)])

    def test_links_to_cards_outside_the_book_are_dropped(self):
        updates = plan_book_updates([_card("a")], _run({}, ("a", "elsewhere")), {})
        self.assertIsNone(updates[0].related_ids)


class MergeAndParseTest(unittest.TestCase):
    def test_links_keep_only_pairs_seen_in_both_runs_regardless_of_direction(self):
        merged = merge_map_runs(_run({}, ("a", "b"), ("b", "c")), _run({}, ("b", "a"), ("c", "d")))
        self.assertEqual(merged.links, {frozenset({"a", "b"})})

    def test_role_disagreement_takes_the_lower_rank(self):
        merged = merge_map_runs(_run({"a": "主軸", "b": "支柱"}), _run({"a": "支柱", "b": "案例"}))
        self.assertEqual(merged.roles, {"a": "支柱", "b": "案例"})

    def test_card_seen_in_one_run_keeps_that_role(self):
        merged = merge_map_runs(_run({"a": "主軸"}), _run({"b": "支柱"}))
        self.assertEqual(merged.roles, {"a": "主軸", "b": "支柱"})

    def test_parse_drops_self_and_out_of_range_links_and_reads_support_alias(self):
        raw = {"cards": [
            {"n": 1, "role": "支撐", "neighbors": [{"n": 1}, {"n": 9}, {"n": 2}]},
            {"n": 2, "role": "主軸"},
        ]}
        run = parse_map_run(raw, ["a", "b"])
        self.assertEqual(run.roles, {"a": "支柱", "b": "主軸"})
        self.assertEqual(run.links, {frozenset({"a", "b"})})

    def test_parse_rejects_low_coverage(self):
        self.assertIsNone(parse_map_run({"cards": [{"n": 1, "role": "主軸"}]}, list("abcdefghij")))

    def test_parse_rejects_garbage_and_empty_ids(self):
        self.assertIsNone(parse_map_run("not json", ["a"]))
        self.assertIsNone(parse_map_run({"cards": []}, ["a"]))
        self.assertIsNone(parse_map_run({"cards": [{"n": 1}]}, []))

    def test_parse_tolerates_malformed_neighbors(self):
        raw = {"cards": [
            {"n": 1, "role": "主軸", "neighbors": "oops"},
            {"n": 2, "role": "案例", "neighbors": ["x", 3, {"n": True}]},
        ]}
        run = parse_map_run(raw, ["a", "b"])
        self.assertEqual(run.links, frozenset())

    def test_same_titled_cards_stay_separate(self):
        raw = {"cards": [
            {"n": 1, "role": "主軸", "neighbors": [{"n": 3}]},
            {"n": 2, "role": "案例"},
            {"n": 3, "role": "支柱"},
        ]}
        run = parse_map_run(raw, ["same-1", "same-2", "other"])
        self.assertEqual(run.links, {frozenset({"same-1", "other"})})
        self.assertEqual(run.roles["same-2"], "案例")


class OrderingTest(unittest.TestCase):
    def test_unknown_positions_sort_last_by_created_time(self):
        cards = [_card("late", created_time="2026-02"), _card("known", source_id="K"), _card("early", created_time="2026-01")]
        self.assertEqual([c.page_id for c in sort_by_book_order(cards, {"K": (1, 0.0)})], ["known", "early", "late"])

    def test_shuffle_is_stable_for_a_title_and_keeps_every_card(self):
        cards = [_card(str(i)) for i in range(8)]
        self.assertEqual(shuffled_listing(cards, "書"), shuffled_listing(cards, "書"))
        self.assertEqual({c.page_id for c in shuffled_listing(cards, "書")}, {c.page_id for c in cards})

    def test_needs_map_when_any_role_blank(self):
        self.assertTrue(needs_map([_card("a", role="主軸"), _card("b")]))
        self.assertFalse(needs_map([_card("a", role="主軸")]))


if __name__ == "__main__":
    unittest.main()
