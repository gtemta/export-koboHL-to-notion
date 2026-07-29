#!/usr/bin/env python
"""Re-split glued concept tags in already-generated cards_output/*.json.

Cards produced before the separator fix stored things like
`["語言演化：社交結構：謊言藝術"]` — one unusable mega-tag instead of three
browsable concepts. This walks the local JSON and re-splits every card's `tags`
through the same rules the generator now uses, leaving every other field
(`uploaded`, `uploaded_at`, card content, review scores, …) untouched.

Local JSON only. Cards already uploaded to Notion keep their old `Key Word`
value until a backfill run pushes the corrected tags.

    python tools/fix_card_tags.py --dry-run
    python tools/fix_card_tags.py --dir cards_output
"""
import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

# allow `python tools/fix_card_tags.py` from anywhere: find the root-level
# zettelkasten_generator module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zettelkasten_generator import ZettelkastenLLMEnhancer  # noqa: E402

# Card lists inside a CardStore payload. `rejected` never uploads, but keeping
# it consistent costs nothing and avoids confusing diffs later.
_CARD_KEYS = ("cards", "rejected")


def resplit_tags(tags: List[str]) -> List[str]:
    """Re-split stored tags through the generator's current rules.

    Joining with 、 first means a list that is already clean survives unchanged,
    while a single glued string gets broken apart.
    """
    joined = "、".join(t for t in (tags or []) if isinstance(t, str) and t.strip())
    return ZettelkastenLLMEnhancer._split_tags(joined)


def fix_payload(data: Dict) -> List[Tuple[str, List[str], List[str]]]:
    """Re-split tags in a loaded payload, in place.

    Returns one (card title, old tags, new tags) row per changed card.
    """
    changes: List[Tuple[str, List[str], List[str]]] = []
    for key in _CARD_KEYS:
        for card in data.get(key) or []:
            if not isinstance(card, dict):
                continue
            old = list(card.get("tags") or [])
            new = resplit_tags(old)
            if new != old:
                card["tags"] = new
                changes.append((card.get("title", "?"), old, new))
    return changes


def _write_atomically(path: str, data: Dict) -> None:
    """Write via a temp file so an interrupted run can't truncate a card batch."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def process_dir(directory: str, dry_run: bool = False) -> Dict[str, int]:
    """Re-split every JSON in `directory`; returns a summary counter dict."""
    stats = {"files": 0, "files_changed": 0, "cards_changed": 0,
             "emptied": 0, "unreadable": 0}
    if not os.path.isdir(directory):
        print(f"找不到目錄：{directory}")
        return stats

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        stats["files"] += 1
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"⚠️  跳過（讀取失敗）{filename}: {e}")
            stats["unreadable"] += 1
            continue

        changes = fix_payload(data)
        if not changes:
            continue

        stats["files_changed"] += 1
        stats["cards_changed"] += len(changes)
        print(f"\n📄 {filename}（{len(changes)} 張）")
        for title, old, new in changes:
            if not new:
                # the whole 標籤 line was prose, not concepts — worth eyeballing
                stats["emptied"] += 1
                print(f"   ⚠️ {title}\n      {old} → []（原標籤不是概念詞，已清空）")
            else:
                print(f"   {title}\n      {old} → {new}")

        if not dry_run:
            try:
                _write_atomically(path, data)
            except OSError as e:
                print(f"⚠️  寫回失敗 {filename}: {e}")
                stats["files_changed"] -= 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="重切 cards_output/*.json 裡黏在一起的概念標籤"
    )
    parser.add_argument("--dir", default="cards_output",
                        help="卡片 JSON 目錄（預設 cards_output）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只印出「原標籤 → 新標籤」預覽，不寫檔")
    args = parser.parse_args()

    mode = "DRY RUN（不寫檔）" if args.dry_run else "正式執行"
    print(f"=== 標籤重切：{args.dir} — {mode} ===")

    stats = process_dir(args.dir, dry_run=args.dry_run)

    print(
        f"\n=== 總結 ===\n"
        f"掃描 {stats['files']} 個檔案，"
        f"{'需要修改' if args.dry_run else '已修改'} {stats['files_changed']} 個，"
        f"共 {stats['cards_changed']} 張卡"
    )
    if stats["emptied"]:
        print(f"其中 {stats['emptied']} 張標籤被清空（原本不是概念詞），建議人工看一下")
    if stats["unreadable"]:
        print(f"{stats['unreadable']} 個檔案讀取失敗，未處理")
    if args.dry_run and stats["files_changed"]:
        print("\n確認無誤後拿掉 --dry-run 正式執行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
