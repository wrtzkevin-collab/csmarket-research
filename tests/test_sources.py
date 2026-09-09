import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.cache import PriceCache  # noqa: E402
from csmarket.sources import (  # noqa: E402
    SOURCE_SKINPORT,
    SOURCE_STEAM,
    build_cache,
    fetch_rows,
    source_provider_name,
)


NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
OBSERVED = "2026-09-07T11:30:00Z"


def steam_row(name):
    return {
        "market_hash_name": name,
        "price": 1.0,
        "median_price": None,
        "volume": None,
        "source": "steam_community_market",
        "currency": "USD",
        "price_type": "lowest_listing",
        "observed_at": OBSERVED,
    }


def skinport_row(name):
    return {
        "market_hash_name": name,
        "price": 2.0,
        "source": "skinport",
        "currency": "USD",
        "price_type": "sales_median_90_days",
        "observed_at": OBSERVED,
        "volume": 5,
    }


class SourceNameTests(unittest.TestCase):
    def test_ids_map_to_provider_names(self):
        self.assertEqual(source_provider_name(SOURCE_STEAM), "steam_community_market")
        self.assertEqual(source_provider_name(SOURCE_SKINPORT), "skinport")

    def test_unknown_id_is_rejected(self):
        with self.assertRaises(ValueError):
            source_provider_name("buff163")


class CachedFetchTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "cache.json"

    def cache(self, hours=24):
        return PriceCache(self.path, max_age=timedelta(hours=hours), clock=lambda: NOW)

    def test_steam_only_fetches_names_missing_from_the_cache(self):
        cache = self.cache()
        cache.put(steam_row("A"))

        client = Mock()
        client.fetch_price.side_effect = lambda name, currency="USD": steam_row(name)
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            rows = fetch_rows(SOURCE_STEAM, ["A", "B"], cache=cache)

        self.assertEqual([row["market_hash_name"] for row in rows], ["A", "B"])
        client.fetch_price.assert_called_once_with("B", currency="USD")

    def test_refresh_bypasses_the_cache(self):
        cache = self.cache()
        cache.put(steam_row("A"))

        client = Mock()
        client.fetch_price.side_effect = lambda name, currency="USD": steam_row(name)
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            fetch_rows(SOURCE_STEAM, ["A"], cache=cache, refresh=True)

        client.fetch_price.assert_called_once()

    def test_progress_counts_only_the_work_actually_done(self):
        # Cached names cost nothing, so counting them would show a crawl racing
        # through items it never fetched and then stalling on the real work.
        cache = self.cache()
        cache.put(steam_row("A"))
        seen = []

        client = Mock()
        client.fetch_price.side_effect = lambda name, currency="USD": steam_row(name)
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            fetch_rows(
                SOURCE_STEAM,
                ["A", "B"],
                cache=cache,
                progress=lambda i, total, name: seen.append((i, total)),
            )

        self.assertEqual(seen, [(1, 1)])

    def test_rows_come_back_in_the_requested_order(self):
        cache = self.cache()
        cache.put(steam_row("B"))

        client = Mock()
        client.fetch_price.side_effect = lambda name, currency="USD": steam_row(name)
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            rows = fetch_rows(SOURCE_STEAM, ["A", "B", "C"], cache=cache)

        self.assertEqual([row["market_hash_name"] for row in rows], ["A", "B", "C"])

    def test_skinport_bulk_pull_is_cached_despite_an_uncacheable_tail(self):
        # Items with no recent sale are absent from Skinport's response, so a
        # "were all names cached" test could never pass and every run would
        # re-fetch.  A fresh bulk-pull marker must serve the request instead.
        cache = self.cache()
        client = Mock()
        client.fetch_sales_history.return_value = [skinport_row("A")]

        with patch("csmarket.sources.SkinportClient", return_value=client):
            first = fetch_rows(
                SOURCE_SKINPORT, ["A", "missing-tail-item"], cache=cache
            )
            second = fetch_rows(
                SOURCE_SKINPORT, ["A", "missing-tail-item"], cache=cache
            )

        client.fetch_sales_history.assert_called_once()
        self.assertEqual([row["market_hash_name"] for row in first], ["A"])
        self.assertEqual([row["market_hash_name"] for row in second], ["A"])

    def test_stale_bulk_marker_triggers_a_new_pull(self):
        cache = PriceCache(
            self.path, max_age=timedelta(minutes=5), clock=lambda: NOW
        )
        client = Mock()
        client.fetch_sales_history.return_value = [skinport_row("A")]

        with patch("csmarket.sources.SkinportClient", return_value=client):
            fetch_rows(SOURCE_SKINPORT, ["A"], cache=cache)
            fetch_rows(SOURCE_SKINPORT, ["A"], cache=cache)

        # The marker is stamped from the observation, which is 30 minutes old.
        self.assertEqual(client.fetch_sales_history.call_count, 2)

    def test_bulk_marker_never_reaches_the_returned_rows(self):
        cache = self.cache()
        client = Mock()
        client.fetch_sales_history.return_value = [skinport_row("A")]

        with patch("csmarket.sources.SkinportClient", return_value=client):
            fetch_rows(SOURCE_SKINPORT, ["A"], cache=cache)
            rows = fetch_rows(SOURCE_SKINPORT, ["A"], cache=cache)

        self.assertTrue(
            all(not row["market_hash_name"].startswith("__") for row in rows)
        )

    def test_no_cache_disables_persistence_entirely(self):
        client = Mock()
        client.fetch_price.side_effect = lambda name, currency="USD": steam_row(name)
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            fetch_rows(SOURCE_STEAM, ["A"], cache=None)

        self.assertFalse(self.path.exists())

    def test_empty_name_list_is_rejected(self):
        with self.assertRaises(ValueError):
            fetch_rows(SOURCE_STEAM, [], cache=None)

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError):
            fetch_rows("buff163", ["A"], cache=None)


