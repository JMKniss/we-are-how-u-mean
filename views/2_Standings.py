import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
from data.espn_client import get_matchups_df, get_manager_map
from analysis.standings import (
    combined_standings,
    strength_of_schedule, alternate_schedule_standings,
    luck_breakdown, luck_total,
    opponent_vs_own_average,
    swapped_schedule_matrix
)
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import season_selector, require_data, sidebar_display_prefs, prep_display
from branding import page_icon

st.set_page_config(page_title="Standings", page_icon=page_icon(), layout="wide")
st.title("📊 Standings")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season), get_manager_map(season)

with st.spinner("Loading..."):
    matchups_df, manager_map = load(season)

require_data(matchups_df, season, "matchup data")

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
        "Vs All": df["_vs_all"],
        "PF": df["points_for"].round(1),
        "PA": df["points_against"].round(1),
        "Avg": df["avg_score"].round(1),
    })
    return out


tab1, tab4, tab5 = st.tabs(
    ["Standings", "Strength of Schedule", "Luck"])

# ── Tab 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Standings")
    df = combined_standings(matchups_df)
    # Record if you had played every other team every week, folded in here so
    # the schedule-free view sits beside the schedule-bound ones.
    _alt = alternate_schedule_standings(matchups_df).set_index("team_id")
    df["_vs_all"] = [
        f"{int(_alt.loc[t, 'alt_wins'])}-"
        f"{int(_alt.loc[t, 'alt_games'] - _alt.loc[t, 'alt_wins'])}"
        if t in _alt.index else "—" for t in df["team_id"]]
    if official_combined:
        st.caption("Two games per week: one H2H matchup and one vs-median. "
                   "Sorted by total wins, which is the official standing from "
                   "2025. Vs All is the record if you had played every other "
                   "team every week, which removes the schedule entirely.")
    else:
        # Median wins were not official before 2025, so the order has to follow
        # head-to-head or the table would rewrite history. The median column is
        # still shown, since the games were played either way.
        df = df.sort_values(["wins", "points_for"], ascending=False)
        st.caption("Head-to-head decided the standings before 2025, so the order "
                   "follows H2H. Median and Vs All are shown for reference "
                   "only; Vs All is the record if you had played every other "
                   "team every week.")
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
        .apply(shade(rank_tbl, WIN_L, LOSS_L, TIE_L), axis=None)
        .format({**{c: "{:.0f}" for c in week_cols}, "Avg": "{:.1f}"}),
        use_container_width=True)


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

    st.divider()
    weeks_played = matchups_df["week"].nunique()
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

