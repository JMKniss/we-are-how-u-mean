import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_boxscores_df, get_manager_map
from analysis.efficiency import (lineup_efficiency, top_players, projected_vs_actual,
                                 player_manager_sequence)
from config import SEASONS, DEFAULT_SEASON
from display_utils import season_selector, require_data, sidebar_display_prefs, prep_display, chart_label
from branding import page_icon

st.set_page_config(page_title="Lineup Efficiency", page_icon=page_icon(), layout="wide")
st.title("🎯 Lineup Efficiency")
st.caption("How well did each manager set their lineup? Optimal score = best possible lineup from their roster.")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def load(season):
    return get_boxscores_df(season), get_manager_map(season)

with st.spinner("Loading player-level data (first load may take a minute)..."):
    box_df, manager_map = load(season)

require_data(box_df, season, "player-level data")

if season < 2018:
    st.info(f"Player data for {season} may not be 100% accurate. But I'm still counting it against you.")

# team_name → team_id lookup from box_df
tid_by_name = box_df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]
def label_for(tname: str) -> str:
    tid = tid_by_name.get(tname)
    mgr = manager_map.get(tid, "?") if tid is not None else "?"
    if show_mgr and show_team:
        return f"{mgr} — {tname}"
    return mgr if show_mgr else tname

summary, weekly = lineup_efficiency(box_df)

# 2016-2017 come from nfl-data-py: starters only, no bench, no real slot names.
# With no bench there is no alternative lineup, so efficiency is not computable
# rather than a meaningless 100%.
efficiency_available = weekly["optimal_score"].notna().any()
if not efficiency_available:
    st.info(
        f"Lineup efficiency is not available for {season}. Player data for "
        "2016-2017 comes from nfl-data-py and covers only the nine starters "
        "each week, with no bench and no lineup-slot detail, so there is no "
        "alternative lineup to compare against. Top Players below is "
        "unaffected."
    )

tab1, tab2, tab3, tab4 = st.tabs(["Season Summary", "Weekly Efficiency", "Top Players", "Projections vs Actual"])

with tab1:
    if not efficiency_available:
        st.caption("Not available for this season - see the note above.")
    else:
        st.subheader("Season Efficiency Summary")
        display = prep_display(summary, manager_map, show_mgr, show_team,
                               cols=["team_name", "avg_actual", "avg_optimal", "avg_efficiency",
                                     "avg_left_on_bench", "total_left_on_bench"],
                               headers=["Team", "Avg Actual", "Avg Optimal", "Efficiency %",
                                        "Avg Left on Bench", "Total Left on Bench"])
        st.dataframe(display, use_container_width=True)

        summary["label"] = chart_label(summary, manager_map, show_mgr, show_team)
        fig = px.bar(summary.sort_values("avg_efficiency"), x="avg_efficiency", y="label",
                     orientation="h", title="Average Lineup Efficiency %",
                     labels={"avg_efficiency": "Efficiency %", "label": ""},
                     color="avg_efficiency", color_continuous_scale="RdYlGn",
                     range_color=[summary["avg_efficiency"].min() - 2, 100])
        fig.add_vline(x=summary["avg_efficiency"].mean(), line_dash="dash", line_color="gray",
                      annotation_text="League Avg")
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            fig2 = px.bar(summary.sort_values("total_left_on_bench", ascending=False),
                          x="label", y="total_left_on_bench",
                          title="Total Points Left on Bench (Season)",
                          labels={"label": "", "total_left_on_bench": "Points"},
                          color="total_left_on_bench", color_continuous_scale="Reds")
            fig2.update_layout(xaxis_tickangle=-30, coloraxis_showscale=False)
            st.plotly_chart(fig2, use_container_width=True)

        with col2:
            fig3 = px.scatter(summary, x="avg_actual", y="avg_efficiency",
                              text="label", title="Actual Score vs Efficiency",
                              labels={"avg_actual": "Avg Actual Score", "avg_efficiency": "Efficiency %"})
            fig3.update_traces(textposition="top center")
            st.plotly_chart(fig3, use_container_width=True)

