"""
ESPN data layer.

Every getter reads in this order: data/archive/*.csv, then the pickle cache in
data/cache/<season>/, then ESPN. In normal use the archive always answers, so
the app needs no ESPN cookies and never calls ESPN; only the weekly update
does, by setting USE_ARCHIVE = False. invalidate_cache(season) drops a stale
pickle - which matters, since a cold pickle from before a draft makes the
league look undrafted.

Pages should ask get_current_week(), which is the last week the archive
holds, rather than reaching through get_league() for current_week: that is
ESPN's open scoring period and runs a week ahead of the data.
"""
import functools
import json
import os
import pickle
from pathlib import Path
from typing import Optional

import pandas as pd
from espn_api.football import League
from espn_api.football.constant import POSITION_MAP
from config import ESPN_S2, SWID, season_config, get_manager_name

CACHE_DIR = Path(__file__).parent / "cache"

# ── Permanent archive ────────────────────────────────────────────────────────
# data/archive/*.csv is the durable record of completed seasons. It is read
# before the pickle cache and before ESPN, so normal use needs no cookies.
# Set USE_ARCHIVE = False to bypass it and force a live ESPN pull.
USE_ARCHIVE = True


def _from_archive(name: str, season: int):
    """Return an archived DataFrame, or None if unavailable."""
    if not USE_ARCHIVE:
        return None
    try:
        from data import archive
        if archive.has(name, season):
            return archive.get(name, season)
    except Exception:
        pass
    return None


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
    for k in [k for k in _BOX_MEMO if k[1] == season]:
        del _BOX_MEMO[k]
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


def _active_player_sum(lineup) -> float:
    """Sum points for all active (non-bench, non-IR) players."""
    return round(sum(p.points for p in lineup if p.lineupSlot not in ("BE", "IR")), 2)


# ── Which weeks have actually been played ────────────────────────────────────
# ESPN's current_week is the scoring period now open, so from Tuesday morning
# it already names a week nobody has played. Fetching up to it returns a week
# of zeroes, and archiving those zeroes is worse than missing the week: the
# next additive update sees the real scores as a CONFLICT against the archived
# zeroes and skips them, freezing the week at 0-0 for good.
#
# So weeks are judged by whether they hold results, not by their number. A
# trailing run of empty weeks is the season simply not having got there yet
# and is dropped quietly. An empty week with played weeks after it is a failed
# fetch, and that raises - 2025 lost boxscore weeks 11 and 14 to a silent
# `except: []` here, and neither the app nor the archive said a word.


class WeekFetchError(RuntimeError):
    """A week inside the played range came back empty or failed to fetch."""


def _week_points(boxes: list) -> float:
    """Total points scored in a week, for either box-score shape."""
    total = 0.0
    for b in boxes:
        if isinstance(b, dict):        # legacy path: plain dicts
            total += float(b.get("home_week_score") or 0)
            total += float(b.get("away_week_score") or 0)
        else:                          # espn_api BoxScore objects
            total += float(getattr(b, "home_score", 0) or 0)
            total += float(getattr(b, "away_score", 0) or 0)
    return total


def _drop_unplayed_weeks(boxes_by_week: dict, errors: dict, season: int) -> dict:
    """Keep weeks with results; drop the unplayed tail; raise on interior gaps."""
    played = {w for w, boxes in boxes_by_week.items() if _week_points(boxes) > 0}
    if not played:
        if errors:
            raise WeekFetchError(
                f"{season}: every week failed to fetch. First error: "
                f"{sorted(errors.items())[0][1]}"
            )
        return {}

    last = max(played)
    gaps = sorted(w for w in range(1, last + 1) if w not in played)
    if gaps:
        detail = "; ".join(
            f"wk {w}: {errors.get(w, 'returned no scores')}" for w in gaps
        )
        raise WeekFetchError(
            f"{season}: weeks {gaps} are empty but week {last} has results. "
            f"This is a failed fetch, not an unplayed week - archiving it would "
            f"leave a permanent hole. {detail}"
        )
    return {w: boxes_by_week[w] for w in sorted(played)}


# One archive build asks for matchups, boxscores and validation, and each of
# them needs every week's box scores. Fetched independently that is three full
# passes over the season against ESPN, which is most of what a weekly update
# costs. They are the same bytes, so fetch once per process and hand the same
# result to all three. Keyed on current_week so a later week invalidates it.
_BOX_MEMO: dict = {}


def _box_scores_all_weeks(league, cfg: dict) -> dict:
    """
    Fetch box_scores for every played week of the season.

    Returns {week: [box, ...]} — used by both get_matchups_df and
    get_validation_df so we only hit the ESPN API once per season build.
    Weeks with no results are dropped by _drop_unplayed_weeks.
    """
    memo_key = ("modern", league.year, league.current_week)
    if memo_key in _BOX_MEMO:
        return _BOX_MEMO[memo_key]

    boxes_by_week, errors = {}, {}
    max_week = min(league.current_week, cfg["total_weeks"])
    for week in range(1, max_week + 1):
        try:
            boxes_by_week[week] = league.box_scores(week=week)
        except Exception as e:
            boxes_by_week[week] = []
            errors[week] = f"{type(e).__name__}: {e}"
    result = _drop_unplayed_weeks(boxes_by_week, errors, league.year)
    _BOX_MEMO[memo_key] = result
    return result


def _fetch_week_raw(league, week: int) -> list:
    """
    Hit ESPN's schedule endpoint directly for a specific scoring period.
    Bypasses the espn_api year < 2019 guard — works for all seasons.
    Returns the raw 'schedule' list from ESPN's JSON response.
    """
    matchup_period = week
    for matchup_id in league.settings.matchup_periods:
        if week in league.settings.matchup_periods[matchup_id]:
            matchup_period = matchup_id
            break
    params = {"view": ["mMatchupScore", "mScoreboard"], "scoringPeriodId": week}
    filters = {"schedule": {"filterMatchupPeriodIds": {"value": [matchup_period]}}}
    headers = {"x-fantasy-filter": json.dumps(filters)}
    data = league.espn_request.league_get(params=params, headers=headers)
    return data.get("schedule", [])


