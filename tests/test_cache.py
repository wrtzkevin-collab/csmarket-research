import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.cache import PriceCache, parse_iso8601  # noqa: E402


NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)


def row(name="Kilowatt Case", *, observed_at="2026-09-07T11:00:00Z", price=0.22):
    return {
        "market_hash_name": name,
        "price": price,
        "source": "steam_community_market",
        "currency": "USD",
        "price_type": "lowest_listing",
        "observed_at": observed_at,
        "volume": 100,
    }


class ParseIsoTests(unittest.TestCase):
    def test_accepts_zulu_and_offset_forms(self):
        self.assertEqual(
            parse_iso8601("2026-09-07T12:00:00Z"),
            parse_iso8601("2026-09-07T14:00:00+02:00"),
        )

    def test_naive_timestamps_are_assumed_utc(self):
        self.assertEqual(
            parse_iso8601("2026-09-07T12:00:00"), parse_iso8601("2026-09-07T12:00:00Z")
        )

    def test_empty_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_iso8601("")


class PriceCacheTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "nested" / "cache.json"
        self.addCleanup(self._dir.cleanup)

    def cache(self, **kwargs):
        kwargs.setdefault("max_age", timedelta(hours=24))
        return PriceCache(self.path, clock=lambda: NOW, **kwargs)

    def test_round_trip_through_disk(self):
        first = self.cache()
        first.put(row())
        first.save()

        second = self.cache()
        stored = second.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case")

        self.assertIsNotNone(stored)
        self.assertAlmostEqual(stored["price"], 0.22)
        self.assertEqual(len(second), 1)

    def test_entries_are_scoped_by_source_and_currency(self):
        cache = self.cache()
        cache.put(row())

        self.assertIsNone(cache.get("skinport", "lowest_listing", "USD", "Kilowatt Case"))
        self.assertIsNone(cache.get("steam_community_market", "lowest_listing", "EUR", "Kilowatt Case"))
        self.assertIsNotNone(cache.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case"))

    def test_stale_entries_are_reported_as_missing(self):
        cache = self.cache()
        cache.put(row(observed_at="2026-09-05T11:00:00Z"))

        self.assertIsNone(cache.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case"))

    def test_max_age_none_keeps_everything(self):
        cache = self.cache(max_age=None)
        cache.put(row(observed_at="2020-01-01T00:00:00Z"))

        self.assertIsNotNone(cache.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case"))

    def test_cached_rows_keep_their_original_observation_time(self):
        cache = self.cache()
        cache.put(row(observed_at="2026-09-07T11:00:00Z"))
        stored = cache.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case")

        self.assertEqual(stored["observed_at"], "2026-09-07T11:00:00Z")

    def test_mutating_a_returned_row_does_not_change_the_cache(self):
        cache = self.cache()
        cache.put(row())
        stored = cache.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case")
        stored["price"] = 999.0

        again = cache.get("steam_community_market", "lowest_listing", "USD", "Kilowatt Case")
        self.assertAlmostEqual(again["price"], 0.22)

    def test_corrupt_cache_file_is_ignored_rather_than_fatal(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")

        cache = self.cache()

        self.assertEqual(len(cache), 0)
        cache.put(row())
        cache.save()
        self.assertEqual(len(self.cache()), 1)

    def test_rows_without_identity_are_rejected(self):
        cache = self.cache()
        broken = row()
        del broken["source"]
        with self.assertRaises(ValueError):
            cache.put(broken)

    def test_save_is_atomic_and_leaves_no_temporary_files(self):
        cache = self.cache()
        cache.put_many([row("A"), row("B")])
        cache.save()

        leftovers = [p.name for p in self.path.parent.iterdir() if p != self.path]
        self.assertEqual(leftovers, [])



class RetentionMatchesSnapshotSpanTests(unittest.TestCase):
    def test_default_retention_equals_the_maximum_snapshot_span(self):
        # Retaining observations longer than a snapshot may span guarantees
        # that some later run assembles prices too far apart and is refused.
        from csmarket.cache import DEFAULT_MAX_AGE_HOURS
        from csmarket.pipeline import DEFAULT_MAX_OBSERVATION_DRIFT_SECONDS

        self.assertEqual(
            DEFAULT_MAX_AGE_HOURS * 3600, DEFAULT_MAX_OBSERVATION_DRIFT_SECONDS
        )



class PriceTypeScopingTests(unittest.TestCase):
    """Two windows of the same item are two observations, not one."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "cache.json"

    def cache(self):
        return PriceCache(self.path, max_age=timedelta(hours=24), clock=lambda: NOW)

    def test_windows_do_not_overwrite_each_other(self):
        # Asking for a ninety-day median once silently returned the thirty-day
        # figure cached earlier, and the two exports stopped agreeing.
        cache = self.cache()
        thirty = row(price=1.0)
        thirty["price_type"] = "sales_median_30_days"
        ninety = row(price=2.0)
        ninety["price_type"] = "sales_median_90_days"
        cache.put(thirty)
        cache.put(ninety)

        self.assertEqual(len(cache), 2)
        self.assertAlmostEqual(
            cache.get("steam_community_market", "sales_median_30_days", "USD",
                      "Kilowatt Case")["price"],
            1.0,
        )
        self.assertAlmostEqual(
            cache.get("steam_community_market", "sales_median_90_days", "USD",
                      "Kilowatt Case")["price"],
            2.0,
        )

    def test_a_row_without_a_price_type_is_rejected(self):
        cache = self.cache()
        broken = row()
        del broken["price_type"]
        with self.assertRaises(ValueError):
            cache.put(broken)
if __name__ == "__main__":
    unittest.main()
