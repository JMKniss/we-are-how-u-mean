"""
Champmissioner's Dashboard: The Champmissioner's calls on the Romarkable Vlog, graded.

Four tabs. This Week shows his preview of the next week to be played, his
matchup picks and his Romarkable players with ESPN's projection, from
vlog_upcoming.csv. It always shows the latest season, whatever the selector
says, and says so when his notes for the week are not in yet.

Season Records, for the selected season, shows his matchup-pick and
Romarkable records, his Romarkable hit rate by position, a count of each
weekly award per manager - the top scorer under that season's title and the
Fascist of the Week - the weekly benchmarks behind them, and how often he
took each manager to win, and how often that manager then won.

Power Rankings shows his rankings week by week for the selected season, each
line labelled at both ends rather than in a legend, which ten colours made
hard to follow. Once the regular season is over, his preseason and final
rankings are set against the playoff seeds, and once the playoffs are over,
against the final standings.

All-Time adds the seasons together, under the generic award names, since the
top award is renamed every year, and ends with Times Picked to Win across
every season, added up by manager.

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
import plotly.graph_objects as go
from plotly.colors import qualitative
import streamlit as st

from analysis import vlog as av
from analysis.standings import compute_season_finish_map, playoff_seeds
from branding import page_icon
from config import DEFAULT_SEASON, season_config
from data import archive
from data.espn_client import get_boxscores_df, get_manager_map, get_matchups_df
from display_utils import season_selector, sidebar_display_prefs

st.set_page_config(page_title="Champmissioner's Dashboard",
                   page_icon=page_icon(), layout="wide")
st.title("🎙️ Champmissioner's Dashboard")
st.caption("Champmissioner Romar's predictions, as seen on the Vlog!")

VLOG_SEASONS = archive.seasons_with_data("vlog_matchups")
if not VLOG_SEASONS:
    st.info("No vlog picks are archived yet.")
    st.stop()

season = season_selector(VLOG_SEASONS, min(DEFAULT_SEASON, max(VLOG_SEASONS)))
show_mgr, show_team = sidebar_display_prefs()


@st.cache_data(ttl=300)
def load():
    """Every vlog season, graded, with the weekly awards."""
    picks, roms, awards, rankings = [], [], [], {}
    vm, vr = archive.get("vlog_matchups"), archive.get("vlog_romarkables")
    vp = (archive.get("vlog_power_rankings")
          if archive.has("vlog_power_rankings") else pd.DataFrame())
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

        # Seeds once the regular season is over; finishes once the playoffs
        # are ({} until then).
        reg_done = len(m) and m["week"].max() >= season_config(yr)["reg_season_end"]
        seeds = ({t: i + 1 for i, t in enumerate(playoff_seeds(yr, m))}
                 if reg_done else {})
        r = vp[vp["season"] == yr] if len(vp) else vp
        if len(r):
            r = r.assign(manager=r["team_id"].map(mgr))
        rankings[yr] = {"ranks": r, "seeds": seeds,
                        "finish": compute_season_finish_map(yr, m), "managers": mgr}
    return (pd.concat(picks, ignore_index=True), pd.concat(roms, ignore_index=True),
            pd.concat(awards, ignore_index=True), rankings)


picks, roms, awards, rankings = load()


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


def count_table(a: pd.DataFrame, award: str) -> pd.DataFrame:
    """Manager and how many times he won one award, most first."""
    c = av.award_counts(a)
    c = c[c[award] > 0].sort_values(award, ascending=False, kind="stable")
    return pd.DataFrame({"Manager": c["manager"], "Count": c[award].astype(int)})


def picked_to_win(seasons: list[int]) -> pd.DataFrame:
    """
    How many times he took each manager to win over these seasons, most
    first, and how many of those the manager won. Added up by manager, since
    a team_id can change hands. A contest still running counts as a pick, not
    yet as a win.
    """
    taken, won = {}, {}
    for yr in seasons:
        mgr = rankings[yr]["managers"]
        for m in mgr.values():
            taken.setdefault(m, 0)
            won.setdefault(m, 0)
        for t in archive.get("vlog_matchups", yr)["pick_id"]:
            taken[mgr[t]] = taken.get(mgr[t], 0) + 1
        sp = picks[picks["season"] == yr]
        for t in (sp.loc[sp["correct"].astype(bool), "pick_id"] if len(sp) else []):
            won[mgr[t]] = won.get(mgr[t], 0) + 1
    t = pd.DataFrame({"Manager": list(taken),
                      "Picked to Win": list(taken.values()),
                      "Correctly Picked to Win": [won.get(m, 0) for m in taken]})
    return t.sort_values(["Picked to Win", "Manager"], ascending=[False, True])


def top_count_title(season_title: str) -> str:
    """'Trainer of the Week' -> 'Top Trainer Count'."""
    return f"Top {season_title.removesuffix(' of the Week')} Count"


def show(df: pd.DataFrame):
    st.dataframe(df, hide_index=True, width="stretch")


def fmt_off(x) -> str:
    return "–" if x is None else f"{x:.1f}"


def render_rankings(info: dict):
    """Week-by-week power rankings, then how they held up once that is known."""
    ranks, mgr = info["ranks"], info["managers"]
    st.subheader("Champmissioner's Power Rankings")
    if ranks is None or ranks.empty:
        st.info("No power rankings this season yet.")
        return

    grid = av.ranking_grid(ranks)
    weeks = list(range(int(min(grid.columns)), int(max(grid.columns)) + 1))
    label = lambda w: "Pre" if w == 1 else f"Wk {w}"
    last = grid[max(grid.columns)].sort_values()

    fig = go.Figure()
    colours = qualitative.Plotly
    for i, tid in enumerate(last.index):
        ys = [grid.at[tid, w] if w in grid.columns else None for w in weeks]
        name = mgr.get(tid, "?")
        # The name at the first and last point he ranked them, in place of a
        # legend. The last also carries the places moved since his first
        # ranking, the preseason one, up being plus. The names take the
        # site's text colour, so they read in dark mode too.
        have = [j for j, y in enumerate(ys) if y is not None and not pd.isna(y)]
        text = [""] * len(ys)
        where = ["middle right"] * len(ys)
        if have:
            end = name
            if len(have) > 1:
                end = f"{name} {int(ys[have[0]] - ys[have[-1]]):+d}"
            text[have[0]], where[have[0]] = name, "middle left"
            text[have[-1]], where[have[-1]] = end, "middle right"
        colour = colours[i % len(colours)]
        fig.add_trace(go.Scatter(
            x=[label(w) for w in weeks], y=ys, mode="lines+markers+text",
            name=name, connectgaps=False, text=text, textposition=where,
            line=dict(color=colour),
            marker=dict(color=colour), cliponaxis=False,
            hovertemplate="%{fullData.name}: %{y}<extra>%{x}</extra>"))
    fig.update_yaxes(autorange="reversed", dtick=1, title="Rank")
    fig.update_xaxes(type="category", title=None)
    fig.update_layout(height=440, showlegend=False,
                      margin=dict(l=90, r=90, t=10, b=10))
    st.plotly_chart(fig, width="stretch")

    # One row per manager in the latest order; a week he skipped says so.
    table = pd.DataFrame({"Manager": [mgr.get(t, "?") for t in last.index]})
    for w in weeks:
        table[label(w)] = (["skip"] * len(last) if w not in grid.columns else
                           [str(int(grid.at[t, w])) for t in last.index])
    show(table)

    seeds, finish = info["seeds"], info["finish"]
    if not seeds:
        st.caption("His preseason and final rankings are set against the playoff "
                   "seeds when the regular season ends, and the final standings "
                   "when the playoffs do.")
        return
    pre, fin = av.first_and_last(ranks)
    st.subheader("How the rankings held up")
    cols = st.columns(4)
    cols[0].metric("Preseason vs seeds", fmt_off(av.places_off(pre, seeds)),
                   help="Average places off: 0 is perfect, a random order averages 3.3.")
    cols[1].metric("Final vs seeds", fmt_off(av.places_off(fin, seeds)))
    cols[2].metric("Preseason vs finish",
                   fmt_off(av.places_off(pre, finish) if finish else None))
    cols[3].metric("Final vs finish",
                   fmt_off(av.places_off(fin, finish) if finish else None))
    order = sorted(seeds, key=lambda t: finish.get(t, seeds[t]))
    rows = [{"Manager": mgr.get(t, "?"),
             "Preseason": str(pre.get(t, "–")),
             "Final ranking": str(fin.get(t, "–")),
             "Seed": str(seeds[t]),
             "Finish": str(finish[t]) if finish else "–"} for t in order]
    show(pd.DataFrame(rows))
    if not finish:
        st.caption("Final standings are added when the playoffs finish.")


tab_week, tab_season, tab_ranks, tab_all = st.tabs(
    ["This Week", "Season Records", "Power Rankings", "All-Time"])

# ── This Week ─────────────────────────────────────────────────────────────────
with tab_week:
    up = (archive.get("vlog_upcoming") if archive.has("vlog_upcoming")
          else pd.DataFrame())
    latest = max(VLOG_SEASONS)
    played = archive.current_week(latest) or 0
    if len(up):
        up = up[(up["season"] == latest) & (up["week"] > played)]
    if up.empty:
        st.info(f"No predictions for week {played + 1} yet.")
    else:
        mgr = get_manager_map(latest)
        st.caption(f"{latest} week {int(up['week'].iloc[0])}.")

        st.subheader("Romarkable Matchup Predictions")
        rows = []
        for r in up[up["kind"] == "matchup"].itertuples(index=False):
            other = r.opp_id if r.pick_id == r.team_id else r.team_id
            rows.append({"Prediction": f"{mgr.get(int(r.pick_id), '?')} over "
                                       f"{mgr.get(int(other), '?')}"})
        if rows:
            show(pd.DataFrame(rows))
        else:
            st.info("No matchup picks this week.")

        st.subheader("Romarkable Player Predictions")
        order = {p: i for i, p in enumerate(av.POSITIONS)}
        pl = (up[up["kind"] == "player"]
              .sort_values("position", key=lambda c: c.map(order)))
        if len(pl):
            show(pd.DataFrame({
                "Position": pl["position"],
                "Player": pl["player_name"],
                "ESPN Projection": ["–" if pd.isna(x) else f"{x:.2f}"
                                    for x in pl["projected"]],
            }))
        else:
            st.info("No player picks this week.")

# ── Season ────────────────────────────────────────────────────────────────────
with tab_season:
    sp = picks[picks["season"] == season]
    sr = roms[roms["season"] == season]
    sa = awards[awards["season"] == season]
    title = av.top_title(season)

    st.subheader("Romarkable Predictions Record")
    mw, ml = av.record(sp["correct"]) if len(sp) else (0, 0)
    rh, rm = av.record(sr["hit"]) if len(sr) else (0, 0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matchup Picks", fmt_record(mw, ml))
    c2.metric("Matchup Pick %", fmt_pct(mw, ml))
    c3.metric("Player Picks", fmt_record(rh, rm))
    c4.metric("Player Hit %", fmt_pct(rh, rm))
    st.caption("A player pick hits when he beats his ESPN projection.")

    st.subheader("Romarkable Player hit rate by position")
    if len(sr):
        show(position_table(sr))
    else:
        st.info("No player picks graded yet this season.")

    left, right = st.columns(2)
    with left:
        st.subheader(top_count_title(title))
        show(count_table(sa, "top"))
    with right:
        st.subheader("Fascist Count")
        show(count_table(sa, "bottom"))

    st.subheader("Weekly Benchmarks")
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

    st.subheader("Times Picked to Win")
    show(picked_to_win([season]))

# ── Power Rankings ────────────────────────────────────────────────────────────
with tab_ranks:
    render_rankings(rankings[season])

# ── All-Time ──────────────────────────────────────────────────────────────────
with tab_all:
    rows = []
    for yr in VLOG_SEASONS:
        p, r = picks[picks["season"] == yr], roms[roms["season"] == yr]
        mw, ml = av.record(p["correct"]) if len(p) else (0, 0)
        rh, rm = av.record(r["hit"]) if len(r) else (0, 0)
        rows.append({"Season": str(yr), "Matchup Picks": fmt_record(mw, ml),
                     "Matchup %": fmt_pct(mw, ml),
                     "Player Picks": fmt_record(rh, rm), "Hit %": fmt_pct(rh, rm)})
    mw, ml = av.record(picks["correct"])
    rh, rm = av.record(roms["hit"])
    rows.append({"Season": "All-Time", "Matchup Picks": fmt_record(mw, ml),
                 "Matchup %": fmt_pct(mw, ml),
                 "Player Picks": fmt_record(rh, rm), "Hit %": fmt_pct(rh, rm)})

    st.subheader("Romarkable Predictions Record")
    show(pd.DataFrame(rows))

    st.subheader("Power rankings vs results")
    st.caption("Average places off between his ranking and where each manager "
               "ended up: 0 is perfect, a random order averages 3.3. A season "
               "appears once its regular season is over.")
    acc = []
    for yr in VLOG_SEASONS:
        info = rankings[yr]
        if info["ranks"] is None or info["ranks"].empty or not info["seeds"]:
            continue
        pre, fin = av.first_and_last(info["ranks"])
        seeds, finish = info["seeds"], info["finish"]
        acc.append({"Season": str(yr),
                    "Preseason vs seeds": av.places_off(pre, seeds),
                    "Final vs seeds": av.places_off(fin, seeds),
                    "Preseason vs finish": av.places_off(pre, finish) if finish else None,
                    "Final vs finish": av.places_off(fin, finish) if finish else None})
    if acc:
        a = pd.DataFrame(acc)
        avg = {"Season": "Average"}
        for c in a.columns[1:]:
            vals = a[c].dropna()
            avg[c] = vals.mean() if len(vals) else None
        a = pd.concat([a, pd.DataFrame([avg])], ignore_index=True)
        for c in a.columns[1:]:
            a[c] = [fmt_off(None if pd.isna(v) else v) for v in a[c]]
        show(a)
    else:
        st.info("No completed regular season with power rankings yet.")

    st.subheader("Romarkable Player hit rate by position")
    show(position_table(roms))

    left, right = st.columns(2)
    with left:
        st.subheader(f"{av.TOP_GENERIC} Count")
        show(count_table(awards, "top"))
    with right:
        st.subheader("Fascist Count")
        show(count_table(awards, "bottom"))

    st.subheader("Times Picked to Win")
    show(picked_to_win(VLOG_SEASONS))