def _parse_roster_legacy(entries: list, starters_only: bool = False) -> list:
    """
    Parse roster entries from a pre-2019 ESPN response.

    starters_only=True: entries come from rosterForMatchupPeriod (2016-2017).
      All 9 entries are active starters; slot IDs are unreliable (all show 0).
      Stats dict contains season totals, not weekly. Use appliedStatTotal for weekly pts.
      Projected not available.

    starters_only=False: entries come from rosterForCurrentScoringPeriod (2018).
      Full 16-player roster with correct slot IDs, per-week stats, and projected.
    """
    players = []
    for e in entries:
        slot_id = e.get("lineupSlotId", 20)
        pi = e.get("playerPoolEntry", {})
        player = pi.get("player", {})

        if starters_only:
            # Slot IDs are all 0 (unreliable) — mark all as active starters
            actual = float(pi.get("appliedStatTotal") or 0)
            projected = 0.0
            is_active = True
            slot_name = "STARTER"
        else:
            slot_name = POSITION_MAP.get(slot_id, "BE")
            actual = None
            projected = None
            for stat in player.get("stats", []):
                if stat.get("statSourceId") == 0:
                    actual = stat.get("appliedTotal")
                elif stat.get("statSourceId") == 1:
                    projected = stat.get("appliedTotal")
            if actual is None:
                actual = pi.get("appliedStatTotal", 0)
            is_active = slot_id not in (20, 21)

        pos_id = player.get("defaultPositionId", 22)
        # ESPN's defaultPositionId uses different numbering than POSITION_MAP (which is lineup slots).
        # Map player positions explicitly.
        _PLAYER_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
        player_pos = _PLAYER_POS.get(pos_id, POSITION_MAP.get(pos_id, "?"))
        players.append({
            "player_id": e.get("playerId"),
            "name": player.get("fullName", "?"),
            "position": player_pos,
            "slot": slot_name,
            "points": round(float(actual or 0), 2),
            "projected": round(float(projected or 0), 2),
            "is_active": is_active,
            "injured": player.get("injured", False),
            "injury_status": player.get("injuryStatus", "ACTIVE"),
            "pro_team": player.get("proTeamId"),
            "percent_owned": pi.get("percentOwned", 0),
        })
    return players


def _box_scores_all_weeks_legacy(league, cfg: dict) -> dict:
    """
    Fetch box scores for every week using direct ESPN API calls.
    Bypasses the year < 2019 library guard — works for all seasons.

    2018: rosterForCurrentScoringPeriod exists — full 16-player roster with
      per-week stats and projected points.
    2016-2017: only rosterForMatchupPeriod — 9 starters, no bench, no projected,
      but correct weekly appliedStatTotal for each starter.

    Returns {week: [matchup_dict, ...]} where each matchup_dict has:
        home_team_id, away_team_id, home_total, away_total,
        home_players, away_players
    """
    memo_key = ("legacy", league.year, league.current_week)
    if memo_key in _BOX_MEMO:
        return _BOX_MEMO[memo_key]

    boxes_by_week, errors = {}, {}
    max_week = min(league.current_week, cfg["total_weeks"])
    for week in range(1, max_week + 1):
        try:
            schedule = _fetch_week_raw(league, week)
            matchups = []
            for m in schedule:
                home = m.get("home", {})
                away = m.get("away", {})
                # Prefer rosterForCurrentScoringPeriod (2018); fall back to matchup period (2016-2017)
                home_cur = home.get("rosterForCurrentScoringPeriod", {}).get("entries", [])
                away_cur = away.get("rosterForCurrentScoringPeriod", {}).get("entries", [])
                if home_cur:
                    home_players = _parse_roster_legacy(home_cur, starters_only=False)
                    away_players = _parse_roster_legacy(away_cur, starters_only=False)
                else:
                    home_matchup = home.get("rosterForMatchupPeriod", {}).get("entries", [])
                    away_matchup = away.get("rosterForMatchupPeriod", {}).get("entries", [])
                    home_players = _parse_roster_legacy(home_matchup, starters_only=True)
                    away_players = _parse_roster_legacy(away_matchup, starters_only=True)
                # pointsByScoringPeriod gives the individual weekly score.
                # totalPoints is cumulative for 2-week playoff matchups,
                # so always prefer the per-week breakdown.
                home_pbsp = home.get("pointsByScoringPeriod", {})
                away_pbsp = away.get("pointsByScoringPeriod", {})
                home_week_score = home_pbsp.get(str(week), home.get("totalPoints", 0))
                away_week_score = away_pbsp.get(str(week), away.get("totalPoints", 0))
                matchups.append({
                    "home_team_id": home.get("teamId"),
                    "away_team_id": away.get("teamId"),
                    "home_total": home.get("totalPoints", 0),
                    "away_total": away.get("totalPoints", 0),
                    "home_week_score": home_week_score,
                    "away_week_score": away_week_score,
                    "home_players": home_players,
                    "away_players": away_players,
                })
            boxes_by_week[week] = matchups
        except Exception as e:
            boxes_by_week[week] = []
            errors[week] = f"{type(e).__name__}: {e}"
    result = _drop_unplayed_weeks(boxes_by_week, errors, league.year)
    _BOX_MEMO[memo_key] = result
    return result


