"""Version-pinned community catalogue adapter.

ByMykel/CSGO-API is a community-maintained MIT-licensed catalogue, not a Valve
API.  Pinning the commit makes the item-to-case mapping reproducible even when
the upstream project changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import requests


CATALOG_COMMIT = "2dc37f61119820135bd4a3bd145d3fff8da8927a"
CATALOG_REPOSITORY = "https://github.com/ByMykel/CSGO-API"
CATALOG_LICENSE = "MIT"
CATALOG_RAW_ROOT = (
    "https://raw.githubusercontent.com/ByMykel/CSGO-API/"
    f"{CATALOG_COMMIT}/public/api/en"
)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class CatalogDataError(RuntimeError):
    """Raised when the pinned catalogue cannot provide a valid case."""


@dataclass(frozen=True, slots=True)
class CatalogVariant:
    market_hash_name: str
    wear: str | None
    stattrak: bool
    souvenir: bool


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: str
    name: str
    rarity: str
    min_float: float | None
    max_float: float | None
    stattrak_eligible: bool
    wears: tuple[str, ...]
    is_special: bool
    market_variants: tuple[CatalogVariant, ...]


@dataclass(frozen=True, slots=True)
class CaseDefinition:
    id: str
    name: str
    items: tuple[CatalogItem, ...]
    catalog_commit: str = CATALOG_COMMIT
    catalog_repository: str = CATALOG_REPOSITORY
    catalog_license: str = CATALOG_LICENSE


class CaseCatalogClient:
    """Fetch and validate cases from an immutable CSGO-API revision."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        max_retries: int = 2,
        backoff_factor: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        raw_root: str = CATALOG_RAW_ROOT,
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
        self._sleep = sleep
        self.raw_root = raw_root.rstrip("/")
        self._cases: list[dict[str, Any]] | None = None
        self._skins_by_id: dict[str, dict[str, Any]] | None = None
        self._variants_by_skin_id: dict[str, list[dict[str, Any]]] | None = None

    def fetch_case(self, case_name: str) -> CaseDefinition:
        """Return one validated case with normal and case-specific special items."""

        wanted = case_name.strip()
        if not wanted:
            raise ValueError("case_name cannot be empty")
        self._load()
        assert self._cases is not None
        assert self._skins_by_id is not None
        assert self._variants_by_skin_id is not None

        matches = [row for row in self._cases if row.get("name") == wanted]
        if len(matches) != 1:
            raise CatalogDataError(
                f"expected one case named {wanted!r}, found {len(matches)}"
            )
        case_row = matches[0]
        items: list[CatalogItem] = []
        seen_ids: set[str] = set()
        for field, is_special in (("contains", False), ("contains_rare", True)):
            references = case_row.get(field)
            if not isinstance(references, list):
                raise CatalogDataError(f"case field {field!r} must be a list")
            for reference in references:
                if not isinstance(reference, dict) or not isinstance(reference.get("id"), str):
                    raise CatalogDataError(f"case field {field!r} contains an invalid item")
                item_id = reference["id"]
                if item_id in seen_ids:
                    raise CatalogDataError(f"duplicate item id in case: {item_id}")
                seen_ids.add(item_id)
                skin = self._skins_by_id.get(item_id)
                if skin is None:
                    raise CatalogDataError(f"catalogue skin is missing: {item_id}")
                variants = self._variants_by_skin_id.get(item_id)
                if not variants:
                    raise CatalogDataError(f"catalogue variants are missing: {item_id}")
                items.append(_parse_skin(skin, variants, is_special=is_special))

        case_id = case_row.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise CatalogDataError("case id must be a non-empty string")
        if not items or not any(item.is_special for item in items):
            raise CatalogDataError("case must contain normal and rare-special items")
        return CaseDefinition(id=case_id, name=wanted, items=tuple(items))

    def _load(self) -> None:
        if (
            self._cases is not None
            and self._skins_by_id is not None
            and self._variants_by_skin_id is not None
        ):
            return
        cases = self._request_json("crates.json")
        skins = self._request_json("skins.json")
        variants = self._request_json("skins_not_grouped.json")
        if not isinstance(cases, list) or not all(isinstance(row, dict) for row in cases):
            raise CatalogDataError("crates.json must be a list of objects")
        if not isinstance(skins, list) or not all(isinstance(row, dict) for row in skins):
            raise CatalogDataError("skins.json must be a list of objects")
        if not isinstance(variants, list) or not all(
            isinstance(row, dict) for row in variants
        ):
            raise CatalogDataError("skins_not_grouped.json must be a list of objects")
        skins_by_id: dict[str, dict[str, Any]] = {}
        for skin in skins:
            skin_id = skin.get("id")
            if not isinstance(skin_id, str) or not skin_id:
                raise CatalogDataError("skin id must be a non-empty string")
            if skin_id in skins_by_id:
                raise CatalogDataError(f"duplicate skin id: {skin_id}")
            skins_by_id[skin_id] = skin
        self._cases = cases
        self._skins_by_id = skins_by_id
        variants_by_skin_id: dict[str, list[dict[str, Any]]] = {}
        for variant in variants:
            skin_id = variant.get("skin_id")
            if not isinstance(skin_id, str) or not skin_id:
                raise CatalogDataError("variant skin_id must be a non-empty string")
            variants_by_skin_id.setdefault(skin_id, []).append(variant)
        self._variants_by_skin_id = variants_by_skin_id

    def _request_json(self, filename: str) -> Any:
        url = f"{self.raw_root}/{filename}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    self._sleep(self.backoff_factor * (2**attempt))
                    continue
                raise CatalogDataError(
                    f"catalogue request failed with HTTP status {status_code or 'unknown'}"
                ) from exc
            except (requests.RequestException, ValueError) as exc:
                if isinstance(exc, requests.RequestException) and attempt < self.max_retries:
                    self._sleep(self.backoff_factor * (2**attempt))
                    continue
                raise CatalogDataError("catalogue request failed") from exc
        raise AssertionError("retry loop exhausted unexpectedly")


