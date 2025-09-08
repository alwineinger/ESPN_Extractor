import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
from dateutil import tz

# TOML loader: stdlib on 3.11+, fallback to tomli on 3.9/3.10
try:
    import tomllib  # py311+
except ModuleNotFoundError:
    import tomli as tomllib

from espn_api.football import League, constant


# --------------------------
# Config & IO helpers
# --------------------------

@dataclass
class Config:
    league_id: int
    season_year: int
    scoring_period: Optional[int]
    my_team_id: Optional[int]
    espn_s2: Optional[str]
    swid: Optional[str]
    out_dir: str
    write_xlsx: bool
    xlsx_path: str
    start_sit_threshold: float
    per_pos_thresholds: Dict[str, float]
    lock_positions: List[str]
    free_agent_pool_size: int
    positions: List[str]
    projection_mode: str


def _as_float_scalar(v: Any, key_path: str = "value") -> float:
    """
    Accept numbers, numeric strings, or single-item lists/tuples of those.
    Raise a friendly error otherwise.
    """
    if isinstance(v, (list, tuple)) and v:
        v = v[0]
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            pass
    raise ValueError(f"{key_path} must be a number (got {type(v).__name__}: {v!r})")


def load_config(path: str = "config.toml") -> Config:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)

    league = cfg.get("league", {})
    auth = cfg.get("auth", {})
    out = cfg.get("output", {})
    advice = cfg.get("advice", {})
    per_pos = advice.get("per_position_thresholds", {}) or {}

    return Config(
        league_id=int(league["league_id"]),
        season_year=int(league["season_year"]),
        scoring_period=league.get("scoring_period"),
        my_team_id=league.get("my_team_id"),
        espn_s2=(auth.get("espn_s2") or None),
        swid=(auth.get("swid") or None),
        out_dir=out.get("dir", "espn_extractor/data"),
        write_xlsx=out.get("write_xlsx", True),
        xlsx_path=out.get("xlsx_path", "espn_extractor/data/league_export.xlsx"),
        start_sit_threshold=_as_float_scalar(advice.get("start_sit_threshold", 1.5), "advice.start_sit_threshold"),
        per_pos_thresholds={str(k): _as_float_scalar(v, f"advice.per_position_thresholds.{k}") for k, v in per_pos.items()},
        lock_positions=[str(p) for p in advice.get("advice_lock_positions", [])],
        free_agent_pool_size=int(advice.get("free_agent_pool_size", 50)),
        positions=list(advice.get("positions", ["QB", "RB", "WR", "TE", "D/ST", "K", "FLEX", "OP"])),
        projection_mode=str(advice.get("projection_mode", "league_plus_thresholds")),
    )


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def today_et_date_str() -> str:
    return datetime.now(tz.gettz("America/New_York")).strftime("%Y-%m-%d")


# --------------------------
# ESPN Client
# --------------------------

def make_league(cfg: Config) -> League:
    kwargs = dict(league_id=cfg.league_id, year=cfg.season_year)
    if cfg.espn_s2 and cfg.swid:
        kwargs["espn_s2"] = cfg.espn_s2
        kwargs["swid"] = cfg.swid
    return League(**kwargs)


# --------------------------
# Exporters
# --------------------------

def export_standings(league: League, out_dir: str) -> pd.DataFrame:
    rows = []
    for t in league.teams:
        rows.append({
            "team_id": t.team_id,
            "team_name": t.team_name,
            "wins": t.wins,
            "losses": t.losses,
            "ties": getattr(t, "ties", 0),
            "points_for": t.points_for,
            "points_against": t.points_against,
            "streak_length": getattr(t, "streak_length", None),
            "final_standing": getattr(t, "final_standing", None),
        })
    df = pd.DataFrame(rows).sort_values(["wins", "points_for"], ascending=[False, False]).reset_index(drop=True)
    df.to_csv(os.path.join(out_dir, "standings.csv"), index=False)
    return df


