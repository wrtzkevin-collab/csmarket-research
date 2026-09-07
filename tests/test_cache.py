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
        stored = second.get("steam_community_market", "USD", "Kilowatt Case")

        self.assertIsNotNone(stored)
        self.assertAlmostEqual(stored["price"], 0.22)
        self.assertEqual(len(second), 1)

    def test_entries_are_scoped_by_source_and_currency(self):
        cache = self.cache()
        cache.put(row())

        self.assertIsNone(cache.get("skinport", "USD", "Kilowatt Case"))
        self.assertIsNone(cache.get("steam_community_market", "EUR", "Kilowatt Case"))
        self.assertIsNotNone(cache.get("steam_community_market", "USD", "Kilowatt Case"))

    def test_stale_entries_are_reported_as_missing(self):
        cache = self.cache()
        cache.put(row(observed_at="2026-09-05T11:00:00Z"))

        self.assertIsNone(cache.get("steam_community_market", "USD", "Kilowatt Case"))

    def test_max_age_none_keeps_everything(self):
        cache = self.cache(max_age=None)
        cache.put(row(observed_at="2020-01-01T00:00:00Z"))

        self.assertIsNotNone(cache.get("steam_community_market", "USD", "Kilowatt Case"))

    def test_cached_rows_keep_their_original_observation_time(self):
        cache = self.cache()
        cache.put(row(observed_at="2026-09-07T11:00:00Z"))
        stored = cache.get("steam_community_market", "USD", "Kilowatt Case")

        self.assertEqual(stored["observed_at"], "2026-09-07T11:00:00Z")

    def test_mutating_a_returned_row_does_not_change_the_cache(self):
        cache = self.cache()
        cache.put(row())
        stored = cache.get("steam_community_market", "USD", "Kilowatt Case")
        stored["price"] = 999.0

        again = cache.get("steam_community_market", "USD", "Kilowatt Case")
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


if __name__ == "__main__":
    unittest.main()
