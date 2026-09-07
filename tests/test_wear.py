import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.wear import (  # noqa: E402
    BASIS_OBSERVED_VOLUME,
    BASIS_UNIFORM_FALLBACK,
    calculate_wear_weights,
    reachable_wears,
    uniform_wear_weights,
)


class UniformWearWeightTests(unittest.TestCase):
    def test_full_range_matches_the_market_interval_widths(self):
        weights = uniform_wear_weights(0.0, 1.0)

        self.assertAlmostEqual(weights["Factory New"], 0.07)
        self.assertAlmostEqual(weights["Minimal Wear"], 0.08)
        self.assertAlmostEqual(weights["Field-Tested"], 0.23)
        self.assertAlmostEqual(weights["Well-Worn"], 0.07)
        self.assertAlmostEqual(weights["Battle-Scarred"], 0.55)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_restricted_range_gives_unreachable_grades_exactly_zero(self):
        weights = uniform_wear_weights(0.10, 0.20)

        self.assertEqual(weights["Factory New"], 0.0)
        self.assertEqual(weights["Well-Worn"], 0.0)
        self.assertEqual(weights["Battle-Scarred"], 0.0)
        self.assertAlmostEqual(weights["Minimal Wear"], 0.5)
        self.assertAlmostEqual(weights["Field-Tested"], 0.5)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_reachable_wears_lists_only_non_zero_grades(self):
        self.assertEqual(
            reachable_wears(0.10, 0.20), ("Minimal Wear", "Field-Tested")
        )

    def test_invalid_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            uniform_wear_weights(0.5, 0.5)
        with self.assertRaises(ValueError):
            uniform_wear_weights(-0.1, 0.5)
        with self.assertRaises(ValueError):
            uniform_wear_weights(0.2, 1.5)
        with self.assertRaises(TypeError):
            uniform_wear_weights("0.2", 0.5)


class ObservedVolumeWeightTests(unittest.TestCase):
    def test_liquid_market_is_weighted_by_observed_volume(self):
        result = calculate_wear_weights(
            0.0,
            1.0,
            volumes={
                "Factory New": 10,
                "Minimal Wear": 20,
                "Field-Tested": 40,
                "Well-Worn": 10,
                "Battle-Scarred": 20,
            },
        )

        self.assertEqual(result.basis, BASIS_OBSERVED_VOLUME)
        self.assertFalse(result.assumption)
        self.assertEqual(result.observed_volume, 100)
        self.assertAlmostEqual(result.weights["Field-Tested"], 0.40)
        self.assertAlmostEqual(sum(result.weights.values()), 1.0)

    def test_volume_on_an_unreachable_grade_is_ignored(self):
        # A 0.10-0.20 float can never produce Factory New, so an observation
        # on that listing must not leak probability into it.
        result = calculate_wear_weights(
            0.10,
            0.20,
            volumes={
                "Factory New": 1000,
                "Minimal Wear": 30,
                "Field-Tested": 70,
            },
        )

        self.assertEqual(result.basis, BASIS_OBSERVED_VOLUME)
        self.assertEqual(result.observed_volume, 100)
        self.assertEqual(result.weights["Factory New"], 0.0)
        self.assertAlmostEqual(result.weights["Minimal Wear"], 0.30)
        self.assertAlmostEqual(result.weights["Field-Tested"], 0.70)

    def test_thin_market_falls_back_to_uniform(self):
        result = calculate_wear_weights(
            0.0, 1.0, volumes={"Factory New": 3, "Field-Tested": 4}
        )

        self.assertEqual(result.basis, BASIS_UNIFORM_FALLBACK)
        self.assertTrue(result.assumption)
        self.assertEqual(result.observed_volume, 7)
        self.assertAlmostEqual(result.weights["Battle-Scarred"], 0.55)

    def test_absent_volumes_fall_back_without_error(self):
        result = calculate_wear_weights(0.0, 1.0, volumes=None)

        self.assertEqual(result.basis, BASIS_UNIFORM_FALLBACK)
        self.assertIsNone(result.observed_volume)
        self.assertAlmostEqual(sum(result.weights.values()), 1.0)

    def test_none_volumes_are_treated_as_unobserved_not_zero(self):
        result = calculate_wear_weights(
            0.0,
            1.0,
            volumes={"Factory New": None, "Field-Tested": 50},
            min_total_volume=20,
        )

        self.assertEqual(result.basis, BASIS_OBSERVED_VOLUME)
        self.assertEqual(result.observed_volume, 50)
        self.assertAlmostEqual(result.weights["Field-Tested"], 1.0)

    def test_threshold_is_configurable(self):
        volumes = {"Factory New": 3, "Field-Tested": 4}
        self.assertEqual(
            calculate_wear_weights(
                0.0, 1.0, volumes=volumes, min_total_volume=5
            ).basis,
            BASIS_OBSERVED_VOLUME,
        )
        with self.assertRaises(ValueError):
            calculate_wear_weights(0.0, 1.0, volumes=volumes, min_total_volume=0)

    def test_negative_volume_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_wear_weights(0.0, 1.0, volumes={"Field-Tested": -1})


if __name__ == "__main__":
    unittest.main()
