"""卡片重審的純規則：讀懂卡片頁、判斷審過沒、組出寫回頁尾的結果。"""
import unittest

from src.domain.entities.card_revision import Candidate, CardBlock, CardBody, Verdict
from src.domain.services.card_revision_rules import (
    RESULT_MARKER,
    fingerprint,
    format_result,
    has_result_for,
    is_result_heading,
    parse_card_body,
    revision_hint,
)


def _p(text):
    return CardBlock("paragraph", text)


def _scores(consistency=4, correctness=4, shareability=4, atomicity=4):
    return {
        "consistency": consistency,
        "correctness": correctness,
        "shareability": shareability,
        "atomicity": atomicity,
    }


class TestParseCardBody(unittest.TestCase):
    def test_generated_card_splits_into_content_and_highlight(self):
        body = parse_card_body([_p("內文"), CardBlock("quote", "原文")])
        self.assertEqual(body, CardBody(content="內文", highlight="原文"))

    def test_hand_edited_lists_count_as_content_in_reading_order(self):
        # 〈全面視角〉的真實形狀：段落、編號清單、段落、quote、空段落、待修正的點
        body = parse_card_body([
            _p("開頭"),
            CardBlock("numbered_list_item", "第一點"),
            CardBlock("numbered_list_item", "第二點"),
            _p("結尾"),
            CardBlock("quote", "原文"),
            _p(""),
            _p("待修正的點 : 寫三維卻有四個層面"),
        ])
        self.assertEqual(body.content, "開頭\n第一點\n第二點\n結尾")
        self.assertEqual(body.highlight, "原文")
        self.assertEqual(body.revision_note, "寫三維卻有四個層面")

    def test_note_marker_accepts_fullwidth_colon_and_no_colon(self):
        self.assertEqual(parse_card_body([_p("待修正的點：太長")]).revision_note, "太長")
        self.assertEqual(parse_card_body([_p("待修正的點 太長")]).revision_note, "太長")

    def test_list_items_right_after_the_marker_belong_to_the_note(self):
        body = parse_card_body([
            _p("內文"),
            _p("待修正的點："),
            CardBlock("bulleted_list_item", "標題太長"),
            CardBlock("bulleted_list_item", "少了例子"),
            CardBlock("quote", "原文"),
        ])
        self.assertEqual(body.revision_note, "標題太長\n少了例子")
        self.assertEqual(body.content, "內文")
        self.assertEqual(body.highlight, "原文")

    def test_note_ends_at_the_first_block_that_is_not_a_list_item(self):
        body = parse_card_body([
            _p("待修正的點：太長"),
            _p("這段是內文"),
            CardBlock("bulleted_list_item", "這也是內文"),
        ])
        self.assertEqual(body.revision_note, "太長")
        self.assertEqual(body.content, "這段是內文\n這也是內文")

    def test_two_marked_paragraphs_both_belong_to_the_note(self):
        body = parse_card_body([_p("內文"), _p("待修正的點：太長"), _p("待修正的點：少了例子")])
        self.assertEqual(body.revision_note, "太長\n少了例子")
        self.assertEqual(body.content, "內文")

    def test_the_phrase_inside_a_sentence_is_not_a_note(self):
        body = parse_card_body([_p("這裡提到待修正的點，但只是內文")])
        self.assertEqual(body.revision_note, "")
        self.assertEqual(body.content, "這裡提到待修正的點，但只是內文")

    def test_only_the_first_quote_is_the_highlight(self):
        body = parse_card_body([
            _p("內文"), CardBlock("quote", "原文"), CardBlock("quote", "我另外引用的"),
        ])
        self.assertEqual(body.highlight, "原文")
        self.assertEqual(body.content, "內文\n我另外引用的")

    def test_earlier_results_never_leak_into_the_content(self):
        body = parse_card_body([
            _p("內文"),
            CardBlock("toggle", f"{RESULT_MARKER} 2026-11-06｜通過〔abc〕"),
        ])
        self.assertEqual(body.content, "內文")

    def test_a_card_without_a_quote_has_no_highlight(self):
        self.assertEqual(parse_card_body([_p("內文")]).highlight, "")


class TestFingerprint(unittest.TestCase):
    BODY = CardBody(content="內文", highlight="原文", revision_note="太長")

    def test_stable_across_calls(self):
        self.assertEqual(fingerprint("標題", self.BODY), fingerprint("標題", self.BODY))

    def test_changes_with_every_part_the_user_can_edit(self):
        base = fingerprint("標題", self.BODY)
        for title, body in (
            ("新標題", self.BODY),
            ("標題", CardBody("新內文", "原文", "太長")),
            ("標題", CardBody("內文", "新原文", "太長")),
            ("標題", CardBody("內文", "原文", "新意見")),
        ):
            self.assertNotEqual(fingerprint(title, body), base)

    def test_moving_text_between_fields_changes_it(self):
        self.assertNotEqual(
            fingerprint("t", CardBody("ab", "c")),
            fingerprint("t", CardBody("a", "bc")),
        )


