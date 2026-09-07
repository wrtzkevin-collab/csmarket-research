"""Rank cases by how much they actually trade.

Valuing every case is expensive and most of the answers are uninteresting: a
case nobody opens is a curiosity, while the handful that trade in the tens of
thousands per day are the ones a person is realistically about to open. Ranking
by observed volume puts the useful cases first and makes a partial run -- the
top few rather than all forty-odd -- a deliberate choice rather than an
arbitrary truncation.

Volume here is the case's own 24-hour sales count, which is a measure of market
activity, not of whether opening it is a good idea. Every case loses money in
expectation; this only decides which losses are worth publishing.
"""

from __future__ import annotations

from typing import Any, Sequence

from .cache import PriceCache
from .catalog import CaseCatalogClient
from .sources import SOURCE_STEAM, ProgressCallback, fetch_rows


def rank_cases(
    catalog: CaseCatalogClient,
    *,
    currency: str = "USD",
    cache: PriceCache | None = None,
    refresh: bool = False,
    timeout: float = 20.0,
    retries: int = 3,
    request_interval: float = 5.0,
    progress: ProgressCallback | None = None,
    names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return every case ordered by observed 24-hour sales volume, busiest first.

    Cases without a reported volume sort last rather than being dropped: an
    absent measurement is not the same as zero activity, and hiding them would
    silently shorten the catalogue.
    """

    case_names = tuple(names) if names is not None else catalog.case_names()
    if not case_names:
        raise ValueError("the catalogue reported no cases")

    rows = fetch_rows(
        SOURCE_STEAM,
        case_names,
        currency=currency,
        cache=cache,
        refresh=refresh,
        timeout=timeout,
        retries=retries,
        request_interval=request_interval,
        progress=progress,
    )
    by_name = {row["market_hash_name"]: row for row in rows}

    ranked = [
        {
            "case_name": name,
            "price": (by_name.get(name) or {}).get("price"),
            "volume_24h": (by_name.get(name) or {}).get("volume"),
            "listings": (by_name.get(name) or {}).get("listings"),
            "currency": currency.upper(),
            "observed_at": (by_name.get(name) or {}).get("observed_at"),
        }
        for name in case_names
    ]
    ranked.sort(
        key=lambda entry: (
            entry["volume_24h"] is None,
            -(entry["volume_24h"] or 0),
            entry["case_name"],
        )
    )
    for position, entry in enumerate(ranked, start=1):
        entry["rank"] = position
    return ranked


def top_case_names(ranked: Sequence[dict[str, Any]], limit: int) -> tuple[str, ...]:
    """Names of the busiest ``limit`` cases, in rank order."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    return tuple(entry["case_name"] for entry in ranked[:limit])