def export_matchups(league: League, out_dir: str, scoring_period: Optional[int]) -> pd.DataFrame:
    """Export matchup information for a given week.

    When ``scoring_period`` is ``None`` the ``espn_api`` library returns box
    scores for the league's current week, but the ``BoxScore`` objects don't
    expose the week number.  Previously we attempted to read a
    ``matchupPeriodId`` attribute, which doesn't exist and resulted in ``None``
    values for the ``week`` column in the exported CSV.  To ensure the week is
    always populated we explicitly determine the week using the ``League``
    object's ``current_week`` attribute when a specific ``scoring_period`` isn't
    provided.
    """

    week = scoring_period or getattr(league, "current_week", None)
    box_scores = league.box_scores(week)
    rows = []
    for bs in box_scores:
        home_proj = getattr(bs, "home_projected", None)
        if not home_proj:
            home_proj = sum(float(getattr(p, "projected_points", 0) or 0) for p in (bs.home_lineup or []))
        away_proj = getattr(bs, "away_projected", None)
        if not away_proj:
            away_proj = sum(float(getattr(p, "projected_points", 0) or 0) for p in (bs.away_lineup or []))
        rows.append({
            "week": week,
            "home_team_id": bs.home_team.team_id,
            "home_team_name": bs.home_team.team_name,
            "away_team_id": bs.away_team.team_id,
            "away_team_name": bs.away_team.team_name,
            "home_score": bs.home_score,
            "away_score": bs.away_score,
            "projected_home": float(home_proj),
            "projected_away": float(away_proj),
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, f"matchups_week_{week}.csv"), index=False)
    return df


def _player_to_row(p, team_id=None, week=None) -> Dict[str, Any]:
    # eligibleSlots can be list[str] or list[int] depending on espn_api version; normalize to strings
    elig = getattr(p, "eligibleSlots", None)
    if isinstance(elig, list):
        elig_str = ",".join(str(s) for s in elig)
    else:
        elig_str = ""

    return {
        "week": week,
        "on_team_id": team_id,
        "player_id": getattr(p, "playerId", None),
        "name": getattr(p, "name", None),
        "position": getattr(p, "position", None),
        "slot": getattr(p, "slot_position", None),
        "pro_team": getattr(p, "proTeam", None),
        "proj_points": float(getattr(p, "projected_points", 0) or 0),
        "actual_points": float(getattr(p, "points", 0) or 0),
        "injury_status": getattr(p, "injuryStatus", None) if hasattr(p, "injuryStatus") else None,
        "percent_owned": getattr(p, "percent_owned", None) if hasattr(p, "percent_owned") else None,
        "percent_started": getattr(p, "percent_started", None) if hasattr(p, "percent_started") else None,
        "eligible_slots": elig_str,
    }


def export_rosters(league: League, out_dir: str, scoring_period: Optional[int]) -> pd.DataFrame:
    """Export roster information for each team for a specific week.

    Similar to :func:`export_matchups`, we need the correct week value even
    when ``scoring_period`` is ``None``.  The previous implementation attempted
    to read a non-existent ``matchupPeriodId`` attribute from ``BoxScore``
    objects which resulted in ``None`` entries.  Instead we explicitly track the
    week and use it for every exported row.
    """

    week = scoring_period or getattr(league, "current_week", None)
    rows = []
    bs_list = league.box_scores(week)
    for team in league.teams:
        bs_for_team = next(
            (bs for bs in bs_list if bs.home_team.team_id == team.team_id or bs.away_team.team_id == team.team_id),
            None,
        )
        if bs_for_team:
            lineup = bs_for_team.home_lineup if bs_for_team.home_team.team_id == team.team_id else bs_for_team.away_lineup
            for p in (lineup or []):
                rows.append(_player_to_row(p, team_id=team.team_id, week=week))
        else:
            for p in team.roster:
                rows.append(_player_to_row(p, team_id=team.team_id, week=week))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, f"rosters_week_{week}.csv"), index=False)
    return df


def export_current_team_rosters(league: League, out_dir: str) -> pd.DataFrame:
    """Export the current roster (starters and bench) for every team.

    ``League`` does not expose slot information for bench players via
    ``team.roster`` which previously caused bench players to be missing and the
    "week" column to remain empty.  To accurately capture the full lineup we use
    :func:`_lineup_for_team` which pulls the latest box score data and includes
    both starters and bench players with their associated slot positions.
    """

    week = getattr(league, "current_week", None)
    rows: List[Dict[str, Any]] = []
    for team in league.teams:
        starters, bench = _lineup_for_team(league, team.team_id, None)
        for player in starters + bench:
            rows.append(
                _player_to_row(player, team_id=team.team_id, week=week)
                | {
                    "team_name": team.team_name,
                    "is_starter": player in starters,
                }
            )
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "current_team_rosters.csv"), index=False)
    return df


