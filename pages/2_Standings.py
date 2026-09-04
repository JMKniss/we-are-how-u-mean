import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from data.espn_client import get_matchups_df, get_manager_map
from analysis.standings import (
    combined_standings,
    strength_of_schedule, luck_index, alternate_schedule_standings,
    opponent_vs_own_average,
    swapped_schedule_matrix
)
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import sidebar_display_prefs, prep_display, chart_label

st.set_page_config(page_title="Standings", page_icon="📊", layout="wide")
st.title("📊 Standings")

if "selected_season" not in st.session_state:
    st.session_state["selected_season"] = DEFAULT_SEASON
season = st.sidebar.selectbox(
    "Season", SEASONS,
    index=SEASONS.index(st.session_state["selected_season"])
)
st.session_state["selected_season"] = season
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def rank_stats_all_seasons():
    """
    League-wide facts about weekly scoring rank, pooled over every season.

    Per-season samples are far too thin for this: one season gives 13 games per
    rank, all seasons give about 127. Returns (win rate by rank, rank-vs-rank
    meeting counts).
    """
    frames = []
    for yr in SEASONS:
        try:
            m = get_matchups_df(yr)
        except Exception:
            continue
        reg = m[m["week"] <= season_config(yr)["reg_season_end"]].copy()
        if reg.empty:
            continue
        reg["rank"] = (reg.groupby("week")["score"]
                       .rank(ascending=False, method="min").astype(int))
        lookup = reg.set_index(["week", "team_id"])["rank"]
        reg["opp_rank"] = [lookup.get((w, o)) for w, o in
                           zip(reg["week"], reg["opp_id"])]
        frames.append(reg)
    if not frames:
        return pd.Series(dtype=float), pd.DataFrame()

    allr = pd.concat(frames, ignore_index=True)
    # a tie is half a win, which only matters for 2016
    allr["pts"] = allr["outcome"].map({"W": 1.0, "T": 0.5, "L": 0.0})
    win_rate = allr.groupby("rank")["pts"].mean() * 100
    paired = allr.dropna(subset=["opp_rank"])
    meetings = pd.crosstab(paired["rank"], paired["opp_rank"].astype(int))
    return win_rate, meetings


@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season), get_manager_map(season)

with st.spinner("Loading..."):
    matchups_df, manager_map = load(season)

cfg = season_config(season)
matchups_df = matchups_df[matchups_df["week"] <= cfg["reg_season_end"]].copy()

# Starting in 2025, combined (H2H + vs median) is the official standings format
official_combined = season >= 2025


def _current_standings_display(df):
    """
    Build the Current Standings table with Manager and Team as separate columns.

    Each win/loss pair is shown as one record. The frame is already sorted by
    total wins, and the rows keep that order, so folding W and L together
    costs nothing.
    """
    def record(w, l):
        return w.astype(int).astype(str) + "-" + l.astype(int).astype(str)

    out = pd.DataFrame({
        "Manager": df["team_id"].map(manager_map).fillna("?"),
        "Team": df["team_name"],
        "Total": record(df["total_wins"], df["total_losses"]),
        "H2H": record(df["wins"], df["losses"]),
        "Median": record(df["median_wins"], df["median_losses"]),
        "PF": df["points_for"].round(1),
        "PA": df["points_against"].round(1),
        "Avg": df["avg_score"].round(1),
    })
    return out


tab1, tab4, tab5, tab6 = st.tabs(
    ["Standings", "Strength of Schedule", "Luck Index", "Alternate Schedule"])

