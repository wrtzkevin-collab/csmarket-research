"""Published rarity probabilities and transparent allocation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


# Standard key-opened weapon cases from the official China disclosure.
#
# The disclosure was published for the 2017 Chinese release.  Treating it as
# current for the global build is this project's largest single assumption: if
# these rates have changed, every downstream number changes with them.
PROBABILITY_DISCLOSURE_URL = (
    "https://www.csgo.com.cn/news/gamebroad/20170911/206155.html"
)
PROBABILITY_DISCLOSURE_PUBLISHED = "2017-09-11"

STANDARD_CASE_RARITY_PROBABILITIES: dict[str, float] = {
    "Mil-Spec": 0.79923,
    "Restricted": 0.15985,
    "Classified": 0.03197,
    "Covert": 0.00639,
    "Rare Special Item": 0.00256,
}

STATTRAK_CONDITIONAL_PROBABILITY = 0.10


def allocate_equal_within_rarity(
    items_by_rarity: Mapping[str, Sequence[str]],
    *,
    rarity_probabilities: Mapping[str, float] = STANDARD_CASE_RARITY_PROBABILITIES,
) -> dict[str, float]:
    """Allocate each rarity's mass equally across its named items.

    The official disclosure states that different items of the same quality are
    equally likely.  This helper intentionally stops before wear, float, pattern,
    or market-listing variants because the rarity disclosure does not define
    those distributions.
    """

    unknown = set(items_by_rarity) - set(rarity_probabilities)
    missing = set(rarity_probabilities) - set(items_by_rarity)
    if unknown:
        raise ValueError(f"unknown rarity names: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing rarity groups: {sorted(missing)}")

    allocation: dict[str, float] = {}
    for rarity, rarity_probability in rarity_probabilities.items():
        names = list(items_by_rarity[rarity])
        if not names:
            raise ValueError(f"rarity group {rarity!r} must contain at least one item")
        if len(set(names)) != len(names):
            raise ValueError(f"rarity group {rarity!r} contains duplicate item names")
        probability = rarity_probability / len(names)
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("item names must be non-empty strings")
            if name in allocation:
                raise ValueError(f"duplicate item name across rarity groups: {name}")
            allocation[name] = probability
    return allocation


def split_stattrak_probability(
    item_probability: float, *, eligible: bool
) -> tuple[float, float]:
    """Return normal and StatTrak probability for one already-allocated item."""

    if not 0 <= item_probability <= 1:
        raise ValueError("item_probability must be from 0 to 1")
    if not eligible:
        return item_probability, 0.0
    stattrak = item_probability * STATTRAK_CONDITIONAL_PROBABILITY
    return item_probability - stattrak, stattrak

