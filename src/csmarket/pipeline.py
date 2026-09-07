"""End-to-end case valuation with explicit catalogue and price provenance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from math import fsum, isclose, isfinite
from typing import Any, Iterable, Mapping

from .cache import parse_iso8601
from .catalog import CaseDefinition, CatalogItem
from .model import EVResult, Outcome, calculate_ev
from .probabilities import (
    STANDARD_CASE_RARITY_PROBABILITIES,
    STATTRAK_CONDITIONAL_PROBABILITY,
)
from .variants import MarketVariant
from .wear import (
    BASIS_OBSERVED_VOLUME,
    BASIS_UNIFORM_FALLBACK,
    DEFAULT_MIN_TOTAL_VOLUME,
    WearWeights,
    calculate_wear_weights,
    reachable_wears,
)


_RARITY_ALIASES = {"Mil-Spec Grade": "Mil-Spec"}
_PROBABILITY_TOLERANCE = 1e-10

# A throttled provider pass takes minutes, so rows inside one snapshot cannot
# share a timestamp.  Drift beyond this is treated as mixing separate snapshots.
DEFAULT_MAX_OBSERVATION_DRIFT_SECONDS = 6 * 60 * 60


@dataclass(frozen=True, slots=True)
class PriceObservation:
    market_hash_name: str
    price: float | None
    source: str
    currency: str
    price_type: str
    observed_at: str
    volume: int | None = None
    median_price: float | None = None

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
        for field_name in ("price", "median_price"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"{field_name} must be a finite non-negative number or null"
                )
        if self.volume is not None and (
            isinstance(self.volume, bool)
            or not isinstance(self.volume, int)
            or self.volume < 0
        ):
            raise ValueError("volume must be a non-negative integer or null")


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """One provider's observations, taken as a single logical pass.

    ``observed_at`` is the newest observation in the pass and
    ``observation_span_seconds`` how long the pass took, so a slow crawl stays
    visible instead of being presented as an instant.
    """

    source: str
    currency: str
    price_type: str
    observed_at: str
    observations: dict[str, PriceObservation]
    observed_from: str | None = None
    observation_span_seconds: float = 0.0

    def volumes_for(self, names_by_wear: Mapping[str, str]) -> dict[str, int | None]:
        """Map wear label to observed volume for one item's market names."""

        volumes: dict[str, int | None] = {}
        for wear, market_name in names_by_wear.items():
            observation = self.observations.get(market_name)
            volumes[wear] = None if observation is None else observation.volume
        return volumes


