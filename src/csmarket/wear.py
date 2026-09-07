"""Auditable wear-probability models for case-generated CS2 skins.

Neither model in this module is a Valve-published probability distribution.
Valve documents that a random wear value is chosen within a finish's range, but
does not publish the sampling distribution.  ``uniform_allowed_range_v1`` is a
transparent uniform assumption.  ``csfloat_empirical_2020_v1`` implements the
piecewise-uniform distribution reported by CSFloat's 2020 observational study.

Both models use the common market wear boundaries 0, .07, .15, .38, .45, and
1.  A skin's final float is obtained by linearly mapping a latent value on
[0, 1] into its allowed [min_float, max_float] range.  Probabilities are then
calculated by integrating the resulting continuous density over the final
market wear intervals.  Vanilla items without a wear value are the caller's
responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isclose, isfinite


VALVE_WEAR_RANGE_SOURCE_URL = (
    "https://www.counter-strike.net/workshop/workshopfinishes"
)
CSFLOAT_EMPIRICAL_SOURCE_URL = (
    "https://blog.csfloat.com/analysis-of-float-value-and-paint-seed-"
    "distribution-in-cs-go/"
)

WEAR_INTERVALS: tuple[tuple[str, float, float], ...] = (
    ("Factory New", 0.00, 0.07),
    ("Minimal Wear", 0.07, 0.15),
    ("Field-Tested", 0.15, 0.38),
    ("Well-Worn", 0.38, 0.45),
    ("Battle-Scarred", 0.45, 1.00),
)


@dataclass(frozen=True, slots=True)
class _DensitySegment:
    """One uniform segment of a latent distribution on [0, 1]."""

    lower: float
    upper: float
    probability: float


@dataclass(frozen=True, slots=True)
class WearModel:
    """A continuous latent wear model plus its audit metadata.

    ``assumption`` is true for the unsupported uniform baseline and false for
    the CSFloat observational model.  False does not mean Valve-official; it
    only distinguishes empirical evidence from the explicit baseline
    assumption.
    """

    model_id: str
    source_url: str
    assumption: bool
    _segments: tuple[_DensitySegment, ...]

    def probabilities(
        self, min_float: float, max_float: float
    ) -> dict[str, float]:
        """Return final market wear-label probabilities for one skin range."""

        minimum, maximum = _validate_float_range(min_float, max_float)
        scale = maximum - minimum
        probabilities: dict[str, float] = {}

        for label, wear_lower, wear_upper in WEAR_INTERVALS:
            latent_lower = max(0.0, (wear_lower - minimum) / scale)
            latent_upper = min(1.0, (wear_upper - minimum) / scale)
            if latent_upper <= latent_lower:
                probabilities[label] = 0.0
                continue

            probabilities[label] = fsum(
                segment.probability
                * _overlap_length(
                    latent_lower,
                    latent_upper,
                    segment.lower,
                    segment.upper,
                )
                / (segment.upper - segment.lower)
                for segment in self._segments
            )

        total = fsum(probabilities.values())
        if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise RuntimeError(
                f"wear probabilities for {self.model_id!r} sum to {total:.12g}"
            )

        # Keep impossible labels exactly zero while correcting only accumulated
        # floating-point error in the largest non-zero interval.
        largest_label = max(probabilities, key=probabilities.__getitem__)
        probabilities[largest_label] += 1.0 - total
        return probabilities


@dataclass(frozen=True, slots=True)
class WearProbabilityResult:
    """Wear probabilities accompanied by the model's audit metadata."""

    model_id: str
    source_url: str
    assumption: bool
    probabilities: dict[str, float]


UNIFORM_ALLOWED_RANGE_MODEL = WearModel(
    model_id="uniform_allowed_range_v1",
    source_url=VALVE_WEAR_RANGE_SOURCE_URL,
    assumption=True,
    _segments=(_DensitySegment(0.0, 1.0, 1.0),),
)

CSFLOAT_EMPIRICAL_2020_MODEL = WearModel(
    model_id="csfloat_empirical_2020_v1",
    source_url=CSFLOAT_EMPIRICAL_SOURCE_URL,
    assumption=False,
    _segments=(
        _DensitySegment(0.00, 0.07, 0.03),
        _DensitySegment(0.07, 0.15, 0.24),
        _DensitySegment(0.15, 0.38, 0.33),
        _DensitySegment(0.38, 0.45, 0.24),
        _DensitySegment(0.45, 1.00, 0.16),
    ),
)

WEAR_MODELS: dict[str, WearModel] = {
    model.model_id: model
    for model in (UNIFORM_ALLOWED_RANGE_MODEL, CSFLOAT_EMPIRICAL_2020_MODEL)
}


def calculate_wear_probabilities(
    min_float: float,
    max_float: float,
    *,
    model_id: str,
) -> WearProbabilityResult:
    """Calculate market wear probabilities using a named, auditable model.

    The returned metadata makes the selected source and assumption status
    available to datasets, reports, and user interfaces without duplicating
    those facts at each call site.
    """

    try:
        model = WEAR_MODELS[model_id]
    except KeyError as error:
        raise ValueError(
            f"unknown wear model {model_id!r}; expected one of "
            f"{sorted(WEAR_MODELS)}"
        ) from error

    return WearProbabilityResult(
        model_id=model.model_id,
        source_url=model.source_url,
        assumption=model.assumption,
        probabilities=model.probabilities(min_float, max_float),
    )


def _validate_float_range(
    min_float: float, max_float: float
) -> tuple[float, float]:
    if isinstance(min_float, bool) or not isinstance(min_float, (int, float)):
        raise TypeError("min_float must be a real number")
    if isinstance(max_float, bool) or not isinstance(max_float, (int, float)):
        raise TypeError("max_float must be a real number")

    minimum = float(min_float)
    maximum = float(max_float)
    if not isfinite(minimum) or not isfinite(maximum):
        raise ValueError("min_float and max_float must be finite")
    if not 0.0 <= minimum < maximum <= 1.0:
        raise ValueError(
            "float range must satisfy 0 <= min_float < max_float <= 1"
        )
    return minimum, maximum


def _overlap_length(
    first_lower: float,
    first_upper: float,
    second_lower: float,
    second_upper: float,
) -> float:
    return max(0.0, min(first_upper, second_upper) - max(first_lower, second_lower))
