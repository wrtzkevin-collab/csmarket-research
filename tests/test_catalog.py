import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.catalog import CaseCatalogClient, CatalogDataError  # noqa: E402


def response(payload, status=200):
    result = Mock()
    result.json.return_value = payload
    result.status_code = status
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class CatalogTests(unittest.TestCase):
    def fixtures(self):
        cases = [
            {
                "id": "case-1",
                "name": "Example Case",
                "contains": [{"id": "skin-normal"}],
                "contains_rare": [{"id": "skin-special"}],
            }
        ]
        skins = [
            {
                "id": "skin-normal",
                "name": "Rifle | Finish",
                "rarity": {"name": "Mil-Spec Grade"},
                "min_float": 0.0,
                "max_float": 0.5,
                "stattrak": True,
                "wears": [{"name": "Factory New"}, {"name": "Field-Tested"}],
            },
            {
                "id": "skin-special",
                "name": "★ Knife",
                "rarity": {"name": "Covert"},
                "min_float": None,
                "max_float": None,
                "stattrak": True,
                "wears": None,
            },
        ]
        variants = [
            {
                "skin_id": "skin-normal",
                "market_hash_name": "Rifle | Finish (Factory New)",
                "wear": {"name": "Factory New"},
                "stattrak": False,
                "souvenir": False,
            },
            {
                "skin_id": "skin-normal",
                "market_hash_name": "StatTrak™ Rifle | Finish (Factory New)",
                "wear": {"name": "Factory New"},
                "stattrak": True,
                "souvenir": False,
            },
            {
                "skin_id": "skin-special",
                "market_hash_name": "★ Knife",
                "wear": None,
                "stattrak": False,
                "souvenir": False,
            },
        ]
        return cases, skins, variants

    def client(self, cases=None, skins=None, variants=None):
        fixture_cases, fixture_skins, fixture_variants = self.fixtures()
        session = Mock()
        session.get.side_effect = [
            response(fixture_cases if cases is None else cases),
            response(fixture_skins if skins is None else skins),
            response(fixture_variants if variants is None else variants),
        ]
        return CaseCatalogClient(session=session, sleep=lambda _: None), session

    def test_fetch_case_joins_normal_and_special_items(self):
        client, session = self.client()
        case = client.fetch_case("Example Case")

        self.assertEqual(case.id, "case-1")
        self.assertEqual(len(case.items), 2)
        self.assertEqual(case.items[0].rarity, "Mil-Spec Grade")
        self.assertEqual(case.items[1].rarity, "Rare Special Item")
        self.assertTrue(case.items[1].is_special)
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(
            case.items[0].market_variants[0].market_hash_name,
            "Rifle | Finish (Factory New)",
        )

    def test_loaded_catalogue_is_cached(self):
        client, session = self.client()
        client.fetch_case("Example Case")
        client.fetch_case("Example Case")
        self.assertEqual(session.get.call_count, 3)

    def test_missing_skin_reference_fails_closed(self):
        cases, skins, variants = self.fixtures()
        cases[0]["contains"][0]["id"] = "missing"
        client, _ = self.client(cases, skins, variants)
        with self.assertRaisesRegex(CatalogDataError, "skin is missing"):
            client.fetch_case("Example Case")

    def test_duplicate_skin_ids_are_rejected(self):
        cases, skins, variants = self.fixtures()
        skins.append(dict(skins[0]))
        client, _ = self.client(cases, skins, variants)
        with self.assertRaisesRegex(CatalogDataError, "duplicate skin id"):
            client.fetch_case("Example Case")

    def test_unknown_case_is_rejected(self):
        client, _ = self.client()
        with self.assertRaisesRegex(CatalogDataError, "found 0"):
            client.fetch_case("Unknown Case")


if __name__ == "__main__":
    unittest.main()
