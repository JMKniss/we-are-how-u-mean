import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_boxscores_df, get_matchups_df, get_manager_map
from analysis.efficiency import lineup_efficiency
from analysis.standings import best_ball_matchups, official_standings
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import season_selector, require_data, sidebar_display_prefs, chart_label, who_columns
from branding import page_icon
from style import bar_chart, frame, page_header, series_colours, show_chart

st.set_page_config(page_title="Lineup Efficiency", page_icon=page_icon(), layout="wide")
page_header("Lineup Efficiency",
            sub="How well did each manager set their lineup? Optimal score = best possible lineup from their roster.")

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
    """A team's chart label: its manager, never the team name (see chart_label)."""
    tid = tid_by_name.get(tname)
    return manager_map.get(tid, "?") if tid is not None else "?"

summary, weekly = lineup_efficiency(box_df)


def team_frame(df, columns, **kw):
    """A table led by each team's picture and name, in df's order."""
    names, subs, pics = who_columns(df, manager_map, season, show_mgr, show_team)
    out = pd.DataFrame({"Manager" if show_mgr else "Team": names})
    for head, values in columns.items():
        out[head] = list(values)
    frame(out, pics=pics, subs=subs, **kw)

# 2016-2017 come from nfl-data-py: starters only, no bench, no real slot names.
# With no bench there is no alternative lineup, so efficiency is not computable
# rather than a meaningless 100%.
efficiency_available = weekly["optimal_score"].notna().any()
if not efficiency_available:
    st.info(
        f"Lineup efficiency is not available for {season}. Player data for "
        "2016-2017 comes from nfl-data-py and covers only the nine starters "
        "each week, with no bench and no lineup-slot detail, so there is no "
        "alternative lineup to compare against."
    )

tab1, tab2, tab3 = st.tabs(["Season Summary", "Weekly Efficiency", "Best-Ball Record"])

with tab1:
    if not efficiency_available:
        st.caption("Not available for this season - see the note above.")
    else:
        st.subheader("Season Efficiency Summary")
        ranked = summary.sort_values("avg_efficiency", ascending=False)
        team_frame(ranked, {
            "Avg Actual": ranked["avg_actual"], "Avg Optimal": ranked["avg_optimal"],
            "Efficiency": ranked["avg_efficiency"], "Avg Left on Bench": ranked["avg_left_on_bench"],
            "Total Left on Bench": ranked["total_left_on_bench"],
        }, rank=True, num=("Avg Actual", "Avg Optimal", "Efficiency", "Avg Left on Bench",
                           "Total Left on Bench"),
            fmt={"Avg Actual": "{:.2f}", "Avg Optimal": "{:.2f}", "Efficiency": "{:.1f}%",
                 "Avg Left on Bench": "{:.2f}", "Total Left on Bench": "{:,.1f}"})

        summary["label"] = chart_label(summary, manager_map)
        avg = summary["avg_efficiency"].mean()
        show_chart(bar_chart(summary, "avg_efficiency", "label",
                             f"Average lineup efficiency · league {avg:.1f}%", fmt="{:.1f}%"))

        col1, col2 = st.columns(2)
        with col1:
            show_chart(bar_chart(summary, "total_left_on_bench", "label",
                                 "Points left on bench, season"))

        with col2:
            fig3 = px.scatter(summary, x="avg_actual", y="avg_efficiency", text="label",
                              title="Actual Score vs Efficiency",
                              labels={"avg_actual": "Avg Actual Score", "avg_efficiency": "Efficiency %"})
            fig3.update_traces(textposition="top center")
            st.plotly_chart(fig3, width="stretch")

with tab2:
    if not efficiency_available:
        st.caption("Not available for this season - see the note above.")
    else:
        st.subheader("Weekly Efficiency by Team")
        teams = sorted(weekly["team_name"].unique())
        selected_team = st.selectbox("Select Team", ["All Teams"] + teams)

        if selected_team == "All Teams":
            weekly["label"] = chart_label(weekly, manager_map)
            fig = px.line(weekly.sort_values("week"), x="week", y="efficiency_pct",
                          color="label", markers=True,
                          title="Lineup Efficiency % by Week",
                          labels={"week": "Week", "efficiency_pct": "Efficiency %", "label": "Team"})
            fig.add_hline(y=100, line_dash="dash", line_color="gray", annotation_text="Perfect")
        else:
            tdf = weekly[weekly["team_name"] == selected_team].sort_values("week")
            lbl = label_for(selected_team)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=tdf["week"], y=tdf["actual_score"], name="Actual", marker_color=series_colours()[0]))
            fig.add_trace(go.Bar(x=tdf["week"], y=tdf["optimal_score"], name="Optimal", marker_color=series_colours()[2]))
            fig.add_trace(go.Scatter(x=tdf["week"], y=tdf["points_left_on_bench"],
                                     name="Left on Bench",
                                     mode="lines+markers", line=dict(color=series_colours()[1])))
            fig.update_layout(barmode="group", title=f"{lbl} — Actual vs Optimal by Week",
                              xaxis_title="Week", yaxis_title="Points", xaxis=dict(dtick=1))
        st.plotly_chart(fig, width="stretch")

        if selected_team != "All Teams":
            tdf = weekly[weekly["team_name"] == selected_team][
                ["week", "actual_score", "optimal_score", "points_left_on_bench", "efficiency_pct"]
            ].round(2)
            tdf.columns = ["Week", "Actual", "Optimal", "Left on Bench", "Eff%"]
            frame(tdf, mid=("Week",), num=("Actual", "Optimal", "Left on Bench", "Eff%"), compact=True,
                  fmt={"Actual": "{:.2f}", "Optimal": "{:.2f}", "Left on Bench": "{:.2f}",
                       "Eff%": "{:.1f}%"})


with tab3:
    st.subheader("Best-Ball Record")
    st.caption("Standings if everyone played their optimal lineup each week")
    if not efficiency_available:
        st.caption("Not available for this season - see the note above.")
    else:
        # Every regular-season game replayed with both sides on their optimal
        # lineup, through the same standings code as the Standings page.
        games = get_matchups_df(season)
        games = games[games["week"] <= season_config(season)["reg_season_end"]]
        bb = official_standings(best_ball_matchups(games, weekly), season)

        def record(w, l):
            return w.astype(int).astype(str) + "-" + l.astype(int).astype(str)

        team_frame(bb, {
            "Total": record(bb["total_wins"], bb["total_losses"]),
            "H2H": record(bb["wins"], bb["losses"]),
            "Median": record(bb["median_wins"], bb["median_losses"]),
            "Vs All": bb["vs_all"],
            "PF": bb["points_for"], "PA": bb["points_against"], "Avg": bb["avg_score"],
        }, rank=True, cut_after=4, mid=("Total", "H2H", "Median", "Vs All"),
            num=("PF", "PA", "Avg"))
