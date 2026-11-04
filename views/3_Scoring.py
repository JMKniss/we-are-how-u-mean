"""
Scoring - weekly trends, distributions, best and worst, head-to-head scores.

Weekly Trends, Individual Manager Trend chart:
- The dropdown lists every manager, with "- League Median -" first.
- A manager plots their weekly scores, the league average (dotted), a season
  trendline and a last-5 trendline. League Median plots the weekly median and
  both trendlines, and hides the average line as redundant.
- The last-5 trendline appears only from six weeks of data onward.
- Slopes show as st.metric chips below the chart, not on-chart annotations,
  which collided with the legend.
- The x-axis stops at the last week played.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_boxscores_df, get_matchups_df, get_manager_map
from analysis.efficiency import top_players, projected_vs_actual, player_manager_sequence
from config import SEASONS, DEFAULT_SEASON
from display_utils import season_selector, require_data, sidebar_display_prefs, chart_label, name_lines, who_columns
from branding import page_icon
from style import (DIVERGING, RED, esc, frame, html_table, page_header, player_pic, rank_cell,
                   series_colours, team_image, who_cell)

st.set_page_config(page_title="Scoring", page_icon=page_icon(), layout="wide")
page_header("Scoring")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season), get_manager_map(season)

with st.spinner("Loading..."):
    df, manager_map = load(season)

require_data(df, season, "scoring data")

# team_name → display label helper
tid_by_name = df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]
def label_for(tname: str) -> str:
    """A team's chart label: its manager, never the team name (see chart_label)."""
    tid = tid_by_name.get(tname)
    return manager_map.get(tid, "?") if tid is not None else "?"

teams = sorted(df["team_name"].unique())


def who_html(tid, tname):
    """A team's picture with its name lines, for a hand-built row."""
    mgr = manager_map.get(tid, "?")
    return who_cell(team_image(season, tid, mgr), *name_lines(mgr, tname, show_mgr, show_team))


def result_badge(outcome):
    return f'<span class="wa-dot {outcome}">{outcome}</span>' if outcome in ("W", "L", "T") else ""

tab1, tab2, tab3, tab4, tab_top, tab_proj = st.tabs(
    ["Weekly Trends", "Score Distributions", "Best & Worst", "Head-to-Head Scores",
     "Top Players", "Projections vs Actual"])

