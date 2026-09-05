import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from data.espn_client import (get_current_week, get_matchups_df, get_manager_map,
                              get_upcoming_df)
from analysis.standings import h2h_standings, combined_standings, luck_index
from analysis.matchup_notes import pair_history, notes_for_matchups
from config import SEASONS, DEFAULT_SEASON, season_config, week_label
from display_utils import season_selector, require_data, sidebar_display_prefs, prep_display
from branding import page_icon, title_html

st.set_page_config(page_title="Dashboard", page_icon=page_icon(), layout="wide")
# The league name carries the branding; "Dashboard" is the subtitle under it.
st.markdown(title_html("Dashboard"), unsafe_allow_html=True)

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()


@st.cache_data(ttl=300)
def load(season):
    return (get_matchups_df(season), get_manager_map(season),
            get_current_week(season), get_upcoming_df(season))


@st.cache_data(ttl=600)
def load_history():
    """Every regular season game ever played, for the matchup notes."""
    frames = []
    for yr in SEASONS:
        m = get_matchups_df(yr)
        if m.empty:
            continue
        mgr = get_manager_map(yr)
        m = m[m["week"] <= season_config(yr)["reg_season_end"]].copy()
        m["manager"] = m["team_id"].map(mgr)
        m["opp_manager"] = m["opp_id"].map(mgr)
        frames.append(m)
    if not frames:
        return pd.DataFrame()
    return pair_history(pd.concat(frames, ignore_index=True))


with st.spinner("Loading league data..."):
    matchups_df, manager_map, current_week, upcoming_df = load(season)

require_data(matchups_df, season, "matchup data")

cfg = season_config(season)
current_week = min(current_week, cfg["total_weeks"])
played_df = matchups_df[matchups_df["week"] <= current_week]
reg_df = played_df[played_df["week"] <= cfg["reg_season_end"]]


def name(mgr, team):
    if show_mgr and show_team:
        return f"{mgr} — {team}"
    return mgr if show_mgr else team


# ── Upcoming matchups ─────────────────────────────────────────────────────────
# Shown only when the archived fixtures are actually ahead of the last played
# week. upcoming.csv holds one week and is replaced each Tuesday, but once a
# season ends nothing replaces it, so the final week's fixtures would sit there
# looking like a game still to come.
last_played = int(played_df["week"].max()) if not played_df.empty else 0
upcoming = upcoming_df
if not upcoming.empty and int(upcoming["week"].iloc[0]) <= last_played:
    upcoming = pd.DataFrame()

if not upcoming.empty:
    up_week = int(upcoming["week"].iloc[0])
    st.subheader(f"{week_label(season, up_week)} Matchups")

    seen, rows = set(), []
    for r in upcoming.itertuples():
        if r.team_id in seen or r.opp_id in seen:
            continue
        seen.add(r.team_id)
        seen.add(r.opp_id)
        rows.append({
            "Home": name(manager_map.get(r.team_id, "?"), r.team_name),
            "Projection": f"{r.projected:.1f} – {r.opp_projected:.1f}",
            "Away": name(manager_map.get(r.opp_id, "?"), r.opp_name),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Matchups to watch ────────────────────────────────────────────────────
    history = load_history()
    pairs = {
        tuple(sorted((manager_map.get(r.team_id, "?"),
                      manager_map.get(r.opp_id, "?"))))
        for r in upcoming.itertuples()
    }
    notes = notes_for_matchups(pairs, history)
    if notes:
        st.markdown("**Matchups to watch**")
        for note in notes:
            st.markdown(f"- {note.text}")

    st.divider()

# ── Quick stats ───────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
col1.metric("Reg Season Avg Score", f"{reg_df['score'].mean():.1f}" if not reg_df.empty else "—")


def _extreme(df, largest: bool):
    if df.empty:
        return None
    row = df.loc[df["score"].idxmax() if largest else df["score"].idxmin()]
    return row, name(manager_map.get(row["team_id"], "?"), row["team_name"])


high = _extreme(reg_df, True)
low = _extreme(reg_df, False)
if high:
    col2.metric("Reg Season High", f"{high[0]['score']:.2f}", delta=high[1])
else:
    col2.metric("Reg Season High", "—")
if low:
    col3.metric("Reg Season Low", f"{low[0]['score']:.2f}", delta=low[1])
else:
    col3.metric("Reg Season Low", "—")

st.divider()

# ── Standings ─────────────────────────────────────────────────────────────────
st.subheader("Regular Season Standings")

if season >= 2025:
    df = combined_standings(reg_df)
    wins, losses = "total_wins", "total_losses"
else:
    df = h2h_standings(reg_df)
    wins, losses = "wins", "losses"

df = df.copy()
df["record"] = df[wins].astype(int).astype(str) + "-" + df[losses].astype(int).astype(str)

# Wins vs expected: what the H2H record was against what those scores usually
# earn. The Luck Index panel this replaces said the same thing in three columns.
luck = luck_index(reg_df).set_index("team_id")
df["wve"] = df["team_id"].map(luck["luck_score"]).round(1)
df["wve"] = df["wve"].map(lambda v: "—" if pd.isna(v) else f"{v:+.1f}")

display = prep_display(
    df, manager_map, show_mgr, show_team,
    cols=["team_name", "record", "points_for", "points_against", "avg_score", "wve"],
    headers=["Team", "Record", "PF", "PA", "Avg", "Wins vs Expected"],
)
for c in ("PF", "PA", "Avg"):
    display[c] = display[c].round(1)
st.dataframe(display, use_container_width=True, hide_index=True)
st.caption(
    "Wins vs Expected compares the head-to-head record with what those scores "
    "usually earn against the rest of the league. Positive means the schedule "
    "helped."
)
