import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.cli import build_parser  # noqa: E402


class CliTests(unittest.TestCase):
    def test_live_analysis_defaults_to_a_cross_venue_comparison(self):
        args = build_parser().parse_args(["analyze-case", "Kilowatt Case"])

        self.assertEqual(args.source, "both")
        self.assertEqual(args.case_names, ["Kilowatt Case"])
        self.assertEqual(args.currency, "USD")
        self.assertIsNone(args.export_web)

    def test_several_cases_can_be_valued_in_one_run(self):
        args = build_parser().parse_args(
            ["analyze-case", "Kilowatt Case", "Revolution Case"]
        )

        self.assertEqual(args.case_names, ["Kilowatt Case", "Revolution Case"])

    def test_caching_is_on_by_default_and_can_be_disabled(self):
        default = build_parser().parse_args(["analyze-case", "Kilowatt Case"])
        self.assertFalse(default.no_cache)
        self.assertFalse(default.refresh)
        self.assertEqual(default.max_age_hours, 6.0)

        disabled = build_parser().parse_args(
            ["analyze-case", "Kilowatt Case", "--no-cache"]
        )
        self.assertTrue(disabled.no_cache)

    def test_export_web_flag_has_a_default_destination(self):
        args = build_parser().parse_args(
            ["analyze-case", "Kilowatt Case", "--export-web"]
        )

        self.assertEqual(args.export_web, "web/results.json")

    def test_export_web_accepts_an_explicit_path(self):
        args = build_parser().parse_args(
            ["analyze-case", "Kilowatt Case", "--export-web", "out/data.json"]
        )

        self.assertEqual(args.export_web, "out/data.json")

    def test_request_interval_defaults_below_the_observed_rate_limit(self):
        args = build_parser().parse_args(["analyze-case", "Kilowatt Case"])

        self.assertGreaterEqual(args.request_interval, 3.0)

    def test_price_command_defaults_to_steam(self):
        args = build_parser().parse_args(["price", "Kilowatt Case"])

        self.assertEqual(args.source, "steam")
        self.assertEqual(args.names, ["Kilowatt Case"])

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                ["analyze-case", "Kilowatt Case", "--source", "buff163"]
            )


if __name__ == "__main__":
    unittest.main()
