"""Provider selection and cached snapshot retrieval.

Two venues answer different questions and the project deliberately keeps both.
Steam lists every tradable variant, including the illiquid rare specials that
decide a case's expected value, but its balance cannot be withdrawn as cash.
Skinport pays out real money but has no recent sale for much of the tail.  A
report that shows only one of them is either complete or cashable, never both,
so the CLI fetches each as its own snapshot and reports them side by side.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence

from .cache import PriceCache
from .data_sources import SkinportClient, SteamMarketClient
from .data_sources.skinport import LISTINGS_SOURCE_NAME, SALES_SOURCE_NAME
from .data_sources.steam import SteamDataError
from .data_sources.steam import SOURCE_NAME as STEAM_SOURCE_NAME
from .data_sources.steam import SteamSearchClient

SOURCE_STEAM = "steam"
SOURCE_SKINPORT = "skinport"
SOURCE_SKINPORT_LISTINGS = "skinport-listings"
SOURCE_IDS: tuple[str, ...] = (
    SOURCE_SKINPORT_LISTINGS,
    SOURCE_SKINPORT,
    SOURCE_STEAM,
)

# The two venues reachable in a single request each.  Steam needs tens of
# requests and throttles hard, so it is opt-in rather than part of the default.
FAST_SOURCE_IDS: tuple[str, ...] = (SOURCE_SKINPORT_LISTINGS, SOURCE_SKINPORT)

SKINPORT_SOURCE_NAME = SALES_SOURCE_NAME
SKINPORT_LISTINGS_SOURCE_NAME = LISTINGS_SOURCE_NAME

# Reserved cache key recording when the last whole-market pull happened.
# It is never a real market name, so it can never reach a snapshot.
_BULK_MARKER_NAME = "__skinport_bulk_pull__"

# Steam is crawled one name at a time, so an interrupted run would otherwise
# throw away every request made so far.
_CACHE_FLUSH_INTERVAL = 25

# One blocked lookup is tolerable and shows up as missing coverage.  A run
# where they never stop is not a thin market, it is a wall, and continuing
# would publish a snapshot describing our access rather than the market.
_MAX_CONSECUTIVE_BLOCKS = 8

# Bulk endpoints return the whole market, so one pull serves every case in a
# run.  --refresh means "do not trust yesterday's snapshot", not "re-pull per
# case": valuing forty cases used to re-download the market forty times and
# got the address rate-limited.  A pull already made by this process is fresh
# by definition.
_REFRESHED_THIS_PROCESS: set[tuple[str, str]] = set()

ProgressCallback = Callable[[int, int, str], None]


def source_provider_name(source_id: str) -> str:
    """Map a CLI source id to the ``source`` value that appears in rows."""

    if source_id == SOURCE_STEAM:
        return STEAM_SOURCE_NAME
    if source_id == SOURCE_SKINPORT:
        return SKINPORT_SOURCE_NAME
    if source_id == SOURCE_SKINPORT_LISTINGS:
        return SKINPORT_LISTINGS_SOURCE_NAME
    raise ValueError(f"unknown source {source_id!r}; expected one of {SOURCE_IDS}")


def fetch_rows(
    source_id: str,
    market_hash_names: Iterable[str],
    *,
    currency: str = "USD",
    cache: PriceCache | None = None,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
    timeout: float = 20.0,
    retries: int = 3,
    request_interval: float = 5.0,
    period: str = "last_30_days",
    statistic: str = "median",
    collection_tags: Sequence[str] = (),
    search_queries: Sequence[str] = (),
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Return normalized rows for ``market_hash_names`` from one provider.

    With ``offline`` set, only observations already in the cache are returned
    and no provider is contacted.  Names the cache does not hold come back
    missing, which flows through to the coverage figure exactly as an
    unpriced item does -- a report built this way is still made only of real
    measurements, just fewer of them.
    """

    names: Sequence[str] = tuple(dict.fromkeys(market_hash_names))
    if not names:
        raise ValueError("market_hash_names must not be empty")

    if source_id == SOURCE_STEAM:
        return _fetch_steam_rows(
            names,
            currency=currency,
            cache=cache,
            refresh=refresh,
            progress=progress,
            timeout=timeout,
            retries=retries,
            request_interval=request_interval,
            collection_tags=collection_tags,
            search_queries=search_queries,
            offline=offline,
        )
    if source_id in (SOURCE_SKINPORT, SOURCE_SKINPORT_LISTINGS):
        return _fetch_skinport_rows(
            names,
            currency=currency,
            cache=cache,
            refresh=refresh,
            progress=progress,
            timeout=timeout,
            retries=retries,
            period=period,
            statistic=statistic,
            offline=offline,
            listings=source_id == SOURCE_SKINPORT_LISTINGS,
        )
    raise ValueError(f"unknown source {source_id!r}; expected one of {SOURCE_IDS}")


