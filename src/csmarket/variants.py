"""Atomic case outcomes after catalogue and probability expansion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketVariant:
    """One mutually exclusive outcome using a catalogue-supplied market name."""

    outcome_id: str
    market_hash_name: str
    probability: float
    rarity: str
    is_special: bool
    stattrak: bool
    wear: str | None