@dataclass(frozen=True, slots=True)
class CaseValuation:
    case_name: str
    case_price: float
    key_price: float
    key_price_source: str
    sell_fee_rate: float
    result: EVResult
    rarity_coverage: dict[str, float]
    priced_outcomes: int
    total_outcomes: int
    missing_market_names: tuple[str, ...]
    wear_basis_coverage: dict[str, float]
    wear_volume_source: str
    publication_ready: bool
    source: str
    currency: str
    price_type: str
    observed_at: str
    observation_span_seconds: float
    catalog_commit: str
    catalog_repository: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self.result)
        result.update(
            {
                "gross_return_percent": self.result.gross_return_ratio * 100,
                "expected_net_roi_percent": self.result.expected_net_roi * 100,
                "loss_probability_percent": self.result.loss_probability * 100,
                "loss_probability_is_lower_bound": self.result.probability_coverage < 1,
                "probability_coverage_percent": self.result.probability_coverage * 100,
                "partial_lower_bound": self.result.probability_coverage < 1,
            }
        )
        return {
            "schema_version": "2.0",
            "case_name": self.case_name,
            "model": {
                "sell_fee_rate": self.sell_fee_rate,
                "wear_weighting": {
                    "method": "observed sales volume per wear grade, "
                    "uniform float density where volume is too thin",
                    "min_total_volume": DEFAULT_MIN_TOTAL_VOLUME,
                    "volume_source": self.wear_volume_source,
                    "probability_mass_by_basis": self.wear_basis_coverage,
                },
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
                "observation_span_seconds": self.observation_span_seconds,
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


def snapshot_from_rows(
    rows: Iterable[dict[str, Any]],
    *,
    required_names: Iterable[str],
    max_drift_seconds: float = DEFAULT_MAX_OBSERVATION_DRIFT_SECONDS,
) -> PriceSnapshot:
    """Build one strict snapshot from normalized provider rows.

    Source, currency and price type must be identical across the pass: mixing a
    listing price with a completed-sale price, or two venues, produces a number
    that means nothing.  Observation times may differ, because a throttled crawl
    genuinely takes minutes, but the spread is bounded and reported.
    """

    required = tuple(dict.fromkeys(required_names))
    if not required:
        raise ValueError("required_names must not be empty")
    required_set = set(required)

    observations: dict[str, PriceObservation] = {}
    identity: tuple[str, str, str] | None = None
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("every price row must be an object")
        name = row.get("market_hash_name")
        if name not in required_set:
            continue
        price = row.get("price")
        median_price = row.get("median_price")
        observation = PriceObservation(
            market_hash_name=name,
            price=None if price is None else float(price),
            source=row.get("source"),
            currency=row.get("currency"),
            price_type=row.get("price_type"),
            observed_at=row.get("observed_at"),
            volume=row.get("volume"),
            median_price=None if median_price is None else float(median_price),
        )
        current = (observation.source, observation.currency, observation.price_type)
        if identity is None:
            identity = current
        elif current != identity:
            raise ValueError("price rows mix source, currency, or price type")
        if name in observations:
            raise ValueError(f"duplicate price observation: {name}")
        observations[name] = observation

    if identity is None:
        raise ValueError("no required price observations were returned")

    timestamps = sorted(
        parse_iso8601(observation.observed_at) for observation in observations.values()
    )
    span = (timestamps[-1] - timestamps[0]).total_seconds()
    if span > max_drift_seconds:
        raise ValueError(
            f"observations span {span:.0f}s, more than the {max_drift_seconds:.0f}s "
            "allowed for one snapshot"
        )

    source, currency, price_type = identity
    return PriceSnapshot(
        source=source,
        currency=currency,
        price_type=price_type,
        observed_at=timestamps[-1].isoformat().replace("+00:00", "Z"),
        observed_from=timestamps[0].isoformat().replace("+00:00", "Z"),
        observation_span_seconds=span,
        observations=observations,
    )


# Retained so existing callers and tests keep working after the rename.
snapshot_from_skinport_rows = snapshot_from_rows


def candidate_market_names(case: CaseDefinition) -> tuple[str, ...]:
    """Every market name a case can actually produce, plus the case itself.

    Enumerated from the catalogue alone so prices can be fetched before any
    wear weighting exists.  Grades outside a skin's float range are excluded
    because the case cannot produce them.
    """

    names: set[str] = {case.name}
    for item in case.items:
        for wear in _item_wears(item):
            for stattrak in (False, True) if item.stattrak_eligible else (False,):
                names.add(_exact_market_name(item, wear=wear, stattrak=stattrak))
    return tuple(sorted(names))


def wear_weights_for_case(
    case: CaseDefinition,
    snapshot: PriceSnapshot,
    *,
    min_total_volume: int = DEFAULT_MIN_TOTAL_VOLUME,
) -> dict[str, WearWeights]:
    """Derive each item's wear weights from the snapshot's observed volumes.

    Volumes are summed over the normal and StatTrak listings of the same grade:
    both are the same drop with the same float, so splitting them would halve
    the evidence for no reason.
    """

    weights: dict[str, WearWeights] = {}
    for item in case.items:
        if item.min_float is None or item.max_float is None:
            continue
        volumes: dict[str, int | None] = {}
        for wear in _item_wears(item):
            if wear is None:
                continue
            total: int | None = None
            for stattrak in (False, True) if item.stattrak_eligible else (False,):
                name = _exact_market_name(item, wear=wear, stattrak=stattrak)
                observation = snapshot.observations.get(name)
                if observation is not None and observation.volume is not None:
                    total = (total or 0) + observation.volume
            volumes[wear] = total
        weights[item.id] = calculate_wear_weights(
            item.min_float,
            item.max_float,
            volumes=volumes,
            min_total_volume=min_total_volume,
            volume_source_url=snapshot.source,
        )
    return weights


def expand_case_variants(
    case: CaseDefinition, *, wear_weights: Mapping[str, WearWeights]
) -> tuple[MarketVariant, ...]:
    """Expand a catalogue case into mutually exclusive market outcomes.

    Three independent factors are multiplied: the published rarity probability
    split equally inside its tier, the published conditional StatTrak
    probability, and the item's wear weights.
    """

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
            wear_split, basis = _wear_split(item, wear_weights)
            stattrak_branches = (
                (
                    (False, 1 - STATTRAK_CONDITIONAL_PROBABILITY),
                    (True, STATTRAK_CONDITIONAL_PROBABILITY),
                )
                if item.stattrak_eligible
                else ((False, 1.0),)
            )
            for stattrak, stattrak_weight in stattrak_branches:
                for wear, wear_weight in wear_split.items():
                    probability = item_probability * stattrak_weight * wear_weight
                    if probability <= 0:
                        continue
                    variants.append(
                        MarketVariant(
                            outcome_id=(
                                f"{item.id}:{'stattrak' if stattrak else 'normal'}:"
                                f"{wear or 'wearless'}"
                            ),
                            market_hash_name=_exact_market_name(
                                item, wear=wear, stattrak=stattrak
                            ),
                            probability=probability,
                            rarity=rarity,
                            is_special=item.is_special,
                            stattrak=stattrak,
                            wear=wear,
                            wear_basis=basis,
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
    basis_probability: dict[str, float] = defaultdict(float)
    missing_names: set[str] = set()
    priced_count = 0
    for variant in variant_list:
        rarity_probability[variant.rarity] += variant.probability
        basis_probability[variant.wear_basis] += variant.probability
        quote = snapshot.observations.get(variant.market_hash_name)
        price = None if quote is None else quote.price
        if price is None:
            missing_names.add(variant.market_hash_name)
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
    publication_ready = isclose(
        result.probability_coverage, 1.0, abs_tol=1e-9
    ) and isclose(special_coverage, 1.0, abs_tol=1e-9)

    return CaseValuation(
        case_name=case.name,
        case_price=case_quote.price,
        key_price=key_price,
        key_price_source=key_price_source,
        sell_fee_rate=sell_fee_rate,
        result=result,
        rarity_coverage=rarity_coverage,
        priced_outcomes=priced_count,
        total_outcomes=len(variant_list),
        missing_market_names=tuple(sorted(missing_names)),
        wear_basis_coverage=dict(basis_probability),
        wear_volume_source=snapshot.source,
        publication_ready=publication_ready,
        source=snapshot.source,
        currency=snapshot.currency,
        price_type=snapshot.price_type,
        observed_at=snapshot.observed_at,
        observation_span_seconds=snapshot.observation_span_seconds,
        catalog_commit=case.catalog_commit,
        catalog_repository=case.catalog_repository,
    )


def required_market_names(
    case: CaseDefinition, variants: Iterable[MarketVariant]
) -> tuple[str, ...]:
    return tuple(
        sorted({case.name, *(variant.market_hash_name for variant in variants)})
    )


def _item_wears(item: CatalogItem) -> tuple[str | None, ...]:
    if item.min_float is None and item.max_float is None:
        return (None,)
    if item.min_float is None or item.max_float is None:
        raise ValueError(f"item {item.id} has incomplete float bounds")
    wears = reachable_wears(item.min_float, item.max_float)
    unknown = set(wears) - set(item.wears)
    if unknown:
        raise ValueError(
            f"float range of {item.id} reaches grades missing from the catalogue: "
            f"{sorted(unknown)}"
        )
    return wears


def _wear_split(
    item: CatalogItem, wear_weights: Mapping[str, WearWeights]
) -> tuple[dict[str | None, float], str]:
    if item.min_float is None and item.max_float is None:
        return {None: 1.0}, BASIS_OBSERVED_VOLUME
    weights = wear_weights.get(item.id)
    if weights is None:
        raise ValueError(f"no wear weights supplied for item {item.id}")
    split = {
        wear: weight for wear, weight in weights.weights.items() if weight > 0
    }
    if not split:
        raise ValueError(f"wear weights for {item.id} are all zero")
    return split, weights.basis


def _exact_market_name(item: CatalogItem, *, wear: str | None, stattrak: bool) -> str:
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