def get_matchups_df(season: int) -> pd.DataFrame:
    """
    Row-per-team-per-week with scores for every played week.

    2019+: uses box_scores() for individual player sums each week — accurate
    for both regular season and playoff individual weeks.

    Pre-2019: ESPN's box_scores() API is not available. Falls back to
    team.schedule/scores/outcomes, which gives individual weekly scores for
    the regular season but only 2-week cumulative round totals for the
    playoffs (reported at the last week of each round: pw[1] and pw[3]).
    The 'is_playoff' flag marks these rows. Individual playoff weeks (pw[0],
    pw[2]) will not exist in the dataframe for pre-2019 seasons.
    """
    arc = _from_archive("matchups", season)
    if arc is not None:
        return arc
    cached = _load(season, "matchups_df")
    if cached is not None:
        return cached

    league = get_league(season)
    cfg = season_config(season)
    reg_season_end = cfg["reg_season_end"]
    pw = cfg["playoff_weeks"]
    rows = []

    if season < 2019:
        # ── Pre-2019: use direct ESPN API calls, bypassing the library guard ──
        # We get individual weekly player sums for all weeks including playoffs.
        boxes_by_week = _box_scores_all_weeks_legacy(league, cfg)
        team_map = {t.team_id: t.team_name.strip() for t in league.teams}

        # Build schedule_map for regular season outcomes from team.outcomes
        # (team.outcomes/schedule are reliable for regular season weeks)
        schedule_map = {}
        for team in league.teams:
            for i, (opp, outcome) in enumerate(zip(team.schedule, team.outcomes)):
                week = i + 1
                if week <= reg_season_end:
                    schedule_map[(team.team_id, week)] = (opp.team_id, outcome)

        # For 2016-2017, individual player weekly scores are not available from
        # the API (rosterForMatchupPeriod returns season-level stats). Use the
        # per-week team total from pointsByScoringPeriod instead.
        # For 2018, rosterForCurrentScoringPeriod has reliable per-week player sums.
        use_player_sums = (season >= 2018)

        for week in sorted(boxes_by_week):
            is_playoff = week in pw
            for matchup in boxes_by_week.get(week, []):
                home_id = matchup["home_team_id"]
                away_id = matchup["away_team_id"]
                if use_player_sums:
                    home_score = round(sum(p["points"] for p in matchup["home_players"] if p["is_active"]), 2)
                    away_score = round(sum(p["points"] for p in matchup["away_players"] if p["is_active"]), 2)
                else:
                    home_score = round(float(matchup["home_week_score"] or 0), 2)
                    away_score = round(float(matchup["away_week_score"] or 0), 2)

                for team_id, my_score, opp_id, opp_score in [
                    (home_id, home_score, away_id, away_score),
                    (away_id, away_score, home_id, home_score),
                ]:
                    if is_playoff:
                        outcome = "W" if my_score > opp_score else ("T" if my_score == opp_score else "L")
                    else:
                        sched = schedule_map.get((team_id, week))
                        if sched is None:
                            continue
                        outcome = sched[1]
                        if outcome == "U":
                            continue

                    rows.append({
                        "season": season,
                        "week": week,
                        "team_id": team_id,
                        "team_name": team_map.get(team_id, str(team_id)),
                        "score": my_score,
                        "opp_id": opp_id,
                        "opp_name": team_map.get(opp_id, str(opp_id)),
                        "opp_score": opp_score,
                        "outcome": outcome,
                        "is_playoff": is_playoff,
                    })

    else:
        # ── 2019+: full box_scores support ───────────────────────────────────
        boxes_by_week = _box_scores_all_weeks(league, cfg)

        schedule_map = {}  # (team_id, week) -> (opp_id, opp_name, outcome)
        for team in league.teams:
            for week_idx, (opp, outcome) in enumerate(
                zip(team.schedule, team.outcomes), start=1
            ):
                schedule_map[(team.team_id, week_idx)] = (
                    opp.team_id, opp.team_name.strip(), outcome
                )

        for week in sorted(boxes_by_week):
            is_playoff = week in pw
            for box in boxes_by_week.get(week, []):
                home_score = _active_player_sum(box.home_lineup)
                away_score = _active_player_sum(box.away_lineup)

                for team, my_score, opp_team, opp_score in [
                    (box.home_team, home_score, box.away_team, away_score),
                    (box.away_team, away_score, box.home_team, home_score),
                ]:
                    sched = schedule_map.get((team.team_id, week))
                    if is_playoff or sched is None:
                        outcome = "W" if my_score > opp_score else ("T" if my_score == opp_score else "L")
                    else:
                        outcome = sched[2]
                        if outcome == "U":
                            continue

                    rows.append({
                        "season": season,
                        "week": week,
                        "team_id": team.team_id,
                        "team_name": team.team_name.strip(),
                        "score": my_score,
                        "opp_id": opp_team.team_id,
                        "opp_name": opp_team.team_name.strip(),
                        "opp_score": opp_score,
                        "outcome": outcome,
                        "is_playoff": is_playoff,
                    })

    df = pd.DataFrame(rows)
    _save(season, "matchups_df", df)
    return df


