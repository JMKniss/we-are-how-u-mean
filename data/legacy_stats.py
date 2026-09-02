"""
NFL stats calculator for 2016-2017 seasons where ESPN API lacks per-player weekly data.

For each starter on every roster:
  - Skill positions (QB/RB/WR/TE/FLEX): nfl-data-py weekly stats via ESPN ID -> GSIS ID crosswalk
  - Kickers (K): nfl-data-py PBP data (FG tiers + PAT)
  - Defense/ST (D/ST): nfl-data-py PBP + schedule data (PA tiers, YA tiers, sacks, turnovers, TDs)

Scoring rules are read directly from ESPN's league settings (same format as 2019+).
"""

import pickle
import pandas as pd
from pathlib import Path

_CACHE_DIR = Path(__file__).parent / "cache"

# Position map matching ESPN's defaultPositionId
_POS_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}

# nfl-data-py uses different abbreviations for relocated/renamed teams.
# For 2016-2017, map old abbreviations to the ones used in PBP data.
_TEAM_REMAP_2016 = {"LAR": "LA", "LV": "OAK", "LAC": "SD"}
_TEAM_REMAP_2017 = {"LAR": "LA", "LV": "OAK", "LAC": "SD"}


def _nfl_import():
    """Lazy import of nfl_data_py (optional dependency)."""
    try:
        import nfl_data_py as nfl
        return nfl
    except ImportError:
        raise ImportError(
            "nfl-data-py is required for 2016-2017 player stats. "
            "Install it with: pip install nfl-data-py --no-deps"
        )


def _load_crosswalk() -> dict[int, str]:
    """Return {espn_id (int): gsis_id (str)} for all players in nfl-data-py's ID table."""
    nfl = _nfl_import()
    ids = nfl.import_ids()
    ids["espn_id"] = ids["espn_id"].astype("Int64")
    mask = ids["espn_id"].notna() & ids["gsis_id"].notna()
    return {int(row["espn_id"]): str(row["gsis_id"]) for _, row in ids[mask].iterrows()}


def _points_allowed_tier(pts: float) -> float:
    if pts == 0:
        return 5.0
    elif pts <= 6:
        return 4.0
    elif pts <= 13:
        return 3.0
    elif pts <= 17:
        return 1.0
    elif pts <= 27:
        return 0.0
    elif pts <= 34:
        return -1.0
    elif pts <= 45:
        return -3.0
    else:
        return -5.0


def _yards_allowed_tier(yds: float) -> float:
    if yds < 100:
        return 5.0
    elif yds < 200:
        return 3.0
    elif yds < 300:
        return 2.0
    elif yds < 350:
        return 0.0
    elif yds < 400:
        return -1.0
    elif yds < 450:
        return -3.0
    elif yds < 500:
        return -5.0
    elif yds < 550:
        return -6.0
    else:
        return -7.0


def _kicker_pts(pbp_week: pd.DataFrame, gsis_id: str) -> float:
    """FG + PAT fantasy points for a kicker in one week from PBP data."""
    fgs = pbp_week[(pbp_week["kicker_player_id"] == gsis_id) & (pbp_week["play_type"] == "field_goal")]
    pats = pbp_week[(pbp_week["kicker_player_id"] == gsis_id) & (pbp_week["play_type"] == "extra_point")]

    pts = 0.0
    for _, fg in fgs.iterrows():
        if fg["field_goal_result"] == "made":
            dist = fg["kick_distance"] or 0
            if dist >= 50:
                pts += 5
            elif dist >= 40:
                pts += 4
            else:
                pts += 3
        else:
            pts -= 1  # FGM: missed or blocked = -1

    pts += float((pats["extra_point_result"] == "good").sum())
    return pts


def _dst_pts(pbp_week: pd.DataFrame, sched_week: pd.DataFrame, team_abbr: str) -> float:
    """D/ST fantasy points for one team in one week from PBP + schedule data."""
    defense = pbp_week[pbp_week["defteam"] == team_abbr]

    sacks = int((defense["sack"] == 1).sum())
    ints = int((defense["interception"] == 1).sum())
    fumbles_rec = int((defense["fumble_lost"] == 1).sum())  # offense lost fumble to defense
    safeties = int((defense["safety"] == 1).sum())
    def_tds = int((defense["td_team"] == team_abbr).sum())
    punt_blocked = int((defense["punt_blocked"] == 1).sum())
    # Blocked FGs credited to defense (kicker already penalized -1 separately)
    fg_blocked = int(((defense["play_type"] == "field_goal") & (defense["field_goal_result"] == "blocked")).sum())

    # Yards allowed: positive yards gained by opponent's offense
    yards_allowed = float(defense["yards_gained"].fillna(0).clip(lower=0).sum())

    # Points allowed: opponent's final score
    game = sched_week[(sched_week["home_team"] == team_abbr) | (sched_week["away_team"] == team_abbr)]
    pts_allowed = 0.0
    if not game.empty:
        row = game.iloc[0]
        pts_allowed = float(row["away_score"] if row["home_team"] == team_abbr else row["home_score"])

    pa = _points_allowed_tier(pts_allowed)
    ya = _yards_allowed_tier(yards_allowed)

    return (sacks * 1.0 + ints * 2.0 + fumbles_rec * 2.0 + safeties * 2.0 +
            def_tds * 6.0 + punt_blocked * 2.0 + fg_blocked * 2.0 + pa + ya)


