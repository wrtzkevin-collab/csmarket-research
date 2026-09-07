import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import requests


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.data_sources.steam import (  # noqa: E402
    SteamDataError,
    SteamMarketClient,
    parse_money,
)


FIXED_TIME = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)


def response(payload=None, *, status=200, text=""):
    mock = Mock()
    mock.status_code = status
    mock.text = text
    if payload is None:
        mock.json.side_effect = ValueError("no json")
    else:
        mock.json.return_value = payload
    if status >= 400:
        error = requests.HTTPError(response=mock)
        mock.raise_for_status.side_effect = error
    else:
        mock.raise_for_status.return_value = None
    return mock


def client(session, **kwargs):
    kwargs.setdefault("request_interval", 0)
    kwargs.setdefault("backoff_factor", 0)
    return SteamMarketClient(
        session=session, sleep=lambda _: None, clock=lambda: FIXED_TIME, **kwargs
    )


class ParseMoneyTests(unittest.TestCase):
    def test_parses_common_formats(self):
        self.assertAlmostEqual(parse_money("$0.19"), 0.19)
        self.assertAlmostEqual(parse_money("$1,234.56"), 1234.56)
        self.assertAlmostEqual(parse_money("1.234,56 EUR"), 1234.56)
        self.assertAlmostEqual(parse_money("R$ 12,34"), 12.34)
        self.assertAlmostEqual(parse_money("12"), 12.0)

    def test_thousands_without_decimals_are_not_split(self):
        # A three-digit group after the separator is grouping, not cents.
        self.assertAlmostEqual(parse_money("$1,234"), 1234.0)
        self.assertAlmostEqual(parse_money("1.234"), 1234.0)

    def test_missing_or_unparsable_values_are_none(self):
        self.assertIsNone(parse_money(None))
        self.assertIsNone(parse_money(""))
        self.assertIsNone(parse_money("n/a"))
        self.assertIsNone(parse_money(["$1.00"]))


class SteamMarketClientTests(unittest.TestCase):
    def test_normalizes_a_full_response(self):
        session = Mock()
        session.get.return_value = response(
            {
                "success": True,
                "lowest_price": "$0.19",
                "volume": "91,521",
                "median_price": "$0.20",
            }
        )

        row = client(session).fetch_price("Kilowatt Case")

        self.assertEqual(row["market_hash_name"], "Kilowatt Case")
        self.assertAlmostEqual(row["price"], 0.19)
        self.assertAlmostEqual(row["median_price"], 0.20)
        self.assertEqual(row["volume"], 91521)
        self.assertEqual(row["source"], "steam_community_market")
        self.assertEqual(row["price_type"], "lowest_listing")
        self.assertEqual(row["currency"], "USD")
        self.assertEqual(row["observed_at"], "2026-09-07T12:00:00Z")

    def test_illiquid_item_keeps_its_ask_without_sale_statistics(self):
        # Steam omits volume and median for items with no sale in 24 hours.
        # That is exactly the rare-special tail, so the ask must still be used.
        session = Mock()
        session.get.return_value = response(
            {"success": True, "lowest_price": "$692.71"}
        )

        row = client(session).fetch_price("Kukri Knife")

        self.assertAlmostEqual(row["price"], 692.71)
        self.assertIsNone(row["median_price"])
        self.assertIsNone(row["volume"])

    def test_unsuccessful_response_yields_a_missing_price_not_an_error(self):
        session = Mock()
        session.get.return_value = response({"success": False})

        row = client(session).fetch_price("Nonexistent Item")

        self.assertIsNone(row["price"])
        self.assertIsNone(row["volume"])

    def test_rate_limit_is_retried_then_surfaced(self):
        session = Mock()
        session.get.return_value = response(status=429)

        with self.assertRaisesRegex(SteamDataError, "429"):
            client(session, max_retries=2).fetch_price("Kilowatt Case")

        self.assertEqual(session.get.call_count, 3)

    def test_rate_limit_recovers_when_a_retry_succeeds(self):
        session = Mock()
        session.get.side_effect = [
            response(status=429),
            response({"success": True, "lowest_price": "$1.00"}),
        ]

        row = client(session, max_retries=2).fetch_price("Kilowatt Case")

        self.assertAlmostEqual(row["price"], 1.0)
        self.assertEqual(session.get.call_count, 2)

    def test_rate_limit_waits_far_longer_than_a_transient_error(self):
        # A 429 means a sustained-rate window is exhausted, which takes about a
        # minute to clear.  Retrying after a couple of seconds just burns the
        # remaining budget and gets the crawl blocked again.
        session = Mock()
        session.get.side_effect = [
            response(status=429),
            response(status=503),
            response(status=429),
        ]
        slept = []

        steam = SteamMarketClient(
            session=session,
            sleep=slept.append,
            clock=lambda: FIXED_TIME,
            request_interval=0,
            max_retries=2,
            backoff_factor=2.0,
            rate_limit_backoff=60.0,
        )
        with self.assertRaises(SteamDataError):
            steam.fetch_price("Kilowatt Case")

        self.assertEqual(slept, [60.0, 4.0])

    def test_retry_after_header_overrides_the_guess(self):
        session = Mock()
        throttled = response(status=429)
        throttled.headers = {"Retry-After": "12"}
        session.get.side_effect = [
            throttled,
            response({"success": True, "lowest_price": "$1.00"}),
        ]
        slept = []

        steam = SteamMarketClient(
            session=session,
            sleep=slept.append,
            clock=lambda: FIXED_TIME,
            request_interval=0,
            rate_limit_backoff=60.0,
        )
        row = steam.fetch_price("Kilowatt Case")

        self.assertEqual(slept, [12.0])
        self.assertAlmostEqual(row["price"], 1.0)

    def test_rate_limit_error_explains_how_to_recover(self):
        session = Mock()
        session.get.return_value = response(status=429)

        with self.assertRaisesRegex(SteamDataError, "request-interval"):
            client(session, max_retries=0).fetch_price("Kilowatt Case")

    def test_non_json_body_is_reported_with_context(self):
        session = Mock()
        session.get.return_value = response(text="<html>maintenance</html>")

        with self.assertRaisesRegex(SteamDataError, "non-JSON"):
            client(session).fetch_price("Kilowatt Case")

    def test_currency_is_translated_to_steam_codes(self):
        session = Mock()
        session.get.return_value = response({"success": True, "lowest_price": "1,00€"})

        client(session).fetch_price("Kilowatt Case", currency="EUR")

        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["currency"], 3)
        self.assertEqual(params["appid"], 730)

    def test_unknown_currency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported currency"):
            client(Mock()).fetch_price("Kilowatt Case", currency="XYZ")

    def test_fetch_prices_deduplicates_and_reports_progress(self):
        session = Mock()
        session.get.return_value = response({"success": True, "lowest_price": "$1.00"})
        seen = []

        rows = client(session).fetch_prices(
            ["A", "B", "A"], progress=lambda i, total, name: seen.append((i, total))
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(seen, [(1, 2), (2, 2)])

    def test_throttle_waits_between_requests(self):
        session = Mock()
        session.get.return_value = response({"success": True, "lowest_price": "$1.00"})
        slept = []
        ticks = iter([0.0, 0.0, 0.5, 0.5])

        steam = SteamMarketClient(
            session=session,
            request_interval=3.0,
            sleep=slept.append,
            monotonic=lambda: next(ticks),
            clock=lambda: FIXED_TIME,
        )
        steam.fetch_price("A")
        steam.fetch_price("B")

        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 2.5)


if __name__ == "__main__":
    unittest.main()
