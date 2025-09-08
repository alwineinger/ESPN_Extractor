from bot_daily_analysis import (
    export_current_team_rosters,
    export_free_agents,
    export_upcoming_pro_schedule,
)
from datetime import datetime, timedelta
from dateutil import tz


class Player:
    def __init__(self, player_id: int, name: str, slot: str, position: str = "QB"):
        self.playerId = player_id
        self.name = name
        self.position = position
        self.slot_position = slot
        self.proTeam = "TEAM"
        self.projected_points = 0
        self.points = 0
        self.injuryStatus = "ACTIVE"
        self.percent_owned = 0
        self.percent_started = 0
        self.eligibleSlots = [position, "OP", "BE"]


class Team:
    def __init__(self, team_id: int, team_name: str, lineup):
        self.team_id = team_id
        self.team_name = team_name
        # Simulate bug where team.roster misses bench players
        self.roster = [p for p in lineup if p.slot_position != "BE"]


class BoxScore:
    def __init__(self, home_team, away_team, home_lineup, away_lineup):
        self.home_team = home_team
        self.away_team = away_team
        self.home_lineup = home_lineup
        self.away_lineup = away_lineup


class LeagueStub:
    def __init__(self):
        self.current_week = 7
        self._team_a_lineup = [
            Player(1, "Starter A1", "QB"),
            Player(2, "Bench A1", "BE"),
        ]
        self._team_b_lineup = [
            Player(3, "Starter B1", "RB"),
            Player(4, "Bench B1", "BE"),
        ]
        self.teams = [
            Team(1, "Team A", self._team_a_lineup),
            Team(2, "Team B", self._team_b_lineup),
        ]
        self._box = BoxScore(
            self.teams[0], self.teams[1], self._team_a_lineup, self._team_b_lineup
        )
        self._fa = {
            "QB": [Player(10, "FA QB", "BE")],
            "RB": [Player(11, "FA RB", "BE", position="RB")],
        }

    def box_scores(self, week=None):
        return [self._box]

    def free_agents(self, size: int, position: str):
        return self._fa.get(position, [])

    def _get_all_pro_schedule(self):
        now = datetime.now(tz.gettz("America/New_York"))
        past = int((now - timedelta(days=1)).timestamp() * 1000)
        future = int((now + timedelta(days=1)).timestamp() * 1000)
        return {
            1: {
                "1": [
                    {"gameId": 1, "date": past, "homeProTeamId": 1, "awayProTeamId": 2},
                    {"gameId": 2, "date": future, "homeProTeamId": 3, "awayProTeamId": 4},
                ]
            },
            2: {"1": [{"gameId": 2, "date": future, "homeProTeamId": 3, "awayProTeamId": 4}]},
        }


def test_export_current_team_rosters_includes_bench_and_week(tmp_path):
    league = LeagueStub()
    df = export_current_team_rosters(league, tmp_path)
    names = df["name"].tolist()
    assert "Bench A1" in names
    # Bench players should be marked as not starters
    assert not df.loc[df["name"] == "Bench A1", "is_starter"].iloc[0]
    assert set(df["week"]) == {league.current_week}


def test_export_free_agents_has_week(tmp_path):
    league = LeagueStub()
    df = export_free_agents(league, tmp_path, pool_size=5, positions=["QB", "RB"])
    assert set(df["week"]) == {league.current_week}


def test_export_upcoming_pro_schedule_filters_and_dedupes(tmp_path):
    league = LeagueStub()
    df = export_upcoming_pro_schedule(league, tmp_path)
    assert df["game_id"].tolist() == [2]
    assert df["home_team_id"].tolist() == [3]
    assert df["home_team_abbrev"].tolist() == ["CHI"]
    assert df["away_team_abbrev"].tolist() == ["CIN"]
