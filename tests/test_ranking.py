import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.data_sources.steam import SteamDataError  # noqa: E402
from csmarket.ranking import rank_cases, top_case_names  # noqa: E402


def row(name, *, price=0.20, listings=None, volume=None):
    return {
        "market_hash_name": name,
        "price": price,
        "listings": listings,
        "volume": volume,
        "median_price": None,
        "source": "steam_community_market",
        "currency": "USD",
        "price_type": "lowest_listing",
        "observed_at": "2026-09-07T12:00:00Z",
    }


def catalog_with(names):
    catalog = Mock()
    catalog.case_names.return_value = tuple(names)
    return catalog


class RankCasesTests(unittest.TestCase):
    def rank(self, facet_rows, names, **kwargs):
        search = Mock()
        search.fetch_type.return_value = facet_rows
        with patch("csmarket.ranking.SteamSearchClient", return_value=search):
            ranked = rank_cases(catalog_with(names), cache=None, **kwargs)
        return ranked, search

    def test_busiest_case_ranks_first(self):
        names = ["Quiet Case", "Busy Case", "Middling Case"]
        facet = [
            row("Quiet Case", listings=12),
            row("Busy Case", listings=757_550),
            row("Middling Case", listings=4_000),
        ]

        ranked, _ = self.rank(facet, names)

        self.assertEqual(
            [entry["case_name"] for entry in ranked],
            ["Busy Case", "Middling Case", "Quiet Case"],
        )
        self.assertEqual([entry["rank"] for entry in ranked], [1, 2, 3])

    def test_containers_that_are_not_cases_are_ignored(self):
        # The facet also holds capsules and souvenir packages; only the
        # catalogue decides what counts as a case.
        names = ["Real Case"]
        facet = [
            row("Sticker Capsule", listings=900_000),
            row("Real Case", listings=10),
        ]

        ranked, _ = self.rank(facet, names)

        self.assertEqual([entry["case_name"] for entry in ranked], ["Real Case"])

    def test_a_case_the_facet_never_returned_still_appears_last(self):
        names = ["Present Case", "Absent Case"]
        facet = [row("Present Case", listings=10)]

        ranked, _ = self.rank(facet, names)

        self.assertEqual(
            [entry["case_name"] for entry in ranked], ["Present Case", "Absent Case"]
        )
        absent = ranked[-1]
        self.assertIsNone(absent["listings"])
        self.assertIsNone(absent["price"])

    def test_ties_break_by_name_so_the_order_is_stable(self):
        names = ["B Case", "A Case"]
        facet = [row("B Case", listings=7), row("A Case", listings=7)]

        ranked, _ = self.rank(facet, names)

        self.assertEqual([entry["case_name"] for entry in ranked], ["A Case", "B Case"])

    def test_explicit_names_override_the_catalogue(self):
        facet = [row("Only Case", listings=1)]
        search = Mock()
        search.fetch_type.return_value = facet
        with patch("csmarket.ranking.SteamSearchClient", return_value=search):
            ranked = rank_cases(
                catalog_with(["Ignored Case"]), cache=None, names=["Only Case"]
            )

        self.assertEqual([entry["case_name"] for entry in ranked], ["Only Case"])

    def test_empty_catalogue_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_cases(catalog_with([]), cache=None)

    def test_no_volume_probe_by_default(self):
        facet = [row("Busy Case", listings=5)]
        with patch("csmarket.ranking.fetch_rows") as fetch:
            ranked, _ = self.rank(facet, ["Busy Case"])

        fetch.assert_not_called()
        self.assertIsNone(ranked[0]["volume_24h"])


class VolumeProbeTests(unittest.TestCase):
    def probe(self, side_effect, *, limit=1):
        search = Mock()
        search.fetch_type.return_value = [
            row("Busy Case", listings=900),
            row("Quiet Case", listings=5),
        ]
        with patch("csmarket.ranking.SteamSearchClient", return_value=search):
            with patch("csmarket.ranking.fetch_rows", side_effect=side_effect) as fetch:
                ranked = rank_cases(
                    catalog_with(["Busy Case", "Quiet Case"]),
                    cache=None,
                    volume_probe=limit,
                )
        return ranked, fetch

    def test_probe_fills_volume_for_the_top_entries_only(self):
        ranked, fetch = self.probe(
            lambda *args, **kwargs: [row("Busy Case", volume=91_521)]
        )

        self.assertEqual(ranked[0]["volume_24h"], 91_521)
        self.assertIsNone(ranked[1]["volume_24h"])
        self.assertEqual(fetch.call_args.args[1], ["Busy Case"])

    def test_a_blocked_probe_leaves_the_ranking_intact(self):
        # The ranking is already computed; a refusal on the expensive endpoint
        # must not throw it away.
        ranked, _ = self.probe(SteamDataError("HTTP 429"))

        self.assertEqual([entry["case_name"] for entry in ranked], ["Busy Case", "Quiet Case"])
        self.assertIsNone(ranked[0]["volume_24h"])


class TopCaseNameTests(unittest.TestCase):
    def test_returns_names_in_rank_order(self):
        ranked = [
            {"case_name": "First"},
            {"case_name": "Second"},
            {"case_name": "Third"},
        ]

        self.assertEqual(top_case_names(ranked, 2), ("First", "Second"))

    def test_limit_beyond_the_list_returns_everything(self):
        self.assertEqual(top_case_names([{"case_name": "Only"}], 9), ("Only",))

    def test_limit_must_be_positive(self):
        with self.assertRaises(ValueError):
            top_case_names([{"case_name": "Only"}], 0)


if __name__ == "__main__":
    unittest.main()
