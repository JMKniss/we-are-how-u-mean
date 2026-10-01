"""
Champmissioner's Dashboard: Mikey's calls on the Romarkable Vlog, graded.

Two tabs. The season tab shows his matchup-pick record, his Romarkable record
by position, and who won the weekly awards - the top scorer under that
season's title and the Fascist of the Week - with a count of each per manager.
All-Time adds the seasons together, under the generic names, since the top
award is renamed every year.

Records only, by design: the league wanted his accuracy, not a week-by-week
replay of his picks. Weeks he made no picks for simply do not count, and a
pick he changed off air counts as the one his recap says he stood by. How the
picks are read and graded is in data/vlog.py and analysis/vlog.py.

Only seasons with vlog picks are offered. The weekly awards are regular
season only, as on the vlog.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from analysis import vlog as av
from branding import page_icon
from config import DEFAULT_SEASON
from data import archive
from data.espn_client import get_boxscores_df, get_manager_map, get_matchups_df
from display_utils import season_selector, sidebar_display_prefs

st.set_page_config(page_title="Champmissioner's Dashboard",
                   page_icon=page_icon(), layout="wide")
st.title("🎙️ Champmissioner's Dashboard")
st.caption("Mikey's calls on the Romarkable Vlog, graded. A Romarkable pick "
           "hits when the player beats his ESPN projection.")

VLOG_SEASONS = archive.seasons_with_data("vlog_matchups")
if not VLOG_SEASONS:
    st.info("No vlog picks are archived yet.")
    st.stop()

season = season_selector(VLOG_SEASONS, min(DEFAULT_SEASON, max(VLOG_SEASONS)))
show_mgr, show_team = sidebar_display_prefs()


@st.cache_data(ttl=300)
def load():
    """Every vlog season, graded, with the weekly awards."""
    matchups, picks, roms, awards = [], [], [], []
    vm, vr = archive.get("vlog_matchups"), archive.get("vlog_romarkables")
    for yr in VLOG_SEASONS:
        m = get_matchups_df(yr)
        if "season" not in m.columns:
            m = m.assign(season=yr)
        box = get_boxscores_df(yr)
        if "season" not in box.columns:
            box = box.assign(season=yr)
        mgr = get_manager_map(yr)
        names = archive.team_names(yr)

        g = av.grade_matchups(vm[vm["season"] == yr], m)
        picks.append(g)
        roms.append(av.grade_romarkables(vr[vr["season"] == yr], box))

        a = av.weekly_awards(m, yr)
        a["manager"] = a["team_id"].map(mgr).fillna("?")
        a["team_name"] = a["team_id"].map(names).fillna("")
        awards.append(a)
    return (pd.concat(picks, ignore_index=True), pd.concat(roms, ignore_index=True),
            pd.concat(awards, ignore_index=True))


picks, roms, awards = load()


def fmt_record(right: int, wrong: int) -> str:
    return f"{right}–{wrong}"


def fmt_pct(right: int, wrong: int) -> str:
    n = right + wrong
    return f"{right / n:.0%}" if n else "–"


def who(row) -> str:
    if show_mgr and show_team and row["team_name"]:
        return f"{row['manager']} — {row['team_name']}"
    return row["manager"] if show_mgr else (row["team_name"] or row["manager"])


def position_table(graded: pd.DataFrame) -> pd.DataFrame:
    t = av.by_position(graded)
    return pd.DataFrame({
        "Position": t["position"],
        "Hits": t["hits"].astype(int),
        "Misses": t["misses"].astype(int),
        "Hit %": [fmt_pct(h, m) for h, m in zip(t["hits"], t["misses"])],
    })


def counts_table(a: pd.DataFrame, top: str, bottom: str) -> pd.DataFrame:
    c = av.award_counts(a)
    return pd.DataFrame({"Manager": c["manager"], top: c["top"].astype(int),
                         bottom: c["bottom"].astype(int)})


def show(df: pd.DataFrame):
    st.dataframe(df, hide_index=True, width="stretch")


tab_season, tab_all = st.tabs([str(season), "All-Time"])

# ── Season ────────────────────────────────────────────────────────────────────
with tab_season:
    sp = picks[picks["season"] == season]
    sr = roms[roms["season"] == season]
    sa = awards[awards["season"] == season]
    title = av.top_title(season)

    mw, ml = av.record(sp["correct"]) if len(sp) else (0, 0)
    rh, rm = av.record(sr["hit"]) if len(sr) else (0, 0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matchup picks", fmt_record(mw, ml))
    c2.metric("Matchup pick %", fmt_pct(mw, ml))
    c3.metric("Romarkable picks", fmt_record(rh, rm))
    c4.metric("Romarkable hit %", fmt_pct(rh, rm))

    left, right = st.columns(2)
    with left:
        st.subheader("Romarkables by position")
        if len(sr):
            show(position_table(sr))
        else:
            st.info("No Romarkable picks graded yet this season.")
    with right:
        st.subheader("Award count")
        show(counts_table(sa, title, av.BOTTOM_TITLE))

    st.subheader("Weekly awards")
    top = sa[sa["award"] == "top"]
    bot = sa[sa["award"] == "bottom"]
    rows = []
    for w in sorted(set(sa["week"])):
        t, b = top[top["week"] == w], bot[bot["week"] == w]
        rows.append({
            "Week": w,
            title: " / ".join(who(r) for _, r in t.iterrows()),
            f"{title} pts": f"{t['score'].iloc[0]:.2f}" if len(t) else "",
            av.BOTTOM_TITLE: " / ".join(who(r) for _, r in b.iterrows()),
            "Fascist pts": f"{b['score'].iloc[0]:.2f}" if len(b) else "",
        })
    if rows:
        show(pd.DataFrame(rows))
    else:
        st.info("No regular-season weeks played yet.")

# ── All-Time ──────────────────────────────────────────────────────────────────
with tab_all:
    rows = []
    for yr in VLOG_SEASONS:
        p, r = picks[picks["season"] == yr], roms[roms["season"] == yr]
        mw, ml = av.record(p["correct"]) if len(p) else (0, 0)
        rh, rm = av.record(r["hit"]) if len(r) else (0, 0)
        rows.append({"Season": str(yr), "Matchup picks": fmt_record(mw, ml),
                     "Matchup %": fmt_pct(mw, ml),
                     "Romarkables": fmt_record(rh, rm), "Hit %": fmt_pct(rh, rm)})
    mw, ml = av.record(picks["correct"])
    rh, rm = av.record(roms["hit"])
    rows.append({"Season": "All-Time", "Matchup picks": fmt_record(mw, ml),
                 "Matchup %": fmt_pct(mw, ml),
                 "Romarkables": fmt_record(rh, rm), "Hit %": fmt_pct(rh, rm)})

    st.subheader("Record by season")
    show(pd.DataFrame(rows))

    left, right = st.columns(2)
    with left:
        st.subheader("Romarkables by position")
        show(position_table(roms))
    with right:
        st.subheader("Award count")
        show(counts_table(awards, av.TOP_GENERIC, av.BOTTOM_GENERIC))
