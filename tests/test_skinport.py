from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from csmarket.data_sources.skinport import SkinportClient, SkinportDataError


NOW = datetime(2026, 9, 6, 12, 34, 56, tzinfo=timezone.utc)


def response_with(payload, *, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


class SkinportClientTests(unittest.TestCase):
    def make_client(self, session, **overrides):
        return SkinportClient(
            session=session,
            timeout=3.5,
            max_retries=2,
            backoff_factor=0,
            sleep=lambda _: None,
            clock=lambda: NOW,
            **overrides,
        )

    def test_fetch_items_sends_documented_request_and_normalizes_listing(self):
        session = Mock()
        session.get.return_value = response_with(
            [
                {
                    "market_hash_name": "Glove Case",
                    "currency": "USD",
                    "suggested_price": 11.2,
                    "min_price": 10.5,
                    "max_price": 12.0,
                    "mean_price": 10.9,
                    "median_price": 10.8,
                    "quantity": 42,
                    "updated_at": 1_725_590_400,
                }
            ]
        )

        rows = self.make_client(session).fetch_items(currency="usd", tradable=False)

        session.get.assert_called_once_with(
            "https://api.skinport.com/v1/items",
            params={"app_id": 730, "currency": "USD", "tradable": 0},
            headers={"Accept-Encoding": "br"},
            timeout=3.5,
        )
        # Listings and completed sales must not share a source name: rows are
        # cached and grouped by source, so sharing one would let a listing
        # overwrite a sale for the same item.
        self.assertEqual(rows[0]["source"], "skinport_listings")
        self.assertEqual(rows[0]["currency"], "USD")
        self.assertEqual(rows[0]["price"], 10.5)
        self.assertEqual(rows[0]["price_type"], "listing_min")
        self.assertEqual(rows[0]["observed_at"], "2026-09-06T12:34:56Z")
        self.assertEqual(rows[0]["quantity"], 42)
        self.assertEqual(rows[0]["source_updated_at"], "2024-09-06T02:40:00Z")

    def test_fetch_items_keeps_out_of_stock_price_as_missing(self):
        session = Mock()
        session.get.return_value = response_with(
            [{"market_hash_name": "Rare Item", "currency": "USD", "min_price": None}]
        )

        row = self.make_client(session).fetch_items()[0]

        self.assertIsNone(row["price"])

    def test_fetch_sales_history_joins_names_and_normalizes_selected_window(self):
        session = Mock()
        session.get.return_value = response_with(
            [
                {
                    "market_hash_name": "Glove Case",
                    "currency": "USD",
                    "last_7_days": {
                        "min": 9.0,
                        "max": 12.0,
                        "avg": 10.3,
                        "median": 10.1,
                        "volume": 730,
                    },
                    "last_30_days": {"median": 9.8, "volume": 2000},
                }
            ]
        )

        rows = self.make_client(session).fetch_sales_history(
            ["Glove Case", "AK-47 | Redline (Field-Tested)"],
            period="last_7_days",
            statistic="avg",
        )

        _, kwargs = session.get.call_args
        self.assertEqual(
            kwargs["params"]["market_hash_name"],
            "Glove Case,AK-47 | Redline (Field-Tested)",
        )
        self.assertEqual(rows[0]["price"], 10.3)
        self.assertEqual(rows[0]["price_type"], "sales_avg_7_days")
        self.assertEqual(rows[0]["volume"], 730)
        self.assertEqual(rows[0]["sales_period"], "last_7_days")
        self.assertIn("last_30_days", rows[0]["sales_windows"])

    def test_fetch_sales_history_without_names_requests_all_items(self):
        session = Mock()
        session.get.return_value = response_with([])

        self.make_client(session).fetch_sales_history()

        _, kwargs = session.get.call_args
        self.assertNotIn("market_hash_name", kwargs["params"])

    def test_fetch_sales_history_accepts_one_name_as_a_string(self):
        session = Mock()
        session.get.return_value = response_with([])

        self.make_client(session).fetch_sales_history("Glove Case")

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["market_hash_name"], "Glove Case")

    def test_retries_timeout_then_succeeds_with_bounded_attempts(self):
        session = Mock()
        session.get.side_effect = [
            requests.Timeout("slow"),
            response_with([]),
        ]

        rows = self.make_client(session).fetch_items()

        self.assertEqual(rows, [])
        self.assertEqual(session.get.call_count, 2)

    def test_retries_retryable_http_status_then_raises(self):
        session = Mock()
        session.get.side_effect = [response_with([], status=503) for _ in range(3)]

        with self.assertRaises(SkinportDataError):
            self.make_client(session).fetch_items()

        self.assertEqual(session.get.call_count, 3)

    def test_does_not_retry_client_error(self):
        session = Mock()
        session.get.return_value = response_with([], status=400)

        with self.assertRaises(SkinportDataError):
            self.make_client(session).fetch_items()

        self.assertEqual(session.get.call_count, 1)

    def test_rejects_invalid_json_shape(self):
        session = Mock()
        session.get.return_value = response_with({"error": "unexpected"})

        with self.assertRaises(SkinportDataError):
            self.make_client(session).fetch_items()

    def test_rejects_unknown_sales_window_before_http_call(self):
        session = Mock()

        with self.assertRaises(ValueError):
            self.make_client(session).fetch_sales_history(period="daily")

        session.get.assert_not_called()



class RateLimitTests(unittest.TestCase):
    """Skinport states how long its window lasts; the client must read it."""

    def _client(self, session, **kwargs):
        from datetime import datetime, timezone

        from csmarket.data_sources.skinport import SkinportClient

        kwargs.setdefault("max_retries", 2)
        return SkinportClient(
            session=session,
            sleep=lambda _: None,
            clock=lambda: datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
            **kwargs,
        )

    def _throttled(self, retry_after):
        response = Mock()
        response.status_code = 429
        response.headers = {"Retry-After": retry_after}
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        return response

    def test_a_long_window_is_reported_rather_than_slept_through(self):
        # 2869 seconds is what the live API returned. Sleeping looks like a
        # hang, and retrying inside the window only extends the block.
        session = Mock()
        session.get.return_value = self._throttled("2869")

        with self.assertRaises(SkinportDataError) as caught:
            self._client(session).fetch_items()

        message = str(caught.exception)
        self.assertIn("48 minutes", message)
        self.assertIn("10:47", message)
        self.assertEqual(session.get.call_count, 1)

    def test_a_short_window_is_waited_out(self):
        session = Mock()
        ok = Mock()
        ok.status_code = 200
        ok.raise_for_status.return_value = None
        ok.json.return_value = []
        session.get.side_effect = [self._throttled("3"), ok]
        slept = []

        client = self._client(session)
        client._sleep = slept.append
        client.fetch_items()

        self.assertEqual(slept, [3.0])

    def test_a_missing_header_falls_back_to_the_normal_backoff(self):
        session = Mock()
        response = Mock()
        response.status_code = 429
        response.headers = {}
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        session.get.return_value = response

        with self.assertRaisesRegex(SkinportDataError, "429"):
            self._client(session).fetch_items()

        self.assertEqual(session.get.call_count, 3)
if __name__ == "__main__":
    unittest.main()
