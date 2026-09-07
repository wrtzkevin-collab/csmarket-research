"""End-to-end case valuation with explicit catalogue and price provenance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from math import fsum, isclose, isfinite
from typing import Any, Iterable

from .catalog import CaseDefinition, CatalogItem
from .model import EVResult, Outcome, calculate_ev
from .probabilities import (
    STANDARD_CASE_RARITY_PROBABILITIES,
    STATTRAK_CONDITIONAL_PROBABILITY,
)
from .variants import MarketVariant
from .wear import WEAR_MODELS, calculate_wear_probabilities


_RARITY_ALIASES = {"Mil-Spec Grade": "Mil-Spec"}
_PROBABILITY_TOLERANCE = 1e-10


@dataclass(frozen=True, slots=True)
class PriceObservation:
    market_hash_name: str
    price: float | None
    source: str
    currency: str
    price_type: str
    observed_at: str
    volume: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "market_hash_name",
            "source",
            "currency",
            "price_type",
            "observed_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.price is not None and (
            isinstance(self.price, bool)
            or not isinstance(self.price, (int, float))
            or not isfinite(self.price)
            or self.price < 0
        ):
            raise ValueError("price must be a finite non-negative number or null")
        if self.volume is not None and (
            isinstance(self.volume, bool)
            or not isinstance(self.volume, int)
            or self.volume < 0
        ):
            raise ValueError("volume must be a non-negative integer or null")


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    source: str
    currency: str
    price_type: str
    observed_at: str
    observations: dict[str, PriceObservation]


@dataclass(frozen=True, slots=True)
class CaseValuation:
    case_name: str
    wear_model_id: str
    case_price: float
    key_price: float
    key_price_source: str
    sell_fee_rate: float
    result: EVResult
    rarity_coverage: dict[str, float]
    priced_outcomes: int
    total_outcomes: int
    missing_market_names: tuple[str, ...]
    publication_ready: bool
    source: str
    currency: str
    price_type: str
    observed_at: str
    catalog_commit: str
    catalog_repository: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self.result)
        result.update(
            {
                "gross_return_percent": self.result.gross_return_ratio * 100,
                "expected_net_roi_percent": self.result.expected_net_roi * 100,
                "observed_loss_probability_percent": self.result.loss_probability * 100,
                "probability_coverage_percent": self.result.probability_coverage * 100,
                "partial_lower_bound": self.result.probability_coverage < 1,
            }
        )
        return {
            "schema_version": "1.0",
            "case_name": self.case_name,
            "model": {
                "wear_model_id": self.wear_model_id,
                "sell_fee_rate": self.sell_fee_rate,
            },
            "cost": {
                "case_price": self.case_price,
                "key_price": self.key_price,
                "key_price_source": self.key_price_source,
                "total_cost": self.result.total_cost,
            },
            "snapshot": {
                "source": self.source,
                "currency": self.currency,
                "price_type": self.price_type,
                "observed_at": self.observed_at,
            },
            "catalog": {
                "commit": self.catalog_commit,
                "repository": self.catalog_repository,
                "classification": "community maintained; not a Valve API",
            },
            "coverage": {
                "overall": self.result.probability_coverage,
                "by_rarity": self.rarity_coverage,
                "priced_outcomes": self.priced_outcomes,
                "total_outcomes": self.total_outcomes,
                "missing_market_names": list(self.missing_market_names),
            },
            "publication_ready": self.publication_ready,
            "result": result,
        }


def snapshot_from_skinport_rows(
    rows: Iterable[dict[str, Any]], *, required_names: Iterable[str]
) -> PriceSnapshot:
    """Create one strict snapshot from normalized Skinport rows."""

    required = tuple(dict.fromkeys(required_names))
    if not required:
        raise ValueError("required_names must not be empty")
    required_set = set(required)
    observations: dict[str, PriceObservation] = {}
    snapshot_fields: tuple[str, str, str, str] | None = None
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("every price row must be an object")
        name = row.get("market_hash_name")
        if name not in required_set:
            continue
        price = row.get("price")
        observation = PriceObservation(
            market_hash_name=name,
            price=None if price is None else float(price),
            source=row.get("source"),
            currency=row.get("currency"),
            price_type=row.get("price_type"),
            observed_at=row.get("observed_at"),
            volume=row.get("volume"),
        )
        current_fields = (
            observation.source,
            observation.currency,
            observation.price_type,
            observation.observed_at,
        )
        if snapshot_fields is None:
            snapshot_fields = current_fields
        elif current_fields != snapshot_fields:
            raise ValueError("price rows mix source, currency, price type, or observation time")
        if name in observations:
            raise ValueError(f"duplicate price observation: {name}")
        observations[name] = observation

    if snapshot_fields is None:
        raise ValueError("no required price observations were returned")
    source, currency, price_type, observed_at = snapshot_fields
    return PriceSnapshot(
        source=source,
        currency=currency,
        price_type=price_type,
        observed_at=observed_at,
        observations=observations,
    )


def expand_case_variants(
    case: CaseDefinition, *, wear_model_id: str
) -> tuple[MarketVariant, ...]:
    """Expand a catalogue case using exact non-Souvenir market names."""

    if wear_model_id not in WEAR_MODELS:
        raise ValueError(f"unknown wear model: {wear_model_id}")
    groups: dict[str, list[CatalogItem]] = defaultdict(list)
    for item in case.items:
        rarity = _RARITY_ALIASES.get(item.rarity, item.rarity)
        if rarity not in STANDARD_CASE_RARITY_PROBABILITIES:
            raise ValueError(f"unsupported catalogue rarity: {item.rarity}")
        groups[rarity].append(item)
    missing = set(STANDARD_CASE_RARITY_PROBABILITIES) - set(groups)
    if missing:
        raise ValueError(f"case is missing rarity groups: {sorted(missing)}")

    variants: list[MarketVariant] = []
    for rarity, rarity_probability in STANDARD_CASE_RARITY_PROBABILITIES.items():
        items = groups[rarity]
        item_probability = rarity_probability / len(items)
        for item in items:
            wear_weights = _wear_weights(item, wear_model_id)
            stattrak_branches = (
                (
                    (False, 1 - STATTRAK_CONDITIONAL_PROBABILITY),
                    (True, STATTRAK_CONDITIONAL_PROBABILITY),
                )
                if item.stattrak_eligible
                else ((False, 1.0),)
            )
            for stattrak, stattrak_weight in stattrak_branches:
                for wear, wear_weight in wear_weights.items():
                    probability = item_probability * stattrak_weight * wear_weight
                    if probability <= 0:
                        continue
                    market_name = _exact_market_name(item, wear=wear, stattrak=stattrak)
                    wear_id = wear or "wearless"
                    branch = "stattrak" if stattrak else "normal"
                    variants.append(
                        MarketVariant(
                            outcome_id=f"{item.id}:{branch}:{wear_id}",
                            market_hash_name=market_name,
                            probability=probability,
                            rarity=rarity,
                            is_special=item.is_special,
                            stattrak=stattrak,
                            wear=wear,
                        )
                    )

    total = fsum(variant.probability for variant in variants)
    if not isclose(total, 1.0, rel_tol=0, abs_tol=_PROBABILITY_TOLERANCE):
        raise AssertionError(f"expanded probabilities sum to {total}, expected 1")
    return tuple(variants)


def value_case(
    case: CaseDefinition,
    variants: Iterable[MarketVariant],
    snapshot: PriceSnapshot,
    *,
    key_price: float,
    key_price_source: str,
    sell_fee_rate: float,
    wear_model_id: str,
) -> CaseValuation:
    """Join exact market observations and calculate a transparent partial EV."""

    variant_list = tuple(variants)
    if not variant_list:
        raise ValueError("variants must not be empty")
    case_quote = snapshot.observations.get(case.name)
    if case_quote is None or case_quote.price is None:
        raise ValueError(f"case price is missing: {case.name}")
    if not 0 <= sell_fee_rate <= 1:
        raise ValueError("sell_fee_rate must be from 0 to 1")
    if not isinstance(key_price_source, str) or not key_price_source.strip():
        raise ValueError("key_price_source must be stated")

    outcomes: list[Outcome] = []
    priced_probability: dict[str, float] = defaultdict(float)
    rarity_probability: dict[str, float] = defaultdict(float)
    missing_names: set[str] = set()
    priced_count = 0
    for variant in variant_list:
        rarity_probability[variant.rarity] += variant.probability
        quote = snapshot.observations.get(variant.market_hash_name)
        price = None if quote is None else quote.price
        if price is None or (quote is not None and quote.volume == 0):
            missing_names.add(variant.market_hash_name)
            price = None
        else:
            priced_probability[variant.rarity] += variant.probability
            priced_count += 1
        outcomes.append(
            Outcome(
                name=variant.outcome_id,
                probability=variant.probability,
                gross_value=price,
                sell_fee_rate=sell_fee_rate,
            )
        )

    result = calculate_ev(outcomes, case_price=case_quote.price, key_price=key_price)
    rarity_coverage = {
        rarity: priced_probability[rarity] / probability
        for rarity, probability in rarity_probability.items()
    }
    special_coverage = rarity_coverage.get("Rare Special Item", 0.0)
    publication_ready = (
        isclose(result.probability_coverage, 1.0, abs_tol=1e-9)
        and isclose(special_coverage, 1.0, abs_tol=1e-9)
    )
    return CaseValuation(
        case_name=case.name,
        wear_model_id=wear_model_id,
        case_price=case_quote.price,
        key_price=key_price,
        key_price_source=key_price_source,
        sell_fee_rate=sell_fee_rate,
        result=result,
        rarity_coverage=rarity_coverage,
        priced_outcomes=priced_count,
        total_outcomes=len(variant_list),
        missing_market_names=tuple(sorted(missing_names)),
        publication_ready=publication_ready,
        source=snapshot.source,
        currency=snapshot.currency,
        price_type=snapshot.price_type,
        observed_at=snapshot.observed_at,
        catalog_commit=case.catalog_commit,
        catalog_repository=case.catalog_repository,
    )


def required_market_names(
    case: CaseDefinition, variants: Iterable[MarketVariant]
) -> tuple[str, ...]:
    return tuple(sorted({case.name, *(variant.market_hash_name for variant in variants)}))


def _wear_weights(item: CatalogItem, wear_model_id: str) -> dict[str | None, float]:
    if item.min_float is None and item.max_float is None:
        return {None: 1.0}
    if item.min_float is None or item.max_float is None:
        raise ValueError(f"item {item.id} has incomplete float bounds")
    probabilities = calculate_wear_probabilities(
        item.min_float, item.max_float, model_id=wear_model_id
    ).probabilities
    nonzero = {wear: weight for wear, weight in probabilities.items() if weight > 0}
    catalog_wears = set(item.wears)
    if set(nonzero) - catalog_wears:
        raise ValueError(f"wear model produced variants missing from catalogue: {item.id}")
    return nonzero


def _exact_market_name(
    item: CatalogItem, *, wear: str | None, stattrak: bool
) -> str:
    matches = [
        variant.market_hash_name
        for variant in item.market_variants
        if not variant.souvenir
        and variant.wear == wear
        and variant.stattrak is stattrak
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one exact market variant for {item.id}, wear={wear!r}, "
            f"stattrak={stattrak}; found {len(matches)}"
        )
    return matches[0]
