import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_matchups_df, get_manager_map
from analysis.standings import (
    h2h_standings, median_standings, combined_standings,
    strength_of_schedule, luck_index, alternate_schedule_standings,
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


if official_combined:
    tab_names = ["Current Standings", "vs Median", "H2H", "Strength of Schedule", "Luck Index", "Alternate Schedule"]
else:
    tab_names = ["H2H", "vs Median", "Combined", "Strength of Schedule", "Luck Index", "Alternate Schedule"]

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(tab_names)

# ── Tab 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    if official_combined:
        st.subheader("Current Standings")
        st.caption("Two games per week: one H2H matchup and one vs-median. Sorted by total wins.")
        df = combined_standings(matchups_df)
        st.dataframe(_current_standings_display(df), use_container_width=True, hide_index=True)
    else:
        st.subheader("Head-to-Head Standings")
        df = h2h_standings(matchups_df)
        display = prep_display(df, manager_map, show_mgr, show_team,
                               cols=["team_name", "wins", "losses", "points_for", "points_against", "avg_score", "win_pct"],
                               headers=["Team", "W", "L", "PF", "PA", "Avg Score", "Win%"])
        display["PF"] = display["PF"].round(1)
        display["PA"] = display["PA"].round(1)
        display["Avg Score"] = display["Avg Score"].round(1)
        display["Win%"] = display["Win%"].round(3)
        st.dataframe(display, use_container_width=True, hide_index=True)

        df["label"] = chart_label(df, manager_map, show_mgr, show_team)
        fig = px.bar(df, x="label", y=["wins", "losses"], barmode="group",
                     labels={"value": "Games", "label": "", "variable": ""},
                     title="Wins vs Losses", color_discrete_map={"wins": "#2ecc71", "losses": "#e74c3c"})
        fig.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

# ── Tab 2: vs Median ──────────────────────────────────────────────────────────
with tab2:
    st.subheader("Vs-Median Standings")
    st.caption("Each week, beating the league median score counts as an additional win.")
    df = median_standings(matchups_df)
    df["median_win_pct"] = (df["median_wins"] / (df["median_wins"] + df["median_losses"]).replace(0, float("nan"))).round(3)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "median_wins", "median_losses", "median_win_pct"],
                           headers=["Team", "W", "L", "Win%"])
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df, x="label", y="median_wins",
                 title="Median Wins per Team",
                 labels={"label": "", "median_wins": "Wins vs Median"},
                 color="median_wins", color_continuous_scale="Greens")
    fig.update_layout(xaxis_tickangle=-30, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

# ── Tab 3: H2H (2025+) or Combined (pre-2025) ────────────────────────────────
with tab3:
    if official_combined:
        st.subheader("Head-to-Head Record")
        st.caption("One game per week against your scheduled opponent only.")
        df = h2h_standings(matchups_df)
        display = prep_display(df, manager_map, show_mgr, show_team,
                               cols=["team_name", "wins", "losses", "win_pct"],
                               headers=["Team", "W", "L", "Win%"])
        display["Win%"] = display["Win%"].round(3)
        st.dataframe(display, use_container_width=True, hide_index=True)

        df["label"] = chart_label(df, manager_map, show_mgr, show_team)
        fig = px.bar(df, x="label", y=["wins", "losses"], barmode="group",
                     labels={"value": "Games", "label": "", "variable": ""},
                     title="H2H Wins vs Losses",
                     color_discrete_map={"wins": "#2ecc71", "losses": "#e74c3c"})
        fig.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.subheader("Combined Standings (H2H + vs Median)")
        st.caption("Two games per week: one H2H matchup win/loss, one vs-median win/loss.")
        df = combined_standings(matchups_df)
        display = prep_display(df, manager_map, show_mgr, show_team,
                               cols=["team_name", "wins", "median_wins", "total_wins", "total_losses", "total_win_pct"],
                               headers=["Team", "H2H W", "Median W", "Total W", "Total L", "Win%"])
        display["Win%"] = display["Win%"].round(3)
        st.dataframe(display, use_container_width=True, hide_index=True)

# ── Tab 4: Strength of Schedule ───────────────────────────────────────────────
with tab4:
    st.subheader("Strength of Schedule")
    st.caption("Average score of opponents faced. Higher = harder schedule.")
    df = strength_of_schedule(matchups_df)
    # Add team's own scoring stats to compare alongside opponent stats
    own = matchups_df.groupby(["team_id", "team_name"])["score"].agg(
        avg_score="mean", total_score="sum"
    ).reset_index()
    df = df.merge(own[["team_id", "avg_score", "total_score"]], on="team_id", how="left")
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "avg_opp_score", "avg_score", "total_opp_score", "total_score"],
                           headers=["Team", "Avg Opp Score", "Avg Score", "Total Opp Score", "Total Score"])
    for col in ["Avg Opp Score", "Avg Score"]:
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
