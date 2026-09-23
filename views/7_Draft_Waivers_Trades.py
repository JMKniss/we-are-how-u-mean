"""
Draft, Waivers & Trades - how every roster was built, from the draft onward.

Draft Board, Team Draft Summary and Draft Value read the draft. Waivers and
Trades read data/archive/transactions.csv, which the weekly update fills in;
see get_transactions_df for how it is recorded and why it only exists from the
2026 season on.

Both transaction tabs are tables rather than dataframes because each move is
shown in one cell with a green + beside what came in and a red - beside what
went out, and st.table renders Markdown colour where st.dataframe shows the
raw text. The sort is chosen with a control instead of a column header for the
same reason.

Draft Value plots each pick's points above replacement against the curve of
what that slot normally returns; the method, and why each part of it is the
way it is, is in analysis/draft_value.py. It is empty for 2016-2017, which
kept too little to measure a replacement level.

Both transaction tabs end with the same per-manager count of waiver adds and trades for
the season (analysis.transactions.move_counts), so either tab answers "who is
most active" without switching.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import pandas as pd
import numpy as np
from data import archive
from data.espn_client import (get_draft_df, get_boxscores_df, get_manager_map,
                              get_transactions_df)
from analysis.draft import apply_recorded_order
from analysis import draft_value
from analysis.transactions import waiver_moves, trade_sides, move_counts
from config import SEASONS, DEFAULT_SEASON
from display_utils import season_selector, require_data, sidebar_display_prefs, prep_display, chart_label
from branding import page_icon

st.set_page_config(page_title="Draft, Waivers & Trades", page_icon=page_icon(), layout="wide")
st.title("📋 Draft, Waivers & Trades")

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
    return draft, box, mgr_map, applied_note, get_transactions_df(season)

@st.cache_data(ttl=3600)
def load_value(season):
    return draft_value.draft_value(season)

with st.spinner("Loading draft data..."):
    draft_df, box_df, manager_map, order_note, tx_df = load(season)

require_data(draft_df, season, "draft data")

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

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Draft Board", "Team Draft Summary", "Draft Value", "Waivers", "Trades"])

with tab1:
    if order_note:
        st.caption(order_note)
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
        st.dataframe(styled, width="stretch")
        st.caption("Blue cells were kept, not drafted.")
    else:
        st.dataframe(board, width="stretch")

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

    st.dataframe(team_picks, width="stretch", hide_index=True)

with tab3:
    st.subheader("Draft Value")
    st.caption("Draft value data only considers players taken in the draft. "
               "Undrafted waiver adds are evaluated separately.")
    st.caption("A pick's value is the points he scored per game above a replacement "
               "starter at his position, minus what a pick in that slot normally "
               "returns based on league history (adjusted for scoring changes we've "
               "made year-to-year).")

    if not draft_value.supported(season):
        st.info("There is not enough preserved data to perform this analysis.")
    else:
        picks, curve, frozen = load_value(season)

        picks["label"] = chart_label(picks, manager_map, show_mgr, show_team)
        fig = px.scatter(
            picks, x="overall_pick", y="vor", color="label",
            hover_name="player_name",
            hover_data={"position": True, "games": True, "ppg": ":.2f",
                        "expected": ":.2f", "value": ":.2f", "label": False},
            title="Points per Game Above Replacement vs Draft Position",
            labels={"overall_pick": "Draft Pick (Overall)",
                    "vor": "Points per Game Above Replacement", "label": "Team",
                    "position": "Pos", "games": "Games", "ppg": "Pts/G",
                    "expected": "Expected", "value": "Value"})
        # Hollow per point rather than px's symbol=, which splits every team
        # into a kept and a dropped legend entry. px keeps row order within a
        # colour, so each trace's points line up with its team's rows.
        # The legend draws a trace's first point, so a team whose first pick
        # was dropped showed hollow there too. Each team's legend entry is a
        # solid stand-in instead, grouped with its trace so clicks still work.
        fig.update_traces(marker=dict(size=9, line=dict(width=1.5)))
        for trace in list(fig.data):
            dropped = picks.loc[picks["label"] == trace.name, "dropped"]
            trace.marker.symbol = np.where(dropped, "circle-open", "circle").tolist()
            trace.legendgroup, trace.showlegend = trace.name, False
            fig.add_scatter(x=[None], y=[None], mode="markers", name=trace.name,
                            legendgroup=trace.name,
                            marker=dict(symbol="circle", size=9, color=trace.marker.color,
                                        line=dict(width=1.5)))
        fig.add_scatter(x=[None], y=[None], mode="markers", name="Hollow: dropped by drafter",
                        marker=dict(symbol="circle-open", size=9, color="gray",
                                    line=dict(width=1.5)))
        x_line = np.arange(1, int(picks["overall_pick"].max()) + 1)
        fig.add_scatter(x=x_line, y=curve["intercept"] + curve["slope"] * np.log(x_line),
                        mode="lines", name="Expected at this pick",
                        line=dict(dash="dash", color="gray"))
        st.plotly_chart(fig, width="stretch")

        cols = ["overall_pick", "round", "player_name", "position", "team_name",
                "games", "ppg", "vor", "expected", "value"]
        headers = ["Pick", "Round", "Player", "Pos", "Team",
                   "Games", "Pts/G", "Over Repl.", "Expected", "Value"]

        st.subheader("Best Value Picks")
        st.dataframe(prep_display(picks.nlargest(15, "value"), manager_map, show_mgr,
                                  show_team, cols, headers).round(2),
                     width="stretch", hide_index=True)

        # A count rather than a Y/N: an N read as "not injured" for a player
        # who missed two games. See analysis/draft_value.py.
        st.subheader("Biggest Busts")
        st.dataframe(prep_display(picks.nsmallest(10, "value"), manager_map, show_mgr,
                                  show_team, cols + ["injury_games"],
                                  headers + ["Games Missed"]).round(2),
                     width="stretch", hide_index=True)
        st.caption("Partial games missed indicates player was hurt mid-game")


# ── Waivers and Trades ───────────────────────────────────────────────────────

LEAGUE = "Whole league"
team_names = archive.team_names(season) or (
    draft_df[["team_id", "team_name"]].drop_duplicates()
    .set_index("team_id")["team_name"].to_dict())
team_by_manager = {m: tid for tid, m in manager_map.items()}


def md_escape(text: str) -> str:
    # $ matters most: two in one cell and Streamlit reads the span between
    # them as LaTeX.
    for ch in "\\`*_[]$~:<>#|":
        text = text.replace(ch, "\\" + ch)
    return text


def plus(names):
    return [f":green[**+**] {md_escape(n)}" for n in names]


def minus(names, suffix=""):
    return [f":red[**−**] {md_escape(n)}{suffix}" for n in names]


def when(executed_at: str) -> str:
    # Blank for a drop ESPN never logged: the rosters show the week, not the day.
    if pd.isna(executed_at):
        return ""
    d = pd.Timestamp(executed_at)
    return f"{d:%a %b} {d.day}"


def who(frame: pd.DataFrame) -> pd.DataFrame:
    """Manager and/or Team columns, following the sidebar display toggles."""
    out = pd.DataFrame(index=frame.index)
    if show_mgr:
        out["Manager"] = frame["team_id"].map(manager_map).fillna("?")
    if show_team:
        out["Team"] = frame["team_id"].map(team_names).fillna("?").map(md_escape)
    return out


def manager_picker(label: str, key: str, team_ids) -> int | None:
    """Selectbox of the managers who appear; returns a team_id, None for all."""
    present = sorted(manager_map[t] for t in set(team_ids) if t in manager_map)
    choice = st.selectbox(label, [LEAGUE] + present, key=key)
    return None if choice == LEAGUE else team_by_manager[choice]


def not_tracked(what: str):
    tracked = archive.seasons_with_data("transactions")
    if season in tracked:
        st.info(f"No {what} yet in {season}. The weekly update adds them every Tuesday.")
    elif tracked and season < tracked[0]:
        # 2016 and 2017: ESPN kept no transactions, and their archived
        # rosters are starters only, so there is nothing to rebuild from.
        st.info(f"ESPN kept no record of {what} before {tracked[0]}.")
    else:
        st.info(f"{what.capitalize()} are not recorded for {season}.")


def counts_table():
    """Waiver adds and trades per manager this season, under both tabs."""
    if tx_df.empty:
        return
    counts = move_counts(tx_df, manager_map)
    st.divider()
    st.subheader(f"{season} Moves by Manager")
    table = pd.concat([who(counts), pd.DataFrame({
        "Waiver Adds": counts["waiver_adds"], "Trades": counts["trades"]})], axis=1)
    # who() escapes team names for the Markdown tables above; a dataframe
    # shows the backslashes, so undo that here.
    if "Team" in table:
        table["Team"] = counts["team_id"].map(team_names).fillna("?")
    st.dataframe(table.sort_values("Waiver Adds", ascending=False),
                 hide_index=True, width="stretch")
    n_trades = tx_df.loc[tx_df["kind"] == "trade", "transaction_id"].nunique()
    st.caption(
        f"{int(counts['waiver_adds'].sum())} waiver adds and {n_trades} "
        f"trade{'s' if n_trades != 1 else ''} league-wide. A waiver add is any "
        "player added, by claim or free-agent pickup; drops are not counted. "
        "A trade counts once for each manager in it, however many players moved.")


with tab4:
    moves = waiver_moves(tx_df)
    if moves.empty:
        not_tracked("waiver moves")
    else:
        c1, c2 = st.columns(2)
        with c1:
            team = manager_picker("Manager", "waiver_manager", moves["team_id"])
        with c2:
            order = st.radio("Sort", ["Newest first", "Oldest first", "FAAB spent"],
                             horizontal=True, key="waiver_sort")
        shown = moves if team is None else moves[moves["team_id"] == team]

        claims = shown[shown["kind"] == "waiver"]
        st.caption(f"{len(shown)} moves · {len(claims)} waiver claims · "
                   f"\\${int(claims['bid'].fillna(0).sum())} FAAB spent")

        if order == "FAAB spent":
            # A $0 claim still outranks a free pickup, and a bare drop spent
            # nothing at all; newest first within each.
            rank = shown["bid"].astype("float").fillna(-1)
            rank = rank.where(shown["adds"].str.len() > 0, -2)
            shown = (shown.assign(_rank=rank)
                     .sort_values(["_rank", "week", "executed_at"], ascending=False))
        else:
            shown = shown.sort_values(["week", "executed_at"],
                                      ascending=order == "Oldest first")

        table = pd.concat([
            pd.DataFrame({"Week": shown["week"], "Date": shown["executed_at"].map(when)}),
            who(shown),
            pd.DataFrame({
                "Waiver Move": [" &nbsp; ".join(plus(a) + minus(d))
                                for a, d in zip(shown["adds"], shown["drops"])],
                # FA is a pickup after waivers cleared; $0 is a claim that won
                # with no money on it. A bare drop has no bid either way.
                "Bid": ["" if not a else "FA" if k != "waiver" else f"\\${int(b)}"
                        for a, k, b in zip(shown["adds"], shown["kind"], shown["bid"])],
            }, index=shown.index),
        ], axis=1)
        st.table(table.set_index("Week"))
    counts_table()

with tab5:
    sides = trade_sides(tx_df)
    if sides.empty:
        not_tracked("trades")
    else:
        with st.columns(2)[0]:
            team = manager_picker("Manager", "trade_manager", sides["team_id"])
        if team is not None:
            sides = sides[sides["team_id"] == team]
        n = sides["transaction_id"].nunique()
        st.caption(f"{n} trade{'s' if n != 1 else ''}")

        # Newest trade first, each trade's sides kept together.
        sides = sides.sort_values(["week", "executed_at", "transaction_id", "team_id"],
                                  ascending=[False, False, False, True])
        table = pd.concat([
            pd.DataFrame({"Week": sides["week"],
                          "Date": [when(d) + (" ≈" if inf else "")
                                   for d, inf in zip(sides["executed_at"], sides["inferred"])]}),
            who(sides),
            pd.DataFrame({
                "Receives": [", ".join(plus(r)) for r in sides["receives"]],
                "Sends": [", ".join(minus(s) + minus(d, " (dropped)"))
                          for s, d in zip(sides["sends"], sides["dropped"])],
                "With": [", ".join(manager_map.get(p, "?") for p in ps)
                         for ps in sides["partners"]],
            }, index=sides.index),
        ], axis=1)
        st.table(table.set_index("Week"))

        if sides["inferred"].any():
            st.caption(
                "≈ rebuilt from week-to-week rosters. ESPN does not keep the "
                "players in a finished season's trades, so they are worked out "
                "from who changed teams without a recorded move, and checked "
                "against the trades ESPN says were accepted.")
            flagged = sides.drop_duplicates("transaction_id")
            flagged = flagged[flagged["notes"].str.len() > 0]
            for _, t in flagged.iterrows():
                teams = " & ".join(manager_map.get(x, "?")
                                   for x in sorted([t["team_id"], *t["partners"]]))
                st.caption(f"Week {t['week']}, {teams}: {'; '.join(t['notes'])}.")
    counts_table()