def export_free_agents(league: League, out_dir: str, pool_size: int, positions: List[str]) -> pd.DataFrame:
    """Export information on free agents for the provided positions.

    The previous implementation left the "week" column empty.  We now populate
    it using the league's current week so downstream consumers know when the
    snapshot was taken.
    """

    week = getattr(league, "current_week", None)
    rows = []
    for pos in positions:
        try:
            for p in league.free_agents(size=pool_size, position=pos):
                rows.append(_player_to_row(p, team_id=None, week=week) | {"fa_position": pos})
        except Exception:
            # Some composite slots (e.g., FLEX, OP) may not be directly queryable; ignore gracefully.
            continue
    df = pd.DataFrame(rows).drop_duplicates(subset=["player_id"])
    df.to_csv(os.path.join(out_dir, "free_agents.csv"), index=False)
    return df


def export_upcoming_pro_schedule(league: League, out_dir: str) -> pd.DataFrame:
    """Export today's and future NFL pro games.

    The ``espn_api`` schedule repeats games for each team.  We deduplicate using
    ``gameId`` and only keep matchups scheduled for today or later (Eastern
    Time).  Results are written to ``pro_schedule_upcoming.csv`` in ``out_dir``.
    """

    tz_et = tz.gettz("America/New_York")
    today = datetime.now(tz_et).date()
    schedule = league._get_all_pro_schedule()

    seen: set[int] = set()
    rows: List[Dict[str, Any]] = []
    for team_sched in schedule.values():
        for week, games in (team_sched or {}).items():
            for g in games:
                game_id = g.get("gameId") or g.get("id")
                if game_id in seen:
                    continue

                raw_date = g.get("date") or g.get("gameDate")
                if isinstance(raw_date, str):
                    try:
                        game_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(tz_et)
                    except ValueError:
                        continue
                else:
                    try:
                        game_dt = datetime.fromtimestamp(float(raw_date) / 1000, tz_et)
                    except Exception:
                        continue

                if game_dt.date() >= today:
                    rows.append(
                        {
                            "week": int(week),
                            "game_id": game_id,
                            "game_date": game_dt.strftime("%Y-%m-%d"),
                            "home_team_id": g.get("homeProTeamId"),
                            "away_team_id": g.get("awayProTeamId"),
                            "home_team_abbrev": constant.PRO_TEAM_MAP.get(g.get("homeProTeamId")),
                            "away_team_abbrev": constant.PRO_TEAM_MAP.get(g.get("awayProTeamId")),
                        }
                    )
                    seen.add(game_id)

    df = pd.DataFrame(rows).sort_values(["game_date", "game_id"]).reset_index(drop=True)
    df.to_csv(os.path.join(out_dir, "pro_schedule_upcoming.csv"), index=False)
    return df


def export_league_settings(league: League, out_dir: str) -> pd.DataFrame:
    """Export the league's Settings object as key/value pairs.

    Parameters
    ----------
    league : League
        An ``espn_api`` :class:`League` instance.
    out_dir : str
        Directory where ``league_settings.txt`` will be written.

    Returns
    -------
    pandas.DataFrame
        Two-column dataframe with ``setting`` and ``value`` entries.
    """

    settings = getattr(league, "settings", None)
    rows: List[Dict[str, Any]] = []
    if settings is not None:
        for key, value in vars(settings).items():
            rows.append({"setting": key, "value": value})

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "league_settings.txt"), index=False)
    return df


# --------------------------
# Analysis (Start/Sit & Trades)
# --------------------------

def _norm_pos(pos: Optional[str]) -> Optional[str]:
    if not pos:
        return pos
    up = str(pos).upper()
    return "D/ST" if up in ("DST", "D/ST") else up


def _lineup_for_team(league: League, team_id: int, week: Optional[int]) -> Tuple[List, List]:
    bs_list = league.box_scores(week) if week else league.box_scores()
    bs = next((b for b in bs_list if b.home_team.team_id == team_id or b.away_team.team_id == team_id), None)
    if not bs:
        return [], []
    lineup = bs.home_lineup if bs.home_team.team_id == team_id else bs.away_lineup
    starters = [p for p in (lineup or []) if (getattr(p, "slot_position", "") not in ("BE", "IR"))]
    bench = [p for p in (lineup or []) if (getattr(p, "slot_position", "") in ("BE", "IR"))]
    return starters, bench


def _threshold_for(pos: Optional[str], cfg: Config) -> float:
    posn = _norm_pos(pos) or ""
    return float(cfg.per_pos_thresholds.get(posn, cfg.start_sit_threshold))


