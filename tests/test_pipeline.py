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
    candidate_market_names,
    expand_case_variants,
    required_market_names,
    snapshot_from_rows,
    value_case,
    wear_weights_for_case,
)
from csmarket.wear import (  # noqa: E402
    BASIS_OBSERVED_VOLUME,
    BASIS_UNIFORM_FALLBACK,
    WearWeights,
)


def item(item_id, rarity, *, special=False, stattrak=False):
    """A single-grade item: float range 0.2-0.3 only reaches Field-Tested."""

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
        name=f"Item {item_id}",
        rarity=rarity,
        min_float=0.2,
        max_float=0.3,
        stattrak_eligible=stattrak,
        wears=("Field-Tested",),
        is_special=special,
        market_variants=tuple(market_variants),
    )


def multi_wear_item(item_id, rarity, *, special=False):
    """A full-range item so wear weighting has more than one grade to split."""

    wears = (
        "Factory New",
        "Minimal Wear",
        "Field-Tested",
        "Well-Worn",
        "Battle-Scarred",
    )
    return CatalogItem(
        id=item_id,
        name=f"Item {item_id}",
        rarity=rarity,
        min_float=0.0,
        max_float=1.0,
        stattrak_eligible=False,
        wears=wears,
        is_special=special,
        market_variants=tuple(
            CatalogVariant(f"exact::{item_id}::{wear}", wear, False, False)
            for wear in wears
        ),
    )


def example_case(blue=None):
    return CaseDefinition(
        id="case-1",
        name="Example Case",
        items=(
            blue or item("blue", "Mil-Spec Grade", stattrak=True),
            item("purple", "Restricted"),
            item("pink", "Classified"),
            item("red", "Covert"),
            item("special", "Rare Special Item", special=True),
        ),
    )


def uniform_weights(case):
    """Weights that put every item's whole mass on its single reachable grade."""

    return {
        catalog_item.id: WearWeights(
            weights={"Field-Tested": 1.0},
            basis=BASIS_OBSERVED_VOLUME,
            observed_volume=100,
            source_url="test",
        )
        for catalog_item in case.items
    }


def rows_for(case, variants, *, omit=(), volume=10, source="steam_community_market"):
    names = required_market_names(case, variants)
    return [
        {
            "market_hash_name": name,
            "price": 1.0 if name == case.name else 5.0,
            "source": source,
            "currency": "USD",
            "price_type": "lowest_listing",
            "observed_at": "2026-09-07T00:00:00Z",
            "volume": volume,
        }
        for name in names
        if name not in omit
    ]


