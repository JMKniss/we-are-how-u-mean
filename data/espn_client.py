"""
ESPN data layer — fetches and caches all league data.
Cache is stored as pickle files in data/cache/<season>/.
Call invalidate_cache(season) to force a fresh pull.
Credentials are loaded automatically from config (via .env).
"""
import os
import pickle
from pathlib import Path
from typing import Optional

import pandas as pd
from espn_api.football import League
from config import ESPN_S2, SWID

CACHE_DIR = Path(__file__).parent / "cache"


def _cache_path(season: int, key: str) -> Path:
    d = CACHE_DIR / str(season)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.pkl"


def _load(season: int, key: str):
    p = _cache_path(season, key)
    if p.exists():
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def _save(season: int, key: str, obj):
    p = _cache_path(season, key)
    with open(p, "wb") as f:
        pickle.dump(obj, f)


def invalidate_cache(season: int):
    d = CACHE_DIR / str(season)
    if d.exists():
        for f in d.glob("*.pkl"):
            f.unlink()


def get_league(season: int, espn_s2: str = None, swid: str = None) -> League:
    cached = _load(season, "league")
    if cached is not None:
        return cached
    s2 = espn_s2 or ESPN_S2
    sw = swid or SWID
    kwargs = {"league_id": 722346, "year": season}
    if s2 and sw:
        kwargs["espn_s2"] = s2
        kwargs["swid"] = sw
    league = League(**kwargs)
    _save(season, "league", league)
    return league


PLAYOFF_WEEKS = [14, 15, 16, 17]
REG_SEASON_END = 13


def _active_player_sum(lineup) -> float:
    """Sum points for all active (non-bench, non-IR) players."""
    return round(sum(p.points for p in lineup if p.lineupSlot not in ("BE", "IR")), 2)


def get_matchups_df(season: int) -> pd.DataFrame:
    """
    Build a row-per-team-per-week DataFrame with true individual weekly scores.

    Regular season (weeks 1-13): uses team.schedule/scores/outcomes — each
    matchup is one week so ESPN's data is accurate.

    Playoff weeks (14-17): ESPN accumulates scores across 2-week matchup
    windows (W14+15, W16+17) so team.scores is useless for individual weeks.
    Instead we pull box_scores(week=N) and sum each team's active player
    points — player stats are always tracked per scoring period individually.
    """
    cached = _load(season, "matchups_df")
    if cached is not None:
        return cached

    league = get_league(season)
    rows = []

    # --- Regular season: use team-level schedule/scores ---
    for team in league.teams:
        for week_idx, (opp, score, outcome) in enumerate(
            zip(team.schedule, team.scores, team.outcomes), start=1
        ):
            if week_idx > REG_SEASON_END:
                break
            if outcome == "U":
                continue
            opp_score = 0.0
            for o in league.teams:
                if o.team_id == opp.team_id:
                    if week_idx <= len(o.scores):
                        opp_score = o.scores[week_idx - 1]
                    break
            rows.append({
                "season": season,
                "week": week_idx,
                "team_id": team.team_id,
                "team_name": team.team_name.strip(),
                "score": score,
                "opp_id": opp.team_id,
                "opp_name": opp.team_name.strip(),
                "opp_score": opp_score,
                "outcome": outcome,
                "is_playoff": False,
            })

    # --- Playoff weeks: sum active player points per week ---
    max_week = min(league.current_week, 17)
    for week in PLAYOFF_WEEKS:
        if week > max_week:
            break
        try:
            boxes = league.box_scores(week=week)
        except Exception:
            continue
        for box in boxes:
            home_score = _active_player_sum(box.home_lineup)
            away_score = _active_player_sum(box.away_lineup)
            # Individual week outcome (not the 2-week matchup outcome)
            home_outcome = "W" if home_score > away_score else ("T" if home_score == away_score else "L")
            away_outcome = "L" if home_outcome == "W" else ("T" if home_outcome == "T" else "W")
            for team, score, opp, opp_score, outcome in [
                (box.home_team, home_score, box.away_team, away_score, home_outcome),
                (box.away_team, away_score, box.home_team, home_score, away_outcome),
            ]:
                rows.append({
                    "season": season,
                    "week": week,
                    "team_id": team.team_id,
                    "team_name": team.team_name.strip(),
                    "score": score,
                    "opp_id": opp.team_id,
                    "opp_name": opp.team_name.strip(),
                    "opp_score": opp_score,
                    "outcome": outcome,
                    "is_playoff": True,
                })

    df = pd.DataFrame(rows)
    _save(season, "matchups_df", df)
    return df


def get_boxscores_df(season: int) -> pd.DataFrame:
    """Player-level box score data for all played weeks."""
    cached = _load(season, "boxscores_df")
    if cached is not None:
        return cached
    league = get_league(season)
    rows = []
    max_week = min(league.current_week, 17)
    for week in range(1, max_week + 1):
        try:
            boxes = league.box_scores(week=week)
        except Exception:
            continue
        for box in boxes:
            for side, lineup, proj in [
                (box.home_team, box.home_lineup, box.home_projected),
                (box.away_team, box.away_lineup, box.away_projected),
            ]:
                # Use player sum for team score — accurate for all weeks including playoffs
                true_score = _active_player_sum(lineup)
                for player in lineup:
                    rows.append({
                        "season": season,
                        "week": week,
                        "team_id": side.team_id,
                        "team_name": side.team_name.strip(),
                        "team_score": true_score,
                        "team_projected": proj,
                        "player_id": player.playerId,
                        "player_name": player.name,
                        "position": player.position,
                        "slot": player.lineupSlot,
                        "points": player.points,
                        "projected": player.projected_points,
                        "is_active_slot": player.lineupSlot not in ("BE", "IR"),
                        "on_bench": player.lineupSlot == "BE",
                        "injured": player.injured,
                        "injury_status": player.injuryStatus,
                        "pro_team": player.proTeam,
                        "percent_owned": player.percent_owned,
                    })
    df = pd.DataFrame(rows)
    _save(season, "boxscores_df", df)
    return df


def get_draft_df(season: int) -> pd.DataFrame:
    cached = _load(season, "draft_df")
    if cached is not None:
        return cached
    league = get_league(season)
    rows = []
    for pick in league.draft:
        rows.append({
            "season": season,
            "overall_pick": (pick.round_num - 1) * league.settings.team_count + pick.round_pick,
            "round": pick.round_num,
            "pick_in_round": pick.round_pick,
            "team_id": pick.team.team_id,
            "team_name": pick.team.team_name.strip(),
            "player_name": pick.playerName,
            "keeper": pick.keeper_status,
        })
    df = pd.DataFrame(rows)
    _save(season, "draft_df", df)
    return df


def get_standings_df(season: int) -> pd.DataFrame:
    cached = _load(season, "standings_df")
    if cached is not None:
        return cached
    league = get_league(season)
    rows = []
    for team in league.teams:
        rows.append({
            "season": season,
            "team_id": team.team_id,
            "team_name": team.team_name.strip(),
            "wins": team.wins,
            "losses": team.losses,
            "ties": team.ties,
            "points_for": team.points_for,
            "points_against": team.points_against,
            "final_standing": team.final_standing,
            "playoff_pct": team.playoff_pct,
            "acquisitions": team.acquisitions,
            "drops": team.drops,
            "trades": team.trades,
            "move_to_ir": team.move_to_ir,
        })
    df = pd.DataFrame(rows)
    _save(season, "standings_df", df)
    return df
