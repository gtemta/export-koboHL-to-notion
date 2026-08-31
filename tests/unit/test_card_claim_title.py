"""K1：產卡 prompt 要主張句，審核 prompt 不動。

斷言刻意只抓規則的關鍵字與長度數字——prompt 文案會微調，但「要求主張句」
與「5-20 字」這兩件事若消失就是回歸。
"""
import unittest

from zettelkasten_generator import CardReviewer, ZettelkastenCard, ZettelkastenLLMEnhancer


class TestClaimStyleTitleRule(unittest.TestCase):
    def test_single_card_prompt_asks_for_a_claim(self):
        prompt = ZettelkastenLLMEnhancer()._build_prompt("劃線文字", "書名")
        self.assertIn("論斷", prompt)
        self.assertIn("5-20", prompt)
        self.assertNotIn("5-15", prompt)

    def test_single_card_prompt_forbids_inventing_conclusions(self):
        # 與審核 correctness 面向共存的接縫：原文沒論斷時不得自行推論。
        prompt = ZettelkastenLLMEnhancer()._build_prompt("劃線文字", "書名")
        self.assertIn("不要自行推論出原文沒有的結論", prompt)

    def test_batch_prompt_asks_for_a_claim(self):
        highlights = [{"text": "劃線一"}, {"text": "劃線二"}]
        prompt = ZettelkastenLLMEnhancer()._build_batch_prompt(highlights, "書名")
        self.assertIn("論斷", prompt)
        self.assertIn("5-20", prompt)
        self.assertNotIn("5-15", prompt)
        # main.py 實際跑的是這條路徑（批次），這個 fallback 子句是審核關卡能
        # 維持不動的唯一原因：原文沒論斷時不准模型自行腦補結論。掉了這條，
        # correctness 面向的退卡率會悄悄升高，卻不會有任何紅燈。
        self.assertIn("不要自行推論出原文沒有的結論", prompt)

    def test_review_prompt_is_untouched(self):
        # 標題風格不進審核關卡：不放寬 correctness，也不加嚴 consistency。
        card = ZettelkastenCard(
            id="id", title="標題", content="內容",
            source_highlight="劃線", chapter_reference="", chapter_progress=0.0,
        )
        prompt = CardReviewer()._build_review_prompt(card, "書名", "", [])
        self.assertNotIn("論斷", prompt)
        self.assertNotIn("主張句", prompt)
        # 正面釘住 K1 fallback 子句共存的那條軸線（correctness 面向），
        # 避免只斷言「沒有」讓不同措辭的標題規則悄悄溜進來也算過關。
        self.assertIn("沒有加入原文沒說的因果、數據或結論", prompt)


if __name__ == "__main__":
    unittest.main()
