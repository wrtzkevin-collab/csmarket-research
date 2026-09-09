import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from unittest.mock import Mock, patch  # noqa: E402

from csmarket.cli import build_parser  # noqa: E402


class CliTests(unittest.TestCase):
    def test_live_analysis_defaults_to_a_cross_venue_comparison(self):
        args = build_parser().parse_args(["analyze-case", "Kilowatt Case"])

        self.assertEqual(args.source, "fast")
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

    def test_sales_window_defaults_to_ninety_days(self):
        # A sale price exists only for what traded inside the window, and the
        # rare tail that drives a case's value trades rarely. Ninety days took
        # average coverage from 95.5% to 99.1%.
        args = build_parser().parse_args(["analyze-case", "Kilowatt Case"])

        self.assertEqual(args.period, "last_90_days")

    def test_source_choices_expand_to_venues(self):
        from csmarket.cli import _selected_sources

        # The default avoids Steam: both fast venues answer in one request each,
        # while Steam needs tens and throttles hard.
        self.assertEqual(
            _selected_sources("fast"), ["skinport-listings", "skinport"]
        )
        self.assertIn("steam", _selected_sources("all"))
        self.assertEqual(_selected_sources("steam"), ["steam"])

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                ["analyze-case", "Kilowatt Case", "--source", "buff163"]
            )



class PartialRunTests(unittest.TestCase):
    """A case that cannot be priced must not discard the ones that could."""

    def _args(self, **overrides):
        args = build_parser().parse_args(
            ["analyze-case", "Good Case", "Bad Case", "--no-cache"]
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_a_failing_case_is_skipped_and_the_rest_are_kept(self):
        import csmarket.cli as cli

        def value(case_name, *rest):
            if case_name == "Bad Case":
                raise RuntimeError("8 lookups in a row were refused")
            valuation = Mock()
            valuation.to_dict.return_value = {"case_name": case_name}
            return [valuation]

        with patch.object(cli, "_value_one_case", side_effect=value):
            with patch.object(cli, "CaseCatalogClient"):
                with patch.object(cli, "_print_json") as printed:
                    exit_code = cli._run_analyze_case(self._args())

        self.assertEqual(exit_code, 0)
        payload = printed.call_args.args[0]
        self.assertEqual(payload, {"case_name": "Good Case"})

    def test_every_case_failing_is_still_an_error(self):
        import csmarket.cli as cli

        with patch.object(
            cli, "_value_one_case", side_effect=RuntimeError("refused")
        ):
            with patch.object(cli, "CaseCatalogClient"):
                with self.assertRaisesRegex(ValueError, "no case could be valued"):
                    cli._run_analyze_case(self._args())
if __name__ == "__main__":
    unittest.main()


class KeyPriceCurrencyTests(unittest.TestCase):
    """The key price is a bare constant, so its currency must be checked."""

    def _args(self, **overrides):
        args = build_parser().parse_args(["analyze-case", "Kilowatt Case"])
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_matching_currency_is_accepted(self):
        from csmarket.cli import _check_key_price_currency

        _check_key_price_currency(self._args(currency="USD"))
        _check_key_price_currency(
            self._args(currency="cny", key_price_currency="CNY")
        )

    def test_mismatched_currency_is_refused_rather_than_silently_wrong(self):
        # Charging a 2.49 USD key against CNY item prices turned a 60% expected
        # loss into an apparent profit on every case in a run.
        from csmarket.cli import _check_key_price_currency

        with self.assertRaisesRegex(ValueError, "will not invent an exchange rate"):
            _check_key_price_currency(self._args(currency="CNY"))

    def test_the_refusal_names_the_flags_that_fix_it(self):
        from csmarket.cli import _check_key_price_currency

        with self.assertRaises(ValueError) as caught:
            _check_key_price_currency(self._args(currency="EUR"))

        message = str(caught.exception)
        self.assertIn("--key-price", message)
        self.assertIn("--key-price-currency EUR", message)
if __name__ == "__main__":
    unittest.main()
