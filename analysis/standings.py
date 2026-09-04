"""
Standings calculations: H2H, vs-median, combined, strength of schedule.
All functions take a matchups_df as produced by espn_client.get_matchups_df().
"""
import numpy as np
import pandas as pd


def h2h_standings(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """Standard H2H win/loss record."""
    df = matchups_df.copy()
    grp = df.groupby(["team_id", "team_name"]).agg(
        wins=("outcome", lambda x: (x == "W").sum()),
        losses=("outcome", lambda x: (x == "L").sum()),
        ties=("outcome", lambda x: (x == "T").sum()),
        points_for=("score", "sum"),
        points_against=("opp_score", "sum"),
    ).reset_index()
    grp["games"] = grp["wins"] + grp["losses"] + grp["ties"]
    grp["win_pct"] = (grp["wins"] + 0.5 * grp["ties"]) / grp["games"].replace(0, np.nan)
    grp["avg_score"] = grp["points_for"] / grp["games"].replace(0, np.nan)
    grp = grp.sort_values(["wins", "points_for"], ascending=False).reset_index(drop=True)
    grp.index += 1
    return grp


def median_standings(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """
    Each week: beat the median = win, below = loss.
    Adds a second game per week on top of H2H.
    """
    df = matchups_df.copy()
    weekly_median = df.groupby("week")["score"].transform("median")
    df["median_win"] = df["score"] > weekly_median
    df["median_loss"] = df["score"] < weekly_median
    df["median_tie"] = df["score"] == weekly_median

    grp = df.groupby(["team_id", "team_name"]).agg(
        median_wins=("median_win", "sum"),
        median_losses=("median_loss", "sum"),
        median_ties=("median_tie", "sum"),
    ).reset_index().astype({"median_wins": int, "median_losses": int, "median_ties": int})
    grp = grp.sort_values("median_wins", ascending=False).reset_index(drop=True)
    grp.index += 1
    return grp


def combined_standings(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """H2H wins + median wins combined (2 games per week)."""
    h = h2h_standings(matchups_df).set_index("team_id")
    m = median_standings(matchups_df).set_index("team_id")
    merged = h.join(m[["median_wins", "median_losses", "median_ties"]], how="left")
    merged["total_wins"] = merged["wins"] + merged["median_wins"].fillna(0).astype(int)
    merged["total_losses"] = merged["losses"] + merged["median_losses"].fillna(0).astype(int)
    merged["total_games"] = merged["total_wins"] + merged["total_losses"]
    merged["total_win_pct"] = merged["total_wins"] / merged["total_games"].replace(0, np.nan)
    merged = merged.sort_values(["total_wins", "points_for"], ascending=False).reset_index()
    merged.index = range(1, len(merged) + 1)
    return merged


def strength_of_schedule(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """Average opponent score faced by each team."""
    grp = matchups_df.groupby(["team_id", "team_name"]).agg(
        avg_opp_score=("opp_score", "mean"),
        total_opp_score=("opp_score", "sum"),
        games=("opp_score", "count"),
    ).reset_index()
    grp = grp.sort_values("avg_opp_score", ascending=False).reset_index(drop=True)
    grp.index += 1
    return grp


def opponent_vs_own_average(matchups_df: pd.DataFrame) -> pd.Series:
    """
    Per team: how many points their opponents scored against them relative to
    what those opponents managed against everyone else.

    The opponent's baseline excludes the game in question, so it is genuinely
    "what they do against other people". Including it would let the game pull
    its own baseline toward itself and shrink every result by roughly 1/n.

    Positive means opponents raise their game against you, which is bad luck
    for you. Negative means they tend to have an off week against you.

    Returns a Series indexed by team_id.
    """
    df = matchups_df
    per_team = df.groupby("team_id")["score"].agg(["sum", "count"])

    opp_sum = df["opp_id"].map(per_team["sum"])
    opp_n = df["opp_id"].map(per_team["count"])
    # leave-one-out mean for the opponent, dropping this very game
    opp_baseline = (opp_sum - df["opp_score"]) / (opp_n - 1).replace(0, np.nan)

    delta = df["opp_score"] - opp_baseline
    return delta.groupby(df["team_id"]).mean()


def luck_index(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """
    Luck score = (actual wins) - (expected wins based on score percentile each week).
    Expected wins: each week, rank all scores 1..N; expected = rank/N.
    """
    df = matchups_df.copy()
    df["score_rank"] = df.groupby("week")["score"].rank(method="average")
    n_teams = df.groupby("week")["team_id"].transform("count")
    df["expected_win"] = df["score_rank"] / n_teams

    per_team = df.groupby(["team_id", "team_name"]).agg(
        actual_wins=("outcome", lambda x: (x == "W").sum()),
        expected_wins=("expected_win", "sum"),
        points_for=("score", "sum"),
    ).reset_index()
    per_team["luck_score"] = per_team["actual_wins"] - per_team["expected_wins"]
    per_team = per_team.sort_values("luck_score", ascending=False).reset_index(drop=True)
    per_team.index += 1
    return per_team


def weekly_scores_wide(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot to wide format: rows=teams, columns=weeks."""
    pivot = matchups_df.pivot_table(
        index=["team_id", "team_name"], columns="week", values="score"
    ).reset_index()
    pivot.columns = ["team_id", "team_name"] + [f"W{int(c)}" for c in pivot.columns[2:]]
    return pivot


def alternate_schedule_standings(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each team, compute wins if they had played every other team each week.
    Returns avg wins and range of possible records.
    """
    weeks = matchups_df["week"].unique()
    teams = matchups_df[["team_id", "team_name"]].drop_duplicates()

    results = []
    for _, row in teams.iterrows():
        tid = row["team_id"]
        total_wins = 0
        total_games = 0
        for week in weeks:
            week_scores = matchups_df[matchups_df["week"] == week][["team_id", "score"]]
            my_score_row = week_scores[week_scores["team_id"] == tid]
            if my_score_row.empty:
                continue
            my_score = my_score_row["score"].values[0]
            opponents = week_scores[week_scores["team_id"] != tid]["score"].values
            wins = (my_score > opponents).sum()
            total_wins += wins
            total_games += len(opponents)
        results.append({
            "team_id": tid,
            "team_name": row["team_name"],
            "alt_wins": total_wins,
            "alt_games": total_games,
            "alt_win_pct": total_wins / total_games if total_games > 0 else 0,
        })
    df = pd.DataFrame(results).sort_values("alt_wins", ascending=False).reset_index(drop=True)
    df.index += 1
    return df


def swapped_schedule_matrix(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """
    wins[R][C] = H2H wins team R would have if it had played team C's schedule.

    For each week, R faces whoever C actually faced that week, and wins if R's
    real score that week beats that opponent's real score.

    Self-match rule: if C's opponent in a week is R itself, R cannot play
    itself, so C is substituted as the opponent. That is also what really
    happened — C played R that week — so the diagonal (R playing R's own
    schedule) equals R's actual win total, which makes the matrix self-checking.

    Ties are not wins, matching how actual wins are counted.

    Returns a DataFrame indexed by team_id with team_id columns.
    """
    df = matchups_df
    score = {(r.team_id, r.week): r.score for r in df.itertuples()}
    sched = {(r.team_id, r.week): r.opp_id for r in df.itertuples()}
    teams = sorted(df["team_id"].unique())
    weeks = sorted(df["week"].unique())

    out = {}
    for row_t in teams:
        row = {}
        for col_t in teams:
            wins = 0
            for w in weeks:
                opp = sched.get((col_t, w))
                my = score.get((row_t, w))
                if opp is None or my is None:
                    continue
                if opp == row_t:          # would face itself; borrow C instead
                    opp = col_t
                opp_score = score.get((opp, w))
                if opp_score is not None and my > opp_score:
                    wins += 1
            row[col_t] = wins
        out[row_t] = row
    return pd.DataFrame(out).T.loc[teams, teams]


def luck_breakdown(matchups_df: pd.DataFrame) -> pd.DataFrame:
    """
    Decompose each team's record into what their scoring earned and what the
    draw handed them. All figures are in games.

    Three components, each an actual minus an expected:

    schedule_luck  actual H2H wins minus the wins those scores earned against
                   the field they actually faced each week. Isolates who you
                   were scheduled against.
    field_luck     wins earned against that week's field minus wins earned
                   against the season's whole pool of scores. Isolates whether
                   your good weeks landed when the league was also scoring.
    median_luck    actual median wins minus the wins your scores would earn
                   against the season's median rather than each week's.

    They are near enough independent to add: across a season the pairwise
    correlations run under 0.2. Each also sums to about zero across the league,
    since one team's good fortune is another's bad.

    Opponent form (points opponents scored against you above their own average)
    is returned for context but deliberately left out of the total: it
    correlates about -0.75 with schedule luck, being a mechanism for it rather
    than a separate effect, so adding it would count the same luck twice.
    """
    df = matchups_df
    n_teams = df["team_id"].nunique()
    opponents = max(n_teams - 1, 1)

    week_scores = {w: g["score"].tolist() for w, g in df.groupby("week")}
    all_scores = np.sort(df["score"].values)
    week_median = df.groupby("week")["score"].median()
    season_median = df["score"].median()

    def beat_that_week(score, week):
        others = list(week_scores.get(week, []))
        if score in others:
            others.remove(score)
        return sum(1 for x in others if x < score) / opponents

    def beat_the_season(score):
        # share of every score posted this season that this one beats
        return np.searchsorted(all_scores, score, side="left") / max(
            len(all_scores) - 1, 1)

    work = df.assign(
        p_week=[beat_that_week(s, w) for s, w in zip(df["score"], df["week"])],
        p_season=[beat_the_season(s) for s in df["score"]],
        med_win=[1.0 if s > week_median[w] else 0.0
                 for s, w in zip(df["score"], df["week"])],
        med_exp=[1.0 if s > season_median else 0.0 for s in df["score"]],
        is_win=(df["outcome"] == "W").astype(float),
    )

    g = work.groupby(["team_id", "team_name"])
    out = g.agg(
        h2h_wins=("is_win", "sum"),
        xw_week=("p_week", "sum"),
        xw_season=("p_season", "sum"),
        median_wins=("med_win", "sum"),
        xmedian=("med_exp", "sum"),
    ).reset_index()

    out["schedule_luck"] = out["h2h_wins"] - out["xw_week"]
    out["field_luck"] = out["xw_week"] - out["xw_season"]
    out["median_luck"] = out["median_wins"] - out["xmedian"]
    out["opp_form"] = out["team_id"].map(opponent_vs_own_average(df))
    return out
