import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from csmarket.ranking import rank_cases, top_case_names  # noqa: E402


def row(name, *, price=0.20, volume=None):
    return {
        "market_hash_name": name,
        "price": price,
        "volume": volume,
        "listings": None,
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
    def rank(self, rows, names):
        with patch("csmarket.ranking.fetch_rows", return_value=rows) as fetch:
            ranked = rank_cases(catalog_with(names), cache=None)
        return ranked, fetch

    def test_busiest_case_ranks_first(self):
        names = ["Quiet Case", "Busy Case", "Middling Case"]
        rows = [
            row("Quiet Case", volume=12),
            row("Busy Case", volume=90_000),
            row("Middling Case", volume=4_000),
        ]

        ranked, _ = self.rank(rows, names)

        self.assertEqual(
            [entry["case_name"] for entry in ranked],
            ["Busy Case", "Middling Case", "Quiet Case"],
        )
        self.assertEqual([entry["rank"] for entry in ranked], [1, 2, 3])

    def test_cases_without_a_volume_sort_last_but_are_not_dropped(self):
        # No reported volume means "not measured", which is not the same as no
        # activity; dropping them would silently shorten the catalogue.
        names = ["Unmeasured Case", "Busy Case"]
        rows = [row("Unmeasured Case", volume=None), row("Busy Case", volume=500)]

        ranked, _ = self.rank(rows, names)

        self.assertEqual(
            [entry["case_name"] for entry in ranked], ["Busy Case", "Unmeasured Case"]
        )
        self.assertIsNone(ranked[-1]["volume_24h"])
        self.assertEqual(len(ranked), 2)

    def test_ties_break_by_name_so_the_order_is_stable(self):
        names = ["B Case", "A Case"]
        rows = [row("B Case", volume=7), row("A Case", volume=7)]

        ranked, _ = self.rank(rows, names)

        self.assertEqual([entry["case_name"] for entry in ranked], ["A Case", "B Case"])

    def test_a_case_missing_from_the_response_still_appears(self):
        names = ["Present Case", "Absent Case"]
        rows = [row("Present Case", volume=10)]

        ranked, _ = self.rank(rows, names)

        absent = [e for e in ranked if e["case_name"] == "Absent Case"][0]
        self.assertIsNone(absent["price"])
        self.assertIsNone(absent["volume_24h"])

    def test_explicit_names_override_the_catalogue(self):
        rows = [row("Only Case", volume=1)]
        with patch("csmarket.ranking.fetch_rows", return_value=rows):
            ranked = rank_cases(
                catalog_with(["Ignored Case"]), cache=None, names=["Only Case"]
            )

        self.assertEqual([entry["case_name"] for entry in ranked], ["Only Case"])

    def test_empty_catalogue_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_cases(catalog_with([]), cache=None)


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
