"""On-disk observation cache.

A full Steam pass over one case costs several hundred throttled requests, so a
report that re-queries the provider on every run is unusable and needlessly
rude to the provider.  Cached rows keep their original ``observed_at`` so that
a stale snapshot stays visibly stale instead of appearing fresh, and each entry
is written under the exact provider and currency it was fetched with.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CACHE_PATH = Path("data/raw/price-cache.json")
CACHE_SCHEMA_VERSION = "1.0"


def parse_iso8601(text: str) -> datetime:
    """Parse an ISO-8601 timestamp, accepting a trailing ``Z``."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("timestamp must be a non-empty string")
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class PriceCache:
    """Provider-scoped cache of normalized price rows keyed by market name."""

    def __init__(
        self,
        path: Path | str = DEFAULT_CACHE_PATH,
        *,
        max_age: timedelta | None = timedelta(hours=24),
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.path = Path(path)
        self.max_age = max_age
        self._clock = clock
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False

    @staticmethod
    def _key(source: str, currency: str, market_hash_name: str) -> str:
        return f"{source}\t{currency.upper()}\t{market_hash_name}"

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt or unreadable cache must never break a run; the next
            # save rewrites it from scratch.
            return
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, dict):
            return
        self._entries = {
            key: row
            for key, row in entries.items()
            if isinstance(key, str) and isinstance(row, dict)
        }

    def get(
        self, source: str, currency: str, market_hash_name: str
    ) -> dict[str, Any] | None:
        """Return a cached row, or ``None`` when absent or older than ``max_age``."""

        self.load()
        row = self._entries.get(self._key(source, currency, market_hash_name))
        if row is None:
            return None
        if self.max_age is None:
            return dict(row)
        observed_at = row.get("observed_at")
        if not isinstance(observed_at, str):
            return None
        try:
            observed = parse_iso8601(observed_at)
        except ValueError:
            return None
        if self._clock() - observed > self.max_age:
            return None
        return dict(row)

    def put(self, row: dict[str, Any]) -> None:
        self.load()
        source = row.get("source")
        currency = row.get("currency")
        name = row.get("market_hash_name")
        if not all(
            isinstance(value, str) and value for value in (source, currency, name)
        ):
            raise ValueError("row must carry source, currency and market_hash_name")
        self._entries[self._key(source, currency, name)] = dict(row)

    def put_many(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.put(row)

    def save(self) -> None:
        """Write the cache atomically so an interrupted run cannot corrupt it."""

        self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "saved_at": self._clock().isoformat().replace("+00:00", "Z"),
            "entries": self._entries,
        }
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(handle.name, self.path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def __len__(self) -> int:
        self.load()
        return len(self._entries)
