"""
Lineup efficiency analysis using player-level box score data.
"""
import pandas as pd
import numpy as np
from scipy.optimize import linear_sum_assignment

# Which player positions may fill each lineup slot.
# Keys are ESPN slot names as they appear in boxscores_df["slot"].
SLOT_ELIGIBILITY = {
    "QB":           {"QB"},
    "RB":           {"RB"},
    "WR":           {"WR"},
    "TE":           {"TE"},
    "K":            {"K"},
    "D/ST":         {"D/ST"},
    "RB/WR":        {"RB", "WR"},
    "WR/TE":        {"WR", "TE"},
    "RB/WR/TE":     {"RB", "WR", "TE"},          # FLEX
    "OP":           {"QB", "RB", "WR", "TE"},    # superflex
    "QB/RB/WR/TE":  {"QB", "RB", "WR", "TE"},
}

# Slots that are not real starting positions.
NON_STARTING_SLOTS = {"BE", "IR"}


def season_slot_requirements(boxscores_df: pd.DataFrame) -> dict:
    """
    The league's canonical starting lineup for a season, as {slot: count}.

    Taken as the most common starting-slot signature across all team-weeks
    rather than per-team-per-week, because a manager who leaves a slot empty
    should be measured against the full lineup they were allowed to field,
    not against their own mistake. Roster construction has never changed
    mid-season in this league, so one signature per season is correct.
    """
    sigs = {}
    for _, g in boxscores_df.groupby(["week", "team_id"]):
        counts = g[g["is_active_slot"]]["slot"].value_counts().to_dict()
        key = tuple(sorted(counts.items()))
        sigs[key] = sigs.get(key, 0) + 1
    if not sigs:
        return {}
    best = max(sigs.items(), key=lambda kv: kv[1])[0]
    return dict(best)


def optimal_lineup_points(positions, points, slot_counts) -> float:
    """
    Highest total points achievable from this player pool under the slot rules.

    Solved as a maximum-weight bipartite assignment rather than greedily, so
    the answer is provably optimal for any slot structure, including multiple
    flex spots. Dummy columns let a slot go unfilled when no eligible player
    is available.
    """
    slots = []
    for slot, n in slot_counts.items():
        slots.extend([slot] * int(n))
    if not slots or len(positions) == 0:
        return 0.0

    n_slots = len(slots)
    n_players = len(positions)
    # Real players plus one dummy per slot, so a slot can always be filled.
    width = n_players + n_slots
    BIG = 1e6
    cost = np.full((n_slots, width), BIG)

    for i, slot in enumerate(slots):
        eligible = SLOT_ELIGIBILITY.get(slot)
        for j in range(n_players):
            if eligible is None or positions[j] in eligible:
                cost[i, j] = -points[j]        # negative: minimising maximises points
        cost[i, n_players + i] = 0.0           # dummy: slot left empty, worth 0

    rows, cols = linear_sum_assignment(cost)
    total = 0.0
    for r, c in zip(rows, cols):
        if c < n_players and cost[r, c] < BIG:
            total += points[c]
    return round(float(total), 2)


