"""卡片重審的純規則：讀懂卡片頁、判斷這個版本審過沒、組出寫回頁尾的結果。

使用者手動改過的卡，審核結果只是參考：模型只能提供意見與候選版本，不會更動卡片本文。
"""
import hashlib
import re
from typing import List, Mapping, Optional, Sequence, Tuple

from ..entities.card_revision import Candidate, CardBlock, CardBody, Verdict

RESULT_MARKER = "🤖 重審結果"

_RESULT_KIND = "toggle"
_NOTE_MARKER = re.compile(r"^\s*待修正的點\s*[:：]?\s*")
_LIST_KINDS = frozenset({"bulleted_list_item", "numbered_list_item", "to_do"})
_AXES = (
    ("consistency", "一致性"),
    ("correctness", "正確性"),
    ("shareability", "分享性"),
    ("atomicity", "最小片段性"),
)


def is_result_heading(kind: str, text: str) -> bool:
    """這個 block 是不是工具之前寫的結果區塊（不屬於卡片內容）。"""
    return kind == _RESULT_KIND and text.startswith(RESULT_MARKER)


def parse_card_body(blocks: Sequence[CardBlock]) -> CardBody:
    """依閱讀順序把卡片頁拆成本文、原文劃線、待修正的點。

    「待修正的點」可以寫成一段，或一段標題加緊接的清單，也可以寫好幾段。不限 block
    類型，排版交給使用者；唯一的判斷依據是開頭那幾個字。
    """
    content: List[str] = []
    note: List[str] = []
    highlight = ""
    in_note = False
    for block in blocks:
        text = block.text.strip()
        if is_result_heading(block.kind, text):
            in_note = False
            continue
        if in_note and block.kind in _LIST_KINDS:
            if text:
                note.append(text)
            continue
        in_note = False
        if not text:
            continue
        if block.kind == "quote" and not highlight:
            highlight = text
        elif _NOTE_MARKER.match(text):
            rest = _NOTE_MARKER.sub("", text).strip()
            if rest:
                note.append(rest)
            in_note = True
        else:
            content.append(text)
    return CardBody("\n".join(content), highlight, "\n".join(note))


def fingerprint(title: str, body: CardBody) -> str:
    """這個版本的指紋：使用者改了任何一處就會變，重跑時才知道要不要再審。"""
    parts = (title, body.content, body.highlight, body.revision_note)
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:12]


def has_result_for(blocks: Sequence[CardBlock], mark: str) -> bool:
    return any(
        is_result_heading(b.kind, b.text.strip()) and f"〔{mark}〕" in b.text
        for b in blocks
    )


def revision_hint(body: CardBody) -> str:
    """給產卡模型的修改指示：使用者要改什麼，加上目前的版本（可能手動改過）。"""
    return f"{body.revision_note}\n\n上一版內容（沒被提到的部分盡量保留）：\n{body.content}"


def format_result(
    verdict: Verdict,
    *,
    threshold: int,
    mark: str,
    day: str,
    candidate: Optional[Candidate] = None,
) -> Tuple[str, List[str]]:
    """(結果區塊的標題, 區塊內每一段文字)。標題帶指紋，只讀頂層 block 就能判斷審過沒。"""
    summary = "通過" if verdict.passed else "未通過"
    extra = "｜有候選版本" if candidate else ""
    heading = f"{RESULT_MARKER} {day}｜{summary}{extra}〔{mark}〕"

    lines = [f"目前版本：{_scores_line(verdict, threshold)}"]
    if verdict.notes:
        lines.append(f"意見：{verdict.notes}")
    if verdict.scores.get("correctness", threshold) < threshold:
        lines.append("提醒：正確性會扣「原文沒寫」的內容。如果那段是你自己的想法，可以不理會這項分數。")
    if candidate:
        lines.append("候選版本（模型依「待修正的點」重產，尚未套用）：")
        lines.append(f"標題：{candidate.title}")
        lines.append(f"內容：{candidate.content}")
        lines.append(f"候選版本評分：{_scores_line(candidate.verdict, threshold)}")
        if candidate.verdict.notes:
            lines.append(f"意見：{candidate.verdict.notes}")
    lines.append("看完可以直接刪掉這個區塊。刪掉後重跑會再審一次；內容改過也會再審。")
    return heading, lines


def _scores_line(verdict: Verdict, threshold: int) -> str:
    return f"{_axes_text(verdict.scores)}（{'通過' if verdict.passed else '未通過'}，每項都要 ≥ {threshold}）"


def _axes_text(scores: Mapping[str, int]) -> str:
    return "／".join(f"{label} {scores.get(key, '?')}" for key, label in _AXES)
