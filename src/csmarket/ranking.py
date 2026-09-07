"""Rank cases by how much of them is on the market.

Valuing all forty-odd cases is expensive and most of the answers are
uninteresting: a case nobody opens is a curiosity, while the few that trade in
the hundreds of thousands are the ones someone is actually about to open.
Ranking first puts the useful cases at the front and makes a partial run -- the
busiest few rather than everything -- a deliberate choice rather than an
arbitrary truncation.

The ranking signal is the number of cases resting on the market, read from the
container facet sorted server-side. It is a popularity proxy, not turnover:
24-hour sales volume would describe activity more directly, but it is only
available one request per case from an endpoint that rate-limits hard, and a
ranking that cannot be computed is worth less than a good proxy that can.
``volume_probe`` spends a few of those expensive requests on the top of the
list when the exact figure is wanted.

None of this says whether opening a case is a good idea. Every case loses money
in expectation; this only decides which losses are worth publishing.
"""

from __future__ import annotations

from typing import Any, Sequence

from .cache import PriceCache
from .catalog import CaseCatalogClient
from .data_sources.steam import SteamDataError, SteamSearchClient
from .sources import SOURCE_STEAM, ProgressCallback, fetch_rows

# Steam's market type facet for containers.  It holds capsules and souvenir
# packages too, so results are intersected with the catalogue's own case list.
CONTAINER_TYPE_TAG = "tag_CSGO_Type_WeaponCase"

# Sorted by quantity descending, the busiest cases arrive in the first pages;
# this bounds the crawl for the long tail of containers that are not cases.
DEFAULT_MAX_PAGES = 30


def rank_cases(
    catalog: CaseCatalogClient,
    *,
    currency: str = "USD",
    cache: PriceCache | None = None,
    refresh: bool = False,
    timeout: float = 20.0,
    retries: int = 3,
    request_interval: float = 5.0,
    max_pages: int = DEFAULT_MAX_PAGES,
    volume_probe: int = 0,
    progress: ProgressCallback | None = None,
    names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the catalogue's cases ordered by resting listings, busiest first.

    Cases the facet never returned sort last rather than being dropped: an
    absent measurement is not the same as no activity, and hiding them would
    silently shorten the catalogue.
    """

    case_names = tuple(names) if names is not None else catalog.case_names()
    if not case_names:
        raise ValueError("the catalogue reported no cases")
    wanted = set(case_names)

    search = SteamSearchClient(
        timeout=timeout, max_retries=retries, request_interval=2.0
    )
    rows = search.fetch_type(
        CONTAINER_TYPE_TAG,
        currency=currency,
        max_pages=max_pages,
        progress=progress,
    )
    by_name = {
        row["market_hash_name"]: row
        for row in rows
        if row["market_hash_name"] in wanted
    }
    if cache is not None and by_name:
        cache.put_many(by_name.values())
        cache.save()

    ranked = [
        {
            "case_name": name,
            "price": (by_name.get(name) or {}).get("price"),
            "listings": (by_name.get(name) or {}).get("listings"),
            "volume_24h": None,
            "currency": currency.upper(),
            "observed_at": (by_name.get(name) or {}).get("observed_at"),
        }
        for name in case_names
    ]
    ranked.sort(
        key=lambda entry: (
            entry["listings"] is None,
            -(entry["listings"] or 0),
            entry["case_name"],
        )
    )
    for position, entry in enumerate(ranked, start=1):
        entry["rank"] = position

    if volume_probe > 0:
        _probe_volumes(
            ranked[:volume_probe],
            currency=currency,
            cache=cache,
            refresh=refresh,
            timeout=timeout,
            retries=retries,
            request_interval=request_interval,
            progress=progress,
        )
    return ranked


def _probe_volumes(
    entries: Sequence[dict[str, Any]],
    *,
    currency: str,
    cache: PriceCache | None,
    refresh: bool,
    timeout: float,
    retries: int,
    request_interval: float,
    progress: ProgressCallback | None,
) -> None:
    """Fill in 24-hour sales volume for a few entries, tolerating a block.

    This is the expensive endpoint, so a refusal leaves ``volume_24h`` as None
    instead of failing the ranking that was already computed.
    """

    if not entries:
        return
    try:
        rows = fetch_rows(
            SOURCE_STEAM,
            [entry["case_name"] for entry in entries],
            currency=currency,
            cache=cache,
            refresh=refresh,
            timeout=timeout,
            retries=retries,
            request_interval=request_interval,
            progress=progress,
        )
    except SteamDataError:
        return
    volumes = {
        row["market_hash_name"]: row.get("volume")
        for row in rows
        if row.get("volume") is not None
    }
    for entry in entries:
        if entry["case_name"] in volumes:
            entry["volume_24h"] = volumes[entry["case_name"]]


def top_case_names(ranked: Sequence[dict[str, Any]], limit: int) -> tuple[str, ...]:
    """Names of the busiest ``limit`` cases, in rank order."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    return tuple(entry["case_name"] for entry in ranked[:limit])