with tab1:
    # ── Individual manager trend ───────────────────────────────────────────────
    st.subheader("Individual Manager Trend")

    weekly_avg = df.groupby("week")["score"].mean()
    weekly_med = df.groupby("week")["score"].median()
    all_weeks = weekly_avg.index.values.astype(float)

    LEAGUE_MEDIAN = "— League Median —"
    mgr_to_team = {manager_map.get(tid_by_name.get(t), t): t for t in teams}
    dropdown_options = [LEAGUE_MEDIAN] + sorted(mgr_to_team.keys())
    selected_mgr = st.selectbox("Select manager", dropdown_options, key="indiv_mgr")

    is_median = selected_mgr == LEAGUE_MEDIAN
    if is_median:
        weeks = all_weeks
        scores = weekly_med.values.astype(float)
        line_color = series_colours()[6]
        display_name = "League Median"
    else:
        selected_team = mgr_to_team[selected_mgr]
        tdf = df[df["team_name"] == selected_team].sort_values("week")
        weeks = tdf["week"].values.astype(float)
        scores = tdf["score"].values.astype(float)
        line_color = series_colours()[0]
        display_name = selected_mgr

    fig3 = go.Figure()

    fig3.add_trace(go.Scatter(
        x=weeks, y=scores, mode="lines+markers",
        name=display_name, line=dict(color=line_color, width=2),
        hovertemplate="Week %{x:.0f}: %{y:.2f} pts<extra></extra>",
    ))
    if not is_median:
        fig3.add_trace(go.Scatter(
            x=all_weeks, y=weekly_avg.values, mode="lines",
            name="League Average", line=dict(dash="dot", color="lightgray", width=1.5),
        ))

    max_week = int(weeks[-1]) if len(weeks) > 0 else int(all_weeks[-1])
    played_weeks = all_weeks[all_weeks <= max_week]

    m_full = m_l5 = None

    # Season-long trendline
    if len(weeks) >= 2:
        m_full, b_full = np.polyfit(weeks, scores, 1)
        fig3.add_trace(go.Scatter(
            x=played_weeks, y=m_full * played_weeks + b_full, mode="lines",
            name="Season trend", line=dict(color=line_color, dash="dash", width=1.5),
        ))

    # Last-5 trendline — only shown from week 6 onward
    if len(weeks) >= 6:
        last5_weeks = weeks[-5:]
        last5_scores = scores[-5:]
        m_l5, b_l5 = np.polyfit(last5_weeks, last5_scores, 1)
        fig3.add_trace(go.Scatter(
            x=last5_weeks, y=m_l5 * last5_weeks + b_l5, mode="lines",
            name="Last 5 trend", line=dict(color=series_colours()[1], dash="dash", width=2),
        ))

    fig3.update_layout(
        height=420, xaxis_title="Week", yaxis_title="Points",
        hovermode="x unified", xaxis=dict(dtick=1, range=[0.5, max_week + 0.5]),
        title=f"{display_name} — Weekly Scoring with Trendlines",
    )
    st.plotly_chart(fig3, width="stretch")

    # Slope metrics below the chart
    if m_full is not None or m_l5 is not None:
        mcols = st.columns(2)
        if m_full is not None:
            mcols[0].metric("Season trend", f"{m_full:+.1f} pts/wk", delta=f"{m_full:.1f}")
        if m_l5 is not None:
            mcols[1].metric("Last 5 trend", f"{m_l5:+.1f} pts/wk", delta=f"{m_l5:.1f}")

    st.divider()

    # ── All teams chart ────────────────────────────────────────────────────────
    st.subheader("Weekly Scoring Trends — All Teams")
    # Managers rather than team names, like the legend: ten long team names
    # filled a phone screen before the chart began.
    picked = st.multiselect("Filter managers", sorted(mgr_to_team), default=sorted(mgr_to_team))
    selected = [mgr_to_team[m] for m in picked]
    filtered = df[df["team_name"].isin(selected)]

    fig = go.Figure()
    for team in selected:
        tdf = filtered[filtered["team_name"] == team].sort_values("week")
        lbl = label_for(team)
        fig.add_trace(go.Scatter(
            x=tdf["week"], y=tdf["score"], mode="lines+markers",
            name=lbl, hovertemplate="Week %{x}: %{y:.2f} pts<extra>" + lbl + "</extra>",
        ))
    weekly_med = df.groupby("week")["score"].median()
    fig.add_trace(go.Scatter(
        x=weekly_med.index, y=weekly_med.values, mode="lines",
        name="League Median", line=dict(dash="dash", color="gray", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=weekly_avg.index, y=weekly_avg.values, mode="lines",
        name="League Average", line=dict(dash="dot", color="lightgray", width=2),
    ))
    fig.update_layout(height=480, xaxis_title="Week", yaxis_title="Points",
                      hovermode="x unified", xaxis=dict(dtick=1))
    st.plotly_chart(fig, width="stretch")

    weekly_stats = df.groupby("week")["score"].agg(["min", "max", "mean", "median"]).reset_index()
    fig2 = go.Figure([
        go.Scatter(x=weekly_stats["week"], y=weekly_stats["max"], mode="lines",
                   line=dict(color="rgba(0,150,0,0.3)"), name="High", fill=None),
        go.Scatter(x=weekly_stats["week"], y=weekly_stats["min"], mode="lines",
                   line=dict(color="rgba(150,0,0,0.3)"), name="Low",
                   fill="tonexty", fillcolor="rgba(200,200,200,0.2)"),
        go.Scatter(x=weekly_stats["week"], y=weekly_stats["mean"], mode="lines",
                   line=dict(color=series_colours()[0], width=2), name="Avg"),
    ])
    fig2.update_layout(title="Weekly Score Range (band = low to high)", height=300,
                       xaxis_title="Week", yaxis_title="Points", xaxis=dict(dtick=1))
    st.plotly_chart(fig2, width="stretch")

with tab2:
    st.subheader("Score Distributions")
    col1, col2 = st.columns(2)

    with col1:
        df_box = df.copy()
        df_box["label"] = chart_label(df_box, manager_map)
        fig = px.box(df_box, x="label", y="score", color="label",
                     title="Score Distribution by Team",
                     labels={"label": "Team", "score": "Points"})
        fig.update_layout(xaxis_tickangle=-30, showlegend=False)
        st.plotly_chart(fig, width="stretch")

    with col2:
        fig = px.histogram(df, x="score", nbins=30, title="Overall Score Distribution",
                           labels={"score": "Points", "count": "Frequency"})
        mu, sigma = df["score"].mean(), df["score"].std()
        x_range = np.linspace(df["score"].min(), df["score"].max(), 100)
        from scipy.stats import norm
        y_norm = norm.pdf(x_range, mu, sigma) * len(df) * (df["score"].max() - df["score"].min()) / 30
        fig.add_trace(go.Scatter(x=x_range, y=y_norm, mode="lines", name="Normal fit",
                                 line=dict(color=RED, width=2)))
        st.plotly_chart(fig, width="stretch")

    # Per-team stats table, grouped by team_id too for the pictures
    team_stats = df.groupby(["team_id", "team_name"])["score"].agg(
        Mean="mean", Median="median", Std="std", Min="min", Max="max"
    ).round(2).reset_index()
    # Consistency: 1 is the steadiest week to week, so rank by the smallest
    # spread. It says nothing about scoring well, only about scoring alike.
    # One game has no spread, so Std is NaN until week 2; Int64 leaves it blank.
    team_stats["Consistency"] = team_stats["Std"].rank(method="min").astype("Int64")
    team_stats = team_stats.sort_values("Mean", ascending=False)
    rows = [[who_html(r.team_id, r.team_name)]
            + [f"{getattr(r, c):.2f}" if pd.notna(getattr(r, c)) else "—"
               for c in ("Mean", "Median", "Min", "Max", "Std")]
            + [str(r.Consistency) if pd.notna(r.Consistency) else "—"]
            for r in team_stats.itertuples()]
    html_table([("Manager" if show_mgr else "Team", ""), ("Mean", "num"), ("Median", "num"),
                ("Min", "num"), ("Max", "num"), ("Std Dev", "num"), ("Consistency", "mid")], rows)
    st.caption("Consistency ranks by standard deviation: 1 is the most "
               "predictable week to week, not the highest scoring.")

with tab3:
    st.subheader("Season Records")

    from config import season_config
    cfg = season_config(season)

    # Tag each row so users know whether a score came from a regular season or playoff week
    def week_label(row):
        if row["week"] > cfg["reg_season_end"]:
            return f"Wk {row['week']} (playoffs)"
        return f"Wk {row['week']}"

    df_tagged = df.copy()
    df_tagged["week_label"] = df_tagged.apply(week_label, axis=1)

    col1, col2 = st.columns(2)

    def score_table(scores):
        """Single scores: who, the week, the score, the opponent and the result."""
        rows = []
        for r in scores.itertuples():
            opp = manager_map.get(r.opp_id, r.opp_name) if show_mgr else r.opp_name
            rows.append([who_html(r.team_id, r.team_name), esc(r.week_label),
                         f"<b>{r.score:.2f}</b>", esc(opp), f"{r.opp_score:.2f}",
                         result_badge(r.outcome)])
        html_table([("Manager" if show_mgr else "Team", ""), ("Week", ""), ("Score", "num"),
                    ("Opponent", ""), ("Opp", "num"), ("", "mid")], rows, compact=True)

    with col1:
        st.markdown("#### Top 5 individual scores")
        score_table(df_tagged.nlargest(5, "score"))

    with col2:
        st.markdown("#### 5 lowest individual scores")
        score_table(df_tagged.nsmallest(5, "score"))

    st.markdown("#### Top 5 highest-scoring matchups")
    # Build a canonical pair key (lower team_id first) so each matchup only appears once
    df_tagged["pair_key"] = df_tagged.apply(
        lambda r: (min(r["team_id"], r["opp_id"]), max(r["team_id"], r["opp_id"])), axis=1
    )
    df_tagged["matchup_total"] = df_tagged["score"] + df_tagged["opp_score"]
    top_matchups = (
        df_tagged.sort_values("matchup_total", ascending=False)
        .drop_duplicates(subset=["week", "pair_key"])
        .head(5)
        .copy()
    )
    rows = [[rank_cell(i + 1), who_html(r.team_id, r.team_name), f"{r.score:.2f}",
             f"{r.opp_score:.2f}", who_html(r.opp_id, r.opp_name), esc(r.week_label),
             f"<b>{r.matchup_total:.2f}</b>"]
            for i, r in enumerate(top_matchups.itertuples())]
    html_table([("#", ""), ("Team", ""), ("Score", "num"), ("Opp", "num"), ("Opponent", ""),
                ("Week", ""), ("Total", "num")], rows)

with tab4:
    st.subheader("Season H2H Record Matrix")
    st.caption("Each cell shows the **row** manager's W-L record against the **column** manager.")
    mgr_labels = [manager_map.get(tid_by_name.get(t), t) for t in teams]
    matrix = pd.DataFrame(index=mgr_labels, columns=mgr_labels, data="-")
    matrix.index.name = "↓ row vs col →"
    for team, lbl in zip(teams, mgr_labels):
        for opp, opp_lbl in zip(teams, mgr_labels):
            if team == opp:
                continue
            rows = df[(df["team_name"] == team) & (df["opp_name"] == opp)]
            if not rows.empty:
                w = (rows["outcome"] == "W").sum()
                l = (rows["outcome"] == "L").sum()
                matrix.loc[lbl, opp_lbl] = f"{w}-{l}"
    # Tinted by who leads the series: green for the row manager, red against.
    grid = pd.DataFrame({"Manager": list(matrix.index)})
    classes = pd.DataFrame({"Manager": [""] * len(matrix)})
    for c in matrix.columns:
        grid[c] = list(matrix[c])
        tints = []
        for row_lbl, v in zip(matrix.index, matrix[c]):
            if row_lbl == c:
                tints.append("wa-self")
            elif isinstance(v, str) and "-" in v and v != "-":
                w, l = (int(x) for x in v.split("-"))
                tints.append("wa-w" if w > l else ("wa-l" if l > w else "wa-t"))
            else:
                tints.append("")
        classes[c] = tints
    grid_pics = [team_image(season, tid_by_name.get(t), manager_map.get(tid_by_name.get(t), "?"))
                 for t in teams]
    frame(grid, pics=grid_pics, mid=list(matrix.columns), classes=classes, compact=True)


# ── Player-level tabs, from the box scores ────────────────────────────────────
@st.cache_data(ttl=300)
def load_box(season):
    return get_boxscores_df(season)


box_df = load_box(season)


def team_frame(df, columns, **kw):
    """A table led by each team's picture and name, in df's order."""
    names, subs, pics = who_columns(df, manager_map, season, show_mgr, show_team)
    out = pd.DataFrame({"Manager" if show_mgr else "Team": names})
    for head, values in columns.items():
        out[head] = list(values)
    frame(out, pics=pics, subs=subs, **kw)


with tab_top:
    st.subheader("Top Scoring Players")
    if season < 2018:
        st.info(f"Player data for {season} may not be 100% accurate. But I'm still counting it against you.")
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

        rows = []
        for i, r in enumerate(top.itertuples()):
            player = (f'<div class="wa-who">{player_pic(r.player_id, r.pro_team)}'
                      f'<span class="wa-name">{esc(player_label(r._asdict()))}</span></div>')
            rows.append([rank_cell(i + 1), esc(str(r.position)), player,
                         esc(manager_chain(r.player_id)), f"<b>{r.total_points:,.1f}</b>",
                         f"{r.avg_points:.1f}", str(r.weeks_played)])
        html_table([("#", ""), ("Pos", ""), ("Player", ""), ("Manager", ""), ("Total", "num"),
                    ("Avg", "num"), ("Weeks", "mid")], rows, compact=True, scroll=len(rows) > 15)

with tab_proj:
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
        team_frame(proj_df, {
            "Avg Proj": proj_df["avg_projected"], "Times Beat Proj": proj_df["times_beat_proj"],
            "Beat Proj %": proj_df["beat_proj_pct"],
        }, num=("Avg Proj", "Times Beat Proj", "Beat Proj %"),
            fmt={"Avg Proj": "{:.1f}", "Beat Proj %": "{:.1f}%"})

        proj_df["label"] = chart_label(proj_df, manager_map)
        fig = px.bar(proj_df.sort_values("avg_proj_diff"), x="avg_proj_diff", y="label",
                     orientation="h", title="Average Points Above/Below ESPN Projection",
                     labels={"avg_proj_diff": "Avg Diff (Actual − Projected)", "label": ""},
                     color="avg_proj_diff", color_continuous_scale=DIVERGING,
                     color_continuous_midpoint=0)
        fig.add_vline(x=0, line_dash="dash", line_color="gray")
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")
