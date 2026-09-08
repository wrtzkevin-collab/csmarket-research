"""Command-line interface for reproducible calculations and source checks."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from .cache import DEFAULT_CACHE_PATH, DEFAULT_MAX_AGE_HOURS
from .catalog import CaseCatalogClient
from .model import Outcome, calculate_ev
from .pipeline import (
    CaseValuation,
    candidate_market_names,
    expand_case_variants,
    snapshot_from_rows,
    value_case,
    wear_weights_for_case,
)
from .ranking import rank_cases, top_case_names
from .sources import SOURCE_IDS, SOURCE_SKINPORT, SOURCE_STEAM, build_cache, fetch_rows
from .wear import DEFAULT_MIN_TOTAL_VOLUME
from .webexport import DEFAULT_OUTPUT_PATH, build_web_document, write_web_document


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


def calculate_file(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    raw_outcomes = payload.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise ValueError("input must contain an outcomes array")

    outcomes: list[Outcome] = []
    for index, item in enumerate(raw_outcomes):
        if not isinstance(item, dict):
            raise ValueError(f"outcomes[{index}] must be an object")
        try:
            outcomes.append(
                Outcome(
                    name=item["name"],
                    probability=item["probability"],
                    gross_value=item.get("gross_value"),
                    sell_fee_rate=item.get("sell_fee_rate"),
                )
            )
        except KeyError as exc:
            raise ValueError(f"outcomes[{index}] is missing {exc.args[0]}") from exc

    result = calculate_ev(
        outcomes,
        case_price=payload.get("case_price", 0),
        key_price=payload.get("key_price", 0),
        opening_fee=payload.get("opening_fee", 0),
    )
    data = asdict(result)
    data["expected_net_roi_percent"] = result.expected_net_roi * 100
    data["gross_return_percent"] = result.gross_return_ratio * 100
    data["loss_probability_percent"] = result.loss_probability * 100
    data["probability_coverage_percent"] = result.probability_coverage * 100
    data["loss_probability_is_lower_bound"] = result.probability_coverage < 1

    return {
        "schema_version": "2.0",
        "case_name": payload.get("case_name"),
        "currency": payload.get("currency"),
        "source": payload.get("source"),
        "price_type": payload.get("price_type"),
        "observed_at": payload.get("observed_at"),
        "assumptions": payload.get("assumptions", []),
        "result": data,
    }


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _progress_reporter(source_id: str, enabled: bool):
    if not enabled:
        return None

    def report(index: int, total: int, name: str) -> None:
        end = "\n" if index == total else "\r"
        print(
            f"  [{source_id}] {index}/{total} {name[:52]:<52}",
            file=sys.stderr,
            end=end,
            flush=True,
        )

    return report


def _collection_tags(case) -> tuple[str, ...]:
    """Translate catalogue collection ids into Steam market item-set facets.

    "collection-set-community-33" is the same set Steam exposes as
    "tag_set_community_33", which is what allows a case's ordinary skins to be
    priced ten per request instead of one per request.
    """

    return tuple(
        "tag_" + identifier.removeprefix("collection-").replace("-", "_")
        for identifier in case.collection_ids
    )


def _run_calculate(args: argparse.Namespace) -> int:
    _print_json(calculate_file(Path(args.input)))
    return 0


def _run_price(args: argparse.Namespace) -> int:
    cache = build_cache(
        None if args.no_cache else args.cache, max_age_hours=args.max_age_hours
    )
    rows = fetch_rows(
        args.source,
        args.names,
        currency=args.currency,
        cache=cache,
        refresh=args.refresh,
        timeout=args.timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        period=args.period,
        statistic=args.statistic,
        progress=_progress_reporter(args.source, args.progress),
    )
    _print_json(rows)
    return 0


def _value_one_case(
    case_name: str,
    args: argparse.Namespace,
    sources: Sequence[str],
    catalog: CaseCatalogClient,
    cache,
) -> list[CaseValuation]:
    # The catalogue client caches its three downloads in memory, so it is shared
    # across cases rather than re-fetched several megabytes at a time per case.
    case = catalog.fetch_case(case_name)
    names = candidate_market_names(case)

    snapshots = {}
    for source_id in sources:
        rows = fetch_rows(
            source_id,
            names,
            currency=args.currency,
            cache=cache,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            request_interval=args.request_interval,
            period=args.period,
            statistic=args.statistic,
            collection_tags=_collection_tags(case),
            search_queries=case.rare_weapon_names,
            offline=args.offline,
            progress=_progress_reporter(source_id, args.progress),
        )
        snapshots[source_id] = snapshot_from_rows(rows, required_names=names)

    # Wear weights are measured once, from the venue with the deepest order
    # book, and reused for every valuation.  Deriving them per venue would make
    # the cross-venue comparison confound price differences with weighting
    # differences instead of isolating price.
    reference_id = SOURCE_STEAM if SOURCE_STEAM in snapshots else sources[0]
    weights = wear_weights_for_case(
        case, snapshots[reference_id], min_total_volume=args.min_wear_volume
    )
    variants = expand_case_variants(case, wear_weights=weights)

    valuations: list[CaseValuation] = []
    for source_id in sources:
        valuations.append(
            value_case(
                case,
                variants,
                snapshots[source_id],
                key_price=args.key_price,
                key_price_source=args.key_price_source,
                sell_fee_rate=args.sell_fee_rate,
            )
        )
    return valuations


def _run_rank_cases(args: argparse.Namespace) -> int:
    catalog = CaseCatalogClient(timeout=args.timeout, max_retries=args.retries)
    cache = build_cache(
        None if args.no_cache else args.cache, max_age_hours=args.max_age_hours
    )
    ranked = rank_cases(
        catalog,
        currency=args.currency,
        cache=cache,
        refresh=args.refresh,
        timeout=args.timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        volume_probe=args.volume_probe,
        progress=_progress_reporter("rank", args.progress),
    )
    _print_json(ranked[: args.limit] if args.limit else ranked)
    return 0


def _resolve_case_names(args: argparse.Namespace, catalog: CaseCatalogClient, cache):
    """Decide which cases to value: the busiest N, or the ones named."""

    if args.top:
        ranked = rank_cases(
            catalog,
            currency=args.currency,
            cache=cache,
            refresh=args.refresh,
            timeout=args.timeout,
            retries=args.retries,
            request_interval=args.request_interval,
            volume_probe=0,
            progress=_progress_reporter("rank", args.progress),
        )
        return top_case_names(ranked, args.top)
    if not args.case_names:
        raise ValueError("name at least one case, or pass --top N")
    return tuple(args.case_names)


def _run_analyze_case(args: argparse.Namespace) -> int:
    sources = list(SOURCE_IDS) if args.source == "both" else [args.source]
    catalog = CaseCatalogClient(timeout=args.timeout, max_retries=args.retries)
    cache = build_cache(
        None if args.no_cache else args.cache, max_age_hours=args.max_age_hours
    )
    # One unreachable case must not discard the cases that were priced. Each
    # is valued independently and a failure is reported rather than swallowed,
    # so a partial run publishes what it measured and says what it could not.
    valuations: list[CaseValuation] = []
    failures: list[tuple[str, str]] = []
    for case_name in _resolve_case_names(args, catalog, cache):
        try:
            valuations.extend(
                _value_one_case(case_name, args, sources, catalog, cache)
            )
        except (ValueError, RuntimeError) as error:
            failures.append((case_name, str(error)))
            print(f"skipped {case_name}: {error}", file=sys.stderr)

    if not valuations:
        raise ValueError(
            "no case could be valued: "
            + "; ".join(f"{name} ({reason})" for name, reason in failures)
        )

    if args.export_web:
        target = write_web_document(
            build_web_document(valuations, label=args.label), args.export_web
        )
        print(f"wrote {target}", file=sys.stderr)

    if len(valuations) == 1:
        _print_json(valuations[0].to_dict())
    else:
        _print_json(
            {
                "schema_version": "2.0",
                "comparison": "one valuation per case per venue",
                "results": [valuation.to_dict() for valuation in valuations],
            }
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csmarket",
        description="Transparent CS2 case expected-value research tools",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    calculate_parser = subparsers.add_parser(
        "calculate", help="calculate EV metrics from an explicit JSON outcome set"
    )
    calculate_parser.add_argument("input", help="path to an input JSON file")
    calculate_parser.set_defaults(handler=_run_calculate)

    price_parser = subparsers.add_parser(
        "price", help="query documented price observations from one venue"
    )
    price_parser.add_argument("names", nargs="+", help="exact market hash name(s)")
    price_parser.add_argument(
        "--source", choices=SOURCE_IDS, default=SOURCE_STEAM
    )
    price_parser.set_defaults(handler=_run_price)

    analysis_parser = subparsers.add_parser(
        "analyze-case",
        help="value one or more cases from the pinned catalogue and live prices",
    )
    analysis_parser.add_argument(
        "case_names", nargs="*", help="exact case market name(s)"
    )
    analysis_parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="value the N busiest cases by 24-hour volume instead of naming them",
    )
    analysis_parser.add_argument(
        "--source",
        choices=(*SOURCE_IDS, "both"),
        default="both",
        help="venue to value against; 'both' reports each separately",
    )
    analysis_parser.add_argument("--key-price", type=float, default=2.49)
    analysis_parser.add_argument(
        "--key-price-source",
        default="configured USD in-game key price; verify before use",
    )
    analysis_parser.add_argument("--sell-fee-rate", type=float, default=0.12)
    analysis_parser.add_argument(
        "--min-wear-volume",
        type=int,
        default=DEFAULT_MIN_TOTAL_VOLUME,
        help="observed sales needed before wear grades are volume-weighted",
    )
    analysis_parser.add_argument(
        "--export-web",
        nargs="?",
        const=str(DEFAULT_OUTPUT_PATH),
        default=None,
        metavar="PATH",
        help=f"also write the published page's data file (default {DEFAULT_OUTPUT_PATH})",
    )
    analysis_parser.add_argument(
        "--label", default="Live snapshot", help="dataset label shown on the page"
    )
    analysis_parser.set_defaults(handler=_run_analyze_case)

    rank_parser = subparsers.add_parser(
        "rank-cases",
        help="order every case by observed 24-hour trading volume",
    )
    rank_parser.add_argument(
        "--limit", type=int, default=None, help="report only the busiest N"
    )
    rank_parser.add_argument(
        "--volume-probe",
        type=int,
        default=0,
        metavar="N",
        help="also fetch 24-hour sales volume for the top N (one slow request each)",
    )
    rank_parser.set_defaults(handler=_run_rank_cases)

    for network_parser in (price_parser, analysis_parser, rank_parser):
        network_parser.add_argument("--currency", default="USD")
        network_parser.add_argument(
            "--cache",
            default=str(DEFAULT_CACHE_PATH),
            help="path to the on-disk observation cache",
        )
        network_parser.add_argument(
            "--no-cache", action="store_true", help="ignore and do not write the cache"
        )
        network_parser.add_argument(
            "--refresh", action="store_true", help="re-fetch even when cached"
        )
        network_parser.add_argument(
            "--offline",
            action="store_true",
            help="use only cached observations; contact no provider",
        )
        network_parser.add_argument(
            "--max-age-hours",
            type=float,
            default=float(DEFAULT_MAX_AGE_HOURS),
            help=(
                "treat cached observations older than this as missing; above "
                "the snapshot span limit a reused cache can be rejected as "
                "internally inconsistent"
            ),
        )
        network_parser.add_argument(
            "--request-interval",
            type=float,
            default=5.0,
            help="minimum seconds between Steam requests; Steam throttles sustained crawling",
        )
        network_parser.add_argument(
            "--period",
            choices=("last_24_hours", "last_7_days", "last_30_days", "last_90_days"),
            default="last_30_days",
            help="Skinport sales window",
        )
        network_parser.add_argument(
            "--statistic",
            choices=("min", "max", "avg", "median"),
            default="median",
            help="Skinport sales statistic",
        )
        network_parser.add_argument("--timeout", type=float, default=20.0)
        network_parser.add_argument("--retries", type=int, default=3)
        network_parser.add_argument(
            "--progress",
            action="store_true",
            help="report crawl progress on stderr",
        )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
