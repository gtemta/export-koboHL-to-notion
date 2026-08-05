"""卡片頁 cover 選色 — 分類 → Notion 內建 cover URL（純函式，零 IO）。

用 Notion 自家 CDN 的內建 cover：不需 API key、不需上傳檔案，也沒有第三方圖床
失效導致整面卡片牆破圖的風險。URL 於 2026-08-05 實地驗證；`gradients_10.png`
與 woodblocks 系列已下架（404），不得加入。

這是整個 repo 唯一知道 cover URL 長相的地方，repository 與回填工具共用，
避免像 `_split_tags` 那次一樣兩邊各寫一份而漂移。
"""
import hashlib
from typing import Optional, Sequence

# 比對鍵沿用分類的 text core（去 emoji），與 Tags 的 emoji-insensitive 慣例一致。
from zettelkasten_generator import ZettelkastenLLMEnhancer

_COVER_BASE = "https://www.notion.so/images/page-cover/"

# 分類 text core → cover 檔名。key 已去 emoji，故 "💞心理學" 與 "心理學" 同解。
_CATEGORY_COVERS = {
    "心理學": "gradients_1.png",
    "學習技巧": "gradients_2.png",
    "商務": "gradients_3.png",
    "人生觀點": "gradients_4.png",
    "邏輯思考": "gradients_5.png",
    "哲學科學": "gradients_6.png",
    "軟體工程": "gradients_7.png",
    "行銷": "gradients_8.png",
    "專案管理": "gradients_9.png",
    "理財投資": "solid_blue.png",
}

# ZETTELKASTEN_TAG_CATEGORIES 可覆寫分類清單，對照表查不到的分類從這裡挑。
_FALLBACK_COVERS = (
    "gradients_1.png", "gradients_2.png", "gradients_3.png",
    "gradients_4.png", "gradients_5.png", "gradients_6.png",
    "gradients_7.png", "gradients_8.png", "gradients_9.png",
    "solid_blue.png", "solid_red.png", "solid_yellow.png",
)

# 完全沒有分類的卡片。
_DEFAULT_COVER = "solid_beige.png"


def cover_url_for(categories: Optional[Sequence[str]]) -> str:
    """卡片 cover 的完整 URL；取第一個有效分類，無分類則用預設色。"""
    for category in categories or []:
        core = ZettelkastenLLMEnhancer._category_core(category)
        if not core:
            continue
        return _COVER_BASE + (_CATEGORY_COVERS.get(core) or _stable_cover(core))
    return _COVER_BASE + _DEFAULT_COVER


def _stable_cover(core: str) -> str:
    """未知分類的固定配色。

    必須用 sha1 而非內建 hash()：字串 hash 每個 process 有隨機 salt，
    會讓同一張卡每次跑換色，回填工具也會失去冪等性。
    """
    digest = hashlib.sha1(core.encode("utf-8")).digest()
    return _FALLBACK_COVERS[int.from_bytes(digest[:4], "big") % len(_FALLBACK_COVERS)]
