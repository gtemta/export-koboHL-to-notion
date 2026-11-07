"""白名單圖示的 SVG 內容（Lucide，ISC 授權，固定版本 lucide-static@0.469.0）。"""
import re
from functools import lru_cache
from pathlib import Path

from ...domain.services.infographic_rules import ICON_NAMES

_ICON_DIR = Path(__file__).parent / "icons"
_INNER = re.compile(r"<svg\b[^>]*>(.*)</svg>", re.DOTALL)


@lru_cache(maxsize=None)
def icon_inner_svg(name: str) -> str:
    """圖示的內層標記（不含 <svg> 外框），由渲染器包進自己的 <svg viewBox="0 0 24 24">。

    只認白名單名稱：名字會被拿去組檔案路徑，不在白名單內一律 KeyError，
    也就不可能讀到圖示資料夾以外的檔案。"""
    if name not in ICON_NAMES:
        raise KeyError(name)
    text = (_ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    match = _INNER.search(text)
    if not match:
        raise ValueError(f"圖示 {name}.svg 不是有效的 SVG")
    return match.group(1).strip()