class PipelineTests(unittest.TestCase):
    def test_catalogue_exact_names_are_used_and_souvenirs_are_filtered(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        names = {variant.market_hash_name for variant in variants}

        self.assertIn("exact::blue::normal", names)
        self.assertIn("exact::blue::stattrak", names)
        self.assertFalse(any(name.startswith("souvenir::") for name in names))
        self.assertAlmostEqual(sum(variant.probability for variant in variants), 1.0)

    def test_candidate_names_cover_every_reachable_grade_before_weighting(self):
        case = example_case(blue=multi_wear_item("blue", "Mil-Spec Grade"))
        names = candidate_market_names(case)

        self.assertIn(case.name, names)
        for wear in ("Factory New", "Field-Tested", "Battle-Scarred"):
            self.assertIn(f"exact::blue::{wear}", names)
        self.assertFalse(any(name.startswith("souvenir::") for name in names))

    def test_complete_same_snapshot_produces_publishable_valuation(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        snapshot = snapshot_from_rows(
            rows_for(case, variants),
            required_names=required_market_names(case, variants),
        )
        valuation = value_case(
            case,
            variants,
            snapshot,
            key_price=2.0,
            key_price_source="explicit test fixture",
            sell_fee_rate=0.1,
        )

        self.assertTrue(valuation.publication_ready)
        self.assertAlmostEqual(valuation.result.probability_coverage, 1.0)
        self.assertAlmostEqual(valuation.result.gross_ev, 5.0)
        self.assertAlmostEqual(valuation.result.expected_net_roi, 0.5)

    def test_missing_special_price_is_visible_even_with_high_overall_coverage(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        special_name = next(v.market_hash_name for v in variants if v.is_special)
        snapshot = snapshot_from_rows(
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
        )

        self.assertAlmostEqual(valuation.result.probability_coverage, 0.99744)
        self.assertEqual(valuation.rarity_coverage["Rare Special Item"], 0.0)
        self.assertFalse(valuation.publication_ready)
        self.assertIn(special_name, valuation.missing_market_names)

    def test_mixed_snapshot_metadata_is_rejected(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        rows = rows_for(case, variants)
        rows[1]["currency"] = "CNY"
        with self.assertRaisesRegex(ValueError, "mix"):
            snapshot_from_rows(
                rows, required_names=required_market_names(case, variants)
            )

    def test_mixed_price_type_is_rejected(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        rows = rows_for(case, variants)
        rows[1]["price_type"] = "sales_median_30_days"
        with self.assertRaisesRegex(ValueError, "mix"):
            snapshot_from_rows(
                rows, required_names=required_market_names(case, variants)
            )

    def test_observation_times_may_drift_within_one_crawl(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        rows = rows_for(case, variants)
        rows[0]["observed_at"] = "2026-09-07T00:00:00Z"
        rows[-1]["observed_at"] = "2026-09-07T00:14:00Z"

        snapshot = snapshot_from_rows(
            rows, required_names=required_market_names(case, variants)
        )

        self.assertEqual(snapshot.observed_at, "2026-09-07T00:14:00Z")
        self.assertEqual(snapshot.observation_span_seconds, 14 * 60)

    def test_observation_drift_beyond_the_limit_is_rejected(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        rows = rows_for(case, variants)
        rows[-1]["observed_at"] = "2026-09-08T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "span"):
            snapshot_from_rows(
                rows, required_names=required_market_names(case, variants)
            )

    def test_missing_case_price_hard_fails(self):
        case = example_case()
        variants = expand_case_variants(case, wear_weights=uniform_weights(case))
        snapshot = snapshot_from_rows(
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
            )


class WearWeightingFromSnapshotTests(unittest.TestCase):
    def _snapshot_with_volumes(self, case, volumes):
        names = candidate_market_names(case)
        rows = []
        for name in names:
            rows.append(
                {
                    "market_hash_name": name,
                    "price": 1.0 if name == case.name else 5.0,
                    "source": "steam_community_market",
                    "currency": "USD",
                    "price_type": "lowest_listing",
                    "observed_at": "2026-09-07T00:00:00Z",
                    "volume": volumes.get(name, 0),
                }
            )
        return snapshot_from_rows(rows, required_names=names)

    def test_observed_volume_drives_the_split(self):
        case = example_case(blue=multi_wear_item("blue", "Mil-Spec Grade"))
        snapshot = self._snapshot_with_volumes(
            case,
            {
                "exact::blue::Factory New": 30,
                "exact::blue::Field-Tested": 70,
            },
        )

        weights = wear_weights_for_case(case, snapshot)

        self.assertEqual(weights["blue"].basis, BASIS_OBSERVED_VOLUME)
        self.assertEqual(weights["blue"].observed_volume, 100)
        self.assertAlmostEqual(weights["blue"].weights["Factory New"], 0.30)
        self.assertAlmostEqual(weights["blue"].weights["Field-Tested"], 0.70)
        self.assertAlmostEqual(weights["blue"].weights["Battle-Scarred"], 0.0)

    def test_thin_market_falls_back_to_uniform_and_says_so(self):
        case = example_case(blue=multi_wear_item("blue", "Mil-Spec Grade"))
        snapshot = self._snapshot_with_volumes(case, {"exact::blue::Factory New": 2})

        weights = wear_weights_for_case(case, snapshot)

        self.assertEqual(weights["blue"].basis, BASIS_UNIFORM_FALLBACK)
        self.assertTrue(weights["blue"].assumption)
        # Uniform over [0, 1] gives each grade its own interval width.
        self.assertAlmostEqual(weights["blue"].weights["Factory New"], 0.07)
        self.assertAlmostEqual(weights["blue"].weights["Battle-Scarred"], 0.55)

    def test_valuation_reports_probability_mass_per_wear_basis(self):
        case = example_case(blue=multi_wear_item("blue", "Mil-Spec Grade"))
        snapshot = self._snapshot_with_volumes(
            case,
            {
                "exact::blue::Factory New": 50,
                "exact::blue::Field-Tested": 50,
            },
        )
        weights = wear_weights_for_case(case, snapshot)
        variants = expand_case_variants(case, wear_weights=weights)
        valuation = value_case(
            case,
            variants,
            snapshot,
            key_price=2.0,
            key_price_source="explicit test fixture",
            sell_fee_rate=0.1,
        )

        basis = valuation.wear_basis_coverage
        # Only the Mil-Spec item had usable volume; it carries 79.923% of mass.
        self.assertAlmostEqual(basis[BASIS_OBSERVED_VOLUME], 0.79923)
        self.assertAlmostEqual(basis[BASIS_UNIFORM_FALLBACK], 1 - 0.79923)
        self.assertAlmostEqual(sum(basis.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