def _dst_abbr(dst_name: str, team_desc: pd.DataFrame) -> str | None:
    """
    Parse 'Bengals D/ST' -> 'CIN' using nfl-data-py team descriptions.
    Returns None if no match found.
    """
    nickname = dst_name.replace(" D/ST", "").strip()
    match = team_desc[team_desc["team_nick"].str.lower() == nickname.lower()]
    if not match.empty:
        return str(match["team_abbr"].values[0])
    # Fallback: partial match anywhere in team_name
    match = team_desc[team_desc["team_name"].str.lower().str.contains(nickname.lower(), na=False)]
    if not match.empty:
        return str(match["team_abbr"].values[0])
    return None


def build_legacy_boxscores(season: int, roster_data: dict) -> pd.DataFrame:
    """
    Build a player-level box score DataFrame for pre-2019 seasons using nfl-data-py.

    Parameters
    ----------
    season : int
        Season year (2016 or 2017).
    roster_data : dict
        {week: [matchup_dict, ...]} from _box_scores_all_weeks_legacy.
        Each player in home_players/away_players must have: player_id, name, position, slot, is_active.

    Returns
    -------
    pd.DataFrame compatible with get_boxscores_df() output:
        season, week, team_id, team_name, player_id, player_name, position, slot,
        points, projected, is_active_slot, on_bench
    """
    cache_path = _CACHE_DIR / str(season) / "legacy_boxscores.pkl"
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    nfl = _nfl_import()

    print(f"[legacy_stats] Loading nfl-data-py data for {season}…")
    weekly = nfl.import_weekly_data([season])
    weekly = weekly[weekly["season_type"] == "REG"].copy()

    pbp = nfl.import_pbp_data([season], downcast=True)
    pbp = pbp[pbp["season_type"] == "REG"].copy()

    sched = nfl.import_schedules([season])
    sched = sched[sched["game_type"] == "REG"].copy()

    team_desc = nfl.import_team_desc()

    # Season-specific team remap (old abbrs used in ESPN/schedule vs PBP)
    remap = _TEAM_REMAP_2016 if season == 2016 else _TEAM_REMAP_2017

    # Season-long gsis_id -> NFL team. Covers kickers, who do not appear in
    # import_weekly_data, and any player whose weekly row is missing.
    try:
        _ros = nfl.import_seasonal_rosters([season])
        roster_team = dict(zip(_ros["player_id"], _ros["team"]))
    except Exception:
        roster_team = {}

    crosswalk = _load_crosswalk()

    rows = []
    for week, matchups in roster_data.items():
        pbp_wk = pbp[pbp["week"] == week].copy()
        sched_wk = sched[sched["week"] == week].copy()
        weekly_wk = weekly[weekly["week"] == week].copy()

        # Apply team remap so PBP abbreviations match schedule/team_desc
        for col in ["home_team", "away_team"]:
            sched_wk[col] = sched_wk[col].replace(remap)
        for col in ["posteam", "defteam", "td_team"]:
            pbp_wk[col] = pbp_wk[col].replace(remap)
        team_desc_remap = team_desc.copy()
        team_desc_remap["team_abbr"] = team_desc_remap["team_abbr"].replace(remap)

        for matchup in matchups:
            for side in ("home", "away"):
                team_id = matchup[f"{side}_team_id"]
                team_name = matchup.get(f"{side}_team_name", str(team_id))
                players = matchup[f"{side}_players"]

                for p in players:
                    espn_id = p.get("player_id")
                    name = p.get("name", "?")
                    pos = p.get("position", "?")
                    slot = p.get("slot", "STARTER")
                    is_active = p.get("is_active", True)

                    pts = 0.0
                    nfl_team = None
                    if pos == "D/ST":
                        abbr = _dst_abbr(name, team_desc_remap)
                        if abbr:
                            pts = _dst_pts(pbp_wk, sched_wk, abbr)
                            nfl_team = abbr          # a defence is its own team
                    elif pos == "K":
                        gsis = crosswalk.get(espn_id) if espn_id else None
                        if gsis:
                            pts = _kicker_pts(pbp_wk, gsis)
                            nfl_team = roster_team.get(gsis)
                    else:
                        gsis = crosswalk.get(espn_id) if espn_id else None
                        if gsis:
                            row_wk = weekly_wk[weekly_wk["player_id"] == gsis]
                            if not row_wk.empty:
                                pts = float(row_wk["fantasy_points"].values[0])
                                # recent_team is per week, so mid-season trades
                                # are reflected correctly.
                                nfl_team = row_wk["recent_team"].values[0]
                            if not nfl_team:
                                nfl_team = roster_team.get(gsis)

                    # nflfastR reports modern abbreviations (LAC/LV/LAR) even for
                    # these seasons. Apply the same historical remap used for
                    # scoring so a player is not shown as SD one week and LAC the
                    # next: in 2016-17 they were SD, OAK and LA.
                    if nfl_team:
                        nfl_team = remap.get(nfl_team, nfl_team)

                    rows.append({
                        "season": season,
                        "week": week,
                        "team_id": team_id,
                        "team_name": team_name,
                        "player_id": espn_id,
                        "player_name": name,
                        "position": pos,
                        "slot": slot,
                        "points": round(pts, 2),
                        "projected": 0.0,
                        "pro_team": nfl_team,
                        "is_active_slot": is_active,
                        "on_bench": not is_active,
                    })

    df = pd.DataFrame(rows)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(df, f)

    return df
