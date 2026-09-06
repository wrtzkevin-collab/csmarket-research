import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.probabilities import (  # noqa: E402
    STANDARD_CASE_RARITY_PROBABILITIES,
    allocate_equal_within_rarity,
    split_stattrak_probability,
)


class ProbabilityTests(unittest.TestCase):
    def test_official_standard_case_distribution_sums_to_one(self):
        self.assertAlmostEqual(sum(STANDARD_CASE_RARITY_PROBABILITIES.values()), 1.0)

    def test_equal_allocation_preserves_total_probability(self):
        groups = {
            rarity: [f"{rarity} A", f"{rarity} B"]
            for rarity in STANDARD_CASE_RARITY_PROBABILITIES
        }
        allocation = allocate_equal_within_rarity(groups)

        self.assertAlmostEqual(sum(allocation.values()), 1.0)
        self.assertEqual(
            allocation["Mil-Spec A"], allocation["Mil-Spec B"]
        )

    def test_missing_rarity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing rarity"):
            allocate_equal_within_rarity({"Mil-Spec": ["A"]})

    def test_stattrak_split_preserves_item_probability(self):
        normal, stattrak = split_stattrak_probability(0.2, eligible=True)
        self.assertAlmostEqual(normal, 0.18)
        self.assertAlmostEqual(stattrak, 0.02)
        self.assertAlmostEqual(normal + stattrak, 0.2)

    def test_ineligible_item_is_not_given_stattrak_mass(self):
        self.assertEqual(
            split_stattrak_probability(0.2, eligible=False), (0.2, 0.0)
        )


if __name__ == "__main__":
    unittest.main()

