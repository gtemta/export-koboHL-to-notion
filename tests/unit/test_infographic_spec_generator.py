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
                {"n": 3, "role": "案例", "neighbors": []},
                {"n": 4, "role": "案例", "neighbors": []},
            ],
        }, ensure_ascii=False)
        gen, fake, patcher = _generator(f"好的：\n```json\n{reply}\n```")
        self.addCleanup(patcher.stop)
        cards = CARDS + [_card("兩分鐘法則"), _card("第五張")]
        theme, entries = gen.build_book_map("原子習慣", cards)
        self.assertEqual(theme, "習慣靠系統")
        self.assertEqual(entries["習慣是複利"].role, "主軸")
        self.assertEqual(entries["習慣是複利"].neighbors[0].title, "改變身分")
        self.assertEqual(entries["第五張"].role, "案例")        # 模型漏掉的卡 → 預設（4/5 仍算地圖）
        _, kwargs = fake.calls[0]
        self.assertEqual((kwargs["model"], kwargs["api_url"], kwargs["timeout_s"]), ("m1", "http://x/api/generate", 7))
        self.assertIs(kwargs["think"], False)

    def test_no_response_or_unparseable_response_means_none(self):
        for reply in (None, "", "我覺得這本書很棒"):
            gen, _, patcher = _generator(reply)
            self.addCleanup(patcher.stop)
            self.assertIsNone(gen.build_book_map("原子習慣", CARDS), reply)
            patcher.stop()

    def test_valid_json_of_the_wrong_shape_is_a_failure_not_a_flat_map(self):
        for reply in ('{"theme": "x"}', '{"cards": "oops"}', '{"cards": [{"n": 99, "role": "主軸"}]}'):
            gen, _, patcher = _generator(reply)
            self.addCleanup(patcher.stop)
            self.assertIsNone(gen.build_book_map("原子習慣", CARDS), reply)
            patcher.stop()

    def test_a_book_without_cards_never_calls_the_model(self):
        gen, fake, patcher = _generator("{}")
        self.addCleanup(patcher.stop)
        self.assertIsNone(gen.build_book_map("原子習慣", []))
        self.assertEqual(fake.calls, [])


class TestAskBookMap(unittest.TestCase):
    def test_ask_book_map_returns_raw_json_without_normalizing(self):
        gen, _, patcher = _generator('{"cards": [{"n": 1, "role": "支撐"}]}')
        self.addCleanup(patcher.stop)
        self.assertEqual(gen.ask_book_map("書", CARDS)["cards"][0]["role"], "支撐")

    def test_unparseable_response_or_model_error_means_none(self):
        gen, _, patcher = _generator("沒有 JSON")
        self.addCleanup(patcher.stop)
        self.assertIsNone(gen.ask_book_map("書", CARDS))
        patcher.stop()
        with mock.patch.object(spec_generator, "_ollama_generate", side_effect=RuntimeError("boom")):
            self.assertIsNone(InfographicSpecGenerator(api_url="u", model="m").ask_book_map("書", CARDS))

    def test_cards_only_need_title_and_content(self):
        class Slim:
            def __init__(self, title, content):
                self.title, self.content = title, content

        gen, fake, patcher = _generator("{}")
        self.addCleanup(patcher.stop)
        gen.ask_book_map("書", [Slim("甲", "內容甲"), Slim("乙", "內容乙")])
        prompt = fake.calls[0][0]
        self.assertIn("1. 甲｜內容甲", prompt)
        self.assertIn("2. 乙｜內容乙", prompt)

    def test_model_property_exposes_the_configured_name(self):
        self.assertEqual(InfographicSpecGenerator(api_url="u", model="gemma4:12b").model, "gemma4:12b")


def _tags_response(names, status=200):
    response = mock.Mock(status_code=status)
    response.json.return_value = {"models": [{"name": n} for n in names]}
    return response


class TestIsAvailable(unittest.TestCase):
    def _gen(self, model="gemma4:12b"):
        return InfographicSpecGenerator(api_url="http://x:11434/api/generate", model=model)

    def test_true_when_the_model_is_installed(self):
        with mock.patch.object(spec_generator.requests, "get", return_value=_tags_response(["gemma4:12b"])) as get:
            self.assertTrue(self._gen().is_available())
        self.assertEqual(get.call_args.args[0], "http://x:11434/api/tags")
        self.assertEqual(get.call_args.kwargs["timeout"], 5)

    def test_false_when_the_model_is_not_installed(self):
        with mock.patch.object(spec_generator.requests, "get", return_value=_tags_response(["gemma4:12b"])):
            with self.assertLogs(spec_generator.logger, level="ERROR") as logs:
                self.assertFalse(self._gen("x").is_available())
        self.assertIn("ollama pull x", "\n".join(logs.output))

    def test_bare_model_name_matches_latest_tag(self):
        with mock.patch.object(spec_generator.requests, "get", return_value=_tags_response(["gemma4:latest"])):
            self.assertTrue(self._gen("gemma4").is_available())

    def test_false_when_the_service_is_down(self):
        with mock.patch.object(
            spec_generator.requests, "get", side_effect=spec_generator.requests.ConnectionError("refused")
        ):
            with self.assertLogs(spec_generator.logger, level="ERROR"):
                self.assertFalse(self._gen().is_available())

    def test_false_on_error_status_or_non_json(self):
        with mock.patch.object(spec_generator.requests, "get", return_value=_tags_response([], status=500)):
            with self.assertLogs(spec_generator.logger, level="ERROR"):
                self.assertFalse(self._gen().is_available())
        bad = mock.Mock(status_code=200)
        bad.json.side_effect = ValueError("no json")
        with mock.patch.object(spec_generator.requests, "get", return_value=bad):
            with self.assertLogs(spec_generator.logger, level="ERROR"):
                self.assertFalse(self._gen().is_available())

    def test_never_loads_the_model(self):
        with mock.patch.object(spec_generator.requests, "get", return_value=_tags_response(["gemma4:12b"])):
            with mock.patch.object(spec_generator, "_ollama_generate") as generate:
                self._gen().is_available()
        generate.assert_not_called()


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
