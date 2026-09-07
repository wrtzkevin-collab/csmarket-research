import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.catalog import (  # noqa: E402
    CaseDefinition,
    CatalogItem,
    CatalogVariant,
)
from csmarket.pipeline import (  # noqa: E402
    expand_case_variants,
    required_market_names,
    snapshot_from_skinport_rows,
    value_case,
)


def item(item_id, rarity, *, special=False, stattrak=False):
    name = f"Item {item_id}"
    normal = f"exact::{item_id}::normal"
    market_variants = [CatalogVariant(normal, "Field-Tested", False, False)]
    if stattrak:
        market_variants.append(
            CatalogVariant(f"exact::{item_id}::stattrak", "Field-Tested", True, False)
        )
    market_variants.append(
        CatalogVariant(f"souvenir::{item_id}", "Field-Tested", False, True)
    )
    return CatalogItem(
        id=item_id,
        name=name,
        rarity=rarity,
        min_float=0.2,
        max_float=0.3,
        stattrak_eligible=stattrak,
        wears=("Field-Tested",),
        is_special=special,
        market_variants=tuple(market_variants),
    )


def example_case():
    return CaseDefinition(
        id="case-1",
        name="Example Case",
        items=(
            item("blue", "Mil-Spec Grade", stattrak=True),
            item("purple", "Restricted"),
            item("pink", "Classified"),
            item("red", "Covert"),
            item("special", "Rare Special Item", special=True),
        ),
    )


def rows_for(case, variants, *, omit=()):
    names = required_market_names(case, variants)
    return [
        {
            "market_hash_name": name,
            "price": 1.0 if name == case.name else 5.0,
            "source": "skinport",
            "currency": "USD",
            "price_type": "sales_median_30_days",
            "observed_at": "2026-09-07T00:00:00Z",
            "volume": 10,
        }
        for name in names
        if name not in omit
    ]


class PipelineTests(unittest.TestCase):
    def test_catalogue_exact_names_are_used_and_souvenirs_are_filtered(self):
        case = example_case()
        variants = expand_case_variants(case, wear_model_id="uniform_allowed_range_v1")
        names = {variant.market_hash_name for variant in variants}

        self.assertIn("exact::blue::normal", names)
        self.assertIn("exact::blue::stattrak", names)
        self.assertFalse(any(name.startswith("souvenir::") for name in names))
        self.assertAlmostEqual(sum(variant.probability for variant in variants), 1.0)

    def test_complete_same_snapshot_produces_publishable_valuation(self):
        case = example_case()
        variants = expand_case_variants(case, wear_model_id="uniform_allowed_range_v1")
        snapshot = snapshot_from_skinport_rows(
            rows_for(case, variants), required_names=required_market_names(case, variants)
        )
        valuation = value_case(
            case,
            variants,
            snapshot,
            key_price=2.0,
            key_price_source="explicit test fixture",
            sell_fee_rate=0.1,
            wear_model_id="uniform_allowed_range_v1",
        )

        self.assertTrue(valuation.publication_ready)
        self.assertAlmostEqual(valuation.result.probability_coverage, 1.0)
        self.assertAlmostEqual(valuation.result.gross_ev, 5.0)
        self.assertAlmostEqual(valuation.result.expected_net_roi, 0.5)

    def test_missing_special_price_is_visible_even_with_high_overall_coverage(self):
        case = example_case()
        variants = expand_case_variants(case, wear_model_id="uniform_allowed_range_v1")
        special_name = next(v.market_hash_name for v in variants if v.is_special)
        snapshot = snapshot_from_skinport_rows(
            rows_for(case, variants, omit={special_name}),
            required_names=required_market_names(case, variants),
        )
        valuation = value_case(
            case,
            variants,
            snapshot,
            key_price=2.0,
            key_price_source="explicit test fixture",
            sell_fee_rate=0.1,
            wear_model_id="uniform_allowed_range_v1",
        )

        self.assertAlmostEqual(valuation.result.probability_coverage, 0.99744)
        self.assertEqual(valuation.rarity_coverage["Rare Special Item"], 0.0)
        self.assertFalse(valuation.publication_ready)
        self.assertIn(special_name, valuation.missing_market_names)

    def test_mixed_snapshot_metadata_is_rejected(self):
        case = example_case()
        variants = expand_case_variants(case, wear_model_id="uniform_allowed_range_v1")
        rows = rows_for(case, variants)
        rows[1]["currency"] = "CNY"
        with self.assertRaisesRegex(ValueError, "mix"):
            snapshot_from_skinport_rows(
                rows, required_names=required_market_names(case, variants)
            )

    def test_missing_case_price_hard_fails(self):
        case = example_case()
        variants = expand_case_variants(case, wear_model_id="uniform_allowed_range_v1")
        snapshot = snapshot_from_skinport_rows(
            rows_for(case, variants, omit={case.name}),
            required_names=required_market_names(case, variants),
        )
        with self.assertRaisesRegex(ValueError, "case price is missing"):
            value_case(
                case,
                variants,
                snapshot,
                key_price=2.0,
                key_price_source="explicit test fixture",
                sell_fee_rate=0.1,
                wear_model_id="uniform_allowed_range_v1",
            )


if __name__ == "__main__":
    unittest.main()