def get_validation_df(season: int) -> pd.DataFrame:
    """
    Compare our player-sum scores against ESPN's reported scores for all weeks.

    HOW ESPN REPORTS PLAYOFF SCORES (discovered empirically):
    - For any 2-week matchup, box_scores(week=N) returns:
        * lineup:    the individual players/points for that specific week N
        * team_total (home_score/away_score): the SETTLED CUMULATIVE total
          for the entire 2-week matchup window once it is finished
    - ESPN reports the cumulative at BOTH weeks of a 2-week matchup.

    PLAYOFF FORMAT DETECTION:
    Two structures exist across seasons. We detect by comparing matchup pairings:
    - Standard (2+2): pw[0] and pw[1] have the same bracket pairings.
        Round 1 = pw[0]+pw[1], ESPN cumulative at pw[0].
        Round 2 = pw[2]+pw[3], ESPN cumulative at pw[2].
        Toilet bowl = teams paired against same opponent at pw[0] AND pw[2] (4 weeks).
    - Non-standard (1+2+2): pw[0] and pw[1] have DIFFERENT pairings (e.g. 2022).
        Round 1 = pw[0] only (1-week individual check).
        Round 2 = pw[1]+pw[2], ESPN cumulative at pw[2].
        Round 3 = pw[2]+pw[3], ESPN cumulative at pw[3].
        Toilet bowl = teams paired against same opponent at pw[1], pw[2], AND pw[3] (3 weeks).
    """
    arc = _from_archive("validation", season)
    if arc is not None:
        return arc
    cached = _load(season, "validation_df")
    if cached is not None:
        return cached

    league = get_league(season)
    cfg = season_config(season)
    pw = cfg["playoff_weeks"]

    if season < 2018:
        # 2016-2017: only rosterForMatchupPeriod is available, which returns
        # season-level stats rather than per-week player scores. There is no
        # independent player sum to validate against, so skip validation.
        df = pd.DataFrame([{
            "season": season, "week": 0, "team_id": 0,
            "team_name": "N/A", "check_type": "not_available",
            "label": f"Pre-2018: per-week player scores not available in ESPN API",
            "our_score": 0, "espn_score": 0, "diff": 0,
        }])
        _save(season, "validation_df", df)
        return df

    if season < 2019:
        boxes_by_week = _box_scores_all_weeks_legacy(league, cfg)
    else:
        boxes_by_week = _box_scores_all_weeks(league, cfg)

    # Gate the playoff checks on weeks that were actually played, not on
    # league.current_week. From Tuesday morning current_week names the week
    # now open, which would let a round look settled before it is.
    max_week = max(boxes_by_week) if boxes_by_week else 0
    rows = []

    team_map = {t.team_id: t.team_name.strip() for t in league.teams}

    def _reg_rows_legacy(week):
        for matchup in boxes_by_week.get(week, []):
            for team_id, players, espn_total in [
                (matchup["home_team_id"], matchup["home_players"], matchup["home_total"]),
                (matchup["away_team_id"], matchup["away_players"], matchup["away_total"]),
            ]:
                our_score = round(sum(p["points"] for p in players if p["is_active"]), 2)
                espn_score = round(espn_total, 2) if espn_total is not None else None
                rows.append({
                    "season": season, "week": week,
                    "team_id": team_id,
                    "team_name": team_map.get(team_id, str(team_id)),
                    "check_type": "regular_season",
                    "label": f"Wk {week}",
                    "our_score": our_score,
                    "espn_score": espn_score,
                    "diff": round(our_score - (espn_score or 0), 2),
                })

    # ── Regular season ───────────────────────────────────────────────────────
    for week in range(1, cfg["reg_season_end"] + 1):
        if week > max_week:
            break
        if season < 2019:
            _reg_rows_legacy(week)
            continue
        for box in boxes_by_week.get(week, []):
            for side, lineup, espn_total in [
                (box.home_team, box.home_lineup, box.home_score),
                (box.away_team, box.away_lineup, box.away_score),
            ]:
                our_score = _active_player_sum(lineup)
                espn_score = round(espn_total, 2) if espn_total is not None else None
                rows.append({
                    "season": season,
                    "week": week,
                    "team_id": side.team_id,
                    "team_name": side.team_name.strip(),
                    "check_type": "regular_season",
                    "label": f"Wk {week}",
                    "our_score": our_score,
                    "espn_score": espn_score,
                    "diff": round(our_score - (espn_score or 0), 2),
                })

    # ── Playoffs ─────────────────────────────────────────────────────────────
    if max_week < pw[0]:
        df = pd.DataFrame(rows)
        _save(season, "validation_df", df)
        return df

    if season == 2022:
        # 2022 playoffs were run manually outside ESPN with a custom format
        # (wk15 = 1-week R1, wks 16-17 = 2-week finals). ESPN's stored cumulative
        # totals reflect a different bracket structure and can't be cleanly validated.
        rows.append({
            "season": season, "week": 0, "team_id": 0,
            "team_name": "N/A", "check_type": "not_available",
            "label": "2022 playoffs: custom format run outside ESPN — playoff validation skipped",
            "our_score": 0, "espn_score": 0, "diff": 0,
        })
        df = pd.DataFrame(rows)
        _save(season, "validation_df", df)
        return df

    # Player sums and ESPN totals keyed by (team_id, week)
    player_sums = {}
    espn_totals = {}
    for week in pw:
        if week > max_week:
            break
        if season < 2019:
            for matchup in boxes_by_week.get(week, []):
                for team_id, players, espn_total in [
                    (matchup["home_team_id"], matchup["home_players"], matchup["home_total"]),
                    (matchup["away_team_id"], matchup["away_players"], matchup["away_total"]),
                ]:
                    player_sums[(team_id, week)] = round(sum(p["points"] for p in players if p["is_active"]), 2)
                    espn_totals[(team_id, week)] = round(espn_total, 2)
        else:
            for box in boxes_by_week.get(week, []):
                for side, lineup, espn_total in [
                    (box.home_team, box.home_lineup, box.home_score),
                    (box.away_team, box.away_lineup, box.away_score),
                ]:
                    player_sums[(side.team_id, week)] = _active_player_sum(lineup)
                    espn_totals[(side.team_id, week)] = round(espn_total, 2)

    def _pairings(week):
        pairs = set()
        for b in boxes_by_week.get(week, []):
            if isinstance(b, dict):
                pairs.add(frozenset([b["home_team_id"], b["away_team_id"]]))
            else:
                pairs.add(frozenset([b.home_team.team_id, b.away_team.team_id]))
        return pairs

    def _append_check(tid, tname, check_type, label, week_reported, our_total, espn_total):
        if espn_total is None:
            return
        rows.append({
            "season": season,
            "week": week_reported,
            "team_id": tid,
            "team_name": tname,
            "check_type": check_type,
            "label": label,
            "our_score": round(our_total, 2),
            "espn_score": espn_total,
            "diff": round(our_total - espn_total, 2),
        })

    pw0_pairs = _pairings(pw[0])
    # Standard format (2+2) requires 4 playoff weeks; 3-week seasons always use the else path
    standard_format = len(pw) >= 4 and max_week >= pw[1] and (pw0_pairs == _pairings(pw[1]))

    if standard_format:
        # ── Standard 2+2 format (most seasons) ───────────────────────────────
        # Toilet bowl: same pairing at pw[0] AND pw[2]
        toilet_bowl_ids = set()
        if max_week >= pw[2]:
            for pair in pw0_pairs & _pairings(pw[2]):
                toilet_bowl_ids.update(pair)

        # Round 1: pw[0]+pw[1] vs ESPN at pw[0] (settled after pw[1])
        if max_week >= pw[1]:
            for team in league.teams:
                tid = team.team_id
                if tid in toilet_bowl_ids:
                    continue
                our = player_sums.get((tid, pw[0]), 0) + player_sums.get((tid, pw[1]), 0)
                _append_check(tid, team.team_name.strip(), "playoff_round1",
                              f"R1 wk{pw[0]}+{pw[1]}", pw[1], our,
                              espn_totals.get((tid, pw[0])))

        # Round 2: pw[2]+pw[3] vs ESPN at pw[2] (settled after pw[3])
        if max_week >= pw[3]:
            for team in league.teams:
                tid = team.team_id
                if tid in toilet_bowl_ids:
                    continue
                our = player_sums.get((tid, pw[2]), 0) + player_sums.get((tid, pw[3]), 0)
                _append_check(tid, team.team_name.strip(), "playoff_round2",
                              f"R2 wk{pw[2]}+{pw[3]}", pw[3], our,
                              espn_totals.get((tid, pw[2])))

        # Toilet bowl: 4-week sum vs ESPN at pw[2]
        if max_week >= pw[2]:
            for team in league.teams:
                tid = team.team_id
                if tid not in toilet_bowl_ids:
                    continue
                our = sum(player_sums.get((tid, w), 0) for w in pw if w <= max_week)
                _append_check(tid, team.team_name.strip(), "toilet_bowl",
                              f"Toilet wk{pw[0]}-{pw[3]}",
                              pw[3] if max_week >= pw[3] else pw[2], our,
                              espn_totals.get((tid, pw[2])))

    else:
        # ── Non-standard 3-week format (2022) ────────────────────────────────
        # R1 = pw[0] (1 week), Finals = pw[1]+pw[2] (2 weeks)
        # Sacko = all 3 playoff weeks: pw[0]+pw[1]+pw[2]

        # Round 1 (1-week individual check at pw[0])
        for box in boxes_by_week.get(pw[0], []):
            if isinstance(box, dict):
                sides = [
                    (box["home_team_id"], round(sum(p["points"] for p in box["home_players"] if p["is_active"]), 2), box["home_total"]),
                    (box["away_team_id"], round(sum(p["points"] for p in box["away_players"] if p["is_active"]), 2), box["away_total"]),
                ]
                for tid, our, espn_total in sides:
                    espn = round(espn_total, 2) if espn_total is not None else None
                    rows.append({
                        "season": season, "week": pw[0],
                        "team_id": tid, "team_name": team_map.get(tid, str(tid)),
                        "check_type": "playoff_round1",
                        "label": f"R1 wk{pw[0]} (1-wk)",
                        "our_score": our, "espn_score": espn,
                        "diff": round(our - (espn or 0), 2),
                    })
            else:
                for side, lineup, espn_total in [
                    (box.home_team, box.home_lineup, box.home_score),
                    (box.away_team, box.away_lineup, box.away_score),
                ]:
                    our = _active_player_sum(lineup)
                    espn = round(espn_total, 2) if espn_total is not None else None
                    rows.append({
                        "season": season, "week": pw[0],
                        "team_id": side.team_id, "team_name": side.team_name.strip(),
                        "check_type": "playoff_round1",
                        "label": f"R1 wk{pw[0]} (1-wk)",
                        "our_score": our, "espn_score": espn,
                        "diff": round(our - (espn or 0), 2),
                    })

        # Sacko: same pairing across all 3 playoff weeks
        toilet_bowl_ids = set()
        if max_week >= pw[2]:
            recurring = _pairings(pw[0]) & _pairings(pw[1]) & _pairings(pw[2])
            for pair in recurring:
                toilet_bowl_ids.update(pair)

        # Finals: pw[1]+pw[2] vs ESPN at pw[1] (ESPN reports cumulative at round start)
        if max_week >= pw[2]:
            for team in league.teams:
                tid = team.team_id
                if tid in toilet_bowl_ids:
                    continue
                our = player_sums.get((tid, pw[1]), 0) + player_sums.get((tid, pw[2]), 0)
                _append_check(tid, team.team_name.strip(), "playoff_round2",
                              f"Finals wk{pw[1]}+{pw[2]}", pw[2], our,
                              espn_totals.get((tid, pw[1])))

        # Sacko: 3-week sum vs ESPN at pw[0] (ESPN reports cumulative at round start)
        if max_week >= pw[2]:
            for team in league.teams:
                tid = team.team_id
                if tid not in toilet_bowl_ids:
                    continue
                our = sum(player_sums.get((tid, w), 0) for w in pw if w <= max_week)
                _append_check(tid, team.team_name.strip(), "toilet_bowl",
                              f"Sacko wk{pw[0]}-{pw[2]}", pw[2], our,
                              espn_totals.get((tid, pw[0])))

    df = pd.DataFrame(rows)
    _save(season, "validation_df", df)
    return df