class BuildCacheTests(unittest.TestCase):
    def test_none_path_disables_caching(self):
        self.assertIsNone(build_cache(None, max_age_hours=24))

    def test_none_max_age_keeps_entries_forever(self):
        cache = build_cache("cache.json", max_age_hours=None)
        self.assertIsNone(cache.max_age)



class ThrottledLookupTests(unittest.TestCase):
    """A block is not an observation, and must not be recorded as one."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "cache.json"

    def cache(self):
        return PriceCache(self.path, max_age=timedelta(hours=24), clock=lambda: NOW)

    def test_a_blocked_lookup_is_left_unmeasured_not_recorded_as_absent(self):
        from csmarket.data_sources.steam import SteamDataError

        cache = self.cache()
        client = Mock()
        client.fetch_price.side_effect = [
            SteamDataError("HTTP 429"),
            steam_row("B"),
        ]
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            rows = fetch_rows(SOURCE_STEAM, ["A", "B"], cache=cache)

        # "A" is absent from the result entirely; it is not a row saying the
        # market has no price, because we never got to ask the market.
        self.assertEqual([row["market_hash_name"] for row in rows], ["B"])
        self.assertIsNone(cache.get("steam_community_market", "lowest_listing", "USD", "A"))

    def test_a_blocked_lookup_is_retried_by_the_next_run(self):
        from csmarket.data_sources.steam import SteamDataError

        cache = self.cache()
        client = Mock()
        client.fetch_price.side_effect = [SteamDataError("HTTP 429"), steam_row("A")]
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            first = fetch_rows(SOURCE_STEAM, ["A"], cache=cache)
            second = fetch_rows(SOURCE_STEAM, ["A"], cache=cache)

        self.assertEqual(first, [])
        self.assertEqual([row["market_hash_name"] for row in second], ["A"])

    def test_an_unbroken_wall_of_blocks_stops_the_run(self):
        # Tolerating blocks forever would publish a snapshot that describes our
        # access to Steam rather than the market.
        from csmarket.data_sources.steam import SteamDataError

        client = Mock()
        client.fetch_price.side_effect = SteamDataError("HTTP 429")
        names = [f"Item {index}" for index in range(20)]

        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            with self.assertRaisesRegex(SteamDataError, "in a row were refused"):
                fetch_rows(SOURCE_STEAM, names, cache=None)

        self.assertEqual(client.fetch_price.call_count, 8)

    def test_intermittent_blocks_do_not_trip_the_wall_check(self):
        from csmarket.data_sources.steam import SteamDataError

        client = Mock()
        client.fetch_price.side_effect = [
            SteamDataError("HTTP 429"),
            steam_row("B"),
            SteamDataError("HTTP 429"),
            steam_row("D"),
        ]
        with patch("csmarket.sources.SteamMarketClient", return_value=client):
            rows = fetch_rows(SOURCE_STEAM, ["A", "B", "C", "D"], cache=None)

        self.assertEqual([row["market_hash_name"] for row in rows], ["B", "D"])



class BlockedBulkPageTests(unittest.TestCase):
    """A refused bulk page must not discard a warm cache or earlier pages."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "cache.json"

    def cache(self):
        return PriceCache(self.path, max_age=timedelta(hours=24), clock=lambda: NOW)

    def test_a_blocked_search_keeps_the_cached_rows(self):
        from csmarket.data_sources.steam import SteamDataError

        cache = self.cache()
        cache.put(steam_row("A"))
        search = Mock()
        search.fetch_item_set.side_effect = SteamDataError("HTTP 429")
        client = Mock()
        client.fetch_price.side_effect = SteamDataError("HTTP 429")

        with patch("csmarket.sources.SteamSearchClient", return_value=search):
            with patch("csmarket.sources.SteamMarketClient", return_value=client):
                rows = fetch_rows(
                    SOURCE_STEAM,
                    ["A", "B"],
                    cache=cache,
                    collection_tags=["tag_set_community_33"],
                )

        self.assertEqual([row["market_hash_name"] for row in rows], ["A"])

    def test_pages_that_arrived_before_the_block_are_kept(self):
        from csmarket.data_sources.steam import SteamDataError

        search = Mock()
        search.fetch_item_set.return_value = [steam_row("A")]
        search.search.side_effect = SteamDataError("HTTP 429")
        client = Mock()
        client.fetch_price.side_effect = SteamDataError("HTTP 429")

        with patch("csmarket.sources.SteamSearchClient", return_value=search):
            with patch("csmarket.sources.SteamMarketClient", return_value=client):
                rows = fetch_rows(
                    SOURCE_STEAM,
                    ["A", "B"],
                    cache=None,
                    collection_tags=["tag_set_community_33"],
                    search_queries=["Kukri Knife"],
                )

        self.assertEqual([row["market_hash_name"] for row in rows], ["A"])
