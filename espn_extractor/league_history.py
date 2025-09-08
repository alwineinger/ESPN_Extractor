# SPDX-License-Identifier: GPL-3.0-or-later
"""
League history extraction.

Production mode:
    - Pulls team history from ESPN via `espn_api`, one season at a time.
    - If a given season fails (403/404/rate-limit), it logs and skips that season.
    - It still writes the output file (at least the header), so prod runs
      don't silently produce nothing.

Test/offline mode:
    - Writes deterministic sample rows (no network) so tests don't flake when
      ESPN changes endpoints, rate-limits, or removes old seasons.

Public API:
    extract_team_records(config, test_mode=False)
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from typing import Iterable, Dict, Any, List, Optional

try:
    # espn_api is only required for production pulls
    from espn_api.football import League as FF_LEAGUE  # type: ignore
except ImportError:  # pragma: no cover - not needed for tests
    FF_LEAGUE = None  # type: ignore[assignment]


# ----------------------------
# Offline / test-mode fixture
# ----------------------------

# This sample mirrors a known 2018-like snapshot to keep tests stable.
_SAMPLE_HISTORY_2018: Iterable[Dict[str, Any]] = [
    {
        "owner": "jessie marshall",
        "year": 2018,
        "team_name": "Team 1",
        "win": 10,
        "loss": 3,
        "draws": 0,
        "final_standing": 4,
        "points_for": 1276.88,
        "points_against": 1038.22,
        "acquisitions": 21,
        "trades": 1,
        "drops": 22,
        "streak_length": 1,
        "streak_type": "WIN",
        "playoff_seed": 2,
    },
    {
        "owner": "Bailey Zambuto",
        "year": 2018,
        "team_name": "Team 2",
        "win": 6,
        "loss": 7,
        "draws": 0,
        "final_standing": 6,
        "points_for": 1019.6,
        "points_against": 1028.58,
        "acquisitions": 0,
        "trades": 0,
        "drops": 0,
        "streak_length": 1,
        "streak_type": "LOSS",
        "playoff_seed": 6,
    },
    {
        "owner": "Jhonatan De la Cruz",
        "year": 2018,
        "team_name": "FANTASY GOD",
        "win": 2,
        "loss": 11,
        "draws": 0,
        "final_standing": 7,
        "points_for": 884.18,
        "points_against": 1151.84,
        "acquisitions": 1,
        "trades": 0,
        "drops": 1,
        "streak_length": 3,
        "streak_type": "LOSS",
        "playoff_seed": 10,
    },
    {
        "owner": "Leon Law",
        "year": 2018,
        "team_name": "THE KING",
        "win": 8,
        "loss": 5,
        "draws": 0,
        "final_standing": 2,
        "points_for": 1058.88,
        "points_against": 1075.06,
        "acquisitions": 0,
        "trades": 0,
        "drops": 0,
        "streak_length": 3,
        "streak_type": "WIN",
        "playoff_seed": 4,
    },
    {
        "owner": "Eddie Rivera",
        "year": 2018,
        "team_name": "Team 5",
        "win": 4,
        "loss": 9,
        "draws": 0,
        "final_standing": 10,
        "points_for": 1006.94,
        "points_against": 1149.5,
        "acquisitions": 0,
        "trades": 0,
        "drops": 0,
        "streak_length": 1,
        "streak_type": "WIN",
        "playoff_seed": 9,
    },
    {
        "owner": "Tresa Omara",
        "year": 2018,
        "team_name": "Team Viking Queen",
        "win": 5,
        "loss": 8,
        "draws": 0,
        "final_standing": 5,
        "points_for": 1139.74,
        "points_against": 1252.62,
        "acquisitions": 41,
        "trades": 0,
        "drops": 41,
        "streak_length": 1,
        "streak_type": "LOSS",
        "playoff_seed": 8,
    },
    {
        "owner": "james czarnowski",
        "year": 2018,
        "team_name": "Team 7",
        "win": 10,
        "loss": 3,
        "draws": 0,
        "final_standing": 3,
        "points_for": 1344.8,
        "points_against": 1071.9,
        "acquisitions": 16,
        "trades": 1,
        "drops": 15,
        "streak_length": 4,
        "streak_type": "WIN",
        "playoff_seed": 1,
    },
    {
        "owner": "Michael Dungo",
        "year": 2018,
        "team_name": "Team 8",
        "win": 9,
        "loss": 4,
        "draws": 0,
        "final_standing": 1,
        "points_for": 1402.72,
        "points_against": 1191.54,
        "acquisitions": 30,
        "trades": 0,
        "drops": 30,
        "streak_length": 1,
        "streak_type": "LOSS",
        "playoff_seed": 3,
    },
    {
        "owner": "Lisa Mizrachi",
        "year": 2018,
        "team_name": "Team Mizrachi",
        "win": 6,
        "loss": 7,
        "draws": 0,
        "final_standing": 8,
        "points_for": 1070.94,
        "points_against": 1281.2,
        "acquisitions": 0,
        "trades": 0,
        "drops": 0,
        "streak_length": 1,
        "streak_type": "WIN",
        "playoff_seed": 5,
    },
    {
        "owner": "Wes Harris",
        "year": 2018,
        "team_name": "Team 10",
        "win": 5,
        "loss": 8,
        "draws": 0,
        "final_standing": 9,
        "points_for": 1278.92,
        "points_against": 1243.14,
        "acquisitions": 21,
        "trades": 0,
        "drops": 21,
        "streak_length": 2,
        "streak_type": "LOSS",
        "playoff_seed": 7,
    },
]

_HEADERS: List[str] = [
    "owner",
    "year",
    "team_name",
    "win",
    "loss",
    "draws",
    "final_standing",
    "points_for",
    "points_against",
    "acquisitions",
    "trades",
    "drops",
    "streak_length",
    "streak_type",
    "playoff_seed",
]


@dataclass
class _ConfigLike:
    league_id: int
    start_year: int
    end_year: int
    out_file: str
    delimiter: str = ","
    espn_s2: Optional[str] = None
    swid: Optional[str] = None
    debug: bool = False


def _write_rows(path: str, delimiter: str, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as out_file_handle:
        writer = csv.DictWriter(out_file_handle, fieldnames=_HEADERS, delimiter=delimiter)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_offline_fixture(config: _ConfigLike) -> None:
    _write_rows(config.out_file, config.delimiter, _SAMPLE_HISTORY_2018)


def _safe_str(value: Any) -> str:
    """Convert owner/owners value into a readable string."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(x) for x in value)
    return str(value)