def get_boxscores_df(season: int) -> pd.DataFrame:
    """Player-level box score data for all played weeks."""
    arc = _from_archive("boxscores", season)
    if arc is not None:
        return arc
    cached = _load(season, "boxscores_df")
    if cached is not None:
        return cached
    league = get_league(season)
    cfg = season_config(season)
    team_map = {t.team_id: t.team_name.strip() for t in league.teams}
    rows = []

    if season < 2018:
        # 2016-2017: build player points from NFL stats (nfl-data-py) since
        # ESPN's per-player weekly scores aren't available via the API.
        from data.legacy_stats import build_legacy_boxscores
        boxes_by_week = _box_scores_all_weeks_legacy(league, cfg)
        # Inject team_name into matchup dicts for legacy_stats
        for week_matchups in boxes_by_week.values():
            for m in week_matchups:
                m.setdefault("home_team_name", team_map.get(m["home_team_id"], str(m["home_team_id"])))
                m.setdefault("away_team_name", team_map.get(m["away_team_id"], str(m["away_team_id"])))
        df = build_legacy_boxscores(season, boxes_by_week)
        _save(season, "boxscores_df", df)
        return df

    elif season == 2018:
        boxes_by_week = _box_scores_all_weeks_legacy(league, cfg)
        for week in sorted(boxes_by_week):
            for matchup in boxes_by_week.get(week, []):
                for team_id, players in [
                    (matchup["home_team_id"], matchup["home_players"]),
                    (matchup["away_team_id"], matchup["away_players"]),
                ]:
                    team_score = round(sum(p["points"] for p in players if p["is_active"]), 2)
                    team_proj = round(sum(p["projected"] for p in players if p["is_active"]), 2)
                    for p in players:
                        rows.append({
                            "season": season,
                            "week": week,
                            "team_id": team_id,
                            "team_name": team_map.get(team_id, str(team_id)),
                            "team_score": team_score,
                            "team_projected": team_proj,
                            "player_id": p["player_id"],
                            "player_name": p["name"],
                            "position": p["position"],
                            "slot": p["slot"],
                            "points": p["points"],
                            "projected": p["projected"],
                            "is_active_slot": p["is_active"],
                            "on_bench": p["slot"] == "BE",
                            "injured": p["injured"],
                            "injury_status": p["injury_status"],
                            "pro_team": p["pro_team"],
                            "percent_owned": p["percent_owned"],
                        })
    else:  # 2019+
        # Fetch through _box_scores_all_weeks rather than looping box_scores
        # here. The hand-rolled loop this replaces swallowed fetch failures
        # with `except: continue`, which is how the 2025 archive ended up
        # missing boxscore weeks 11 and 14 while every other dataset had them.
        boxes_by_week = _box_scores_all_weeks(league, cfg)
        for week in sorted(boxes_by_week):
            for box in boxes_by_week[week]:
                for side, lineup, proj in [
                    (box.home_team, box.home_lineup, box.home_projected),
                    (box.away_team, box.away_lineup, box.away_projected),
                ]:
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


