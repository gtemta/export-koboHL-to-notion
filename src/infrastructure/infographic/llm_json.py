"""從小模型的回應裡撈出 JSON 物件。"""
import json
import re
from typing import Optional

_THINK_BLOCK = re.compile(r"(?is)<think>.*?</think>")
_decoder = json.JSONDecoder()
# 一個失敗的 `{` 之後還會試下一個；惡意或失控的回應（上萬個 `{`）不該讓這裡跑到天荒地老。
_MAX_ATTEMPTS = 50


def parse_json_object(text: Optional[str]) -> Optional[dict]:
    """回應裡「最左邊那個能完整解析的 JSON 物件」；找不到回傳 None。

    小模型愛在 JSON 前後加說明、code fence 或 <think> 區塊。這裡從每個 `{` 試著
    解碼一個完整物件，所以巢狀結構會整個回來，物件後面多出來的文字（含大括號）也不影響。
    刻意不沿用 zettelkasten_generator 的 `_loads_json`——它先取「最內層」大括號，
    遇到巢狀 JSON 只會拿到最裡面那個小物件。"""
    if not text:
        return None
    cleaned = _THINK_BLOCK.sub("", text)
    start = cleaned.find("{")
    for _ in range(_MAX_ATTEMPTS):
        if start == -1:
            break
        try:
            parsed, _end = _decoder.raw_decode(cleaned, start)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        start = cleaned.find("{", start + 1)
    return None