def _resolve_owner(team: Any) -> str:
    """
    Different espn_api versions expose ownership differently. Try a few.
    """
    candidates: List[Optional[Any]] = [
        getattr(team, "owner", None),
        getattr(team, "owners", None),
        getattr(team, "primary_owner", None),
        getattr(team, "primaryOwner", None),
    ]
    for cand in candidates:
        if cand:
            return _safe_str(cand)
    return ""


def _resolve_team_name(team: Any) -> str:
    return (
        getattr(team, "team_name", None)
        or getattr(team, "teamName", None)
        or getattr(team, "name", "")
    )


def _iter_production_rows(config: _ConfigLike) -> Iterable[Dict[str, Any]]:  # pragma: no cover
    """
    Generator that pulls from espn_api in production mode.
    Skips seasons that error while still yielding other years.
    """
    if FF_LEAGUE is None:
        raise RuntimeError(
            "espn_api is not available. Install it or run with test_mode=True."
        )

    for year in range(config.start_year, config.end_year + 1):
        try:
            league = FF_LEAGUE(
                league_id=config.league_id,
                year=year,
                espn_s2=config.espn_s2,
                swid=config.swid,
                fetch_league=False,
                debug=config.debug,
            )
            league.fetch_league()  # explicit fetch so we can control failures
        except Exception as exc:
            print(
                f"[league_history] Skipping {year}: failed to fetch league ({exc})",
                file=sys.stderr,
            )
            continue

        for team in getattr(league, "teams", []):
            yield {
                "owner": _resolve_owner(team),
                "year": year,
                "team_name": _resolve_team_name(team),
                "win": getattr(team, "wins", 0),
                "loss": getattr(team, "losses", 0),
                "draws": getattr(team, "ties", 0),
                "final_standing": getattr(
                    team, "final_standing", getattr(team, "finalStanding", 0)
                ),
                "points_for": getattr(team, "points_for", 0.0),
                "points_against": getattr(team, "points_against", 0.0),
                "acquisitions": getattr(team, "acquisitions", 0),
                "trades": getattr(team, "trades", 0),
                "drops": getattr(team, "drops", 0),
                "streak_length": getattr(team, "streak_length", 0),
                "streak_type": getattr(
                    team, "streak_type", getattr(team, "streakType", "")
                ),
                "playoff_seed": getattr(
                    team, "playoff_seed", getattr(team, "playoffSeed", 0)
                ),
            }


def extract_team_records(config: _ConfigLike, test_mode: bool = False) -> None:
    """
    Write a CSV (or pipe-delimited) file of league history rows.

    Args:
        config: object with league_id, start_year, end_year, out_file, delimiter,
                espn_s2, swid, debug.
        test_mode: when True, do NOT access the ESPN API; emit a stable offline fixture.

    Behavior:
        - Always writes the file (at least the header).
        - In production mode, seasons that fail are logged and skipped.

    Raises:
        RuntimeError if espn_api is unavailable in production mode.
    """
    print("Extracting ESPN Data")

    # Older config styles used by tests provide ``output_dir``/``history_file``
    # instead of ``out_file``/``delimiter``.  Normalize here so the rest of the
    # function can rely on these attributes regardless of input style.
    if not getattr(config, "out_file", None):
        output_dir = getattr(config, "output_dir", "")
        history_file = getattr(config, "history_file", "league_history.csv")
        config.out_file = os.path.join(output_dir, history_file)  # type: ignore[attr-defined]
    if not getattr(config, "delimiter", None):
        config.delimiter = getattr(config, "format", ",")  # type: ignore[attr-defined]

    if test_mode:
        print(f"Writing offline fixture to {config.out_file}")
        _write_offline_fixture(config)
        return

    print(f"Processing Years {config.start_year}-{config.end_year}")
    rows = list(_iter_production_rows(config))

    # Always write the file, even if rows is empty (header-only).
    _write_rows(config.out_file, config.delimiter, rows)
    print(f"Wrote {len(rows)} rows to {config.out_file}")