def get_manager_map(season: int) -> dict[int, str]:
    """
    Returns {team_id: manager_name} for a given season.
    Applies MANAGER_OVERRIDES and OWNER_ID_TO_NAME from config.
    Safe to call on every page render — uses the cached league object.
    """
    if USE_ARCHIVE:
        try:
            from data import archive
            m = archive.manager_map(season)
            if m:
                return m
        except Exception:
            pass
    league = get_league(season)
    result = {}
    for team in league.teams:
        owner_ids = [o.get("id", "") for o in getattr(team, "owners", [])]
        result[team.team_id] = get_manager_name(season, team.team_id, owner_ids)
    return result


def get_current_week(season: int) -> int:
    """
    Last scoring period ESPN recorded for the season.

    Reads the archive first so completed seasons need neither the pickled
    League object nor a live ESPN call.
    """
    if USE_ARCHIVE:
        try:
            from data import archive
            cw = archive.current_week(season)
            if cw is not None:
                return cw
        except Exception:
            pass
    try:
        return get_league(season).current_week
    except Exception:
        if USE_ARCHIVE:
            return 0
        raise


def get_upcoming_df(season: int) -> pd.DataFrame:
    """
    The week about to be played: who faces whom, and ESPN's projected scores.

    Deliberately not routed through _drop_unplayed_weeks, which exists to throw
    exactly this week away. Everywhere else an unplayed week is a week of
    zeroes that must never reach the archive; here it is the whole point, and
    it is kept in its own dataset so it can never be mistaken for a result.

    The deployed site has no ESPN credentials, so this is captured by the
    weekly job and read back from data/archive/upcoming.csv like everything
    else. Projections are therefore a Tuesday snapshot and will drift as
    players are ruled out later in the week.

    Returns an empty frame once the season is over, which is what tells the
    Dashboard to show no matchup table at all.

    `projected` is the best lineup each team could start, not ESPN's total for
    the lineup as set. The snapshot is taken Tuesday, before most managers
    have touched their lineups, so ESPN's own figure mostly measures last
    week's decisions: a bench WR projected above the starting flex still counts
    zero. Starters are re-picked from ESPN's player projections under the
    league's slot rules (the same assignment Lineup Efficiency uses), leaving
    out IR-slotted players and anyone already ruled out.
    """
    arc = _from_archive("upcoming", season)
    if arc is not None:
        return arc

    league = get_league(season)
    cfg = season_config(season)
    week = min(league.current_week, cfg["total_weeks"])
    if week < 1 or league.current_week > cfg["total_weeks"]:
        return pd.DataFrame()

    try:
        boxes = league.box_scores(week=week)
    except Exception:
        return pd.DataFrame()

    from analysis.efficiency import optimal_lineup_points, season_slot_requirements

    # The slot rules come from this week's lineups themselves - the most common
    # starting signature across the league, so one manager's empty slot does
    # not shrink everyone's lineup. A week-1 snapshot has no archived boxscores
    # to learn them from, and espn-api's position_slot_counts pairs labels to
    # counts by position in a list, which is not something to lean on.
    lineups = [lu for box in boxes
               for lu in (box.home_lineup, box.away_lineup) if lu]
    slot_counts = season_slot_requirements(pd.DataFrame(
        {"week": week, "team_id": i, "slot": p.lineupSlot,
         "is_active_slot": p.lineupSlot not in ("BE", "IR")}
        for i, lineup in enumerate(lineups) for p in lineup
    ))

    unavailable = {"OUT", "INJURY_RESERVE", "SUSPENSION"}

    def best_projected(lineup, espn_proj):
        pool = [p for p in (lineup or [])
                if p.lineupSlot != "IR" and p.injuryStatus not in unavailable]
        if not slot_counts or not pool:
            return round(float(espn_proj or 0), 2)
        return optimal_lineup_points(
            [p.position for p in pool],
            [float(p.projected_points or 0) for p in pool],
            slot_counts,
        )

    rows = []
    for box in boxes:
        home = best_projected(box.home_lineup, box.home_projected)
        away = best_projected(box.away_lineup, box.away_projected)
        for team, proj, opp, opp_proj in [
            (box.home_team, home, box.away_team, away),
            (box.away_team, away, box.home_team, home),
        ]:
            if team is None or opp is None:
                continue
            rows.append({
                "season": season,
                "week": week,
                "team_id": team.team_id,
                "team_name": team.team_name.strip(),
                "projected": proj,
                "opp_id": opp.team_id,
                "opp_name": opp.team_name.strip(),
                "opp_projected": opp_proj,
                "is_playoff": week in cfg["playoff_weeks"],
            })
    return pd.DataFrame(rows)


def get_draft_df(season: int) -> pd.DataFrame:
    arc = _from_archive("draft", season)
    if arc is not None:
        return arc
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
    arc = _from_archive("standings", season)
    if arc is not None:
        return arc
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


# ── Transactions: waiver claims, free-agent moves, drops, trades ─────────────

