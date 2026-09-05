import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import pandas as pd
from data.espn_client import get_draft_df, get_boxscores_df, get_manager_map
from analysis.draft import apply_recorded_order
from config import SEASONS, DEFAULT_SEASON
from display_utils import season_selector, require_data, sidebar_display_prefs, prep_display, chart_label

st.set_page_config(page_title="Draft Review", page_icon="📋", layout="wide")
st.title("📋 Draft Review")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=3600)
def load(season):
    draft = get_draft_df(season)
    mgr_map = get_manager_map(season)
    # ESPN's pick order is rebuilt by the commissioner after an in-person
    # draft and comes out wrong. Reseat the board onto the league's own
    # record before anything reads a pick number - Best Value and Biggest
    # Busts both rank on overall_pick, so they were being scored against the
    # wrong draft position too, not just the board.
    applied_note = ""
    if not draft.empty:
        draft, applied, applied_note = apply_recorded_order(draft, season, mgr_map)
    try:
        box = get_boxscores_df(season)
    except Exception:
        box = pd.DataFrame()
    return draft, box, mgr_map, applied_note

with st.spinner("Loading draft data..."):
    draft_df, box_df, manager_map, order_note = load(season)

require_data(draft_df, season, "draft data")

if order_note:
    st.caption(order_note)

# team_name → team_id from draft_df (if present) or box_df
if "team_id" in draft_df.columns:
    tid_by_name = draft_df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]
elif not box_df.empty and "team_id" in box_df.columns:
    tid_by_name = box_df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]
else:
    tid_by_name = {}

def label_for(tname: str) -> str:
    tid = tid_by_name.get(tname) if isinstance(tid_by_name, dict) else tid_by_name.get(tname)
    mgr = manager_map.get(tid, "?") if tid is not None else "?"
    if show_mgr and show_team:
        return f"{mgr} — {tname}"
    return mgr if show_mgr else tname

teams = sorted(draft_df["team_name"].unique())

tab1, tab2, tab3 = st.tabs(["Draft Board", "Team Draft Summary", "Draft Value"])

with tab1:
    st.subheader("Full Draft Board")
    team_options = ["All Teams"] + teams
    selected = st.selectbox("Filter by team", team_options)
    df = draft_df if selected == "All Teams" else draft_df[draft_df["team_name"] == selected]

    display = df[["overall_pick", "round", "pick_in_round", "team_name", "player_name", "keeper"]].copy()
    display["Team"] = display["team_name"].map(label_for)
    display = display[["overall_pick", "round", "pick_in_round", "Team", "player_name", "keeper"]]
    display.columns = ["Overall", "Round", "Pick", "Team", "Player", "Keeper"]
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Draft grid (snake style)
    pivot = draft_df.pivot_table(
        index="round", columns="pick_in_round",
        values="player_name", aggfunc="first"
    )
    # Head each column with the manager who sat there in round 1, rather than
    # a bare pick number. The board snakes, so a column is one seat all the way
    # down and the name is what makes the order legible.
    seat_names = (draft_df[draft_df["round"] == 1]
                  .set_index("pick_in_round")["team_id"].map(manager_map).to_dict())
    pivot.columns = [f"{c}. {seat_names.get(c, '')}".strip(". ")
                     for c in pivot.columns]
    st.subheader("Draft Grid")
    st.dataframe(pivot, use_container_width=True)

with tab2:
    st.subheader("Picks by Team")
    team_pick_counts = draft_df.groupby("team_name").size().reset_index(name="total_picks")
    keeper_counts = draft_df[draft_df["keeper"]].groupby("team_name").size().reset_index(name="keepers")
    summary = team_pick_counts.merge(keeper_counts, on="team_name", how="left").fillna(0)
    summary["keepers"] = summary["keepers"].astype(int)
    summary["draft_picks"] = summary["total_picks"] - summary["keepers"]
    summary["Team"] = summary["team_name"].map(label_for)
    summary_disp = summary[["Team", "total_picks", "keepers", "draft_picks"]].copy()
    summary_disp.columns = ["Team", "Total Picks", "Keepers", "Draft Picks"]
    st.dataframe(summary_disp, use_container_width=True, hide_index=True)

    # Per team picks
    selected_team = st.selectbox("Team", teams, key="team_draft")
    team_picks = draft_df[draft_df["team_name"] == selected_team][
        ["round", "pick_in_round", "overall_pick", "player_name", "keeper"]
    ].copy()
    team_picks.columns = ["Round", "Pick in Round", "Overall", "Player", "Keeper"]

    if not box_df.empty:
        player_pts = box_df[box_df["is_active_slot"]].groupby("player_name")["points"].sum().reset_index()
        player_pts.columns = ["Player", "Season Points"]
        team_picks = team_picks.merge(player_pts, on="Player", how="left")

    st.dataframe(team_picks, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Draft Value Analysis")
    st.caption("How many points did each pick actually score? Earlier picks should score more.")

    if box_df.empty:
        st.info("Box score data needed for draft value analysis. Loading box scores may take a moment.")
    else:
        player_pts = box_df[box_df["is_active_slot"]].groupby("player_name")["points"].sum().reset_index()
        player_pts.columns = ["player_name", "season_points"]
        value_df = draft_df.merge(player_pts, on="player_name", how="left").fillna(0)
        value_df["label"] = value_df["team_name"].map(label_for)

        fig = px.scatter(value_df, x="overall_pick", y="season_points",
                         color="label", hover_name="player_name",
                         title="Points Scored vs Draft Position",
                         labels={"overall_pick": "Draft Pick (Overall)", "season_points": "Season Points", "label": "Team"})
        import numpy as np
        valid = value_df[value_df["season_points"] > 0]
        if len(valid) > 2:
            z = np.polyfit(valid["overall_pick"], valid["season_points"], 1)
            p = np.poly1d(z)
            x_line = sorted(valid["overall_pick"].unique())
            fig.add_scatter(x=x_line, y=p(x_line), mode="lines", name="Trend",
                            line=dict(dash="dash", color="gray"))
        st.plotly_chart(fig, use_container_width=True)

        value_df["value_score"] = value_df["season_points"] / (value_df["overall_pick"] ** 0.5 + 1)
        best_value = value_df.nlargest(15, "value_score")[
            ["overall_pick", "round", "player_name", "label", "season_points", "value_score"]
        ].round(2)
        best_value.columns = ["Pick", "Round", "Player", "Team", "Season Pts", "Value Score"]
        st.subheader("Best Value Picks")
        st.dataframe(best_value, use_container_width=True, hide_index=True)

        busts = value_df[value_df["overall_pick"] <= 30].nsmallest(10, "season_points")[
            ["overall_pick", "round", "player_name", "label", "season_points"]
        ].round(2)
        busts.columns = ["Pick", "Round", "Player", "Team", "Season Pts"]
        st.subheader("Biggest Busts (Top 30 picks)")
        st.dataframe(busts, use_container_width=True, hide_index=True)
