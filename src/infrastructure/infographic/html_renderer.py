"""InfographicSpec → 自含式 HTML（1080×1350，IG 4:5）。

這份 HTML 的用途是丟進 Figma 的 html.to.design 外掛，轉成可編輯的圖層，所以刻意只用
flex 版面、行內 SVG、實色，不用絕對定位／濾鏡／CSS 變數這類匯入時容易走樣的東西。
所有來自模型或書名的文字一律 html.escape。
"""
import math
from html import escape
from typing import List, Sequence

from ...domain.entities.infographic_spec import InfographicSpec, Node
from .icon_library import icon_inner_svg

# 畫布高度是固定的 1350px，沒有自動縮放；底下小地圖能佔的高度要有上限，
# 版面預算的實測見 CLAUDE.md「卡片概念圖卡」。
_NEIGHBOR_TITLE_CHARS = 14

_ROLE_TAG = {"主軸": "全書主軸", "支柱": "支柱觀念", "案例": "案例"}
_ROLE_ACCENT = {"主軸": "#B5532A", "支柱": "#B8895A", "案例": "#7A8F6B"}

_ARROW = (
    '<div class="arrow"><svg viewBox="0 0 24 24">'
    f'{icon_inner_svg("arrow-right")}</svg></div>'
)

_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { width: 1080px; height: 1350px; font-family: 'Noto Sans TC', sans-serif; background: #FBF7F0; color: #2B2A28; }
  .card { width: 1080px; height: 1350px; padding: 80px 72px; display: flex; flex-direction: column; }
  .tag { align-self: flex-start; font-size: 26px; font-weight: 500; color: #5C574E; background: #F1E3CF; padding: 8px 22px; border-radius: 999px; }
  .title { margin-top: 36px; font-size: 64px; font-weight: 900; line-height: 1.25; }
  .visual { margin-top: 56px; }
  .flow, .contrast { display: flex; align-items: center; justify-content: space-between; }
  .node { width: 250px; display: flex; flex-direction: column; align-items: center; gap: 24px; }
  .node-cap { font-size: 24px; font-weight: 500; color: ACCENT; }
  .bubble { width: 170px; height: 170px; border-radius: 50%; background: #FFFFFF; border: 4px solid #2B2A28; display: flex; align-items: center; justify-content: center; }
  .bubble.result { background: ACCENT; border-color: ACCENT; }
  .bubble svg { width: 80px; height: 80px; stroke: #2B2A28; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .bubble.result svg { stroke: #FFFFFF; }
  .node-label { font-size: 32px; font-weight: 700; text-align: center; line-height: 1.35; }
  .arrow svg { width: 52px; height: 52px; stroke: ACCENT; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .side { display: flex; flex-direction: column; align-items: flex-start; gap: 24px; }
  .layout-contrast .node { width: auto; flex-direction: row; gap: 20px; }
  .layout-contrast .bubble { width: 104px; height: 104px; }
  .layout-contrast .bubble svg { width: 50px; height: 50px; }
  .layout-contrast .node-label { font-size: 30px; text-align: left; }
  .vs { font-size: 40px; font-weight: 900; color: #FFFFFF; background: ACCENT; width: 96px; height: 96px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
  .stack { display: flex; flex-direction: column; gap: 14px; }
  .tier { display: flex; }
  .layout-hierarchy .node { width: auto; flex-direction: row; gap: 22px; }
  .layout-hierarchy .bubble { width: 84px; height: 84px; }
  .layout-hierarchy .bubble svg { width: 40px; height: 40px; }
  .layout-hierarchy .node-label { font-size: 30px; text-align: left; }
  .loopback { margin-top: 36px; display: flex; align-items: center; justify-content: center; gap: 16px; font-size: 28px; font-weight: 500; color: ACCENT; border-top: 4px dashed ACCENT; padding-top: 24px; }
  .loopback svg { width: 40px; height: 40px; stroke: ACCENT; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .lines { margin-top: 56px; display: flex; flex-direction: column; gap: 18px; }
  .line { font-size: 38px; font-weight: 500; line-height: 1.5; padding-left: 28px; border-left: 8px solid ACCENT; }
  .spacer { flex: 1; }
  .map { border-top: 3px solid #E4D8C6; padding-top: 30px; }
  .map-label { font-size: 24px; color: #8C8579; margin-bottom: 18px; }
  .map-row { display: flex; align-items: center; gap: 8px; }
  .dot { width: 24px; height: 24px; border-radius: 50%; background: #D9CDBB; }
  .dot.on { width: 38px; height: 38px; background: ACCENT; }
  .conn { flex: 1; height: 4px; background: #D9CDBB; }
  .map-note { margin-top: 18px; font-size: 26px; color: #5C574E; line-height: 1.6; }
  .map-note b { color: #2B2A28; }
"""


def _node(node: Node, *, result: bool = False, cap: str = "") -> str:
    bubble_cls = "bubble result" if result else "bubble"
    cap_html = f'<div class="node-cap">{escape(cap)}</div>' if cap else ""
    label_html = f'<div class="node-label">{escape(node.label)}</div>' if node.label else ""
    return (
        '<div class="node">'
        f"{cap_html}"
        f'<div class="{bubble_cls}"><svg viewBox="0 0 24 24">{icon_inner_svg(node.icon)}</svg></div>'
        f"{label_html}"
        "</div>"
    )


def _flow(nodes: List[Node]) -> str:
    return '<div class="flow">' + _ARROW.join(_node(n) for n in nodes) + "</div>"


def _cause(nodes: List[Node]) -> str:
    last = len(nodes) - 1
    parts = [
        _node(n, result=i == last, cap="起因" if i == 0 else "結果" if i == last else "")
        for i, n in enumerate(nodes)
    ]
    return '<div class="flow">' + _ARROW.join(parts) + "</div>"


def _contrast(nodes: List[Node]) -> str:
    split = math.ceil(len(nodes) / 2)
    left = "".join(_node(n) for n in nodes[:split])
    right = "".join(_node(n) for n in nodes[split:])
    return (
        '<div class="contrast">'
        f'<div class="side">{left}</div><div class="vs">VS</div><div class="side">{right}</div>'
        "</div>"
    )


def _hierarchy(nodes: List[Node]) -> str:
    tiers = "".join(
        f'<div class="tier" style="margin-left: {i * 56}px">{_node(n)}</div>'
        for i, n in enumerate(nodes)
    )
    return f'<div class="stack">{tiers}</div>'


def _cycle(nodes: List[Node]) -> str:
    return (
        _flow(nodes)
        + '<div class="loopback"><svg viewBox="0 0 24 24">'
        f'{icon_inner_svg("repeat")}</svg>回到起點</div>'
    )


_LAYOUT_BUILDERS = {
    "flow": _flow,
    "cause": _cause,
    "contrast": _contrast,
    "hierarchy": _hierarchy,
    "cycle": _cycle,
}


def _short(title: str) -> str:
    """鄰居卡標題在小地圖底下只是提示，過長會把版面往下擠出畫布。"""
    return title if len(title) <= _NEIGHBOR_TITLE_CHARS else title[: _NEIGHBOR_TITLE_CHARS - 1] + "…"


def _book_map(spec: InfographicSpec, book_titles: Sequence[str]) -> str:
    parts: List[str] = []
    if spec.card_title in book_titles:
        position = list(book_titles).index(spec.card_title)
        dots = '<div class="conn"></div>'.join(
            '<div class="dot on"></div>' if i == position else '<div class="dot"></div>'
            for i in range(len(book_titles))
        )
        parts.append(
            f'<div class="map-label">全書位置 · 第 {position + 1} / {len(book_titles)} 張</div>'
            f'<div class="map-row">{dots}</div>'
        )
    if spec.neighbors:
        notes = "　".join(
            f"{escape(n.relation)}：<b>{escape(_short(n.title))}</b>" for n in spec.neighbors
        )
        parts.append(f'<div class="map-note">{notes}</div>')
    return f'<div class="map">{"".join(parts)}</div>' if parts else ""


def render_infographic_html(
    spec: InfographicSpec, book_title: str, book_titles: Sequence[str]
) -> str:
    """book_titles 是同一本書所有卡的標題（閱讀順序），用來畫「全書位置」小地圖。"""
    accent = _ROLE_ACCENT.get(spec.role, _ROLE_ACCENT["案例"])
    css = _CSS.replace("ACCENT", accent)
    visual = _LAYOUT_BUILDERS.get(spec.layout, _flow)(spec.nodes)
    lines = "".join(f'<div class="line">{escape(line)}</div>' for line in spec.lines)
    tag = f"{_ROLE_TAG.get(spec.role, spec.role)} · 《{book_title}》"
    return (
        "<!doctype html>\n"
        '<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(spec.card_title)}</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap" rel="stylesheet">\n'
        f"<style>{css}</style>\n</head>\n<body>\n"
        '<div class="card">\n'
        f'<div class="tag">{escape(tag)}</div>\n'
        f'<div class="title">{escape(spec.card_title)}</div>\n'
        f'<div class="visual layout-{escape(spec.layout)}">{visual}</div>\n'
        f'<div class="lines">{lines}</div>\n'
        '<div class="spacer"></div>\n'
        f"{_book_map(spec, book_titles)}\n"
        "</div>\n</body>\n</html>\n"
    )
