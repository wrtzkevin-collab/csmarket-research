"""Command-line interface for reproducible calculations and source checks."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from .data_sources import SkinportClient
from .model import Outcome, calculate_ev


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
        "schema_version": "1.0",
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


def _run_calculate(args: argparse.Namespace) -> int:
    _print_json(calculate_file(Path(args.input)))
    return 0


def _run_skinport_price(args: argparse.Namespace) -> int:
    client = SkinportClient(timeout=args.timeout, max_retries=args.retries)
    if args.kind == "listing":
        wanted = set(args.names)
        rows = [
            row
            for row in client.fetch_items(currency=args.currency)
            if row["market_hash_name"] in wanted
        ]
    else:
        rows = client.fetch_sales_history(
            args.names,
            currency=args.currency,
            period=args.period,
            statistic=args.statistic,
        )
    _print_json(rows)
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
        "skinport-price", help="query documented Skinport price observations"
    )
    price_parser.add_argument("names", nargs="+", help="exact market hash name(s)")
    price_parser.add_argument("--currency", default="USD")
    price_parser.add_argument(
        "--kind", choices=("sales", "listing"), default="sales"
    )
    price_parser.add_argument(
        "--period",
        choices=("last_24_hours", "last_7_days", "last_30_days", "last_90_days"),
        default="last_30_days",
    )
    price_parser.add_argument(
        "--statistic", choices=("min", "max", "avg", "median"), default="median"
    )
    price_parser.add_argument("--timeout", type=float, default=15.0)
    price_parser.add_argument("--retries", type=int, default=2)
    price_parser.set_defaults(handler=_run_skinport_price)
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

