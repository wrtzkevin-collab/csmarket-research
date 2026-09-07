"""Steam Community Market adapter.

Steam is the reference venue for CS2 items: it lists every tradable market
variant, including the illiquid rare specials that third-party venues often
lack.  Two properties make it different from a cash market and both are
recorded on every observation rather than hidden in a comment.

``lowest_price`` is the cheapest current *ask*.  It is an offer to sell, not a
completed sale, so it is systematically optimistic about what a holder can
realise.  ``median_price`` and ``volume`` describe completed sales in the last
24 hours and are absent for items that did not trade in that window, which is
exactly the illiquid tail this adapter exists to cover.  The adapter therefore
values items on the ask and exposes the sale statistics separately instead of
mixing two price types inside one snapshot.

Steam funds also cannot be withdrawn as cash.  Callers must not treat a Steam
valuation and a cash-market valuation as the same unit; the pipeline keeps them
as separate snapshots for exactly this reason.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

import requests


STEAM_BASE_URL = "https://steamcommunity.com"
CS2_APP_ID = 730
SOURCE_NAME = "steam_community_market"
PRICE_TYPE = "lowest_listing"

# Steam identifies currencies by integer code, not ISO name.
CURRENCY_CODES: dict[str, int] = {
    "USD": 1,
    "GBP": 2,
    "EUR": 3,
    "CHF": 4,
    "RUB": 5,
    "PLN": 6,
    "BRL": 7,
    "JPY": 8,
    "SEK": 9,
    "IDR": 10,
    "MYR": 11,
    "PHP": 12,
    "SGD": 13,
    "THB": 14,
    "VND": 15,
    "KRW": 16,
    "TRY": 17,
    "UAH": 18,
    "MXN": 19,
    "CAD": 20,
    "AUD": 21,
    "NZD": 22,
    "CNY": 23,
    "INR": 24,
    "NOK": 25,
    "ZAR": 28,
    "HKD": 29,
    "TWD": 30,
}

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_NUMBER_PATTERN = re.compile(r"[0-9][0-9.,   ]*")


class SteamDataError(RuntimeError):
    """Raised when Steam cannot provide a usable response."""


def parse_money(text: Any) -> float | None:
    """Parse a Steam price string such as ``"$1,234.56"`` into a float.

    Steam formats prices for the requested currency's locale, so both
    ``1,234.56`` and ``1.234,56`` occur.  The separator that appears last and is
    followed by one or two digits is treated as the decimal separator; every
    other separator is a grouping mark.  Returns ``None`` for absent values so
    that a missing price stays missing instead of silently becoming zero.
    """

    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        value = float(text)
        return value if value >= 0 else None
    if not isinstance(text, str):
        return None

    match = _NUMBER_PATTERN.search(text.replace("−", "-"))
    if match is None:
        return None
    raw = match.group(0).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if not raw:
        return None

    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    decimal_at = max(last_dot, last_comma)
    if decimal_at != -1 and len(raw) - decimal_at - 1 in (1, 2):
        integer_part = re.sub(r"[.,]", "", raw[:decimal_at])
        fraction_part = raw[decimal_at + 1 :]
        candidate = f"{integer_part or '0'}.{fraction_part}"
    else:
        candidate = re.sub(r"[.,]", "", raw)

    try:
        value = float(candidate)
    except ValueError:
        return None
    return value if value >= 0 else None


def _parse_volume(text: Any) -> int | None:
    if text is None:
        return None
    if isinstance(text, bool):
        return None
    if isinstance(text, int):
        return text if text >= 0 else None
    if not isinstance(text, str):
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


class SteamMarketClient:
    """Throttled client for Steam's public ``priceoverview`` endpoint.

    Steam applies an undocumented rate limit and answers ``429`` once it is
    exceeded.  Measured behaviour is roughly twenty requests per minute
    sustained, so ``request_interval`` defaults to three seconds and every
    request waits for that spacing.  A case expands to a few hundred market
    names, which makes a full pass slow but predictable; callers are expected to
    cache the resulting snapshot rather than re-query per report.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        max_retries: int = 5,
        backoff_factor: float = 2.0,
        rate_limit_backoff: float = 30.0,
        max_backoff: float = 180.0,
        request_interval: float = 5.0,
        base_url: str = STEAM_BASE_URL,
        app_id: int = CS2_APP_ID,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if backoff_factor < 0:
            raise ValueError("backoff_factor cannot be negative")
        if rate_limit_backoff < 0:
            raise ValueError("rate_limit_backoff cannot be negative")
        if max_backoff <= 0:
            raise ValueError("max_backoff must be positive")
        if request_interval < 0:
            raise ValueError("request_interval cannot be negative")

        self.session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.rate_limit_backoff = rate_limit_backoff
        self.max_backoff = max_backoff
        self.request_interval = request_interval
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self._sleep = sleep
        self._monotonic = monotonic
        self._clock = clock
        self._last_request_at: float | None = None

    def fetch_price(
        self, market_hash_name: str, *, currency: str = "USD"
    ) -> dict[str, Any]:
        """Return one normalized observation for an exact market hash name.

        An item Steam does not know, or knows without any current listing, comes
        back with ``price=None`` instead of raising.  Absence of a listing is a
        legitimate observation about the market, not a transport failure.
        """

        name = market_hash_name.strip() if isinstance(market_hash_name, str) else ""
        if not name:
            raise ValueError("market_hash_name cannot be empty")
        currency_code = self._currency_code(currency)

        payload = self._request_json(
            "/market/priceoverview/",
            params={
                "appid": self.app_id,
                "currency": currency_code,
                "market_hash_name": name,
            },
        )
        if not isinstance(payload, dict):
            raise SteamDataError("priceoverview response must be an object")

        observed_at = self._observed_at()
        if payload.get("success") is not True:
            return self._row(name, currency, observed_at, None, None, None)

        return self._row(
            name,
            currency,
            observed_at,
            parse_money(payload.get("lowest_price")),
            parse_money(payload.get("median_price")),
            _parse_volume(payload.get("volume")),
        )

    def fetch_prices(
        self,
        market_hash_names: Iterable[str],
        *,
        currency: str = "USD",
        progress: Callable[[int, int, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch every name in order, de-duplicated, preserving first order.

        One shared ``observed_at`` is not imposed here: each row keeps the time
        it was actually observed, and the pipeline decides how much drift a
        snapshot may contain.
        """

        names: Sequence[str] = tuple(dict.fromkeys(market_hash_names))
        total = len(names)
        rows: list[dict[str, Any]] = []
        for index, name in enumerate(names, start=1):
            rows.append(self.fetch_price(name, currency=currency))
            if progress is not None:
                progress(index, total, name)
        return rows

    def _currency_code(self, currency: str) -> int:
        if not isinstance(currency, str):
            raise ValueError("currency must be a string")
        code = CURRENCY_CODES.get(currency.strip().upper())
        if code is None:
            raise ValueError(
                f"unsupported currency {currency!r}; expected one of "
                f"{sorted(CURRENCY_CODES)}"
            )
        return code

    def _observed_at(self) -> str:
        return (
            self._clock()
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _row(
        self,
        name: str,
        currency: str,
        observed_at: str,
        price: float | None,
        median_price: float | None,
        volume: int | None,
    ) -> dict[str, Any]:
        return {
            "market_hash_name": name,
            "price": price,
            "median_price": median_price,
            "volume": volume,
            "source": SOURCE_NAME,
            "currency": currency.strip().upper(),
            "price_type": PRICE_TYPE,
            "observed_at": observed_at,
        }

    def _retry_delay(self, status_code: int | None, attempt: int, response) -> float:
        """Choose how long to wait before retrying a retryable status.

        A ``429`` from Steam is not a transient blip: it means a sustained-rate
        window has been exhausted and takes on the order of a minute to clear,
        so it gets its own much longer backoff.  A ``Retry-After`` header, when
        present, always wins over the guess.
        """

        retry_after = None
        try:
            retry_after = float((response.headers or {}).get("Retry-After", ""))
        except (TypeError, ValueError, AttributeError):
            retry_after = None
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, self.max_backoff)
        # Doubling without a ceiling reaches a quarter of an hour by the fifth
        # attempt, which looks indistinguishable from a hang.
        if status_code == 429:
            return min(self.rate_limit_backoff * (2**attempt), self.max_backoff)
        return min(self.backoff_factor * (2**attempt), self.max_backoff)

    def _throttle(self) -> None:
        if self.request_interval <= 0:
            return
        now = self._monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.request_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _request_json(self, path: str, *, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code is None:
                    status_code = getattr(response, "status_code", None)
                if status_code in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    self._sleep(self._retry_delay(status_code, attempt, response))
                    continue
                detail = (
                    ". Steam throttles sustained crawling over a window longer "
                    "than one minute; raise --request-interval and re-run, the "
                    "cache keeps what was already fetched"
                    if status_code == 429
                    else ""
                )
                raise SteamDataError(
                    f"Steam request failed with HTTP status "
                    f"{status_code or 'unknown'}{detail}"
                ) from exc
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    self._sleep(self.backoff_factor * (2**attempt))
                    continue
                raise SteamDataError("Steam request failed") from exc

            try:
                return response.json()
            except ValueError as exc:
                body = (response.text or "")[:120]
                raise SteamDataError(
                    f"Steam returned a non-JSON body (HTTP {response.status_code}): {body!r}"
                ) from exc

        raise AssertionError("retry loop exhausted unexpectedly")


SEARCH_PAGE_SIZE = 10
SEARCH_SOURCE_NAME = SOURCE_NAME


class SteamSearchClient:
    """Paginated reader for Steam's market search endpoint.

    ``priceoverview`` answers one item per request and throttles hard: measured
    behaviour is roughly twenty requests per minute, so a case of a few hundred
    market names takes about half an hour.  The search endpoint returns ten
    priced rows per request and, measured against the same account and address,
    does not throttle at anything like the same rate.  Pricing a case through it
    costs tens of requests instead of hundreds.

    The trade is what each endpoint reports.  Search returns ``sell_listings``,
    the number of offers currently resting on the market, and no completed-sale
    statistics at all.  Listings describe accumulated supply rather than recent
    turnover, and unlike 24-hour volume they exist for the illiquid tail, which
    is why they can weight the grades of a knife that has not traded today.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        max_retries: int = 4,
        backoff_factor: float = 2.0,
        rate_limit_backoff: float = 30.0,
        max_backoff: float = 180.0,
        request_interval: float = 2.0,
        base_url: str = STEAM_BASE_URL,
        app_id: int = CS2_APP_ID,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._transport = SteamMarketClient(
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            rate_limit_backoff=rate_limit_backoff,
            max_backoff=max_backoff,
            request_interval=request_interval,
            base_url=base_url,
            app_id=app_id,
            sleep=sleep,
            monotonic=monotonic,
            clock=clock,
        )
        self.app_id = app_id

    def fetch_item_set(
        self,
        collection_tag: str,
        *,
        currency: str = "USD",
        progress: Callable[[int, int, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Return every priced row in one market item-set facet."""

        return self._paginate(
            {f"category_{self.app_id}_ItemSet[]": collection_tag},
            currency=currency,
            label=collection_tag,
            progress=progress,
        )

    def search(
        self,
        query: str,
        *,
        currency: str = "USD",
        max_pages: int | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Return priced rows matching a free-text market search."""

        return self._paginate(
            {"query": query},
            currency=currency,
            label=query,
            max_pages=max_pages,
            progress=progress,
        )

    def _paginate(
        self,
        params: dict[str, Any],
        *,
        currency: str,
        label: str,
        max_pages: int | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        currency_code = self._transport._currency_code(currency)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        start = 0
        total: int | None = None
        pages = 0

        while True:
            payload = self._transport._request_json(
                "/market/search/render/",
                params={
                    **params,
                    "appid": self.app_id,
                    "currency": currency_code,
                    "norender": 1,
                    "count": SEARCH_PAGE_SIZE,
                    "start": start,
                },
            )
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise SteamDataError(f"market search failed for {label!r}")

            results = payload.get("results")
            if not isinstance(results, list):
                raise SteamDataError("market search results must be a list")
            if total is None:
                reported = payload.get("total_count")
                total = reported if isinstance(reported, int) else 0

            observed_at = self._transport._observed_at()
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("hash_name")
                if not isinstance(name, str) or not name or name in seen:
                    continue
                seen.add(name)
                rows.append(self._row(entry, name, currency, observed_at))

            pages += 1
            start += SEARCH_PAGE_SIZE
            if progress is not None:
                progress(min(start, total), total, label)
            if not results or start >= total:
                break
            if max_pages is not None and pages >= max_pages:
                break

        return rows

    def _row(
        self, entry: dict[str, Any], name: str, currency: str, observed_at: str
    ) -> dict[str, Any]:
        # The formatted text carries the venue's own locale, so it is the
        # authority; the integer is a minor-unit fallback for odd currencies.
        price = parse_money(entry.get("sell_price_text"))
        if price is None:
            minor = entry.get("sell_price")
            price = minor / 100 if isinstance(minor, int) and minor >= 0 else None

        listings = entry.get("sell_listings")
        if isinstance(listings, bool) or not isinstance(listings, int) or listings < 0:
            listings = None

        return {
            "market_hash_name": name,
            "price": price,
            "median_price": None,
            "volume": None,
            "listings": listings,
            "source": SEARCH_SOURCE_NAME,
            "currency": currency.strip().upper(),
            "price_type": PRICE_TYPE,
            "observed_at": observed_at,
        }