# ── Tab 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Standings")
    df = combined_standings(matchups_df)
    if official_combined:
        st.caption("Two games per week: one H2H matchup and one vs-median. "
                   "Sorted by total wins, which is the official standing from 2025.")
    else:
        # Median wins were not official before 2025, so the order has to follow
        # head-to-head or the table would rewrite history. The median column is
        # still shown, since the games were played either way.
        df = df.sort_values(["wins", "points_for"], ascending=False)
        st.caption("Head-to-head decided the standings before 2025, so the order "
                   "follows H2H. The median column is shown for reference only.")
    st.dataframe(_current_standings_display(df), use_container_width=True,
                 hide_index=True)

    st.divider()
    st.subheader("Weekly Scoring Rank")
    st.caption(
        "Where each manager finished on the weekly scoreboard: 1 is the "
        "highest score that week, 10 the lowest. Ties share the better rank. "
        "Rows follow the standings order above."
    )
    rank_src = matchups_df.assign(
        rank=matchups_df.groupby("week")["score"]
        .rank(ascending=False, method="min").astype(int),
        Manager=matchups_df["team_id"].map(manager_map).fillna("?"),
    )
    rank_tbl = rank_src.pivot(index="Manager", columns="week", values="rank")
    rank_tbl.columns = [f"Wk {int(w)}" for w in rank_tbl.columns]
    # keep the row order the same as the standings table above
    order = [manager_map.get(t, "?") for t in df["team_id"]]
    rank_tbl = rank_tbl.reindex([m for m in order if m in rank_tbl.index])
    # average weekly finish, appended after the last week
    rank_tbl["Avg"] = rank_tbl.mean(axis=1).round(1)
    rank_tbl.index.name = ""

    # Result of each week's matchup, same shape, used only to colour the cells.
    outcome_tbl = (rank_src.pivot(index="Manager", columns="week",
                                  values="outcome")
                   .reindex(rank_tbl.index))
    outcome_tbl.columns = [f"Wk {int(w)}" for w in outcome_tbl.columns]
    outcome_tbl["Avg"] = None

    WIN, LOSS, TIE = "#a8d5a2", "#f2a2a2", "#f5e6a8"
    WIN_L, LOSS_L, TIE_L = "#ddf0dc", "#fadddd", "#fcf5dc"

    def shade(frame, win, loss, tie):
        """Background colour per cell, driven by that week's result."""
        def _style(_):
            out = pd.DataFrame("", index=frame.index, columns=frame.columns)
            for c in frame.columns:
                if c == "Avg":
                    continue
                out[c] = outcome_tbl[c].map(
                    {"W": f"background-color: {win}",
                     "L": f"background-color: {loss}",
                     "T": f"background-color: {tie}"}).fillna("")
            return out
        return _style

    week_cols = [c for c in rank_tbl.columns if c != "Avg"]
    st.dataframe(
        rank_tbl.style
        .apply(shade(rank_tbl, WIN, LOSS, TIE), axis=None)
        .format({**{c: "{:.0f}" for c in week_cols}, "Avg": "{:.1f}"}),
        use_container_width=True)

    # ── Expected win rate for the rank you posted ──────────────────────────
    st.divider()
    st.subheader("Win Rate for That Rank")
    win_rate, meetings = rank_stats_all_seasons()
    if win_rate.empty:
        st.info("Not enough history to estimate win rates by rank.")
    else:
        st.caption(
            "How often a score of that rank has won, across every season "
            f"({int(len(SEASONS))} years, about {int(meetings.values.sum() / 2 / 10)} "
            "games per rank). Shading shows what actually happened: green if "
            "they won that week, red if they lost. Green on a low number is a "
            "win they had no business getting."
        )
        exp_tbl = rank_tbl[week_cols].apply(
            lambda col: col.map(win_rate.to_dict()))
        exp_tbl["Avg"] = exp_tbl.mean(axis=1).round(1)
        st.dataframe(
            exp_tbl.style
            .apply(shade(exp_tbl, WIN_L, LOSS_L, TIE_L), axis=None)
            # one dict, not chained calls: a second .format() does not merge
            # with the first and silently leaves columns unformatted
            .format({**{c: "{:.0f}%" for c in week_cols}, "Avg": "{:.1f}%"}),
            use_container_width=True)

        # ── How often each rank has met each rank ──────────────────────────
        st.divider()
        st.subheader("Rank vs Rank Meetings")
        st.caption(
            "How often a team scoring at each rank has faced a team scoring at "
            "another, across every season. Only the upper half is shown: the "
            "matrix is symmetric, so the lower half repeats it. Every cell is a "
            "count of matchups, and they sum to the total played. The diagonal "
            "is not always zero: tied scores share a rank and can meet at it."
        )
        # Blank the mirror image rather than print every count twice.
        mm_tbl = meetings.copy()
        # A cross-rank matchup lands one row in each of two cells, but a
        # same-rank matchup lands both its rows in the one diagonal cell, so
        # the diagonal counts double. Halve it and every cell means matchups.
        for i in mm_tbl.index:
            if i in mm_tbl.columns:
                mm_tbl.loc[i, i] = mm_tbl.loc[i, i] // 2
        mask = np.tril(np.ones(mm_tbl.shape, dtype=bool), k=-1)
        mm_tbl = mm_tbl.astype(object).mask(mask, "")
        mm_tbl.index = [f"Rank {i}" for i in mm_tbl.index]
        mm_tbl.columns = [f"{i}" for i in mm_tbl.columns]
        mm_tbl.index.name = "vs →"
        st.dataframe(mm_tbl, use_container_width=True)


