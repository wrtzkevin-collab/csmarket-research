"""Wear weighting from observed market activity, with a declared fallback.

Valve documents that a random wear value is chosen inside a finish's range but
has never published the sampling distribution.  Earlier versions of this project
therefore compared two *theoretical* densities.  Measured against a real case
the two answers differed by well under two percentage points of expected ROI,
which is far smaller than the uncertainty introduced by prices, so paying for
that machinery with a pile of unfalsifiable assumptions was a bad trade.

This module replaces the guessing with an observation wherever the market
supplies one.  Each wear grade of a skin is a separate market listing with its
own sales volume, so the volume split across an item's grades is a directly
measured quantity.  It is a proxy, not a drop rate: holders sell grades at
different rates, so pristine grades are likely under-represented relative to how
often they drop.  It is nonetheless an observation with a timestamp and a
source, which an assumed density is not.

When the market is too thin to measure -- typically the illiquid knives, which
are also the highest-value outcomes -- the uniform density over the skin's
allowed float range is used instead and the result is labelled as such.  Callers
are expected to report how much probability mass rests on each basis rather than
presenting a mixed result as uniformly observed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import fsum, isclose, isfinite


VALVE_WEAR_RANGE_SOURCE_URL = "https://www.counter-strike.net/workshop/workshopfinishes"

BASIS_OBSERVED_VOLUME = "observed_volume"
BASIS_OBSERVED_LISTINGS = "observed_listings"
BASIS_UNIFORM_FALLBACK = "uniform_fallback"

OBSERVED_BASES = frozenset({BASIS_OBSERVED_VOLUME, BASIS_OBSERVED_LISTINGS})

# The market's own wear boundaries on the final float value.
WEAR_INTERVALS: tuple[tuple[str, float, float], ...] = (
    ("Factory New", 0.00, 0.07),
    ("Minimal Wear", 0.07, 0.15),
    ("Field-Tested", 0.15, 0.38),
    ("Well-Worn", 0.38, 0.45),
    ("Battle-Scarred", 0.45, 1.00),
)

WEAR_LABELS: tuple[str, ...] = tuple(label for label, _, _ in WEAR_INTERVALS)

# Below this many observed sales across an item's grades the split is noise, so
# the uniform fallback is used instead of pretending to have measured anything.
DEFAULT_MIN_TOTAL_VOLUME = 20


@dataclass(frozen=True, slots=True)
class WearWeights:
    """Wear-grade weights plus the evidence they rest on.

    ``weights`` sums to one across the grades the skin's float range can
    actually produce.  ``basis`` names the evidence, and ``observed_volume`` is
    the total sales count behind an observed split, or ``None`` for a fallback.
    """

    weights: dict[str, float]
    basis: str
    observed_volume: int | None
    source_url: str

    @property
    def assumption(self) -> bool:
        """True when no measurement was available and uniform was assumed."""

        return self.basis == BASIS_UNIFORM_FALLBACK


def reachable_wears(min_float: float, max_float: float) -> tuple[str, ...]:
    """Return the wear grades a skin's float range can actually produce."""

    return tuple(
        label
        for label, weight in uniform_wear_weights(min_float, max_float).items()
        if weight > 0
    )


def uniform_wear_weights(min_float: float, max_float: float) -> dict[str, float]:
    """Integrate a uniform float density over the market's wear boundaries.

    The latent value is uniform on the skin's own ``[min_float, max_float]``
    range, so each grade's weight is the fraction of that range it covers.
    Grades the range cannot reach are exactly zero rather than a small residue.
    """

    minimum, maximum = _validate_float_range(min_float, max_float)
    span = maximum - minimum
    weights = {
        label: max(0.0, min(upper, maximum) - max(lower, minimum)) / span
        for label, lower, upper in WEAR_INTERVALS
    }

    total = fsum(weights.values())
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError(f"uniform wear weights sum to {total:.12g}")
    # Correct accumulated floating-point error in the widest non-zero grade so
    # that impossible grades stay exactly zero.
    widest = max(weights, key=weights.__getitem__)
    weights[widest] += 1.0 - total
    return weights


def calculate_wear_weights(
    min_float: float,
    max_float: float,
    *,
    volumes: Mapping[str, int | None] | None = None,
    min_total_volume: int = DEFAULT_MIN_TOTAL_VOLUME,
    volume_source_url: str = "",
    basis: str = BASIS_OBSERVED_VOLUME,
) -> WearWeights:
    """Weight an item's wear grades by observed volume where the data allows.

    ``volumes`` maps wear label to that listing's observed sales count.  Only
    grades the float range can reach are considered, so a stray observation on
    an impossible grade cannot leak probability into it.  Falls back to the
    uniform density when the observed total is below ``min_total_volume``.
    """

    if min_total_volume < 1:
        raise ValueError("min_total_volume must be at least 1")
    if basis not in OBSERVED_BASES:
        raise ValueError(
            f"unknown observed basis {basis!r}; expected one of {sorted(OBSERVED_BASES)}"
        )

    uniform = uniform_wear_weights(min_float, max_float)
    reachable = {label for label, weight in uniform.items() if weight > 0}

    observed = _usable_volumes(volumes, reachable)
    total = sum(observed.values())
    if total < min_total_volume:
        return WearWeights(
            weights=uniform,
            basis=BASIS_UNIFORM_FALLBACK,
            observed_volume=total or None,
            source_url=VALVE_WEAR_RANGE_SOURCE_URL,
        )

    weights = {
        label: (observed.get(label, 0) / total if label in reachable else 0.0)
        for label in WEAR_LABELS
    }
    return WearWeights(
        weights=weights,
        basis=basis,
        observed_volume=total,
        source_url=volume_source_url,
    )


def _usable_volumes(
    volumes: Mapping[str, int | None] | None, reachable: Iterable[str]
) -> dict[str, int]:
    if not volumes:
        return {}
    allowed = set(reachable)
    usable: dict[str, int] = {}
    for label, value in volumes.items():
        if label not in allowed or value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"volume for {label!r} must be a non-negative integer")
        if value:
            usable[label] = value
    return usable


def _validate_float_range(min_float: float, max_float: float) -> tuple[float, float]:
    if isinstance(min_float, bool) or not isinstance(min_float, (int, float)):
        raise TypeError("min_float must be a real number")
    if isinstance(max_float, bool) or not isinstance(max_float, (int, float)):
        raise TypeError("max_float must be a real number")

    minimum = float(min_float)
    maximum = float(max_float)
    if not isfinite(minimum) or not isfinite(maximum):
        raise ValueError("min_float and max_float must be finite")
    if not 0.0 <= minimum < maximum <= 1.0:
        raise ValueError("float range must satisfy 0 <= min_float < max_float <= 1")
    return minimum, maximum