def _parse_skin(
    row: dict[str, Any],
    variant_rows: list[dict[str, Any]],
    *,
    is_special: bool,
) -> CatalogItem:
    item_id = row.get("id")
    name = row.get("name")
    rarity = row.get("rarity")
    if not isinstance(item_id, str) or not item_id:
        raise CatalogDataError("skin id must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise CatalogDataError(f"skin {item_id} has no valid name")
    if not isinstance(rarity, dict) or not isinstance(rarity.get("name"), str):
        raise CatalogDataError(f"skin {item_id} has no valid rarity")

    min_float = _optional_float(row.get("min_float"), f"{item_id}.min_float")
    max_float = _optional_float(row.get("max_float"), f"{item_id}.max_float")
    if (min_float is None) != (max_float is None):
        raise CatalogDataError(f"skin {item_id} must define both float bounds or neither")
    if min_float is not None and (not 0 <= min_float <= max_float <= 1):
        raise CatalogDataError(f"skin {item_id} has invalid float bounds")

    raw_wears = row.get("wears")
    if raw_wears is None:
        wears: tuple[str, ...] = ()
    elif isinstance(raw_wears, list) and all(
        isinstance(wear, dict) and isinstance(wear.get("name"), str)
        for wear in raw_wears
    ):
        wears = tuple(wear["name"] for wear in raw_wears)
    else:
        raise CatalogDataError(f"skin {item_id} has invalid wears")

    market_variants: list[CatalogVariant] = []
    seen_market_names: set[str] = set()
    for variant in variant_rows:
        market_name = variant.get("market_hash_name")
        wear = variant.get("wear")
        if not isinstance(market_name, str) or not market_name:
            raise CatalogDataError(f"skin {item_id} has a variant without market name")
        if market_name in seen_market_names:
            raise CatalogDataError(f"skin {item_id} has duplicate market name: {market_name}")
        seen_market_names.add(market_name)
        if wear is None:
            wear_name = None
        elif isinstance(wear, dict) and isinstance(wear.get("name"), str):
            wear_name = wear["name"]
        else:
            raise CatalogDataError(f"skin {item_id} has a variant with invalid wear")
        market_variants.append(
            CatalogVariant(
                market_hash_name=market_name,
                wear=wear_name,
                stattrak=variant.get("stattrak") is True,
                souvenir=variant.get("souvenir") is True,
            )
        )

    return CatalogItem(
        id=item_id,
        name=name,
        rarity="Rare Special Item" if is_special else rarity["name"],
        min_float=min_float,
        max_float=max_float,
        stattrak_eligible=row.get("stattrak") is True,
        wears=wears,
        is_special=is_special,
        market_variants=tuple(market_variants),
    )


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CatalogDataError(f"{field_name} must be numeric or null")
    return float(value)