# ── Tab 5: Luck Index ─────────────────────────────────────────────────────────
with tab5:
    st.subheader("Luck")
    st.caption(
        "Each number is wins you got minus wins your scores deserved. "
        "Positive means lucky, negative means unlucky."
    )
    lb = luck_breakdown(matchups_df)
    lb.insert(0, "Manager", lb["team_id"].map(manager_map).fillna("?"))

    def small(cols, headers, sort_col):
        t = lb.sort_values(sort_col, ascending=False)[["Manager"] + cols].copy()
        t.columns = ["Manager"] + headers
        for c in headers:
            t[c] = t[c].round(2)
        return t

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Schedule luck**")
        st.caption("Did you draw easy opponents? Wins you would have had "
                   "against opponents at their normal level, compared with "
                   "what your scores earned against the whole week.")
        st.dataframe(small(["w_form", "w_field", "schedule_luck"],
                           ["vs Normal", "Earned", "Luck"], "schedule_luck"),
                     use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**Field luck**")
        st.caption("Did your good scores land on low-scoring weeks? Lucky if "
                   "you scored well when the rest of the league did not.")
        st.dataframe(small(["w_field", "w_season", "field_luck"],
                           ["vs Week", "vs Season", "Luck"], "field_luck"),
                     use_container_width=True, hide_index=True)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Median luck**")
        st.caption("Median wins you got compared with what your scores usually "
                   "get. Lucky if you beat the median in weak weeks.")
        st.dataframe(small(["median_wins", "xmedian", "median_luck"],
                           ["Med W", "Earned", "Luck"], "median_luck"),
                     use_container_width=True, hide_index=True)
    with c4:
        st.markdown("**Opponent form**")
        st.caption("Did opponents play above or below their usual level "
                   "against you? Shown in games, with the points behind it.")
        st.dataframe(small(["opp_luck", "opp_form_pts"], ["Luck", "Points"],
                           "opp_luck"),
                     use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("**Cumulative luck**")
    tot = luck_total(lb, official_combined)
    cols = ["Manager", "opp_luck", "schedule_luck", "field_luck"]
    heads = ["Manager", "Opponent", "Schedule", "Field"]
    if official_combined:
        cols.append("median_luck")
        heads.append("Median")
    cols += ["total_luck", "luck_sigma", "luck_label"]
    heads += ["Total", "Rating", ""]
    td = tot.sort_values("total_luck", ascending=False)[cols].copy()
    td.columns = heads
    for c in heads:
        if c in ("Manager", ""):
            continue
        td[c] = td[c].round(2)
    td["Rating"] = td["Rating"].map(lambda z: f"{z:+.1f}σ")
    st.dataframe(td, use_container_width=True, hide_index=True)
    st.caption(
        ("Opponent + Schedule + Field + Median, in games. "
         if official_combined else
         "Opponent + Schedule + Field, in games. Median is left out because it "
         "did not count toward the standings before 2025. ")
        + "The first three are steps down a chain, each removing one kind of "
        "luck from the one before, so they add up exactly with nothing counted "
        "twice. Rating divides the total by how much luck varied across the "
        "league this season, so it says how unusual the total is rather than "
        "just how big: a quiet season and a wild one can hand out the same "
        "number of games and mean very different things."
    )

    # ── How likely that result was, given the score ────────────────────────
    st.divider()
    st.subheader("Chance of Result")
    st.caption(
        "How likely the week's result was, given only where the score ranked. "
        "Rank 10 that loses shows 100%: all nine other managers outscored them, "
        "so every possible opponent beats them. Rank 6 that wins shows 44%, "
        "four of the nine being beatable. A low number is a result that needed "
        "the schedule's help."
    )

    n_teams = matchups_df["team_id"].nunique()
    opponents = max(n_teams - 1, 1)

    # Counted from the actual weekly scores rather than from rank arithmetic,
    # so tied scores fall out correctly instead of needing a special case.
    week_scores = {w: g["score"].tolist()
                   for w, g in matchups_df.groupby("week")}

    def chance(row_score, week, result):
        others = list(week_scores.get(week, []))
        # A statement, not a conditional expression: as an expression this
        # evaluates to None, and Streamlit's magic renders every one of them.
        if row_score in others:
            others.remove(row_score)
        if result == "W":
            hits = sum(1 for x in others if x < row_score)
        elif result == "L":
            hits = sum(1 for x in others if x > row_score)
        else:
            hits = sum(1 for x in others if x == row_score)
        return hits / opponents * 100

    chance_src = rank_src.assign(
        chance=[chance(sc, wk, oc) for sc, wk, oc in
                zip(rank_src["score"], rank_src["week"], rank_src["outcome"])])
    chance_tbl = (chance_src.pivot(index="Manager", columns="week",
                                   values="chance")
                  .reindex(rank_tbl.index))
    chance_tbl.columns = [f"Wk {int(w)}" for w in chance_tbl.columns]
    chance_tbl["Avg"] = chance_tbl.mean(axis=1).round(1)
    st.dataframe(
        chance_tbl.style
        .apply(shade(chance_tbl, WIN_L, LOSS_L, TIE_L), axis=None)
        .format({**{c: "{:.0f}%" for c in week_cols}, "Avg": "{:.1f}%"}),
        use_container_width=True)


    # ── How often each rank met each rank, this season ─────────────────────
    st.divider()
    st.subheader("Rank vs Rank Meetings")
    st.caption(
        f"How often a team scoring at each rank faced a team scoring at another "
        f"in {season}. Only the upper half is shown, since the matrix is "
        "symmetric. Every cell counts matchups and they sum to the season's "
        "total. The all-time version lives on the All-Time Records page."
    )
    rank_lookup = rank_src.set_index(["week", "team_id"])["rank"]
    paired = rank_src.assign(
        opp_rank=[rank_lookup.get((w, o)) for w, o in
                  zip(rank_src["week"], rank_src["opp_id"])]).dropna(
        subset=["opp_rank"])
    meetings = pd.crosstab(paired["rank"], paired["opp_rank"].astype(int))
    # A same-rank meeting drops both its rows in one diagonal cell, so that
    # cell counts double; every other cell already equals matchups.
    for i in meetings.index:
        if i in meetings.columns:
            meetings.loc[i, i] = meetings.loc[i, i] // 2
    # Same reason as the all-time matrix: NA keeps the column one type, so
    # Arrow serialises it instead of Streamlit having to repair it.
    mm_tbl = meetings.astype("Int64").where(
        np.triu(np.ones(meetings.shape, dtype=bool)), pd.NA)
    mm_tbl.index = [f"Rank {i}" for i in mm_tbl.index]
    mm_tbl.columns = [f"{i}" for i in mm_tbl.columns]
    mm_tbl.index.name = "vs →"
    st.dataframe(mm_tbl, use_container_width=True)
