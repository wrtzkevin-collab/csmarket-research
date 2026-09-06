"""Core expected-value model for case-opening outcomes.

All monetary values must use the same currency.  Missing prices are represented
by ``gross_value=None``.  They reduce ``probability_coverage`` and are never
silently reweighted into the priced part of the outcome distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Iterable


DEFAULT_PROBABILITY_TOLERANCE = 1e-6


def _require_finite_non_negative(value: float, field_name: str) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be a finite, non-negative number")


@dataclass(frozen=True, slots=True)
class Outcome:
    """One mutually exclusive result in a case's full outcome distribution.

    ``sell_fee_rate`` is a fraction of sale value, so 0.15 means a 15% fee.
    A value of ``None`` means that no selling fee is applied.  A missing market
    price belongs in ``gross_value`` as ``None``; it must not be replaced by
    zero or removed from the distribution.
    """

    name: str
    probability: float
    gross_value: float | None
    sell_fee_rate: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")

        if not isfinite(self.probability) or not 0 <= self.probability <= 1:
            raise ValueError("probability must be a finite number from 0 to 1")

        if self.gross_value is not None:
            _require_finite_non_negative(self.gross_value, "gross_value")

        if self.sell_fee_rate is not None and (
            not isfinite(self.sell_fee_rate) or not 0 <= self.sell_fee_rate <= 1
        ):
            raise ValueError("sell_fee_rate must be a finite number from 0 to 1")

    @property
    def net_value(self) -> float | None:
        """Sale proceeds after this outcome's fee, or ``None`` if unpriced."""

        if self.gross_value is None:
            return None
        return self.gross_value * (1 - (self.sell_fee_rate or 0.0))


@dataclass(frozen=True, slots=True)
class EVResult:
    """Summary statistics calculated without renormalizing missing prices."""

    gross_ev: float
    total_cost: float
    gross_return_ratio: float
    net_ev: float
    expected_net_roi: float
    loss_probability: float
    probability_coverage: float


def calculate_ev(
    outcomes: Iterable[Outcome],
    *,
    case_price: float,
    key_price: float = 0.0,
    opening_fee: float = 0.0,
    probability_tolerance: float = DEFAULT_PROBABILITY_TOLERANCE,
) -> EVResult:
    """Calculate expected return and loss risk for a complete outcome set.

    ``gross_ev`` is expected sale value before fees.  ``net_ev`` is expected
    sale proceeds after each outcome's optional fee.  The return measures are::

        gross_return_ratio = gross_ev / total_cost
        expected_net_roi = (net_ev - total_cost) / total_cost

    Unpriced outcomes contribute neither value nor a loss classification.  Their
    original probability remains visible through ``probability_coverage``.  This
    makes every reported estimate conservative and, more importantly, prevents
    incomplete data from being presented as a complete valuation.
    """

    _require_finite_non_negative(case_price, "case_price")
    _require_finite_non_negative(key_price, "key_price")
    _require_finite_non_negative(opening_fee, "opening_fee")
    _require_finite_non_negative(probability_tolerance, "probability_tolerance")

    outcome_list = tuple(outcomes)
    if not outcome_list:
        raise ValueError("outcomes must not be empty")
    if not all(isinstance(outcome, Outcome) for outcome in outcome_list):
        raise TypeError("every outcome must be an Outcome")

    total_probability = sum(outcome.probability for outcome in outcome_list)
    if not isclose(
        total_probability,
        1.0,
        rel_tol=0.0,
        abs_tol=probability_tolerance,
    ):
        raise ValueError(
            "outcome probabilities must sum to 1 "
            f"(got {total_probability:.12g}, tolerance {probability_tolerance:g})"
        )

    total_cost = case_price + key_price + opening_fee
    if total_cost <= 0:
        raise ValueError("total_cost must be greater than zero")

    priced_outcomes = tuple(
        outcome for outcome in outcome_list if outcome.gross_value is not None
    )
    probability_coverage = sum(
        outcome.probability for outcome in priced_outcomes
    )
    gross_ev = sum(
        outcome.probability * outcome.gross_value
        for outcome in priced_outcomes
        if outcome.gross_value is not None
    )
    net_ev = sum(
        outcome.probability * outcome.net_value
        for outcome in priced_outcomes
        if outcome.net_value is not None
    )
    loss_probability = sum(
        outcome.probability
        for outcome in priced_outcomes
        if outcome.net_value is not None and outcome.net_value < total_cost
    )

    return EVResult(
        gross_ev=gross_ev,
        total_cost=total_cost,
        gross_return_ratio=gross_ev / total_cost,
        net_ev=net_ev,
        expected_net_roi=(net_ev - total_cost) / total_cost,
        loss_probability=loss_probability,
        probability_coverage=probability_coverage,
    )