# ── Tab 4: Strength of Schedule ───────────────────────────────────────────────
with tab4:
    st.subheader("Strength of Schedule")
    st.caption(
        "Avg Opp Score is how much opponents scored against you. "
        "Opp vs Own Avg compares that to what those same opponents managed "
        "against everyone else, excluding the game with you: positive means "
        "they raised their game against you, negative means they tended to "
        "have an off week."
    )
    df = strength_of_schedule(matchups_df)
    # Add team's own scoring stats to compare alongside opponent stats
    own = matchups_df.groupby(["team_id", "team_name"])["score"].agg(
        avg_score="mean", total_score="sum"
    ).reset_index()
    df = df.merge(own[["team_id", "avg_score", "total_score"]], on="team_id", how="left")
    df["opp_vs_own"] = df["team_id"].map(opponent_vs_own_average(matchups_df))
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "avg_opp_score", "avg_score",
                                 "opp_vs_own", "total_opp_score", "total_score"],
                           headers=["Team", "Avg Opp Score", "Avg Score",
                                    "Opp vs Own Avg", "Total Opp Score", "Total Score"])
    for col in ["Avg Opp Score", "Avg Score", "Opp vs Own Avg"]:
        display[col] = display[col].round(2)
    for col in ["Total Opp Score", "Total Score"]:
        display[col] = display[col].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df, x="label", y="avg_opp_score",
                 title="Average Opponent Score Faced",
                 labels={"label": "", "avg_opp_score": "Avg Opp Score"},
                 color="avg_opp_score", color_continuous_scale="RdYlGn_r")
    fig.update_layout(xaxis_tickangle=-30, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

# ── Tab 5: Luck Index ─────────────────────────────────────────────────────────
with tab5:
    st.subheader("Luck Index")
    st.caption("Luck = Actual Wins − Expected Wins (based on weekly score percentile). Positive = lucky, negative = unlucky.")
    df = luck_index(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "actual_wins", "expected_wins", "luck_score"],
                           headers=["Team", "Actual W", "Expected W", "Luck Score"])
    display["Expected W"] = display["Expected W"].round(1)
    display["Luck Score"] = display["Luck Score"].round(2)
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df.sort_values("luck_score"), x="luck_score", y="label",
                 orientation="h",
                 title="Luck Score by Team",
                 labels={"luck_score": "Luck Score", "label": ""},
                 color="luck_score", color_continuous_scale="RdYlGn")
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

# ── Tab 6: Alternate Schedule ─────────────────────────────────────────────────
with tab6:
    weeks_played = matchups_df["week"].nunique()
    n_teams = matchups_df["team_id"].nunique()
    opp_per_week = n_teams - 1

    # ── Swapped schedules ─────────────────────────────────────────────────────
    st.subheader("If You Had Played Someone Else's Schedule")
    st.caption(
        "Each cell: H2H wins the **row** manager would have if they had played the "
        "**column** manager's schedule, using their own real weekly scores. "
        "The diagonal is their own schedule, so it equals their actual record. "
        f"Regular season only ({weeks_played} weeks)."
    )

    with st.spinner("Computing swapped schedules..."):
        mat = swapped_schedule_matrix(matchups_df)

    ts = mat.mean(axis=1)   # row average — how well this team does against any schedule
    ss = mat.mean(axis=0)   # column average — how generous this schedule is to anyone

    order = ts.sort_values(ascending=False).index.tolist()
    mat = mat.loc[order, order]
    names = {t: manager_map.get(t, "?") for t in order}

    # Values are formatted as text so integer wins and one-decimal averages can
    # share a column without pandas widening the wins to 9.0.
    rows = []
    for r in order:
        row = {"Manager": names[r]}
        for c in order:
            row[names[c]] = str(int(mat.loc[r, c]))
        row["TS"] = f"{ts[r]:.1f}"
        rows.append(row)
    ss_row = {"Manager": "SS"}
    for c in order:
        ss_row[names[c]] = f"{ss[c]:.1f}"
    ss_row["TS"] = ""
    rows.append(ss_row)

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "**TS** (Team Strength) = that team's average wins across all 10 schedules. "
        "**SS** (Schedule Strength) = average wins any team would get playing that "
        "schedule, so a **higher SS means an easier schedule**."
    )

    st.divider()

    # ── Play everyone every week ──────────────────────────────────────────────
    st.subheader("If Everyone Played Everyone, Every Week")
    st.caption(
        f"Each week every team is scored against all {opp_per_week} others. "
        f"Maximum possible: **{opp_per_week * weeks_played} wins** "
        f"({opp_per_week} per week x {weeks_played} weeks)."
    )
    with st.spinner("Computing..."):
        alt = alternate_schedule_standings(matchups_df)
    display = prep_display(alt, manager_map, show_mgr, show_team,
                           cols=["team_name", "alt_wins", "alt_win_pct"],
                           headers=["Team", "Wins", "Win%"])
    display["Win%"] = display["Win%"].round(3)
    st.dataframe(display, use_container_width=True, hide_index=True)
