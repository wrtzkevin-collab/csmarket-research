"""Skinport public API adapter.

The adapter deliberately exposes cash-market listing and completed-sale prices as
different ``price_type`` values.  Consumers must not silently treat one as the
other when calculating expected value.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


SKINPORT_BASE_URL = "https://api.skinport.com"
SALES_SOURCE_NAME = "skinport"
LISTINGS_SOURCE_NAME = "skinport_listings"
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_SALES_PERIODS = frozenset(
    {"last_24_hours", "last_7_days", "last_30_days", "last_90_days"}
)
_SALES_STATISTICS = frozenset({"min", "max", "avg", "median"})


class SkinportDataError(RuntimeError):
    """Raised when Skinport cannot provide a usable response."""


def _retry_after_seconds(response: Any) -> float | None:
    """Read a ``Retry-After`` delay in seconds, if the response carries one."""

    try:
        raw = (response.headers or {}).get("Retry-After")
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _brotli_available() -> bool:
    """Report whether urllib3 can transparently decode a ``br`` response."""

    try:
        import brotli  # noqa: F401
    except ImportError:
        try:
            import brotlicffi  # noqa: F401
        except ImportError:
            return False
    return True


class SkinportClient:
    """Small, testable client for Skinport's unauthenticated market endpoints.

    ``max_retries`` counts retries after the first request.  A value of two
    therefore permits at most three HTTP requests.  Passing a session makes the
    transport injectable for tests and lets production callers reuse connections.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_factor: float = 0.25,
        max_wait: float = 60.0,
        base_url: str = SKINPORT_BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if backoff_factor < 0:
            raise ValueError("backoff_factor cannot be negative")

        self.session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_wait = max_wait
        self.base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._clock = clock

    def fetch_items(
        self,
        *,
        currency: str = "USD",
        app_id: int = 730,
        tradable: bool = False,
    ) -> list[dict[str, Any]]:
        """Return normalized current listings from ``/v1/items``.

        ``price`` is the lowest current listing.  It can be ``None`` when an item
        has no active listings; callers should treat that as missing data rather
        than a zero-price item.
        """

        requested_currency = _normalize_currency(currency)
        payload = self._request_json(
            "/v1/items",
            params={
                "app_id": app_id,
                "currency": requested_currency,
                "tradable": int(tradable),
            },
        )
        observed_at = self._observed_at()
        return [
            self._normalize_item(row, requested_currency, observed_at)
            for row in _require_rows(payload, "/v1/items")
        ]

    def fetch_sales_history(
        self,
        market_hash_names: Sequence[str] | None = None,
        *,
        currency: str = "USD",
        app_id: int = 730,
        period: str = "last_30_days",
        statistic: str = "median",
    ) -> list[dict[str, Any]]:
        """Return normalized aggregate sale prices from ``/v1/sales/history``.

        Skinport publishes aggregate windows, not a daily time series.  The
        selected window and statistic are encoded in ``price_type`` so downstream
        code cannot mistake them for point-in-time transaction records.
        """

        if period not in _SALES_PERIODS:
            raise ValueError(f"unsupported sales period: {period}")
        if statistic not in _SALES_STATISTICS:
            raise ValueError(f"unsupported sales statistic: {statistic}")

        requested_currency = _normalize_currency(currency)
        params: dict[str, Any] = {
            "app_id": app_id,
            "currency": requested_currency,
        }
        if market_hash_names is not None:
            candidate_names = (
                [market_hash_names]
                if isinstance(market_hash_names, str)
                else market_hash_names
            )
            names = [name.strip() for name in candidate_names if name.strip()]
            if not names:
                raise ValueError("market_hash_names cannot be empty")
            params["market_hash_name"] = ",".join(names)

        payload = self._request_json("/v1/sales/history", params=params)
        observed_at = self._observed_at()
        return [
            self._normalize_sale(
                row,
                requested_currency,
                observed_at,
                period=period,
                statistic=statistic,
            )
            for row in _require_rows(payload, "/v1/sales/history")
        ]

    def _request_json(self, path: str, *, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={"Accept-Encoding": "br"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code is None:
                    status_code = getattr(response, "status_code", None)
                retry_after = _retry_after_seconds(response)
                if status_code == 429 and retry_after is not None:
                    # Skinport states exactly how long the window lasts.  It can
                    # be the better part of an hour, so sleeping through it would
                    # look like a hang and retrying inside it only extends the
                    # block: report when it clears and let the caller decide.
                    if retry_after > self.max_wait:
                        clears_at = self._clock() + timedelta(seconds=retry_after)
                        raise SkinportDataError(
                            "Skinport is rate limiting this address for another "
                            f"{retry_after / 60:.0f} minutes, until about "
                            f"{clears_at.strftime('%H:%M')} UTC"
                        ) from exc
                    if attempt < self.max_retries:
                        self._sleep(retry_after)
                        continue
                if status_code in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                raise SkinportDataError(
                    f"Skinport request failed with HTTP status {status_code or 'unknown'}"
                ) from exc
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                raise SkinportDataError("Skinport request failed") from exc

            try:
                return response.json()
            except ValueError as exc:
                # The request advertises Brotli, so a body that will not parse is
                # usually still compressed: requests only decodes ``br`` when a
                # Brotli backend is installed.  Saying "invalid JSON" there sends
                # the reader looking for a parsing bug that does not exist.
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                if "br" in encoding and not _brotli_available():
                    raise SkinportDataError(
                        "Skinport returned a Brotli-compressed body but no Brotli "
                        "decoder is installed; install the 'brotli' package"
                    ) from exc
                raise SkinportDataError(
                    "Skinport returned a body that is not JSON "
                    f"(HTTP {response.status_code}, Content-Encoding "
                    f"{encoding or 'none'})"
                ) from exc

        raise AssertionError("retry loop exhausted unexpectedly")

    def _wait_before_retry(self, attempt: int) -> None:
        self._sleep(self.backoff_factor * (2**attempt))

    def _observed_at(self) -> str:
        observed = self._clock()
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_item(
        row: dict[str, Any], requested_currency: str, observed_at: str
    ) -> dict[str, Any]:
        # A distinct source name, not merely a distinct price type: rows are
        # cached and grouped by source, so sharing "skinport" with the
        # completed-sale endpoint would let a listing overwrite a sale for the
        # same item and let one snapshot mix the two.
        return {
            "market_hash_name": row.get("market_hash_name"),
            "source": LISTINGS_SOURCE_NAME,
            "currency": str(row.get("currency") or requested_currency).upper(),
            "price": row.get("min_price"),
            "price_type": "listing_min",
            "observed_at": observed_at,
            "quantity": row.get("quantity"),
            "listings": row.get("quantity"),
            "min_price": row.get("min_price"),
            "max_price": row.get("max_price"),
            "mean_price": row.get("mean_price"),
            "median_price": row.get("median_price"),
            "suggested_price": row.get("suggested_price"),
            "source_updated_at": _unix_timestamp_to_iso(row.get("updated_at")),
            "item_page": row.get("item_page"),
            "market_page": row.get("market_page"),
        }

    @staticmethod
    def _normalize_sale(
        row: dict[str, Any],
        requested_currency: str,
        observed_at: str,
        *,
        period: str,
        statistic: str,
    ) -> dict[str, Any]:
        window = row.get(period)
        if not isinstance(window, dict):
            window = {}
        period_label = period.removeprefix("last_")
        return {
            "market_hash_name": row.get("market_hash_name"),
            "source": "skinport",
            "currency": str(row.get("currency") or requested_currency).upper(),
            "price": window.get(statistic),
            "price_type": f"sales_{statistic}_{period_label}",
            "observed_at": observed_at,
            "sales_period": period,
            "sales_statistic": statistic,
            "volume": window.get("volume"),
            "min_price": window.get("min"),
            "max_price": window.get("max"),
            "mean_price": window.get("avg"),
            "median_price": window.get("median"),
            "sales_windows": {
                key: row.get(key)
                for key in sorted(_SALES_PERIODS)
                if isinstance(row.get(key), dict)
            },
            "item_page": row.get("item_page"),
            "market_page": row.get("market_page"),
        }


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if not normalized:
        raise ValueError("currency cannot be empty")
    return normalized


def _require_rows(payload: Any, endpoint: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise SkinportDataError(f"Skinport {endpoint} response must be a list of objects")
    return payload


def _unix_timestamp_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
