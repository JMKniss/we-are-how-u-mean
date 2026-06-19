"""
Lineup efficiency analysis using player-level box score data.
"""
import pandas as pd
import numpy as np


def lineup_efficiency(boxscores_df: pd.DataFrame) -> pd.DataFrame:
    """
    Actual score vs optimal possible score (best available lineup).
    Efficiency % = actual / optimal * 100.
    Bench points = sum of bench player points.
    """
    df = boxscores_df.copy()

    # Positions that count as active (not bench/IR)
    active = df[df["is_active_slot"]].groupby(["season", "week", "team_id", "team_name"])["points"].sum().reset_index()
    active = active.rename(columns={"points": "actual_score"})

    bench = df[df["on_bench"]].groupby(["season", "week", "team_id", "team_name"])["points"].sum().reset_index()
    bench = bench.rename(columns={"points": "bench_points"})

    # Optimal: for each week/team, find best possible lineup
    # Group by position slot and pick top scorers to fill slots
    def optimal_score(group):
        # Use slot eligibility to find optimal — simplified: take top N by position
        # Active slots from that week
        active_slots = group[group["is_active_slot"]]["slot"].value_counts()
        slot_counts = active_slots.to_dict()

        all_players = group[~group["slot"].isin(["IR"])].copy()
        all_players = all_players.sort_values("points", ascending=False)

        total = 0.0
        filled = {}
        # First pass: fill exact position slots
        for _, player in all_players.iterrows():
            pos = player["position"]
            slot = player["slot"]
            needed = slot_counts.get(slot, 0)
            used = filled.get(slot, 0)
            if used < needed:
                total += player["points"]
                filled[slot] = used + 1
        return total

    opt_rows = []
    for (season, week, team_id, team_name), group in df.groupby(["season", "week", "team_id", "team_name"]):
        active_pts = group[group["is_active_slot"]]["points"].sum()
        bench_pts = group[group["on_bench"]]["points"].sum()
        all_pts = group[~group["slot"].isin(["IR"])]["points"].sum()
        # Optimal: active + any bench players who outscored active
        # Simple proxy: sort all non-IR by points, take top N where N = active count
        n_active = group[group["is_active_slot"]].shape[0]
        top_n = group[~group["slot"].isin(["IR"])].nlargest(n_active, "points")["points"].sum()
        opt_rows.append({
            "season": season,
            "week": week,
            "team_id": team_id,
            "team_name": team_name,
            "actual_score": active_pts,
            "optimal_score": top_n,
            "bench_points": bench_pts,
            "points_left_on_bench": max(0, top_n - active_pts),
        })

    result = pd.DataFrame(opt_rows)
    result["efficiency_pct"] = (result["actual_score"] / result["optimal_score"].replace(0, np.nan) * 100).round(1)

    summary = result.groupby(["team_id", "team_name"]).agg(
        avg_actual=("actual_score", "mean"),
        avg_optimal=("optimal_score", "mean"),
        avg_bench=("bench_points", "mean"),
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
    grp = df.groupby(["player_id", "player_name", "position", "pro_team"]).agg(
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
        avg_proj_diff=("proj_diff", "mean"),
    ).reset_index()
    summary["beat_proj_pct"] = (summary["times_beat_proj"] / summary["total_weeks"] * 100).round(1)
    return summary.sort_values("avg_proj_diff", ascending=False).reset_index(drop=True)