def lineup_efficiency(boxscores_df: pd.DataFrame):
    """
    Actual score vs the best lineup that could legally have been fielded.

    The optimal lineup respects position eligibility: two big quarterback
    weeks cannot both count, because only one QB slot exists. The pool is
    every non-IR player on the roster that week (starters plus bench).

    Efficiency % = actual / optimal * 100.

    Seasons without bench data (2016-2017, sourced from nfl-data-py) have no
    alternatives to choose from, so optimal would trivially equal actual.
    Those rows get NaN efficiency instead of a meaningless 100%.
    """
    df = boxscores_df.copy()

    rows = []
    for season, season_df in df.groupby("season"):
        slot_counts = season_slot_requirements(season_df)
        # Real slot names mean real lineup rules. 2016-2017 report "STARTER"
        # for everything and carry no bench, so optimal is not computable.
        computable = (
            bool(slot_counts)
            and not set(slot_counts) & {"STARTER"}
            and bool(season_df["on_bench"].any())
        )

        for (week, team_id, team_name), g in season_df.groupby(
            ["week", "team_id", "team_name"]
        ):
            actual = round(float(g[g["is_active_slot"]]["points"].sum()), 2)

            if computable:
                pool = g[~g["slot"].isin(["IR"])]
                optimal = optimal_lineup_points(
                    pool["position"].tolist(),
                    pool["points"].tolist(),
                    slot_counts,
                )
                # Actual can exceed a computed optimal only if the data is odd;
                # clamp so efficiency never exceeds 100%.
                optimal = max(optimal, actual)
                left = round(optimal - actual, 2)
                eff = round(actual / optimal * 100, 1) if optimal else np.nan
            else:
                optimal, left, eff = np.nan, np.nan, np.nan

            rows.append({
                "season": season,
                "week": week,
                "team_id": team_id,
                "team_name": team_name,
                "actual_score": actual,
                "optimal_score": optimal,
                "points_left_on_bench": left,
                "efficiency_pct": eff,
            })

    result = pd.DataFrame(rows)

    summary = result.groupby(["team_id", "team_name"]).agg(
        avg_actual=("actual_score", "mean"),
        avg_optimal=("optimal_score", "mean"),
        avg_left_on_bench=("points_left_on_bench", "mean"),
        avg_efficiency=("efficiency_pct", "mean"),
        total_left_on_bench=("points_left_on_bench", "sum"),
    ).reset_index().round(2)
    summary = summary.sort_values("avg_efficiency", ascending=False).reset_index(drop=True)
    summary.index += 1
    return summary, result


def top_players(boxscores_df: pd.DataFrame, position: str = None, top_n: int = 20) -> pd.DataFrame:
    """Top scoring players across all weeks."""
    df = boxscores_df[boxscores_df["is_active_slot"]].copy()
    if position:
        df = df[df["position"] == position]
    # dropna=False: pro_team is NaN for every 2016-2017 player (nfl-data-py path
    # never sets it) and for released players in later seasons. Without this the
    # groupby silently drops those rows — 2016/2017 returned an empty leaderboard.
    grp = df.groupby(["player_id", "player_name", "position", "pro_team"],
                     dropna=False).agg(
        total_points=("points", "sum"),
        avg_points=("points", "mean"),
        weeks_played=("points", "count"),
        avg_projected=("projected", "mean"),
    ).reset_index().round(2)
    return grp.sort_values("total_points", ascending=False).head(top_n).reset_index(drop=True)


def projected_vs_actual(boxscores_df: pd.DataFrame) -> pd.DataFrame:
    """Team-level: how often did they outscore their projection?"""
    df = boxscores_df[boxscores_df["is_active_slot"]].copy()
    team_weekly = df.groupby(["season", "week", "team_id", "team_name"]).agg(
        actual=("points", "sum"),
        projected=("projected", "sum"),
    ).reset_index()
    team_weekly["beat_projection"] = team_weekly["actual"] > team_weekly["projected"]
    team_weekly["proj_diff"] = team_weekly["actual"] - team_weekly["projected"]

    summary = team_weekly.groupby(["team_id", "team_name"]).agg(
        times_beat_proj=("beat_projection", "sum"),
        total_weeks=("beat_projection", "count"),
        avg_projected=("projected", "mean"),
        avg_proj_diff=("proj_diff", "mean"),
    ).reset_index()
    summary["beat_proj_pct"] = (summary["times_beat_proj"] / summary["total_weeks"] * 100).round(1)
    return summary.sort_values("beat_proj_pct", ascending=False).reset_index(drop=True)


def player_manager_sequence(boxscores_df: pd.DataFrame, player_ids=None) -> dict:
    """
    Ordered fantasy teams that rostered each player, as {player_id: [team_id, ...]}.

    Consecutive repeats are collapsed, so a player held all season yields one
    entry and a player who changed hands yields one entry per spell. A player
    who leaves and later returns to the same manager correctly yields
    A, B, A rather than A, B.

    Counts every week the player was on a roster, bench included, since the
    question is who held him rather than who started him.
    """
    df = boxscores_df
    if player_ids is not None:
        df = df[df["player_id"].isin(list(player_ids))]
    df = df.sort_values(["player_id", "season", "week"])

    out = {}
    for pid, g in df.groupby("player_id", sort=False):
        seq = []
        for tid in g["team_id"]:
            if not seq or seq[-1] != tid:
                seq.append(tid)
        out[pid] = seq
    return out
