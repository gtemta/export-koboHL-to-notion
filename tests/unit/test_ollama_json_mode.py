"""_ollama_generate 的 json_mode：要求 Ollama 只輸出合法 JSON（format: "json"）。

小模型（實測 qwen3:4b）在「只輸出 JSON」的指令下仍會先寫一大段推理文字直到
num_predict 用完；JSON 模式從解碼端就限制輸出，才可靠。預設關閉，既有呼叫不受影響。
"""
import json
import unittest
from unittest import mock

import zettelkasten_generator as zg


class _Resp:
    status_code = 200
    text = ""

    def iter_lines(self, decode_unicode=True):
        yield json.dumps({"response": '{"a": 1}', "done": True, "done_reason": "stop"})


def _call(**kwargs):
    with mock.patch.object(zg.requests, "post", return_value=_Resp()) as post:
        out = zg._ollama_generate(
            "p", api_url="http://x", model="m", timeout_s=5, temperature=0.1, num_predict=10,
            **kwargs,
        )
    return out, post.call_args.kwargs["json"]


class TestJsonMode(unittest.TestCase):
    def test_json_mode_sends_format_json(self):
        out, payload = _call(json_mode=True)
        self.assertEqual(payload["format"], "json")
        self.assertEqual(out, '{"a": 1}')

    def test_default_sends_no_format_key(self):
        _, payload = _call()
        self.assertNotIn("format", payload)

    def test_json_mode_survives_the_think_param_retry(self):
        first, second = mock.Mock(status_code=400, text="no think"), _Resp()
        with mock.patch.object(zg.requests, "post", side_effect=[first, second]) as post:
            zg._ollama_generate(
                "p", api_url="http://x", model="m", timeout_s=5, temperature=0.1,
                num_predict=10, think=False, json_mode=True,
            )
        retry_payload = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("think", retry_payload)
        self.assertEqual(retry_payload["format"], "json")


if __name__ == "__main__":
    unittest.main()
