"""Atomic case outcomes after catalogue and probability expansion."""

from __future__ import annotations

from dataclasses import dataclass

from .wear import BASIS_OBSERVED_VOLUME


@dataclass(frozen=True, slots=True)
class MarketVariant:
    """One mutually exclusive outcome using a catalogue-supplied market name.

    ``wear_basis`` records whether this outcome's wear weight was measured from
    market volume or fell back to the uniform assumption, so a report can say
    how much of its probability mass rests on each.
    """

    outcome_id: str
    market_hash_name: str
    probability: float
    rarity: str
    is_special: bool
    stattrak: bool
    wear: str | None
    wear_basis: str = BASIS_OBSERVED_VOLUME
