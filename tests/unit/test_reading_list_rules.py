"""書籍種類推算：卡片 Tags 多數決（spec「書籍種類推算」）。"""
import unittest

from src.config.settings import DEFAULT_BOOK_TYPE_MAPPING
from src.domain.entities.book_card import BookCard
from src.domain.services.reading_list_rules import derive_book_types


def _cards(*tag_lists):
    return [BookCard(page_id=f"c{i}", title=f"卡{i}", tags=list(tags))
            for i, tags in enumerate(tag_lists)]


class TestDeriveBookTypes(unittest.TestCase):
    def test_dopamine_nation_example(self):
        # 《多巴胺國度》實際分布：心理學 15、人生觀點 2、哲學科學 2、商務 1、邏輯思考 1
        cards = _cards(
            *[["💞心理學"]] * 12,
            ["💼商務", "💞心理學"],
            ["🧘‍♂️人生觀點", "💞心理學"],
            ["🔬哲學科學"],
            ["🔬哲學科學", "🧘‍♂️人生觀點"],
            ["💞心理學", "🧩邏輯思考"],
        )
        self.assertEqual(derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING), ["Psychology"])

    def test_runner_up_with_half_the_votes_is_kept(self):
        cards = _cards(*[["💞心理學"]] * 4, *[["📈行銷"]] * 2)
        self.assertEqual(
            derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING), ["Psychology", "Marketing"])

    def test_tie_keeps_mapping_order(self):
        cards = _cards(*[["💼商務"]] * 3, *[["🧠學習技巧"]] * 3)
        self.assertEqual(
            derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING),
            ["Learning Skills", "Business & Finance"])

    def test_same_card_votes_once_per_type(self):
        cards = _cards(["💼商務", "💰理財投資"], ["💞心理學"], ["💞心理學"])
        self.assertEqual(
            derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING),
            ["Psychology", "Business & Finance"])

    def test_emoji_insensitive(self):
        self.assertEqual(
            derive_book_types(_cards(["心理學"]), DEFAULT_BOOK_TYPE_MAPPING), ["Psychology"])

    def test_at_most_two_types(self):
        cards = _cards(*[["💞心理學"]] * 2, *[["📈行銷"]] * 2, *[["💻軟體工程"]] * 2)
        self.assertEqual(len(derive_book_types(cards, DEFAULT_BOOK_TYPE_MAPPING)), 2)

    def test_unmapped_or_no_cards(self):
        self.assertEqual(derive_book_types(_cards(["🍳料理"]), DEFAULT_BOOK_TYPE_MAPPING), [])
        self.assertEqual(derive_book_types([], DEFAULT_BOOK_TYPE_MAPPING), [])


if __name__ == "__main__":
    unittest.main()
