"""卡片上傳時的視覺欄位：cover / icon / 加工狀態，以及自動建欄。"""
import unittest

from src.infrastructure.notion.card_visuals import _COVER_BASE
from src.infrastructure.notion.zettelkasten_card_repository import (
    _CREATED_PROPERTY,
    _REVIEWED_PROPERTY,
    _STAGE_PROPERTY,
    _STAGE_UNPROCESSED,
    ZettelkastenCardRepository,
)
from zettelkasten_generator import ZettelkastenCard


def _card(icon="🧭", categories=None):
    card = ZettelkastenCard(
        id="id", title="卡片標題", content="內容", source_highlight="劃線",
        chapter_reference="第一章", chapter_progress=0.5,
        categories=list(categories or ["💞心理學"]),
    )
    card.icon = icon
    return card


def _repo():
    # Client(auth=...) does no network at construction.
    repo = ZettelkastenCardRepository(token="dummy", database_id="db")
    repo._schema_props = None  # 跳過 schema 抓取；照舊寫入全部屬性
    return repo


class TestBuildVisuals(unittest.TestCase):
    def test_cover_from_first_category(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card())
        self.assertEqual(
            visuals["cover"],
            {"type": "external",
             "external": {"url": _COVER_BASE + "gradients_1.png"}},
        )

    def test_icon_written_as_emoji(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card(icon="🎯"))
        self.assertEqual(visuals["icon"], {"type": "emoji", "emoji": "🎯"})

    def test_blank_icon_key_omitted(self):
        # 送 icon=None 會被 Notion 拒收；沒有就整個 key 不要出現
        visuals = ZettelkastenCardRepository._build_visuals(_card(icon=""))
        self.assertNotIn("icon", visuals)
        self.assertIn("cover", visuals)

    def test_whitespace_icon_omitted(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card(icon="  "))
        self.assertNotIn("icon", visuals)

    def test_no_category_still_gets_a_cover(self):
        visuals = ZettelkastenCardRepository._build_visuals(_card(categories=[]))
        self.assertTrue(visuals["cover"]["external"]["url"].startswith(_COVER_BASE))


class TestStageProperty(unittest.TestCase):
    def test_new_card_is_unprocessed(self):
        props = _repo()._build_properties(_card(), books_page_id=None)
        self.assertEqual(
            props[_STAGE_PROPERTY], {"select": {"name": _STAGE_UNPROCESSED}})

    def test_skipped_when_db_lacks_the_column(self):
        repo = _repo()
        repo._schema_props = {"標題"}  # DB 只有標題
        props = repo._build_properties(_card(), books_page_id=None)
        self.assertNotIn(_STAGE_PROPERTY, props)


class TestSchemaAdditions(unittest.TestCase):
    def test_adds_all_three_when_missing(self):
        add = ZettelkastenCardRepository._schema_additions({"標題": {}})
        self.assertIn(_STAGE_PROPERTY, add)
        self.assertIn(_CREATED_PROPERTY, add)
        self.assertIn(_REVIEWED_PROPERTY, add)

    def test_stage_seeds_three_options(self):
        add = ZettelkastenCardRepository._schema_additions({})
        names = [o["name"] for o in add[_STAGE_PROPERTY]["select"]["options"]]
        self.assertEqual(len(names), 3)
        self.assertIn(_STAGE_UNPROCESSED, names)

    def test_created_is_created_time_type(self):
        add = ZettelkastenCardRepository._schema_additions({})
        self.assertEqual(add[_CREATED_PROPERTY], {"created_time": {}})

    def test_reviewed_is_date_type(self):
        add = ZettelkastenCardRepository._schema_additions({})
        self.assertEqual(add[_REVIEWED_PROPERTY], {"date": {}})

    def test_existing_columns_left_alone(self):
        existing = {_STAGE_PROPERTY: {}, _CREATED_PROPERTY: {}, _REVIEWED_PROPERTY: {}}
        self.assertEqual(ZettelkastenCardRepository._schema_additions(existing), {})


class TestCreatePayload(unittest.TestCase):
    """pages.create 必須同時帶 properties / children / icon / cover。"""

    def test_create_receives_icon_and_cover(self):
        repo = _repo()
        calls = []

        class _FakePages:
            def create(self, **kwargs):
                calls.append(kwargs)
                return {"id": "new-page"}

        class _FakeDatabases:
            # upload_cards 在沒有 Books DB 時會走 _filter_new_cards_by_query，
            # 逐卡查「來源劃線ID」——不擋掉就會對 Notion 發真的 HTTP 請求。
            def query(self, **kwargs):
                return {"results": []}

        repo._client.pages = _FakePages()
        repo._client.databases = _FakeDatabases()
        repo._schema_ensured = True  # 跳過 _ensure_schema 的網路呼叫
        created = repo.upload_cards([_card()], book_title="某書")

        self.assertEqual(created, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["icon"], {"type": "emoji", "emoji": "🧭"})
        self.assertTrue(calls[0]["cover"]["external"]["url"].startswith(_COVER_BASE))
        self.assertIn("標題", calls[0]["properties"])


if __name__ == "__main__":
    unittest.main()
