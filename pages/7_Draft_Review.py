import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import pandas as pd
import numpy as np
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
    # A column is a manager, not a pick number. The board snakes, so pick 3 is
    # a different person in round 2 than in round 1 - pivoting on pick_in_round
    # put a different manager in each column depending on the round's parity.
    # Keyed on the team, a column is one manager the whole way down and the
    # snake is just how the picks run: left to right, then back.
    board_src = draft_df.copy()
    board_src["manager"] = board_src["team_id"].map(manager_map)

    # Left to right in seat order, which is round 1's order.
    seat_order = (draft_df[draft_df["round"] == 1]
                  .sort_values("pick_in_round")["team_id"]
                  .map(manager_map).tolist())

    # aggfunc="first" would quietly drop a player: 2018 had traded picks, so
    # two managers hold two picks in one round and none in another, and the
    # board showed 158 of that draft's 160 players. Join instead, so a doubled
    # cell shows both names and the empty cell opposite it is visibly empty.
    board = board_src.pivot_table(
        index="round", columns="manager", values="player_name",
        aggfunc=lambda names: " / ".join(names))
    kept = board_src.pivot_table(
        index="round", columns="manager", values="keeper",
        aggfunc="max")
    cols = [m for m in seat_order if m in board.columns]
    board, kept = board[cols], kept.reindex(columns=cols)
    board.index.name = "Round"

    if kept.fillna(False).to_numpy().any():
        # Keepers are shown by colour alone - no column, no marker, nothing to
        # read. Text colour is set alongside the fill so the cell stays legible
        # in dark mode, where the grid would otherwise put light text on it.
        blue = "background-color: #cfe8f7; color: #0b3954"
        styled = board.style.apply(
            lambda _: np.where(kept.reindex_like(board).fillna(False), blue, ""),
            axis=None)
        st.dataframe(styled, use_container_width=True)
        st.caption("Blue cells were kept, not drafted.")
    else:
        st.dataframe(board, use_container_width=True)

with tab2:
    # The old summary above this broke each team's picks into total, keepers
    # and drafted. With keepers off the page it would have read Total Picks
    # 17, ten times over, so it is gone rather than kept as filler.
    selected_team = st.selectbox("Team", teams, key="team_draft")
    team_picks = draft_df[draft_df["team_name"] == selected_team][
        ["round", "overall_pick", "player_name"]
    ].copy()
    team_picks.columns = ["Round", "Overall", "Player"]

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