with tab2:
    if not efficiency_available:
        st.caption("Not available for this season - see the note above.")
    else:
        st.subheader("Weekly Efficiency by Team")
        teams = sorted(weekly["team_name"].unique())
        selected_team = st.selectbox("Select Team", ["All Teams"] + teams)

        if selected_team == "All Teams":
            weekly["label"] = chart_label(weekly, manager_map, show_mgr, show_team)
            fig = px.line(weekly.sort_values("week"), x="week", y="efficiency_pct",
                          color="label", markers=True,
                          title="Lineup Efficiency % by Week",
                          labels={"week": "Week", "efficiency_pct": "Efficiency %", "label": "Team"})
            fig.add_hline(y=100, line_dash="dash", line_color="gray", annotation_text="Perfect")
        else:
            tdf = weekly[weekly["team_name"] == selected_team].sort_values("week")
            lbl = label_for(selected_team)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=tdf["week"], y=tdf["actual_score"], name="Actual", marker_color="#3498db"))
            fig.add_trace(go.Bar(x=tdf["week"], y=tdf["optimal_score"], name="Optimal", marker_color="#2ecc71"))
            fig.add_trace(go.Scatter(x=tdf["week"], y=tdf["points_left_on_bench"],
                                     name="Left on Bench",
                                     mode="lines+markers", line=dict(color="orange")))
            fig.update_layout(barmode="group", title=f"{lbl} — Actual vs Optimal by Week",
                              xaxis_title="Week", yaxis_title="Points", xaxis=dict(dtick=1))
        st.plotly_chart(fig, use_container_width=True)

        if selected_team != "All Teams":
            tdf = weekly[weekly["team_name"] == selected_team][
                ["week", "actual_score", "optimal_score", "points_left_on_bench", "efficiency_pct"]
            ].round(2)
            tdf.columns = ["Week", "Actual", "Optimal", "Left on Bench", "Eff%"]
            st.dataframe(tdf, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Top Scoring Players")
    positions = ["All"] + sorted(box_df["position"].dropna().unique().tolist())
    col1, col2 = st.columns([1, 3])
    with col1:
        pos_filter = st.selectbox("Position", positions)
        top_n = st.slider("Show top N", 10, 50, 20)
    pos = None if pos_filter == "All" else pos_filter
    top = top_players(box_df, position=pos, top_n=top_n)

    if top.empty:
        st.info("No player data for this selection.")
    else:
        def player_label(row):
            """Josh Allen (BUF), or just the name when the team is unknown."""
            team = row["pro_team"]
            if isinstance(team, str) and team.strip() and team.strip().lower() != "nan":
                return f"{row['player_name']} ({team.strip()})"
            return row["player_name"]

        # Who rostered each of these players, in order. Only the displayed
        # players are looked up, and the slider caps that at 50.
        seqs = player_manager_sequence(box_df, top["player_id"])

        def manager_chain(pid):
            teams = seqs.get(pid, [])
            names = [manager_map.get(t, "?") for t in teams]
            # collapse again in case two team_ids map to the same manager
            chain = [n for i, n in enumerate(names) if i == 0 or n != names[i - 1]]
            return " → ".join(chain)

        disp = pd.DataFrame({
            "Pos": top["position"],
            "Player": top.apply(player_label, axis=1),
            "Manager": top["player_id"].map(manager_chain),
            "Total": top["total_points"].round(1),
            "Avg": top["avg_points"].round(1),
            "Weeks": top["weeks_played"],
        })
        disp.index = range(1, len(disp) + 1)
        st.dataframe(disp, use_container_width=True,
                     column_config={"Pos": st.column_config.TextColumn("Pos", width="small")})

with tab4:
    st.subheader("Projected vs Actual Scoring")
    st.caption("Did teams consistently outscore or underperform their ESPN projections?")
    # 2016-2017 carry no ESPN projections at all, so every team "beats" a
    # projection of zero. The comparison is meaningless for those seasons.
    projections_available = (box_df["projected"].fillna(0) != 0).any()
    if not projections_available:
        st.info(
            f"ESPN projections are not available for {season}, so there is "
            "nothing to compare actual scoring against."
        )
    else:
        proj_df = projected_vs_actual(box_df)
        display = prep_display(proj_df, manager_map, show_mgr, show_team,
                               cols=["team_name", "avg_projected", "times_beat_proj", "beat_proj_pct"],
                               headers=["Team", "Avg Proj", "Times Beat Proj", "Beat Proj %"])
        display["Avg Proj"] = display["Avg Proj"].round(1)
        st.dataframe(display, use_container_width=True, hide_index=True)

        proj_df["label"] = chart_label(proj_df, manager_map, show_mgr, show_team)
        fig = px.bar(proj_df.sort_values("avg_proj_diff"), x="avg_proj_diff", y="label",
                     orientation="h", title="Average Points Above/Below ESPN Projection",
                     labels={"avg_proj_diff": "Avg Diff (Actual − Projected)", "label": ""},
                     color="avg_proj_diff", color_continuous_scale="RdYlGn")
        fig.add_vline(x=0, line_dash="dash", line_color="gray")
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
