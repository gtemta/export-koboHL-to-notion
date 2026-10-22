"""概念圖卡規格的 LLM 呼叫：提示詞內容與回應處理（Ollama 以假函式取代）。"""
import json
import unittest
from unittest import mock

from src.domain.services.infographic_rules import (
    ICON_NAMES,
    LAYOUTS,
    MAX_LABEL_CHARS,
    MAX_LINE_CHARS,
)
from src.infrastructure.infographic import spec_generator
from src.infrastructure.infographic.spec_generator import (
    InfographicSpecGenerator,
    build_book_map_prompt,
    build_card_prompt,
)
from zettelkasten_generator import ZettelkastenCard


def _card(title, content="內容", highlight="劃線"):
    return ZettelkastenCard(
        id=f"id-{title}", title=title, content=content, source_highlight=highlight,
        chapter_reference="", chapter_progress=0.0,
    )


CARDS = [_card("習慣是複利"), _card("改變身分"), _card("環境設計")]


class TestPrompts(unittest.TestCase):
    def test_card_prompt_carries_the_card_the_theme_and_every_constraint(self):
        card = _card("改變身分", content="身分決定行動。", highlight="每個行動都是投票")
        prompt = build_card_prompt(card, "原子習慣", "習慣靠系統")
        for text in ("改變身分", "身分決定行動。", "每個行動都是投票", "原子習慣", "習慣靠系統"):
            self.assertIn(text, prompt)
        self.assertIn(str(MAX_LINE_CHARS), prompt)
        self.assertIn(str(MAX_LABEL_CHARS), prompt)
        for name in ICON_NAMES:
            self.assertIn(name, prompt)
        for layout in LAYOUTS:
            self.assertIn(layout, prompt)

    def test_card_prompt_without_theme_has_no_empty_theme_line(self):
        prompt = build_card_prompt(_card("改變身分"), "原子習慣", "")
        self.assertNotIn("全書主軸", prompt)

    def test_card_prompt_asks_lines_not_to_repeat_the_title(self):
        # 實測 gemma4:12b 常把第一行寫成標題的複誦；標題在圖上已經是最大的字
        prompt = build_card_prompt(_card("改變身分"), "原子習慣", "")
        self.assertIn("不要重複卡片標題", prompt)

    def test_card_prompt_forbids_adding_conclusions_the_card_does_not_state(self):
        prompt = build_card_prompt(_card("改變身分"), "原子習慣", "")
        self.assertIn("不得加入", prompt)

    def test_book_map_prompt_numbers_every_card_from_one(self):
        prompt = build_book_map_prompt("原子習慣", CARDS)
        self.assertIn("1. 習慣是複利", prompt)
        self.assertIn("2. 改變身分", prompt)
        self.assertIn("3. 環境設計", prompt)
        for word in ("主軸", "支柱", "案例", "前提", "導向", "對照"):
            self.assertIn(word, prompt)


class _FakeOllama:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.reply


def _generator(reply):
    fake = _FakeOllama(reply)
    patcher = mock.patch.object(spec_generator, "_ollama_generate", fake)
    patcher.start()
    return InfographicSpecGenerator(api_url="http://x/api/generate", model="m1", timeout_s=7), fake, patcher


class TestBuildBookMap(unittest.TestCase):
    def test_valid_response_becomes_theme_and_entries(self):
        reply = json.dumps({
            "theme": "習慣靠系統",
            "cards": [
                {"n": 1, "role": "主軸", "neighbors": [{"relation": "導向", "n": 2}]},
                {"n": 2, "role": "支柱", "neighbors": []},
            ],
        }, ensure_ascii=False)
        gen, fake, patcher = _generator(f"好的：\n```json\n{reply}\n```")
        self.addCleanup(patcher.stop)
        theme, entries = gen.build_book_map("原子習慣", CARDS)
        self.assertEqual(theme, "習慣靠系統")
        self.assertEqual(entries["習慣是複利"].role, "主軸")
        self.assertEqual(entries["習慣是複利"].neighbors[0].title, "改變身分")
        self.assertEqual(entries["環境設計"].role, "案例")      # 模型漏掉的卡 → 預設
        _, kwargs = fake.calls[0]
        self.assertEqual((kwargs["model"], kwargs["api_url"], kwargs["timeout_s"]), ("m1", "http://x/api/generate", 7))
        self.assertIs(kwargs["think"], False)

    def test_no_response_or_unparseable_response_means_none(self):
        for reply in (None, "", "我覺得這本書很棒"):
            gen, _, patcher = _generator(reply)
            self.addCleanup(patcher.stop)
            self.assertIsNone(gen.build_book_map("原子習慣", CARDS), reply)
            patcher.stop()

    def test_a_book_without_cards_never_calls_the_model(self):
        gen, fake, patcher = _generator("{}")
        self.addCleanup(patcher.stop)
        self.assertIsNone(gen.build_book_map("原子習慣", []))
        self.assertEqual(fake.calls, [])


class TestGenerateCardSpec(unittest.TestCase):
    def test_returns_the_raw_dict_for_normalize_spec(self):
        reply = '{"lines": ["甲"], "nodes": [{"icon": "target", "label": "乙"}], "layout": "cycle"}'
        gen, fake, patcher = _generator(reply)
        self.addCleanup(patcher.stop)
        raw = gen.generate_card_spec(_card("改變身分"), "原子習慣", "")
        self.assertEqual(raw["layout"], "cycle")
        self.assertEqual(raw["nodes"][0]["icon"], "target")
        self.assertIs(fake.calls[0][1]["think"], False)

    def test_unparseable_or_empty_response_means_none(self):
        for reply in (None, "", "沒有 JSON"):
            gen, _, patcher = _generator(reply)
            self.addCleanup(patcher.stop)
            self.assertIsNone(gen.generate_card_spec(_card("改變身分"), "原子習慣", ""), reply)
            patcher.stop()

    def test_ollama_errors_surface_as_none_not_exceptions(self):
        with mock.patch.object(spec_generator, "_ollama_generate", side_effect=RuntimeError("boom")):
            gen = InfographicSpecGenerator(api_url="u", model="m")
            self.assertIsNone(gen.generate_card_spec(_card("改變身分"), "書", ""))
            self.assertIsNone(gen.build_book_map("書", CARDS))


if __name__ == "__main__":
    unittest.main()
