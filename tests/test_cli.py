import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.cli import build_parser  # noqa: E402


class CliTests(unittest.TestCase):
    def test_live_analysis_defaults_to_same_snapshot_model_comparison(self):
        args = build_parser().parse_args(["analyze-case", "Kilowatt Case"])

        self.assertEqual(args.wear_model, "both")
        self.assertEqual(args.period, "last_30_days")
        self.assertEqual(args.statistic, "median")
        self.assertEqual(args.currency, "USD")


if __name__ == "__main__":
    unittest.main()

