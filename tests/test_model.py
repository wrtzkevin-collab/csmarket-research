import math
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.model import Outcome, calculate_ev  # noqa: E402


class CalculateEVTests(unittest.TestCase):
    def test_complete_distribution_reports_gross_net_and_loss_metrics(self):
        result = calculate_ev(
            [
                Outcome(
                    name="common",
                    probability=0.75,
                    gross_value=2.0,
                    sell_fee_rate=0.10,
                ),
                Outcome(
                    name="rare",
                    probability=0.25,
                    gross_value=10.0,
                    sell_fee_rate=0.20,
                ),
            ],
            case_price=1.5,
            key_price=2.0,
            opening_fee=0.5,
        )

        self.assertAlmostEqual(result.gross_ev, 4.0)
        self.assertAlmostEqual(result.total_cost, 4.0)
        self.assertAlmostEqual(result.gross_return_ratio, 1.0)
        self.assertAlmostEqual(result.net_ev, 3.35)
        self.assertAlmostEqual(result.expected_net_roi, -0.1625)
        self.assertAlmostEqual(result.loss_probability, 0.75)
        self.assertAlmostEqual(result.probability_coverage, 1.0)

    def test_missing_price_reduces_coverage_without_renormalizing_ev(self):
        result = calculate_ev(
            [
                Outcome(name="priced", probability=0.6, gross_value=5.0),
                Outcome(name="missing", probability=0.4, gross_value=None),
            ],
            case_price=2.0,
        )

        self.assertAlmostEqual(result.probability_coverage, 0.6)
        self.assertAlmostEqual(result.gross_ev, 3.0)
        self.assertAlmostEqual(result.net_ev, 3.0)
        self.assertAlmostEqual(result.gross_return_ratio, 1.5)
        self.assertAlmostEqual(result.expected_net_roi, 0.5)
        self.assertAlmostEqual(result.loss_probability, 0.0)

    def test_missing_price_is_not_assumed_to_be_a_loss(self):
        result = calculate_ev(
            [
                Outcome(name="known loss", probability=0.3, gross_value=1.0),
                Outcome(name="unknown", probability=0.7, gross_value=None),
            ],
            case_price=2.0,
        )

        self.assertAlmostEqual(result.loss_probability, 0.3)
        self.assertAlmostEqual(result.probability_coverage, 0.3)

    def test_probability_sum_accepts_small_floating_point_tolerance(self):
        result = calculate_ev(
            [
                Outcome(name="a", probability=0.7999995, gross_value=1.0),
                Outcome(name="b", probability=0.2, gross_value=2.0),
            ],
            case_price=1.0,
        )

        self.assertAlmostEqual(result.probability_coverage, 0.9999995)

    def test_probability_sum_outside_tolerance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "probabilities must sum to 1"):
            calculate_ev(
                [Outcome(name="incomplete", probability=0.9, gross_value=1.0)],
                case_price=1.0,
            )

    def test_invalid_outcome_values_are_rejected(self):
        invalid_arguments = (
            {"name": "", "probability": 1.0, "gross_value": 1.0},
            {"name": "x", "probability": -0.1, "gross_value": 1.0},
            {"name": "x", "probability": 1.1, "gross_value": 1.0},
            {"name": "x", "probability": math.nan, "gross_value": 1.0},
            {"name": "x", "probability": 1.0, "gross_value": -1.0},
            {
                "name": "x",
                "probability": 1.0,
                "gross_value": 1.0,
                "sell_fee_rate": 1.01,
            },
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    Outcome(**arguments)

    def test_invalid_costs_and_empty_outcomes_are_rejected(self):
        outcome = Outcome(name="only", probability=1.0, gross_value=1.0)

        with self.assertRaisesRegex(ValueError, "total_cost"):
            calculate_ev([outcome], case_price=0.0)
        with self.assertRaisesRegex(ValueError, "case_price"):
            calculate_ev([outcome], case_price=-1.0)
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            calculate_ev([], case_price=1.0)


if __name__ == "__main__":
    unittest.main()