class TestHasResultFor(unittest.TestCase):
    def test_finds_a_result_for_this_version(self):
        blocks = [_p("內文"), CardBlock("toggle", f"{RESULT_MARKER} 2026-11-06｜通過〔abc〕")]
        self.assertTrue(has_result_for(blocks, "abc"))

    def test_result_for_an_older_version_does_not_count(self):
        blocks = [CardBlock("toggle", f"{RESULT_MARKER} 2026-11-06｜通過〔old〕")]
        self.assertFalse(has_result_for(blocks, "abc"))

    def test_user_text_quoting_the_mark_does_not_count(self):
        self.assertFalse(has_result_for([_p(f"{RESULT_MARKER}〔abc〕")], "abc"))
        self.assertFalse(has_result_for([CardBlock("toggle", "我的筆記〔abc〕")], "abc"))


class TestIsResultHeading(unittest.TestCase):
    def test_only_a_toggle_starting_with_the_marker(self):
        self.assertTrue(is_result_heading("toggle", f"{RESULT_MARKER} 2026-11-06"))
        self.assertFalse(is_result_heading("paragraph", f"{RESULT_MARKER} 2026-11-06"))
        self.assertFalse(is_result_heading("toggle", "我的摺疊筆記"))


class TestRevisionHint(unittest.TestCase):
    def test_carries_the_request_and_the_current_version(self):
        hint = revision_hint(CardBody("目前內文", "原文", "寫三維卻有四個層面"))
        self.assertIn("寫三維卻有四個層面", hint)
        self.assertIn("目前內文", hint)


class TestFormatResult(unittest.TestCase):
    def _format(self, verdict, candidate=None, threshold=4):
        return format_result(verdict, threshold=threshold, mark="abc",
                             day="2026-11-06", candidate=candidate)

    def test_heading_has_marker_date_verdict_and_mark(self):
        heading, _ = self._format(Verdict(_scores(), "", True))
        self.assertTrue(heading.startswith(RESULT_MARKER))
        self.assertIn("2026-11-06", heading)
        self.assertIn("通過", heading)
        self.assertTrue(heading.endswith("〔abc〕"))

    def test_heading_of_a_written_result_is_recognised_by_the_rules(self):
        heading, _ = self._format(Verdict(_scores(), "", True))
        self.assertTrue(has_result_for([CardBlock("toggle", heading)], "abc"))

    def test_failed_verdict_is_called_out_in_heading_and_body(self):
        heading, lines = self._format(Verdict(_scores(atomicity=2), "塞了兩個概念", False))
        self.assertIn("未通過", heading)
        text = "\n".join(lines)
        self.assertIn("最小片段性 2", text)
        self.assertIn("塞了兩個概念", text)

    def test_empty_notes_add_no_line(self):
        _, lines = self._format(Verdict(_scores(), "", True))
        self.assertFalse([line for line in lines if line.startswith("意見")])

    def test_low_correctness_warns_that_own_ideas_get_penalised(self):
        _, lines = self._format(Verdict(_scores(correctness=3), "", False))
        self.assertTrue(any("你自己的想法" in line for line in lines))

    def test_no_warning_when_correctness_clears_the_threshold(self):
        _, lines = self._format(Verdict(_scores(shareability=2), "", False))
        self.assertFalse(any("你自己的想法" in line for line in lines))

    def test_review_only_result_mentions_no_candidate(self):
        heading, lines = self._format(Verdict(_scores(), "", True))
        self.assertNotIn("候選", heading + "\n".join(lines))

    def test_candidate_is_shown_whole_with_its_own_verdict(self):
        candidate = Candidate("新標題", "新內容", Verdict(_scores(atomicity=5), "更聚焦", True))
        heading, lines = self._format(Verdict(_scores(), "", True), candidate)
        text = "\n".join(lines)
        self.assertIn("候選", heading)
        for needle in ("新標題", "新內容", "最小片段性 5", "更聚焦"):
            self.assertIn(needle, text)

    def test_says_how_to_trigger_another_review(self):
        _, lines = self._format(Verdict(_scores(), "", True))
        self.assertIn("刪掉", lines[-1])


if __name__ == "__main__":
    unittest.main()
