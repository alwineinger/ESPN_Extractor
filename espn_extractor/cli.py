# SPDX-License-Identifier: GPL-3.0-or-later
"""
Command-line interface for ESPN Extractor.

Example:
    python -m espn_extractor.cli \
        --league-id 123456 \
        --start-year 2021 \
        --end-year 2024 \
        --out league_history.csv \
        --delimiter "," \
        --offline \
        --debug

For private leagues, set environment variables:
    export ESPN_S2="AECp....."
    export SWID="{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}"
"""

from __future__ import annotations

import argparse
import os
from typing import Optional

from espn_extractor.config import Config
from espn_extractor.league_history import extract_team_records


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return value


def _valid_delimiter(text: str) -> str:
    if len(text) == 0:
        raise argparse.ArgumentTypeError("delimiter must not be empty")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ESPN Fantasy league history extractor"
    )
    parser.add_argument(
        "--league-id",
        type=_positive_int,
        required=True,
        help="ESPN league id (integer).",
    )
    parser.add_argument(
        "--start-year",
        type=_positive_int,
        required=True,
        help="First season (e.g., 2019).",
    )
    parser.add_argument(
        "--end-year",
        type=_positive_int,
        required=True,
        help="Last season (inclusive).",
    )
    parser.add_argument(
        "--out",
        dest="out_file",
        type=str,
        required=True,
        help="Output file path (CSV or delimited text).",
    )
    parser.add_argument(
        "--delimiter",
        type=_valid_delimiter,
        default=",",
        help="Field delimiter (default: ',').",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Write deterministic, network-free sample rows for tests/dev.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable espn_api debug logging (passes debug=True to League).",
    )
    parser.add_argument(
        "--print-cookies",
        action="store_true",
        help="Echo whether ESPN_S2/SWID are set (for troubleshooting).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.print_cookies:
        espn_s2 = os.getenv("ESPN_S2")
        swid = os.getenv("SWID")
        msg = [
            f"ESPN_S2 set: {'yes' if espn_s2 else 'no'}",
            f"SWID set: {'yes' if swid else 'no'}",
        ]
        print(" | ".join(msg))

    config = Config.from_env(
        league_id=args.league_id,
        start_year=args.start_year,
        end_year=args.end_year,
        out_file=args.out_file,
        delimiter=args.delimiter,
        debug=bool(args.debug),
    )

    extract_team_records(config, test_mode=bool(args.offline))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())