def recommend_start_sit(league: League, cfg: Config) -> List[Dict[str, Any]]:
    if cfg.my_team_id is None:
        return []
    starters, bench = _lineup_for_team(league, cfg.my_team_id, cfg.scoring_period)
    advice: List[Dict[str, Any]] = []

    lockset = {_norm_pos(p) for p in (cfg.lock_positions or [])}

    for starter in starters:
        starter_pos = _norm_pos(getattr(starter, "position", None))
        if starter_pos in lockset:
            continue

        start_proj = float(getattr(starter, "projected_points", 0) or 0)

        eligible_bench = []
        for b in bench:
            bpos = _norm_pos(getattr(b, "position", None))
            if bpos in lockset:
                continue
            eligible = False
            try:
                eligible_slots = set(str(s) for s in (getattr(b, "eligibleSlots", []) or []))
                # Treat matching position as eligible; some installs encode by names, others by slot codes
                eligible = (starter_pos in eligible_slots) or (bpos == starter_pos)
            except Exception:
                eligible = (bpos == starter_pos)
            if eligible:
                eligible_bench.append(b)

        if not eligible_bench:
            continue

        best_bench = max(eligible_bench, key=lambda p: float(getattr(p, "projected_points", 0) or 0))
        bench_proj = float(getattr(best_bench, "projected_points", 0) or 0)
        delta = round(bench_proj - start_proj, 2)

        thresh = _threshold_for(starter_pos, cfg)
        if delta >= thresh:
            advice.append({
                "type": "start_sit",
                "bench_in": best_bench.name,
                "bench_pos": getattr(best_bench, "position", None),
                "starter_out": starter.name,
                "starter_pos": getattr(starter, "position", None),
                "proj_delta": delta,
                "threshold_used": thresh,
            })
    return advice


def _team_strength_by_pos(league: League, team_id: int, week: Optional[int]) -> Dict[str, float]:
    starters, _ = _lineup_for_team(league, team_id, week)
    strength: Dict[str, float] = {}
    for p in starters:
        pos = _norm_pos(getattr(p, "position", None))
        strength[pos] = strength.get(pos, 0.0) + float(getattr(p, "projected_points", 0) or 0)
    return strength


def recommend_trades(league: League, cfg: Config) -> List[Dict[str, Any]]:
    if cfg.my_team_id is None:
        return []

    my_strength = _team_strength_by_pos(league, cfg.my_team_id, cfg.scoring_period)
    my_starters, my_bench = _lineup_for_team(league, cfg.my_team_id, cfg.scoring_period)

    lockset = {_norm_pos(p) for p in (cfg.lock_positions or [])}
    bench_assets = [p for p in my_bench if _norm_pos(getattr(p, "position", None)) not in lockset]

    recs: List[Dict[str, Any]] = []
    need_margin = 8.0  # simple threshold for positional imbalance

    for opp in league.teams:
        if opp.team_id == cfg.my_team_id:
            continue
        opp_strength = _team_strength_by_pos(league, opp.team_id, cfg.scoring_period)

        for give_pos in ["RB", "WR", "QB", "TE"]:
            gp = _norm_pos(give_pos)
            if gp in lockset:
                continue
            if my_strength.get(gp, 0.0) > opp_strength.get(gp, 0.0) + need_margin:
                for need_pos in ["RB", "WR", "QB", "TE"]:
                    np = _norm_pos(need_pos)
                    if np == gp or np in lockset:
                        continue
                    if opp_strength.get(np, 0.0) > my_strength.get(np, 0.0) + need_margin:
                        opp_starters, opp_bench = _lineup_for_team(league, opp.team_id, cfg.scoring_period)
                        send = next((p for p in bench_assets if _norm_pos(getattr(p, "position", None)) == gp), None)
                        recv = next((p for p in opp_bench if _norm_pos(getattr(p, "position", None)) == np), None)
                        if send and recv:
                            recs.append({
                                "type": "trade",
                                "trade_with_team": opp.team_name,
                                "send_player": f"{send.name} ({getattr(send, 'position', None)})",
                                "receive_player": f"{recv.name} ({getattr(recv, 'position', None)})",
                                "rationale": f"Surplus at {gp} for us vs. {opp.team_name}; they’re deeper at {np}.",
                            })
    return recs[:5]


