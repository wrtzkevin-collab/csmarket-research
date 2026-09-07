import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.model import EVResult  # noqa: E402
from csmarket.pipeline import CaseValuation  # noqa: E402
from csmarket.wear import BASIS_OBSERVED_VOLUME, BASIS_UNIFORM_FALLBACK  # noqa: E402
from csmarket.webexport import (  # noqa: E402
    build_web_document,
    valuation_to_web_entry,
    write_web_document,
)


def valuation(
    *,
    case_name="Kilowatt Case",
    source="steam_community_market",
    coverage=1.0,
    publication_ready=True,
):
    result = EVResult(
        gross_ev=0.86,
        total_cost=2.71,
        gross_return_ratio=0.86 / 2.71,
        net_ev=0.76,
        expected_net_roi=(0.76 - 2.71) / 2.71,
        loss_probability=0.95,
        probability_coverage=coverage,
    )
    return CaseValuation(
        case_name=case_name,
        case_price=0.22,
        key_price=2.49,
        key_price_source="configured",
        sell_fee_rate=0.12,
        result=result,
        rarity_coverage={"Covert": 1.0, "Rare Special Item": coverage},
        priced_outcomes=282,
        total_outcomes=282,
        missing_market_names=(),
        wear_basis_coverage={
            BASIS_OBSERVED_VOLUME: 0.997,
            BASIS_UNIFORM_FALLBACK: 0.003,
        },
        wear_volume_source="steam_community_market",
        publication_ready=publication_ready,
        source=source,
        currency="USD",
        price_type="lowest_listing",
        observed_at="2026-09-07T12:00:00Z",
        observation_span_seconds=840.0,
        catalog_commit="2dc37f6",
        catalog_repository="https://github.com/ByMykel/CSGO-API",
    )


class WebEntryTests(unittest.TestCase):
    def test_entry_carries_the_numbers_the_page_renders(self):
        entry = valuation_to_web_entry(valuation())

        self.assertEqual(entry["source_label"], "Steam Community Market")
        self.assertEqual(entry["price_type"], "lowest_listing")
        self.assertAlmostEqual(entry["opening_cost"], 2.71)
        self.assertAlmostEqual(entry["coverage"], 1.0)
        self.assertFalse(entry["loss_probability_is_lower_bound"])
        self.assertTrue(entry["publication_ready"])

    def test_partial_coverage_is_flagged_as_a_lower_bound(self):
        entry = valuation_to_web_entry(
            valuation(coverage=0.9957, publication_ready=False)
        )

        self.assertTrue(entry["loss_probability_is_lower_bound"])
        self.assertFalse(entry["publication_ready"])

    def test_wear_basis_split_is_exposed(self):
        entry = valuation_to_web_entry(valuation())

        self.assertAlmostEqual(entry["wear_basis"]["observed_volume"], 0.997)
        self.assertAlmostEqual(entry["wear_basis"]["uniform_fallback"], 0.003)


class WebDocumentTests(unittest.TestCase):
    def test_valuations_of_one_case_are_grouped_across_venues(self):
        document = build_web_document(
            [
                valuation(source="steam_community_market"),
                valuation(source="skinport"),
            ]
        )

        self.assertEqual(len(document["cases"]), 1)
        sources = [entry["source"] for entry in document["cases"][0]["sources"]]
        self.assertEqual(sources, ["steam_community_market", "skinport"])
        self.assertEqual(document["dataset"]["mode"], "live")
        self.assertEqual(document["dataset"]["case_count"], 1)

    def test_case_order_follows_the_input(self):
        document = build_web_document(
            [
                valuation(case_name="Kilowatt Case"),
                valuation(case_name="Revolution Case"),
                valuation(case_name="Kilowatt Case", source="skinport"),
            ]
        )

        self.assertEqual(
            [entry["name"] for entry in document["cases"]],
            ["Kilowatt Case", "Revolution Case"],
        )
        self.assertEqual(len(document["cases"][0]["sources"]), 2)

    def test_provenance_blocks_are_always_present(self):
        document = build_web_document([valuation()])

        self.assertIn("commit", document["catalog_source"])
        self.assertIn("2017", document["probability_source"]["basis"])
        self.assertTrue(document["assumptions"])
        self.assertTrue(
            any("volume" in text for text in document["assumptions"]),
            "the wear-weighting basis must be disclosed on the page",
        )

    def test_empty_input_is_rejected(self):
        with self.assertRaises(ValueError):
            build_web_document([])

    def test_written_document_is_valid_json_the_page_can_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "web" / "results.json"
            write_web_document(build_web_document([valuation()]), target)

            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "2.0")
        self.assertEqual(payload["cases"][0]["name"], "Kilowatt Case")


if __name__ == "__main__":
    unittest.main()
