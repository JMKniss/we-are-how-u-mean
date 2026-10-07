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
from display_utils import season_selector, require_data, sidebar_display_prefs
import display_utils as du
from branding import page_icon
import style
from style import esc

st.set_page_config(page_title="Dashboard", page_icon=page_icon(), layout="wide")

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

# No require_data here. A drafted season with week 1 still to come has no
# matchups and is exactly when the fixtures below matter most - stopping the
# page on "no matchup data" hid the one section built for this moment. Only
# the standings and season records below need games actually played.
if upcoming_df.empty and matchups_df.empty:
    require_data(matchups_df, season, "matchup data")

cfg = season_config(season)
current_week = min(current_week, cfg["total_weeks"])
if matchups_df.empty:
    played_df = reg_df = matchups_df
else:
    played_df = matchups_df[matchups_df["week"] <= current_week]
    reg_df = played_df[played_df["week"] <= cfg["reg_season_end"]]


def name(mgr, team):
    if show_mgr and show_team:
        return f"{mgr} — {team}"
    return mgr if show_mgr else team


def name_lines(mgr, team):
    return du.name_lines(mgr, team, show_mgr, show_team)


def team_pic(team_id):
    return style.team_image(season, team_id, manager_map.get(team_id, "?"))


# ── Upcoming matchups ─────────────────────────────────────────────────────────
# Shown only when the archived fixtures are actually ahead of the last played
# week. upcoming.csv holds one week and is replaced each Tuesday, but once a
# season ends nothing replaces it, so the final week's fixtures would sit there
# looking like a game still to come.
last_played = int(played_df["week"].max()) if len(played_df) else 0
upcoming = upcoming_df
if not upcoming.empty and int(upcoming["week"].iloc[0]) <= last_played:
    upcoming = pd.DataFrame()

# The league name carries the branding; the season and week are the kicker.
kicker = f"{season} season"
if last_played:
    kicker += f" · through {week_label(season, last_played).lower()}"
style.page_header("We Are How U Mean", kicker=kicker)

if not upcoming.empty:
    up_week = int(upcoming["week"].iloc[0])
    st.subheader(f"{week_label(season, up_week)} Matchups")

    seen, games = set(), []
    for r in upcoming.itertuples():
        if r.team_id in seen or r.opp_id in seen:
            continue
        seen.add(r.team_id)
        seen.add(r.opp_id)
        home = name_lines(manager_map.get(r.team_id, "?"), r.team_name)
        away = name_lines(manager_map.get(r.opp_id, "?"), r.opp_name)
        side = lambda tid, lines, cls: (
            f'<div class="wa-side {cls}">{style.pic(team_pic(tid))}<div style="min-width:0">'
            f'<span class="wa-name">{esc(lines[0])}</span>'
            f'<span class="wa-team">{esc(lines[1])}</span></div></div>')
        games.append(f'<div class="wa-match">{side(r.team_id, home, "home")}'
                     f'<span class="wa-proj">{r.projected:.1f} – {r.opp_projected:.1f}</span>'
                     f'{side(r.opp_id, away, "away")}</div>')
    st.html(f'<div class="wa-matchups">{"".join(games)}</div>')
    st.caption("Projections based on highest projected startable lineup per ESPN projections")

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
if reg_df.empty:
    st.info(
        f"No games played in {season} yet. Standings and season records "
        f"appear here once week 1 is final."
    )
    st.stop()

def _extreme(largest: bool) -> dict:
    row = reg_df.loc[reg_df["score"].idxmax() if largest else reg_df["score"].idxmin()]
    who_ = name(manager_map.get(row["team_id"], "?"), row["team_name"])
    return {"label": "Reg season high" if largest else "Reg season low",
            "value": f"{row['score']:.2f}", "sub": f"{who_}, week {int(row['week'])}",
            "img": team_pic(row["team_id"])}


style.cards([
    {"label": "Reg season average", "value": f"{reg_df['score'].mean():.1f}",
     "sub": f"{len(reg_df)} scores, {reg_df['week'].nunique()} weeks"},
    _extreme(True),
    _extreme(False),
])

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

# Last four head-to-head results, oldest first.
form = (reg_df.sort_values("week").groupby("team_id")["outcome"]
        .apply(lambda x: list(x.tail(4))))
rows = []
for i, r in enumerate(df.reset_index(drop=True).itertuples()):
    mgr = manager_map.get(r.team_id, "?")
    wve = r.wve
    tone = "wa-pos" if wve.startswith("+") and wve != "+0.0" else ("wa-neg" if wve.startswith("-") else "")
    rows.append([
        style.rank_cell(i + 1),
        style.who_cell(team_pic(r.team_id), *name_lines(mgr, r.team_name)),
        f"<b>{r.record}</b>",
        f"{r.points_for:,.1f}", f"{r.points_against:,.1f}", f"{r.avg_score:.1f}",
        f'<span class="{tone}">{wve}</span>',
        style.form_cell(form.get(r.team_id, [])),
    ])
style.html_table(
    [("#", ""), ("Manager" if show_mgr else "Team", ""), ("Record", ""), ("PF", "num"),
     ("PA", "num"), ("Avg", "num"), ("Wins vs Exp.", "num"), ("Last 4", "")],
    rows, cut_after=4)
st.caption(
    "Wins vs Expected compares the head-to-head record with what those scores "
    "usually earn against the rest of the league. Positive means the schedule "
    "helped."
)