def free_agent_targets(league: League, cfg: Config) -> List[Dict[str, Any]]:
    lockset = {_norm_pos(p) for p in (cfg.lock_positions or [])}
    recs: List[Dict[str, Any]] = []
    for pos in ["RB", "WR", "TE", "QB", "D/ST", "K"]:
        if _norm_pos(pos) in lockset:
            continue
        try:
            fas = league.free_agents(size=cfg.free_agent_pool_size, position=pos)
        except Exception:
            continue
        best = sorted(fas, key=lambda p: float(getattr(p, "projected_points", 0) or 0), reverse=True)[:5]
        for p in best:
            recs.append({
                "type": "add",
                "player": f"{p.name} ({getattr(p, 'position', None)})",
                "proj_points": round(float(getattr(p, "projected_points", 0) or 0), 2),
                "why": f"Top available {pos} by projections; {getattr(p, 'percent_owned', None)}% rostered.",
            })
    return recs[:10]


def write_advice_markdown(out_dir: str, week: Optional[int], advice_items: List[Dict[str, Any]], cfg: Config, league: League) -> None:
    league_scoring = getattr(getattr(league, "settings", None), "scoringType", None) or "Unknown"
    if not advice_items:
        content = f"# Daily Pre-Game Analysis\n\n**League scoring:** {league_scoring}\n\n_No actionable recommendations today._\n"
    else:
        lines = [f"# Daily Pre-Game Analysis", f"**League scoring:** {league_scoring}", ""]
        start_sit = [a for a in advice_items if a["type"] == "start_sit"]
        trades = [a for a in advice_items if a["type"] == "trade"]
        adds = [a for a in advice_items if a["type"] == "add"]
        if start_sit:
            lines.append("## Start/Sit")
            for a in start_sit:
                lines.append(
                    f"- **Start {a['bench_in']} ({a['bench_pos']}) over {a['starter_out']} ({a['starter_pos']})** "
                    f"— +{a['proj_delta']} proj pts (threshold {a['threshold_used']})."
                )
            lines.append("")
        if adds:
            lines.append("## Free-Agent Targets")
            for a in adds:
                lines.append(f"- **{a['player']}** — {a['proj_points']} proj pts. {a['why']}")
            lines.append("")
        if trades:
            lines.append("## Trade Ideas")
            for a in trades:
                lines.append(f"- With **{a['trade_with_team']}**: Send **{a['send_player']}**, receive **{a['receive_player']}** — {a['rationale']}")
            lines.append("")
        content = "\n".join(lines)

    fname = f"analysis_week_{week or 'current'}_{today_et_date_str()}.md"
    with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
        f.write(content)


# --------------------------
# Workbook writer
# --------------------------

def write_workbook(xlsx_path: str, dfs: Dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        for name, df in dfs.items():
            sheet = name[:31]
            df.to_excel(writer, sheet_name=sheet, index=False)


# --------------------------
# Main
# --------------------------

def main() -> None:
    cfg = load_config()
    ensure_dir(cfg.out_dir)

    league = make_league(cfg)

    # Determine the week to operate on.  ``cfg.scoring_period`` allows users to
    # override the week, otherwise we fall back to the league's current week so
    # that downstream exports always receive a concrete value.
    week = cfg.scoring_period or getattr(league, "current_week", None)

    # Exports
    df_standings = export_standings(league, cfg.out_dir)
    df_matchups = export_matchups(league, cfg.out_dir, week)
    df_rosters = export_rosters(league, cfg.out_dir, week)
    df_current_rosters = export_current_team_rosters(league, cfg.out_dir)
    df_free = export_free_agents(league, cfg.out_dir, cfg.free_agent_pool_size, cfg.positions)
    df_pro = export_upcoming_pro_schedule(league, cfg.out_dir)
    df_settings = export_league_settings(league, cfg.out_dir)

    # Advice
    advice_items: List[Dict[str, Any]] = []
    advice_items += recommend_start_sit(league, cfg)
    advice_items += free_agent_targets(league, cfg)
    advice_items += recommend_trades(league, cfg)

    write_advice_markdown(cfg.out_dir, week, advice_items, cfg, league)

    if cfg.write_xlsx:
        write_workbook(cfg.xlsx_path, {
            "standings": df_standings,
            f"matchups_wk_{week}": df_matchups,
            f"rosters_wk_{week}": df_rosters,
            "free_agents": df_free,
            "current_rosters": df_current_rosters,
            "pro_schedule": df_pro,
            "league_settings": df_settings,
        })

    print("Done.")


if __name__ == "__main__":
    main()