if __name__ == "__main__":
    unittest.main()


class SkinportBulkScopeTests(unittest.TestCase):
    """The bulk marker claims the whole market, so the whole market is stored."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "cache.json"

    def cache(self):
        return PriceCache(self.path, max_age=timedelta(hours=6), clock=lambda: NOW)

    def test_a_later_case_is_served_from_the_same_bulk_pull(self):
        # One response covers every case. Caching only the first caller's names
        # left the marker asserting freshness over rows that were never stored,
        # so the second case found an empty "fresh" cache and had no prices.
        cache = self.cache()
        client = Mock()
        client.fetch_sales_history.return_value = [
            skinport_row("Case One Item"),
            skinport_row("Case Two Item"),
        ]

        with patch("csmarket.sources.SkinportClient", return_value=client):
            first = fetch_rows(SOURCE_SKINPORT, ["Case One Item"], cache=cache)
            second = fetch_rows(SOURCE_SKINPORT, ["Case Two Item"], cache=cache)

        client.fetch_sales_history.assert_called_once()
        self.assertEqual([r["market_hash_name"] for r in first], ["Case One Item"])
        self.assertEqual([r["market_hash_name"] for r in second], ["Case Two Item"])
if __name__ == "__main__":
    unittest.main()


class RefreshScopeTests(unittest.TestCase):
    """--refresh means one fresh pull per run, not one per case."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "cache.json"
        import csmarket.sources as sources

        sources._REFRESHED_THIS_PROCESS.clear()
        self.addCleanup(sources._REFRESHED_THIS_PROCESS.clear)

    def cache(self):
        return PriceCache(self.path, max_age=timedelta(hours=6), clock=lambda: NOW)

    def test_refresh_pulls_once_and_serves_later_cases_from_it(self):
        # Valuing forty cases with --refresh re-downloaded the whole market
        # forty times and got the address rate-limited by the provider.
        cache = self.cache()
        client = Mock()
        client.fetch_sales_history.return_value = [
            skinport_row("Case One Item"),
            skinport_row("Case Two Item"),
        ]

        with patch("csmarket.sources.SkinportClient", return_value=client):
            fetch_rows(
                SOURCE_SKINPORT, ["Case One Item"], cache=cache, refresh=True
            )
            second = fetch_rows(
                SOURCE_SKINPORT, ["Case Two Item"], cache=cache, refresh=True
            )

        client.fetch_sales_history.assert_called_once()
        self.assertEqual([r["market_hash_name"] for r in second], ["Case Two Item"])
if __name__ == "__main__":
    unittest.main()
