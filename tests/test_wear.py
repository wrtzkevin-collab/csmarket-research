import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.wear import (  # noqa: E402
    CSFLOAT_EMPIRICAL_2020_MODEL,
    UNIFORM_ALLOWED_RANGE_MODEL,
    WEAR_INTERVALS,
    calculate_wear_probabilities,
)


class WearProbabilityTests(unittest.TestCase):
    def test_uniform_full_range_matches_market_interval_widths(self):
        result = calculate_wear_probabilities(
            0.0,
            1.0,
            model_id="uniform_allowed_range_v1",
        )

        self.assertEqual(result.model_id, "uniform_allowed_range_v1")
        self.assertTrue(result.assumption)
        self.assertEqual(
            result.source_url, UNIFORM_ALLOWED_RANGE_MODEL.source_url
        )
        self.assertEqual(
            tuple(result.probabilities),
            tuple(label for label, _, _ in WEAR_INTERVALS),
        )
        expected = {
            "Factory New": 0.07,
            "Minimal Wear": 0.08,
            "Field-Tested": 0.23,
            "Well-Worn": 0.07,
            "Battle-Scarred": 0.55,
        }
        for label, probability in expected.items():
            self.assertAlmostEqual(result.probabilities[label], probability)
        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0)

    def test_empirical_full_range_matches_published_bucket_weights(self):
        result = calculate_wear_probabilities(
            0.0,
            1.0,
            model_id="csfloat_empirical_2020_v1",
        )

        self.assertEqual(result.model_id, "csfloat_empirical_2020_v1")
        self.assertFalse(result.assumption)
        self.assertEqual(
            result.source_url, CSFLOAT_EMPIRICAL_2020_MODEL.source_url
        )
        expected = {
            "Factory New": 0.03,
            "Minimal Wear": 0.24,
            "Field-Tested": 0.33,
            "Well-Worn": 0.24,
            "Battle-Scarred": 0.16,
        }
        for label, probability in expected.items():
            self.assertAlmostEqual(result.probabilities[label], probability)
        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0)

    def test_uniform_model_integrates_over_final_capped_range(self):
        result = calculate_wear_probabilities(
            0.10,
            0.50,
            model_id="uniform_allowed_range_v1",
        )

        expected = {
            "Factory New": 0.0,
            "Minimal Wear": 0.125,
            "Field-Tested": 0.575,
            "Well-Worn": 0.175,
            "Battle-Scarred": 0.125,
        }
        for label, probability in expected.items():
            self.assertAlmostEqual(result.probabilities[label], probability)
        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0)

    def test_empirical_model_integrates_latent_density_for_capped_range(self):
        result = calculate_wear_probabilities(
            0.10,
            0.50,
            model_id="csfloat_empirical_2020_v1",
        )

        expected = {
            "Factory New": 0.0,
            "Minimal Wear": 0.195,
            "Field-Tested": 0.7177272727272728,
            "Well-Worn": 0.05090909090909091,
            "Battle-Scarred": 0.03636363636363636,
        }
        for label, probability in expected.items():
            self.assertAlmostEqual(result.probabilities[label], probability)
        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0)

    def test_ranges_confined_to_one_market_label_still_sum_to_one(self):
        for model_id in (
            "uniform_allowed_range_v1",
            "csfloat_empirical_2020_v1",
        ):
            with self.subTest(model_id=model_id):
                result = calculate_wear_probabilities(
                    0.20,
                    0.30,
                    model_id=model_id,
                )
                self.assertEqual(result.probabilities["Field-Tested"], 1.0)
                self.assertAlmostEqual(sum(result.probabilities.values()), 1.0)

    def test_invalid_float_ranges_are_rejected(self):
        invalid_ranges = (
            (-0.01, 0.50),
            (0.10, 1.01),
            (0.50, 0.50),
            (0.60, 0.50),
            (math.nan, 0.50),
            (0.10, math.inf),
        )
        for minimum, maximum in invalid_ranges:
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaises(ValueError):
                    calculate_wear_probabilities(
                        minimum,
                        maximum,
                        model_id="uniform_allowed_range_v1",
                    )

    def test_non_numeric_bounds_and_unknown_model_are_rejected(self):
        with self.assertRaises(TypeError):
            calculate_wear_probabilities(
                "0.1",  # type: ignore[arg-type]
                0.5,
                model_id="uniform_allowed_range_v1",
            )
        with self.assertRaisesRegex(ValueError, "unknown wear model"):
            calculate_wear_probabilities(0.1, 0.5, model_id="unknown")


if __name__ == "__main__":
    unittest.main()