class TransactionsUnavailable(RuntimeError):
    """ESPN no longer serves the record needed to build a season's transactions."""


# defaultPositionId on ESPN's player list. Not the lineup-slot POSITION_MAP,
# which numbers positions differently and would call every WR a RB.
_PRO_POSITION = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}

# The executed moves the activity feed carries a trade as: 244 is one player
# changing hands, 239 a player dropped to make room as part of the deal.
_MSG_TRADED, _MSG_TRADE_DROP = 244, 239


def _eastern(ms) -> str:
    return (pd.Timestamp(int(ms), unit="ms", tz="UTC")
            .tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S"))


def _activity_trade_topics(league) -> list:
    """Every trade topic in the league's activity feed, newest first."""
    from espn_api.requests.espn_requests import ESPNInvalidLeague
    topics, offset, page = [], 0, 25
    while True:
        filters = {"topics": {
            "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
            "limit": page, "limitPerMessageSet": {"value": 25}, "offset": offset,
            "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
            "sortFor": {"sortPriority": 2, "sortAsc": False},
            "filterIncludeMessageTypeIds": {"value": [_MSG_TRADED, _MSG_TRADE_DROP]},
        }}
        try:
            data = league.espn_request.league_get(
                extend="/communication/",
                params={"view": "kona_league_communication"},
                headers={"x-fantasy-filter": json.dumps(filters)})
        except ESPNInvalidLeague as e:
            raise TransactionsUnavailable(
                f"{league.year}: ESPN's activity feed is gone ({e}). It is only "
                f"served for the live season, and trades cannot be rebuilt "
                f"without it - see get_transactions_df.") from e
        batch = data.get("topics", [])
        topics += batch
        if len(batch) < page:
            return [t for t in topics
                    if any(m.get("messageTypeId") == _MSG_TRADED
                           for m in t.get("messages", []))]
        offset += page


def get_transactions_df(season: int) -> pd.DataFrame:
    """
    Every player movement of the season: one row per player per transaction.

    A row is a player going from one team to another, with team 0 standing for
    the free-agent pool. So a waiver claim that drops someone is two rows, an
    add (0 -> team) and a drop (team -> 0), sharing a transaction_id, and a
    two-for-one trade is three rows, one per player, each with the team that
    sent him and the team that got him. Nothing is stored per manager: "what
    did Matt receive" is to_team_id == Matt's team, and "sent" is
    from_team_id. That keeps a trade from being recorded twice, once from each
    side, where the two copies could drift apart.

    It is shaped for the analysis this exists for, which is judging how moves
    paid off. player_id joins straight onto boxscores, and boxscores already
    knows, week by week, which roster a player sat on and what he scored there.
    That weekly roster is the truth about when a player was actually yours;
    `week` here is ESPN's scoring period when the move went through, and a
    Wednesday waiver claim is already stamped with the week about to be
    played. executed_at is exact, in US Eastern time.

    kind is waiver, free_agent or trade. The waiver/free_agent split is what
    tells a $0 bid from a player picked up for nothing after waivers cleared:
    both have no money attached, and only the transaction type separates
    them. bid is the FAAB amount for waiver claims and blank for everything
    else. A drop with no add is kind free_agent.

    Waiver, free-agent and drop moves come from mTransactions2, one request per
    scoring period, which carries the transaction type and the bid. ESPN keeps
    those for past seasons back to 2018, and nothing before. Trades are harder:

    - While a season is live they come from the league activity feed.
      mTransactions2 does list trades, but by the end of 2025 it had dropped
      the player lists from 12 of the season's 13 accepted trades. The feed
      has them, but ESPN deletes it once the season is over - 2025 answers
      "This Communication Group does not exist".
    - For a finished season they are rebuilt from the weekly rosters in the
      archived boxscores, checked against the acceptances ESPN still keeps.
      data/trade_inference.py has the method and the evidence for it.

    source says which: espn for a move ESPN recorded, inferred for one worked
    out from the rosters. note explains any inferred row that needed a
    judgment - a drop ESPN never logged, a player traded twice in one week, a
    vetoed trade the commissioner entered by hand. The feed is still preferred
    while it exists, because it is a record rather than a deduction.

    Only transactions that went through are kept. Cancelled and failed claims,
    declined and vetoed trades, and lineup moves are all left out.
    """
    if USE_ARCHIVE:
        arc = _from_archive("transactions", season)
        if arc is not None:
            return arc
        # Tracking started with a live season, so most seasons have no rows,
        # and falling through to ESPN would make every page view of 2019 a
        # live call for data ESPN cannot give back anyway.
        try:
            from data import archive
            if archive.has("transactions"):
                return pd.DataFrame()
        except Exception:
            pass

    league = get_league(season)
    cfg = season_config(season)
    last_period = min(max(int(league.current_week), 1), cfg["total_weeks"])

    # One period at a time: the view returns only the period asked for. Some
    # records repeat across periods (preseason roster moves came back in all
    # eighteen for 2026), so de-duplicate on id, keeping the first sighting.
    raw = {}
    for period in range(0, last_period + 1):
        data = league.espn_request.league_get(
            params={"view": "mTransactions2", "scoringPeriodId": period})
        for t in data.get("transactions", []):
            raw.setdefault(t["id"], t)

    players = {p["id"]: p for p in league.espn_request.get_pro_players()}

    def name(pid):
        n = league.player_map.get(pid)
        if isinstance(n, str):
            return n
        return players.get(pid, {}).get("fullName") or f"Unknown ({pid})"

    def position(pid):
        return _PRO_POSITION.get(players.get(pid, {}).get("defaultPositionId"), "")

    # Standalone drops are filed as ROSTER, not FREEAGENT. Leaving ROSTER out
    # lost most drops that came without an add, and made every one of those
    # players look, from the rosters, like he had been traded away.
    moves = []
    for t in raw.values():
        if t.get("status") != "EXECUTED" or t["type"] not in ("WAIVER", "FREEAGENT", "ROSTER"):
            continue
        kind = "waiver" if t["type"] == "WAIVER" else "free_agent"
        for item in t.get("items", []):
            if item["type"] not in ("ADD", "DROP"):
                continue
            moves.append({
                "ms": int(t.get("processDate") or t.get("proposedDate")),
                "week": int(t["scoringPeriodId"]),
                "transaction_id": t["id"],
                "kind": kind,
                "action": item["type"].lower(),
                "from_team_id": int(item["fromTeamId"]),
                "to_team_id": int(item["toTeamId"]),
                "player_id": int(item["playerId"]),
                "bid": t.get("bidAmount", 0) if kind == "waiver" else None,
                "source": "espn",
                "note": "",
            })

    try:
        trades = _feed_trades(league, raw, season)
    except TransactionsUnavailable:
        # The season is over and its feed with it: work the trades out from
        # the weekly rosters instead. See data/trade_inference.py.
        from data import archive
        from data.trade_inference import infer_trades
        box = archive.get("boxscores", season)
        if box.empty:
            raise TransactionsUnavailable(
                f"{season}: no activity feed and no archived boxscores to "
                f"rebuild trades from")
        # The draft is the roster before week 1. It carries names, not ids,
        # so resolve them through that season's boxscores, then ESPN's map;
        # the few that neither knows are left out rather than guessed.
        draft = archive.get("draft", season)
        by_name = dict(zip(box["player_name"], box["player_id"]))
        week0 = {}
        for pname, team in zip(draft["player_name"], draft["team_id"]):
            # player_map maps both ways, so a name that is not a player comes
            # back as None or as another name, never as a number.
            pid = by_name.get(pname, league.player_map.get(pname))
            if pid is not None and not isinstance(pid, str):
                week0[int(pid)] = int(team)
        legs, loose, remove, notes = infer_trades(season, box, moves, raw, week0)
        for line in notes:
            print(f"  trades      {season}  {line}")
        moves = [m for m in moves if (m["transaction_id"], m["player_id"]) not in remove]
        trades = ([{**l, "kind": "trade", "bid": None} for l in legs]
                  + [{**l, "kind": "free_agent", "bid": None} for l in loose])

    rows = []
    for m in moves + trades:
        pid = m["player_id"]
        rows.append({
            "season": season,
            "week": m["week"],
            "executed_at": _eastern(m["ms"]) if m.get("ms") is not None else None,
            "transaction_id": m["transaction_id"],
            "kind": m["kind"],
            "action": m["action"],
            "from_team_id": m["from_team_id"],
            "to_team_id": m["to_team_id"],
            "player_id": pid,
            "player_name": name(pid),
            "position": position(pid),
            "bid": m["bid"],
            "source": m["source"],
            "note": m["note"],
        })

    df = pd.DataFrame(rows, columns=TRANSACTION_COLUMNS)
    df["bid"] = df["bid"].astype("Int64")
    return df.sort_values(["executed_at", "transaction_id", "action", "player_id"],
                          ignore_index=True)


TRANSACTION_COLUMNS = ["season", "week", "executed_at", "transaction_id", "kind",
                       "action", "from_team_id", "to_team_id", "player_id",
                       "player_name", "position", "bid", "source", "note"]


def _feed_trades(league, raw: dict, season: int) -> list:
    """A live season's trades, from the activity feed. Raises once it is gone."""
    # The feed carries no scoring period, so a trade takes the period of the
    # latest move ESPN recorded at or before it. FUTURE_ROSTER is left out of
    # that timeline: it is a lineup set ahead for a later week and would pull
    # a trade forward.
    timeline = sorted(
        (int(t.get("processDate") or t.get("proposedDate")), int(t["scoringPeriodId"]))
        for t in raw.values()
        if t["type"] != "FUTURE_ROSTER" and (t.get("processDate") or t.get("proposedDate")))

    def period_at(ms):
        earlier = [p for when, p in timeline if when <= ms]
        return earlier[-1] if earlier else (timeline[0][1] if timeline else 1)

    trades = []
    for topic in _activity_trade_topics(league):
        when = int(topic["date"])
        for m in topic["messages"]:
            mtype = m.get("messageTypeId")
            if mtype == _MSG_TRADED:
                src, dst = m.get("from"), m.get("to")
            elif mtype == _MSG_TRADE_DROP:
                src, dst = m.get("for"), 0
            else:
                continue
            pid = m.get("targetId")
            # Stop rather than archive a half-understood trade. The feed is
            # gone after the season, so a bad row cannot be re-pulled later,
            # but a failed build can be fixed and re-run while it still exists.
            if not all(isinstance(v, int) for v in (src, dst, pid)):
                raise ValueError(
                    f"{season}: trade message not understood, topic {topic.get('id')}: "
                    f"{json.dumps(m)[:400]}")
            trades.append({
                "ms": when, "week": period_at(when), "transaction_id": topic["id"],
                "kind": "trade", "action": "trade" if mtype == _MSG_TRADED else "drop",
                "from_team_id": src, "to_team_id": dst, "player_id": pid,
                "bid": None, "source": "espn", "note": "",
            })
    return trades


# ── App-mode safety net ──────────────────────────────────────────────────────
# A season the archive has not reached yet falls through to a live ESPN call.
# That is fine while it works, but ESPN_S2 expires, and when it does the whole
# page dies on a traceback - which reads to a league mate as the site being
# broken rather than as a season that has not started.
#
# So in app mode (USE_ARCHIVE on) an unreachable season yields an empty frame
# and the page's require_data says so plainly. Archive builds set USE_ARCHIVE
# to False and still raise, because a build that quietly wrote nothing would be
# far worse than one that stopped and said why.
def _empty_when_unavailable(fn):
    @functools.wraps(fn)
    def wrapper(season, *args, **kwargs):
        try:
            return fn(season, *args, **kwargs)
        except Exception:
            if USE_ARCHIVE:
                return pd.DataFrame()
            raise
    return wrapper


get_matchups_df = _empty_when_unavailable(get_matchups_df)
get_boxscores_df = _empty_when_unavailable(get_boxscores_df)
get_draft_df = _empty_when_unavailable(get_draft_df)
get_standings_df = _empty_when_unavailable(get_standings_df)
get_validation_df = _empty_when_unavailable(get_validation_df)
get_upcoming_df = _empty_when_unavailable(get_upcoming_df)
get_transactions_df = _empty_when_unavailable(get_transactions_df)