def _fetch_steam_rows(
    names: Sequence[str],
    *,
    currency: str,
    cache: PriceCache | None,
    refresh: bool,
    progress: ProgressCallback | None,
    timeout: float,
    retries: int,
    request_interval: float,
    collection_tags: Sequence[str] = (),
    search_queries: Sequence[str] = (),
    offline: bool = False,
) -> list[dict[str, Any]]:
    wanted = set(names)
    found: dict[str, dict[str, Any]] = {}

    if cache is not None and not refresh:
        for name in names:
            row = cache.get(STEAM_SOURCE_NAME, currency, name)
            if row is not None:
                found[name] = row

    if offline:
        return [found[name] for name in names if name in found]

    # Bulk pages first: ten priced rows per request against an endpoint that
    # does not throttle the way priceoverview does.  Only what the pages miss
    # falls through to the one-request-per-item path.
    if (collection_tags or search_queries) and len(found) < len(wanted):
        search = SteamSearchClient(
            timeout=timeout, max_retries=retries, request_interval=2.0
        )
        harvested: list[dict[str, Any]] = []
        # A refused bulk page is not a reason to discard a warm cache or the
        # pages that did come back.  Whatever was harvested is kept, the
        # per-item path picks up the remainder, and the coverage figure shows
        # honestly how much of the case went unmeasured.
        try:
            for tag in collection_tags:
                harvested.extend(
                    search.fetch_item_set(tag, currency=currency, progress=progress)
                )
            for query in search_queries:
                covered = set(found) | {row["market_hash_name"] for row in harvested}
                if wanted <= covered:
                    break
                harvested.extend(
                    search.search(query, currency=currency, progress=progress)
                )
        except SteamDataError:
            pass
        useful = [row for row in harvested if row["market_hash_name"] in wanted]
        if cache is not None and useful:
            cache.put_many(useful)
            cache.save()
        for row in useful:
            found.setdefault(row["market_hash_name"], row)

    missing = [name for name in names if name not in found]
    if missing:
        client = SteamMarketClient(
            timeout=timeout, max_retries=retries, request_interval=request_interval
        )
        fetched_since_flush = 0
        blocked_run = 0
        for index, name in enumerate(missing, start=1):
            try:
                row = client.fetch_price(name, currency=currency)
            except SteamDataError as error:
                # Being throttled is not the same as the market having no price,
                # so the item is left unmeasured rather than recorded as absent,
                # and deliberately not cached: a later run must retry it instead
                # of inheriting a block frozen in as an observation.
                blocked_run += 1
                if progress is not None:
                    progress(index, len(missing), f"blocked {name}")
                if blocked_run >= _MAX_CONSECUTIVE_BLOCKS:
                    raise SteamDataError(
                        f"{blocked_run} lookups in a row were refused by Steam "
                        f"({error}); stopping rather than reporting a snapshot "
                        "made mostly of blocked lookups"
                    ) from error
                continue
            blocked_run = 0
            found[name] = row
            if cache is not None:
                cache.put(row)
                fetched_since_flush += 1
                if fetched_since_flush >= _CACHE_FLUSH_INTERVAL:
                    cache.save()
                    fetched_since_flush = 0
            if progress is not None:
                progress(index, len(missing), f"fallback {name}")
        if cache is not None and fetched_since_flush:
            cache.save()

    return [found[name] for name in names if name in found]


def _fetch_skinport_rows(
    names: Sequence[str],
    *,
    currency: str,
    cache: PriceCache | None,
    refresh: bool,
    progress: ProgressCallback | None,
    timeout: float,
    retries: int,
    period: str,
    statistic: str,
    offline: bool = False,
    listings: bool = False,
) -> list[dict[str, Any]]:
    wanted = set(names)
    provider = SKINPORT_LISTINGS_SOURCE_NAME if listings else SKINPORT_SOURCE_NAME
    marker_name = f"{_BULK_MARKER_NAME}{'listings' if listings else 'sales'}"

    if offline:
        if cache is None:
            return []
        return [
            row
            for row in (cache.get(provider, currency, name) for name in names)
            if row is not None
        ]

    # Skinport answers with the whole market in one response, and items with no
    # recent sale are simply absent from it.  Deciding freshness by "are all
    # requested names cached" would therefore never be satisfied -- the missing
    # tail is exactly what cannot be cached -- and every run would re-fetch.
    # A marker row records when the bulk pull happened instead, so a fresh pull
    # serves whatever it contained and absent names stay correctly absent.
    already_pulled = (provider, currency.upper()) in _REFRESHED_THIS_PROCESS
    if cache is not None and (not refresh or already_pulled):
        marker = cache.get(provider, currency, marker_name)
        if marker is not None:
            rows = []
            for name in names:
                row = cache.get(provider, currency, name)
                if row is not None:
                    rows.append(row)
            if progress is not None:
                for index, name in enumerate(names, start=1):
                    progress(index, len(names), name)
            return rows

    client = SkinportClient(timeout=timeout, max_retries=retries)
    fetched = (
        client.fetch_items(currency=currency)
        if listings
        else client.fetch_sales_history(
            currency=currency, period=period, statistic=statistic
        )
    )
    _REFRESHED_THIS_PROCESS.add((provider, currency.upper()))
    rows = [row for row in fetched if row.get("market_hash_name") in wanted]
    if cache is not None:
        # The whole market arrives in one response and the marker below claims
        # exactly that, so all of it is stored.  Caching only the names this
        # call happened to want would leave the marker lying to the next case,
        # which would then find a "fresh" cache holding nothing it needs.
        cache.put_many(fetched)
        cache.put(
            {
                "market_hash_name": marker_name,
                "price": None,
                "source": provider,
                "currency": currency.upper(),
                "price_type": "bulk-pull marker",
                "observed_at": _bulk_marker_time(fetched),
            }
        )
        cache.save()
    if progress is not None:
        for index, name in enumerate(names, start=1):
            progress(index, len(names), name)
    return rows


def _bulk_marker_time(rows: Sequence[dict[str, Any]]) -> str:
    """Timestamp the marker from the pull itself, never from the local clock."""

    for row in rows:
        observed_at = row.get("observed_at")
        if isinstance(observed_at, str) and observed_at.strip():
            return observed_at
    return (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


def build_cache(
    path: str | None, *, max_age_hours: float | None
) -> PriceCache | None:
    """Create a cache, or ``None`` when caching is disabled."""

    if path is None:
        return None
    max_age = None if max_age_hours is None else timedelta(hours=max_age_hours)
    return PriceCache(path, max_age=max_age)
