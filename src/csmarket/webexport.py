"""Bridge between calculated valuations and the published research page.

The static page used to ship hand-written illustrative numbers that no part of
the pipeline produced, so nothing on it could be traced back to a calculation.
This module is the only supported way to fill it: it consumes real
``CaseValuation`` objects and writes the exact document the page reads, so the
site cannot silently drift away from the code that produced it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .catalog import CATALOG_COMMIT, CATALOG_LICENSE, CATALOG_REPOSITORY
from .pipeline import CaseValuation
from .probabilities import PROBABILITY_DISCLOSURE_URL
from .wear import (
    BASIS_OBSERVED_LISTINGS,
    BASIS_OBSERVED_VOLUME,
    BASIS_UNIFORM_FALLBACK,
)


WEB_SCHEMA_VERSION = "2.0"
DEFAULT_OUTPUT_PATH = Path("web/results.json")

SOURCE_LABELS: dict[str, str] = {
    "steam_community_market": "Steam Community Market",
    "skinport": "Skinport",
    "skinport_listings": "Skinport",
}

SOURCE_NOTES_BY_LOCALE: dict[str, dict[str, str]] = {
    "zh-CN": {
        "steam_community_market": (
            "V 社自己市场上的最低挂单价。能交易的东西它全都有，覆盖最全；"
            "但 Steam 余额提不出来，而且挂着的价不等于卖掉的价。"
        ),
        "skinport": (
            "第三方现金市场近一个月的成交价中位数。这笔钱能提现，"
            "但最近没人买卖的东西就查不到价，会把覆盖率拉下来。"
        ),
        "skinport_listings": (
            "同一个现金市场上当前最低的挂单价。冷门东西基本都有人挂着，"
            "所以比成交价能覆盖多得多；代价是挂着不等于卖得掉，要价通常偏高。"
        ),
    }
}

PROBABILITY_NOTE_BY_LOCALE: dict[str, str] = {
    "zh-CN": (
        "官方公示的各档稀有度掉落概率，以及 StatTrak 的条件概率。"
        "这份公示是 2017 年国服发的，直接拿来套现在的版本，是本项目没能独立核实的一个假设。"
    )
}

PROBABILITY_NAME_BY_LOCALE: dict[str, str] = {
    "zh-CN": "反恐精英官方概率公示"
}

CATALOG_NOTE_BY_LOCALE: dict[str, str] = {
    "zh-CN": (
        "社区维护的数据，不是 V 社官方接口。普通皮肤是机器人从游戏文件里扒出来的；"
        "刀和手套属于哪个箱子则是人工整理的，得逐箱核对。"
    )
}

SOURCE_NOTES: dict[str, str] = {
    "steam_community_market": (
        "Lowest current ask on Valve's own market. It lists every tradable "
        "variant, so coverage is high, but Steam balance cannot be withdrawn "
        "as cash and an ask is not a completed sale."
    ),
    "skinport": (
        "Median completed sale on a cash market over the selected window. "
        "Proceeds are withdrawable, but items with no recent sale have no "
        "price and lower the coverage."
    ),
    "skinport_listings": (
        "Cheapest current listing on the same cash market. It covers far more "
        "of the tail than completed sales do, because an item can be listed on "
        "a day nobody buys it, but an asking price is not a sale."
    ),
}

SOURCE_URLS: dict[str, str] = {
    "steam_community_market": "https://steamcommunity.com/market/",
    "skinport": "https://docs.skinport.com/",
    "skinport_listings": "https://docs.skinport.com/",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _basis_percentages(valuation: CaseValuation) -> dict[str, float]:
    """Split probability mass by the evidence its wear weighting rested on.

    Both observed bases are reported separately and also summed, so a reader
    sees at a glance how much of the estimate was measured at all without
    having to know which count the crawl happened to obtain.
    """

    coverage = valuation.wear_basis_coverage
    listings = coverage.get(BASIS_OBSERVED_LISTINGS, 0.0)
    volume = coverage.get(BASIS_OBSERVED_VOLUME, 0.0)
    return {
        "observed_listings": listings,
        "observed_volume": volume,
        "observed_total": listings + volume,
        "uniform_fallback": coverage.get(BASIS_UNIFORM_FALLBACK, 0.0),
    }


def valuation_to_web_entry(valuation: CaseValuation) -> dict[str, Any]:
    """Flatten one valuation into the shape the page renders per source."""

    result = valuation.result
    return {
        "source": valuation.source,
        "source_label": SOURCE_LABELS.get(valuation.source, valuation.source),
        "price_type": valuation.price_type,
        "currency": valuation.currency,
        "observed_at": valuation.observed_at,
        "observation_span_seconds": valuation.observation_span_seconds,
        "case_price": valuation.case_price,
        "key_price": valuation.key_price,
        "opening_cost": result.total_cost,
        "gross_expected_value": result.gross_ev,
        "net_expected_value": result.net_ev,
        "gross_return_ratio": result.gross_return_ratio,
        # The same fact as expected_net_roi, stated as a share rather than a
        # change: "you get 26% of your money back" instead of "you lose 74%".
        # Neither is softer than the other; a table of nothing but minus signs
        # is just harder to read than one that also says what comes back.
        "net_return_ratio": (
            result.net_ev / result.total_cost if result.total_cost else None
        ),
        "expected_net_roi": result.expected_net_roi,
        "loss_probability": result.loss_probability,
        "loss_probability_is_lower_bound": result.probability_coverage < 1,
        "coverage": result.probability_coverage,
        "coverage_by_rarity": valuation.rarity_coverage,
        "priced_outcomes": valuation.priced_outcomes,
        "total_outcomes": valuation.total_outcomes,
        "missing_count": len(valuation.missing_market_names),
        "thin_ev_share": valuation.thin_ev_share,
        "thin_depth": valuation.thin_depth,
        "publication_ready": valuation.publication_ready,
        "wear_basis": _basis_percentages(valuation),
    }


def build_web_document(
    valuations: Iterable[CaseValuation],
    *,
    label: str = "Live snapshot",
    generated_at: str | None = None,
    display_names: Mapping[str, str] | None = None,
    locale: str = "en",
) -> dict[str, Any]:
    """Group valuations by case and attach the provenance the page displays."""

    grouped: dict[str, list[CaseValuation]] = {}
    order: list[str] = []
    for valuation in valuations:
        if valuation.case_name not in grouped:
            grouped[valuation.case_name] = []
            order.append(valuation.case_name)
        grouped[valuation.case_name].append(valuation)
    if not order:
        raise ValueError("at least one valuation is required")

    # The market key stays English because that is what the venues index on;
    # the localized name is presentation only, and falls back to the key rather
    # than to a guess when the catalogue has no string for it.
    names = display_names or {}
    localized_notes = SOURCE_NOTES_BY_LOCALE.get(locale, {})
    cases = [
        {
            "name": case_name,
            "display_name": names.get(case_name, case_name),
            "sources": [
                valuation_to_web_entry(valuation) for valuation in grouped[case_name]
            ],
        }
        for case_name in order
    ]

    every = [valuation for group in grouped.values() for valuation in group]
    currencies = sorted({valuation.currency for valuation in every})
    observed = sorted({valuation.observed_at for valuation in every})
    source_ids = list(dict.fromkeys(valuation.source for valuation in every))

    return {
        "schema_version": WEB_SCHEMA_VERSION,
        "dataset": {
            "label": label,
            "mode": "live",
            "currency": currencies[0] if len(currencies) == 1 else "mixed",
            "observed_at": observed[-1],
            "generated_at": generated_at or _utc_now(),
            "case_count": len(cases),
            "locale": locale,
        },
        "sources": [
            {
                "id": source_id,
                "name": SOURCE_LABELS.get(source_id, source_id),
                "url": SOURCE_URLS.get(source_id, ""),
                "basis": localized_notes.get(
                    source_id, SOURCE_NOTES.get(source_id, "")
                ),
            }
            for source_id in source_ids
        ],
        "probability_source": {
            "name": PROBABILITY_NAME_BY_LOCALE.get(
                locale, "Counter-Strike official rarity disclosure"
            ),
            "url": PROBABILITY_DISCLOSURE_URL,
            "basis": PROBABILITY_NOTE_BY_LOCALE.get(
                locale,
                "Published rarity probabilities and the conditional StatTrak "
                "probability. Issued for the Chinese release in 2017; its "
                "applicability to the current global build is an assumption "
                "this project has not independently verified.",
            ),
        },
        "catalog_source": {
            "name": "ByMykel/CSGO-API",
            "url": CATALOG_REPOSITORY,
            "commit": CATALOG_COMMIT,
            "license": CATALOG_LICENSE,
            "basis": CATALOG_NOTE_BY_LOCALE.get(
                locale,
                "Community maintained, not a Valve API. Ordinary skins are "
                "parsed from the game manifest; the rare-special pools are "
                "curated by hand and need per-case checking.",
            ),
        },
        "assumptions": [
            "Opening cost is the case price plus one key. Deposit, withdrawal "
            "and currency-conversion costs are excluded.",
            "Net expected value applies one stated seller fee to every outcome. "
            "Real fees vary by venue and account.",
            "Items inside a rarity tier are treated as equally likely, as the "
            "official disclosure states.",
            "Wear grades are weighted by observed sales volume where the market "
            "is liquid enough to measure, and by a uniform float density "
            "otherwise. Each case reports how much probability mass rests on "
            "each basis.",
            "Sales volume measures turnover, not drop frequency. Grades that "
            "holders keep rather than sell are under-represented.",
            "Outcomes with no price are excluded and reported through coverage. "
            "They are never treated as zero or redistributed.",
            "The key price is a configured constant, not a market observation.",
            "This is an analysis of opening a case. It says nothing about the "
            "future price of an unopened case.",
        ],
        "cases": cases,
    }


def write_web_document(
    document: dict[str, Any], path: Path | str = DEFAULT_OUTPUT_PATH
) -> Path:
    """Write the page's data document, creating parent directories."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def export_valuations(
    valuations: Sequence[CaseValuation],
    *,
    path: Path | str = DEFAULT_OUTPUT_PATH,
    label: str = "Live snapshot",
    display_names: Mapping[str, str] | None = None,
    locale: str = "en",
) -> Path:
    return write_web_document(
        build_web_document(
            valuations, label=label, display_names=display_names, locale=locale
        ),
        path,
    )
