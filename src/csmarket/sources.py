"""Provider selection and cached snapshot retrieval.

Two venues answer different questions and the project deliberately keeps both.
Steam lists every tradable variant, including the illiquid rare specials that
decide a case's expected value, but its balance cannot be withdrawn as cash.
Skinport pays out real money but has no recent sale for much of the tail.  A
report that shows only one of them is either complete or cashable, never both,
so the CLI fetches each as its own snapshot and reports them side by side.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, Iterable, Sequence

from .cache import PriceCache
from .data_sources import SkinportClient, SteamMarketClient
from .data_sources.steam import SOURCE_NAME as STEAM_SOURCE_NAME

SOURCE_STEAM = "steam"
SOURCE_SKINPORT = "skinport"
SOURCE_IDS: tuple[str, ...] = (SOURCE_STEAM, SOURCE_SKINPORT)

SKINPORT_SOURCE_NAME = "skinport"

# Steam is crawled one name at a time, so an interrupted run would otherwise
# throw away every request made so far.
_CACHE_FLUSH_INTERVAL = 25

ProgressCallback = Callable[[int, int, str], None]


def source_provider_name(source_id: str) -> str:
    """Map a CLI source id to the ``source`` value that appears in rows."""

    if source_id == SOURCE_STEAM:
        return STEAM_SOURCE_NAME
    if source_id == SOURCE_SKINPORT:
        return SKINPORT_SOURCE_NAME
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
) -> list[dict[str, Any]]:
    """Return normalized rows for ``market_hash_names`` from one provider."""

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
        )
    if source_id == SOURCE_SKINPORT:
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
) -> list[dict[str, Any]]:
    client = SteamMarketClient(
        timeout=timeout, max_retries=retries, request_interval=request_interval
    )
    rows: list[dict[str, Any]] = []
    fetched_since_flush = 0
    total = len(names)
    for index, name in enumerate(names, start=1):
        row = None
        if cache is not None and not refresh:
            row = cache.get(STEAM_SOURCE_NAME, currency, name)
        if row is None:
            row = client.fetch_price(name, currency=currency)
            if cache is not None:
                cache.put(row)
                fetched_since_flush += 1
                if fetched_since_flush >= _CACHE_FLUSH_INTERVAL:
                    cache.save()
                    fetched_since_flush = 0
        rows.append(row)
        if progress is not None:
            progress(index, total, name)
    if cache is not None and fetched_since_flush:
        cache.save()
    return rows


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
) -> list[dict[str, Any]]:
    wanted = set(names)
    cached: dict[str, dict[str, Any]] = {}
    if cache is not None and not refresh:
        for name in names:
            row = cache.get(SKINPORT_SOURCE_NAME, currency, name)
            if row is not None:
                cached[name] = row

    # Skinport answers with the whole market in one response, so a partial cache
    # hit saves nothing.  Re-fetch unless every requested name is already held.
    if len(cached) == len(wanted):
        rows = [cached[name] for name in names]
        if progress is not None:
            for index, name in enumerate(names, start=1):
                progress(index, len(names), name)
        return rows

    client = SkinportClient(timeout=timeout, max_retries=retries)
    fetched = client.fetch_sales_history(
        currency=currency, period=period, statistic=statistic
    )
    rows = [row for row in fetched if row.get("market_hash_name") in wanted]
    if cache is not None:
        cache.put_many(rows)
        cache.save()
    if progress is not None:
        for index, name in enumerate(names, start=1):
            progress(index, len(names), name)
    return rows


def build_cache(
    path: str | None, *, max_age_hours: float | None
) -> PriceCache | None:
    """Create a cache, or ``None`` when caching is disabled."""

    if path is None:
        return None
    max_age = None if max_age_hours is None else timedelta(hours=max_age_hours)
    return PriceCache(path, max_age=max_age)
