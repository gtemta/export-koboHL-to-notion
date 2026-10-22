"""從小模型的回應裡撈出 JSON 物件（含巢狀）。"""
import unittest

from src.infrastructure.infographic.llm_json import parse_json_object


class TestParseJsonObject(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_code_fence_and_prose_around_it(self):
        text = '好的，結果如下：\n```json\n{"a": "甲"}\n```\n以上。'
        self.assertEqual(parse_json_object(text), {"a": "甲"})

    def test_nested_objects_come_back_whole(self):
        text = '{"cards": [{"n": 1, "neighbors": [{"relation": "導向", "n": 2}]}], "theme": "x"}'
        parsed = parse_json_object(text)
        self.assertEqual(parsed["theme"], "x")
        self.assertEqual(parsed["cards"][0]["neighbors"][0]["n"], 2)

    def test_trailing_prose_with_braces_is_ignored(self):
        text = '{"a": 1} 備註：請把 {這個} 當範例'
        self.assertEqual(parse_json_object(text), {"a": 1})

    def test_think_block_is_stripped_even_if_it_contains_braces(self):
        text = '<think>先想一下 {"a": 0}</think>{"a": 2}'
        self.assertEqual(parse_json_object(text), {"a": 2})

    def test_unparseable_text_returns_none(self):
        for text in ("沒有 JSON", "{壞掉的", "", None, "[1, 2, 3]"):
            self.assertIsNone(parse_json_object(text), text)


if __name__ == "__main__":
    unittest.main()
