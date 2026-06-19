"""
Monte Carlo playoff projections.
"""
import numpy as np
import pandas as pd


def simulate_playoffs(
    matchups_df: pd.DataFrame,
    reg_season_weeks: int = 13,
    playoff_spots: int = 4,
    n_simulations: int = 10_000,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Simulate remaining regular season games using each team's scoring distribution.
    Returns playoff probability for each team.
    """
    rng = np.random.default_rng(seed)
    played = matchups_df[matchups_df["week"] <= reg_season_weeks].copy()
    remaining_weeks = [
        w for w in range(1, reg_season_weeks + 1)
        if w not in played["week"].unique()
    ]

    teams = played[["team_id", "team_name"]].drop_duplicates().reset_index(drop=True)
    team_ids = teams["team_id"].tolist()

    # Build per-team score distribution params
    score_params = {}
    for tid in team_ids:
        scores = played[played["team_id"] == tid]["score"].values
        score_params[tid] = (scores.mean() if len(scores) > 0 else 100.0,
                             scores.std() if len(scores) > 1 else 15.0)

    # Current wins
    current_wins = played.groupby("team_id").apply(
        lambda x: (x["outcome"] == "W").sum()
    ).to_dict()

    # Schedule for remaining weeks — pair up teams round-robin style
    # For simplicity, use the existing schedule if we have it
    future_matchups = matchups_df[matchups_df["week"].isin(remaining_weeks)][
        ["week", "team_id", "opp_id"]
    ].drop_duplicates()

    playoff_counts = {tid: 0 for tid in team_ids}

    for _ in range(n_simulations):
        sim_wins = current_wins.copy()

        if not future_matchups.empty:
            processed = set()
            for _, row in future_matchups.iterrows():
                pair = tuple(sorted([row["team_id"], row["opp_id"]]))
                if pair in processed:
                    continue
                processed.add(pair)
                t1, t2 = pair
                mu1, s1 = score_params.get(t1, (100, 15))
                mu2, s2 = score_params.get(t2, (100, 15))
                sc1 = max(0, rng.normal(mu1, s1))
                sc2 = max(0, rng.normal(mu2, s2))
                if sc1 > sc2:
                    sim_wins[t1] = sim_wins.get(t1, 0) + 1
                else:
                    sim_wins[t2] = sim_wins.get(t2, 0) + 1

        # Playoff spots go to top N by wins (tiebreak: points_for)
        pf = played.groupby("team_id")["score"].sum().to_dict()
        sorted_teams = sorted(team_ids, key=lambda t: (sim_wins.get(t, 0), pf.get(t, 0)), reverse=True)
        for t in sorted_teams[:playoff_spots]:
            playoff_counts[t] += 1

    result = []
    for _, row in teams.iterrows():
        tid = row["team_id"]
        result.append({
            "team_id": tid,
            "team_name": row["team_name"],
            "current_wins": current_wins.get(tid, 0),
            "current_losses": played[played["team_id"] == tid].shape[0] - current_wins.get(tid, 0),
            "playoff_pct": round(playoff_counts[tid] / n_simulations * 100, 1),
        })

    return pd.DataFrame(result).sort_values("playoff_pct", ascending=False).reset_index(drop=True)


def win_probability_by_score(score: float, opp_mean: float, opp_std: float) -> float:
    """P(team scores > opp_mean) using normal CDF."""
    from scipy import stats
    if opp_std <= 0:
        return float(score > opp_mean)
    return float(stats.norm.cdf(score, loc=opp_mean, scale=opp_std))
