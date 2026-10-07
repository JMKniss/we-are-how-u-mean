"""
Playoffs — the bracket, and the odds of reaching it.

One page rather than two, because the two halves are complementary in time
rather than alternatives: projections matter while the regular season is
running and are moot afterwards, and the bracket does not exist until the
playoffs start. Keeping them apart meant one of the two pages was always the
wrong one to be looking at.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from data import archive
from data.espn_client import (get_current_week, get_matchups_df, get_manager_map,
                              get_schedule_df, get_rosters_df, get_boxscores_df)
from analysis.standings import h2h_standings, combined_standings
from analysis.efficiency import lineup_efficiency, season_slot_requirements
from analysis.projections import (fixtures, simulate_team_model, simulate_player_model,
                                  odds_by_week, fit_player_spread, fit_injury_rates,
                                  team_efficiency, magic_numbers, PRIOR_GAMES)
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import (season_selector, require_data, sidebar_display_prefs,
                           chart_label, name_lines, who_columns)
from branding import page_icon
from style import (RED, badge, esc, frame, html_table, page_header, series_colours, team_image,
                   who_cell)

# The player model is ~20x the work of the team model per simulation; past
# 5,000 its odds move by tenths of a percent and the page waits seconds.
PLAYER_SIMS_CAP = 5000

st.set_page_config(page_title="Playoffs", page_icon=page_icon(), layout="wide")
page_header("Playoffs")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()


@st.cache_data(ttl=300)
def load(s):
    return get_matchups_df(s), get_manager_map(s), get_current_week(s)


with st.spinner("Loading..."):
    matchups_df, manager_map, current_week = load(season)

require_data(matchups_df, season, "matchup data")

cfg = season_config(season)
pw = cfg["playoff_weeks"]
reg_end = cfg["reg_season_end"]
# Last week the archive holds. Gating the bracket on ESPN's open scoring
# period instead would let a round look playable a week before it is.
current_week = min(current_week, cfg["total_weeks"])

# team_name → team_id lookup for tables without team_id
tid_by_name = matchups_df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]
NAME_HEAD = "Manager" if show_mgr else "Team"


def team_frame(df, columns, **kw):
    """A table led by each team's picture and name, in df's order."""
    names, subs, pics = who_columns(df, manager_map, season, show_mgr, show_team)
    out = pd.DataFrame({NAME_HEAD: names})
    for head, values in columns.items():
        out[head] = list(values)
    frame(out, pics=pics, subs=subs, **kw)


def render_bracket():
    # ── Regular season still in progress ─────────────────────────────────────────
    if current_week <= reg_end:
        st.info(
            f"The regular season is underway. "
            f"Playoff data for {season} will become available during playoffs. Obviously."
        )
        return

    # ── Split data ────────────────────────────────────────────────────────────────
    reg_df = matchups_df[matchups_df["week"] <= reg_end]
    playoff_df = matchups_df[matchups_df["is_playoff"]].copy()

    # ── Seedings from regular season standings ────────────────────────────────────
    # 2025+: official seeding uses combined (H2H + median) standings
    standings = (combined_standings(reg_df) if season >= 2025 else h2h_standings(reg_df)).reset_index(drop=True)
    standings.insert(0, "seed", range(1, len(standings) + 1))
    seed_map = dict(zip(standings["team_id"], standings["seed"]))
    name_map = dict(zip(standings["team_id"], standings["team_name"]))


    # Bottom 2 seeds = sacko bowl; top 8 = championship/consolation bracket
    sacko_ids = set(standings.tail(2)["team_id"].tolist())
    bracket_seeds = [tid for tid in standings["team_id"] if tid not in sacko_ids]


    def week_score(team_id, week):
        r = playoff_df[(playoff_df["team_id"] == team_id) & (playoff_df["week"] == week)]
        return float(r["score"].values[0]) if not r.empty else None


    # ── Detect playoff format ─────────────────────────────────────────────────────
    # 3-week format (2022): R1 = pw[0] only (1 week), Finals = pw[1]+pw[2]
    # 4-week format (all others): R1 = pw[0]+pw[1], R2 = pw[2]+pw[3]
    three_week = len(pw) == 3

    pw0_opp = {r.team_id: r.opp_id for r in playoff_df[playoff_df["week"] == pw[0]].itertuples()}
    pw1_opp = (
        {r.team_id: r.opp_id for r in playoff_df[playoff_df["week"] == pw[1]].itertuples()}
        if current_week >= pw[1] else {}
    )
    bracket_set = set(bracket_seeds)
    # Standard format only applies to 4-week seasons where R1 spans the same pairs both weeks
    standard_format = (not three_week) and bool(pw1_opp) and all(
        pw0_opp.get(t) == pw1_opp.get(t) for t in bracket_seeds if t in pw0_opp
    )


    # ── Round 1 pairs ─────────────────────────────────────────────────────────────
    def _pairs_from_espn(opp_lookup):
        seen, pairs = set(), []
        for tid in bracket_seeds:
            if tid in seen:
                continue
            opp = opp_lookup.get(tid)
            if opp and opp in bracket_set and opp not in seen:
                pairs.append((tid, opp))
                seen |= {tid, opp}
        return pairs


    if standard_format:
        r1_pairs = _pairs_from_espn(pw0_opp)
    else:
        b = bracket_seeds
        r1_pairs = (
            [(b[0], b[3]), (b[1], b[2]), (b[4], b[7]), (b[5], b[6])]
            if len(b) >= 8 else []
        )


    # ── Round 1 results ───────────────────────────────────────────────────────────
    def r1_cumulative(tid):
        if three_week:
            return week_score(tid, pw[0]) or 0.0
        return (week_score(tid, pw[0]) or 0.0) + (week_score(tid, pw[1]) or 0.0)


    r1_done_week = pw[0] if three_week else pw[1]
    r1_result_map = {}
    if current_week >= r1_done_week:
        for t1, t2 in r1_pairs:
            winner, loser = (t1, t2) if r1_cumulative(t1) >= r1_cumulative(t2) else (t2, t1)
            r1_result_map[(t1, t2)] = (winner, loser)


    def r1_winner_of(a, b):
        res = r1_result_map.get((a, b)) or r1_result_map.get((b, a))
        return res[0] if res else None


    def r1_loser_of(a, b):
        res = r1_result_map.get((a, b)) or r1_result_map.get((b, a))
        return res[1] if res else None


    # ── Round 2 pairs and week references ────────────────────────────────────────
    r2_start_week = pw[1] if three_week else pw[2]
    r1_display_weeks = [pw[0]] if three_week else [pw[0], pw[1]]
    r2_display_weeks = [pw[1], pw[2]] if three_week else [pw[2], pw[3]]
    r1_caption = f"Week {pw[0]}" if three_week else f"Weeks {pw[0]} + {pw[1]}"
    r2_caption = f"Weeks {pw[1]} + {pw[2]}" if three_week else f"Weeks {pw[2]} + {pw[3]}"

    r2_pairs = []
    if current_week >= r2_start_week:
        if standard_format:
            pw2_opp = {r.team_id: r.opp_id for r in playoff_df[playoff_df["week"] == pw[2]].itertuples()}
            r2_pairs = _pairs_from_espn(pw2_opp)
        else:
            champ_r1 = [(t1, t2) for t1, t2 in r1_pairs if seed_map.get(t1, 99) <= 4]
            consol_r1 = [(t1, t2) for t1, t2 in r1_pairs if seed_map.get(t1, 99) > 4]
            for group in [champ_r1, consol_r1]:
                if len(group) == 2 and all((t1, t2) in r1_result_map for t1, t2 in group):
                    w1, l1 = r1_result_map[group[0]]
                    w2, l2 = r1_result_map[group[1]]
                    r2_pairs += [(w1, w2), (l1, l2)]


    # ── Split into championship and consolation sub-brackets ──────────────────────
    def is_champ_match(t1, t2):
        return seed_map.get(t1, 99) <= 4 and seed_map.get(t2, 99) <= 4


    champ_r1_pairs = [(t1, t2) for t1, t2 in r1_pairs if is_champ_match(t1, t2)]
    consol_r1_pairs = [(t1, t2) for t1, t2 in r1_pairs if not is_champ_match(t1, t2)]
    champ_r2_pairs = [(t1, t2) for t1, t2 in r2_pairs if is_champ_match(t1, t2)]
    consol_r2_pairs = [(t1, t2) for t1, t2 in r2_pairs if not is_champ_match(t1, t2)]

    champ_r1_winners = {r1_winner_of(t1, t2) for t1, t2 in champ_r1_pairs} - {None}
    consol_r1_winners = {r1_winner_of(t1, t2) for t1, t2 in consol_r1_pairs} - {None}


    def r2_label(t1, t2):
        if is_champ_match(t1, t2):
            return "Championship Game" if t1 in champ_r1_winners and t2 in champ_r1_winners else "3rd Place"
        else:
            return "5th Place Game" if t1 in consol_r1_winners and t2 in consol_r1_winners else "7th Place"


    # ── Matchup display helper ────────────────────────────────────────────────────
    def show_match(t1, t2, weeks):
        scores_t1 = [week_score(t1, w) for w in weeks]
        scores_t2 = [week_score(t2, w) for w in weeks]
        total_t1 = sum(s for s in scores_t1 if s is not None)
        total_t2 = sum(s for s in scores_t2 if s is not None)
        all_done = all(s is not None for s in scores_t1 + scores_t2)
        t1_wins = total_t1 > total_t2 if all_done else None

        rows = []
        for tid, scrs, total, won in [
            (t1, scores_t1, total_t1, t1_wins),
            (t2, scores_t2, total_t2, (not t1_wins) if t1_wins is not None else None),
        ]:
            mgr = manager_map.get(tid, "?")
            result = ("W" if won else "L") if all_done else ""
            # The winner's row in bold, the result as a W/L box.
            strong = "wa-strong" if won else ""
            rows.append(
                [f'<span class="wa-rank">{seed_map.get(tid, "?")}</span>',
                 (who_cell(team_image(season, tid, mgr),
                           *name_lines(mgr, name_map.get(tid, str(tid)), show_mgr, show_team)), strong)]
                + [f"{x:.2f}" if x is not None else "—" for x in scrs]
                + [(f"{total:.2f}", strong),
                   f'<span class="wa-dot {result}">{result}</span>' if result else ""])
        html_table([("Seed", ""), (NAME_HEAD, "")] + [(f"Wk {w}", "num") for w in weeks]
                   + [("Total", "num"), ("", "mid")], rows, compact=True)


    # ── Regular season seedings table ─────────────────────────────────────────────
    st.subheader(f"{season} Regular Season Final Standings")
    w_col, l_col = ("total_wins", "total_losses") if season >= 2025 else ("wins", "losses")
    team_frame(standings, {"W": standings[w_col].astype(int), "L": standings[l_col].astype(int),
                           "PF": standings["points_for"]},
               rank=True, cut_after=4, mid=("W", "L"), num=("PF",))

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────────
    tab_champ, tab_consol, tab_sacko = st.tabs([
        ":material/trophy: Championship (Seeds 1–4)",
        ":material/military_tech: Consolation (Seeds 5–8)",
        "🚽 Sacko Bowl (Seeds 9–10)",
    ])

    with tab_champ:
        st.caption(f"Round 1: {r1_caption}  ·  Round 2: {r2_caption}")

        if not champ_r1_pairs:
            st.info("Championship bracket not yet determined.")
        else:
            st.markdown(f"#### Round 1 · {r1_caption}")
            cols = st.columns(len(champ_r1_pairs))
            for i, (t1, t2) in enumerate(champ_r1_pairs):
                with cols[i]:
                    show_match(t1, t2, r1_display_weeks)

            if champ_r2_pairs:
                st.markdown(f"#### Round 2 · {r2_caption}")
                cols = st.columns(len(champ_r2_pairs))
                ordered = sorted(
                    champ_r2_pairs,
                    key=lambda p: (0 if (p[0] in champ_r1_winners and p[1] in champ_r1_winners) else 1)
                )
                for i, (t1, t2) in enumerate(ordered):
                    with cols[i]:
                        st.caption(f"**{r2_label(t1, t2)}**")
                        show_match(t1, t2, r2_display_weeks)
            elif current_week < r2_start_week:
                st.info(f"Round 2 begins Week {r2_start_week}.")

    with tab_consol:
        st.caption(f"Round 1: {r1_caption}  ·  Round 2: {r2_caption}")

        if not consol_r1_pairs:
            st.info("Consolation bracket not yet determined.")
        else:
            st.markdown(f"#### Round 1 · {r1_caption}")
            cols = st.columns(len(consol_r1_pairs))
            for i, (t1, t2) in enumerate(consol_r1_pairs):
                with cols[i]:
                    show_match(t1, t2, r1_display_weeks)

            if consol_r2_pairs:
                st.markdown(f"#### Round 2 · {r2_caption}")
                cols = st.columns(len(consol_r2_pairs))
                ordered = sorted(
                    consol_r2_pairs,
                    key=lambda p: (0 if (p[0] in consol_r1_winners and p[1] in consol_r1_winners) else 1)
                )
                for i, (t1, t2) in enumerate(ordered):
                    with cols[i]:
                        st.caption(f"**{r2_label(t1, t2)}**")
                        show_match(t1, t2, r2_display_weeks)
            elif current_week < r2_start_week:
                st.info(f"Round 2 begins Week {r2_start_week}.")

    with tab_sacko:
        sacko_list = sorted(sacko_ids, key=lambda t: seed_map.get(t, 99))
        if len(sacko_list) < 2:
            st.info("Sacko bowl teams not yet determined.")
        else:
            t1, t2 = sacko_list[0], sacko_list[1]
            sacko_week_count = len(pw)
            st.caption(
                f"#{seed_map.get(t1)} Seed vs #{seed_map.get(t2)} Seed  ·  "
                f"Weeks {pw[0]}–{pw[-1]}  ·  {sacko_week_count}-week cumulative  ·  "
                f"Lowest total = 🚽 Sacko"
            )
            show_match(t1, t2, pw)


@st.cache_data(ttl=300)
def team_odds(s, spots, n):
    m = get_matchups_df(s)
    reg_end = season_config(s)["reg_season_end"]
    fx = fixtures(m, get_schedule_df(s), reg_end)
    return simulate_team_model(m, fx, reg_end, median_game=s >= 2025,
                               playoff_spots=spots, n_simulations=n)


@st.cache_data(ttl=300)
def team_odds_by_week(s, spots):
    m = get_matchups_df(s)
    reg_end = season_config(s)["reg_season_end"]
    fx = fixtures(m, get_schedule_df(s), reg_end)
    return odds_by_week(m, fx, reg_end, median_game=s >= 2025, playoff_spots=spots)


@st.cache_data(ttl=3600)
def player_model_inputs():
    """Position spreads and injury rates, fitted on every archived season."""
    pw, gs, box = archive.get("player_weeks"), archive.get("game_status"), archive.get("boxscores")
    return fit_player_spread(pw, gs), fit_injury_rates(box, gs)


@st.cache_data(ttl=300)
def player_odds(s, spots, n):
    rosters = get_rosters_df(s)
    m = get_matchups_df(s)
    reg_end = season_config(s)["reg_season_end"]
    if rosters.empty or m.empty or m["week"].max() >= reg_end:
        return None
    box = get_boxscores_df(s)
    _, eff_weeks = lineup_efficiency(box)
    spread, injury = player_model_inputs()
    fx = fixtures(m, get_schedule_df(s), reg_end)
    return simulate_player_model(
        m, fx, rosters, reg_end, median_game=s >= 2025,
        slot_counts=season_slot_requirements(box), spread=spread, injury=injury,
        efficiency=team_efficiency(eff_weeks), playoff_spots=spots, n_simulations=n)


def render_projections():
    reg_season_weeks = cfg["reg_season_end"]
    reg_df = matchups_df[matchups_df["week"] <= reg_season_weeks]
    weeks_played = reg_df["week"].nunique()
    weeks_remaining = max(0, reg_season_weeks - weeks_played)
    median_game = season >= 2025

    col1, col2, col3 = st.columns(3)
    col1.metric("Regular Season Weeks", reg_season_weeks)
    col2.metric("Weeks Played", weeks_played)
    col3.metric("Weeks Remaining", weeks_remaining)

    n_sims = st.sidebar.slider("Simulations", 1000, 50000, 10000, 1000)
    playoff_spots = st.sidebar.slider("Playoff spots", 2, 6, 4)
    player_sims = min(n_sims, PLAYER_SIMS_CAP)

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["Playoff Odds", "Odds by Week",
                                      "Score Distribution", "Magic Numbers"])

    with st.spinner("Simulating..."):
        team_df = team_odds(season, playoff_spots, n_sims)
        player_df = player_odds(season, playoff_spots, player_sims)

    with tab1:
        st.subheader("Monte Carlo Playoff Simulation")
        if weeks_remaining == 0:
            st.info("Regular season is complete. Showing the final playoff picture.")
        st.caption(
            f"Each model plays out the remaining schedule {n_sims:,} times"
            + (f" (the player model {player_sims:,})"
               if player_df is not None and player_sims < n_sims else "")
            + ". **Team model**: each team's weekly scores so far, pulled toward "
            "the league average, because a few weeks of scores say less about a "
            "team than they seem to. **Player model**: the current rosters, week "
            "by week: ESPN's player projections, NFL byes, injuries, the best "
            "lineup each team can field, and how close its manager usually gets "
            "to that lineup."
            + (" Median wins count, as they do in the standings." if median_game else "")
        )

        odds = team_df.drop(columns="seed_dist").rename(columns={
            "playoff_pct": "team_pct", "exp_wins": "team_exp_wins", "first_pct": "team_first"})
        if player_df is not None:
            odds = odds.merge(player_df[["team_id", "playoff_pct", "exp_wins", "first_pct"]]
                              .rename(columns={"playoff_pct": "player_pct",
                                               "exp_wins": "player_exp_wins",
                                               "first_pct": "player_first"}),
                              on="team_id")
            odds["blend_pct"] = ((odds["team_pct"] + odds["player_pct"]) / 2).round(1)
            odds = odds.sort_values("blend_pct", ascending=False).reset_index(drop=True)
            cols = ["team_name", "current_wins", "current_losses", "team_pct",
                    "player_pct", "blend_pct", "player_exp_wins", "player_first"]
            headers = ["Team", "W", "L", "Team Model %", "Player Model %",
                       "Average %", "Proj. Wins", "#1 Seed %"]
        else:
            cols = ["team_name", "current_wins", "current_losses", "team_pct",
                    "team_exp_wins", "team_first"]
            headers = ["Team", "W", "L", "Playoff Odds %", "Proj. Wins", "#1 Seed %"]
            if weeks_remaining:
                st.caption("The player model needs this season's roster snapshot, "
                           "which the weekly update captures.")
        pct = {"team_pct", "player_pct", "blend_pct", "player_first", "team_first"}
        team_frame(odds, {h: odds[c] for c, h in zip(cols[1:], headers[1:])}, rank=True,
                   cut_after=playoff_spots,
                   mid=("W", "L"), num=[h for c, h in zip(cols[1:], headers[1:]) if c not in
                                         ("current_wins", "current_losses")],
                   fmt={h: ("{:.1f}%" if c in pct else "{:.1f}") for c, h in zip(cols[1:], headers[1:])
                        if c not in ("current_wins", "current_losses")})
        if player_df is not None:
            st.caption("Proj. Wins and #1 Seed % are from the player model"
                       + (" and count median wins." if median_game else "."))

        odds["label"] = chart_label(odds, manager_map, show_mgr, show_team)
        fig = go.Figure()
        fig.add_bar(x=odds["label"], y=odds["team_pct"], name="Team model",
                    marker_color=series_colours()[0], text=[f"{p:.0f}%" for p in odds["team_pct"]],
                    textposition="outside")
        if player_df is not None:
            fig.add_bar(x=odds["label"], y=odds["player_pct"], name="Player model",
                        marker_color=series_colours()[1], text=[f"{p:.0f}%" for p in odds["player_pct"]],
                        textposition="outside")
        fig.update_layout(title="Playoff Probability by Team", barmode="group",
                          xaxis_tickangle=-30, yaxis_title="Playoff Probability %",
                          yaxis_range=[0, 110], legend_title_text="")
        st.plotly_chart(fig, width="stretch")

        st.markdown("#### Where each team finishes")
        seed_src = player_df if player_df is not None else team_df
        st.caption("Probability of each final seed"
                   + (", player model." if player_df is not None else "."))
        seed_mat = np.vstack(seed_src["seed_dist"].values) * 100
        fig = go.Figure(go.Heatmap(
            z=seed_mat, x=list(range(1, seed_mat.shape[1] + 1)),
            y=chart_label(seed_src, manager_map, show_mgr, show_team),
            # Transparent to red, so an unlikely seed is the page itself in
            # either theme rather than a white tile on the dark one.
            colorscale=[[0, "rgba(213,10,10,0)"], [1, RED]], zmin=0, zmax=100, showscale=False,
            text=[[f"{v:.0f}" if v >= 0.5 else "" for v in row] for row in seed_mat],
            texttemplate="%{text}",
            hovertemplate="%{y}<br>Seed %{x}: %{z:.1f}%<extra></extra>",
        ))
        fig.add_vline(x=playoff_spots + 0.5, line_dash="dash", line_color="gray")
        fig.update_layout(yaxis_autorange="reversed", xaxis_title="Final seed",
                          xaxis_dtick=1, xaxis_side="top", margin=dict(t=40, b=10),
                          height=80 + 36 * len(seed_src))
        st.plotly_chart(fig, width="stretch")

    with tab2:
        st.subheader("Playoff Odds After Each Week")
        st.caption("Team model, re-run as the season stood after each week. "
                   "Week 0 is before a game was played, when only the schedule "
                   "separates the teams.")
        with st.spinner("Replaying the season..."):
            trend = team_odds_by_week(season, playoff_spots)
        trend["label"] = chart_label(trend, manager_map, show_mgr, show_team)
        fig = px.line(trend, x="after_week", y="playoff_pct", color="label", markers=True,
                      labels={"after_week": "After week", "playoff_pct": "Playoff odds %",
                              "label": ""})
        fig.update_layout(yaxis_range=[-2, 102], xaxis_dtick=1)
        st.plotly_chart(fig, width="stretch")

    with tab3:
        st.subheader("Scoring Distribution by Team")
        st.caption("Scores from games played so far. Team Model Avg is the "
                   "average the team model plays with: the team's own, pulled "
                   f"toward the league's as if that were {PRIOR_GAMES} extra games."
                   + (" Player Model Avg is the player model's average simulated "
                      "score over the remaining weeks, byes and injuries included."
                      if player_df is not None else ""))

        stats = reg_df.groupby(["team_id", "team_name"])["score"].agg(
            ["mean", "std", "min", "max", "count"]).reset_index()
        stats = stats.merge(team_df[["team_id", "proj_mean"]], on="team_id")
        cols = ["team_name", "mean", "std", "min", "max", "count", "proj_mean"]
        headers = ["Team", "Mean", "Std Dev", "Min", "Max", "Games", "Team Model Avg"]
        if player_df is not None:
            stats = stats.merge(player_df[["team_id", "proj_mean"]]
                                .rename(columns={"proj_mean": "player_mean"}), on="team_id")
            cols.append("player_mean")
            headers.append("Player Model Avg")
        stats = stats.sort_values("mean", ascending=False).round(2)
        team_frame(stats, {h: stats[c] for c, h in zip(cols[1:], headers[1:])},
                   num=[h for h in headers[1:] if h != "Games"], mid=("Games",),
                   fmt={h: "{:.2f}" for h in headers[1:] if h != "Games"})

        stats["label"] = chart_label(stats, manager_map, show_mgr, show_team)
        fig = px.scatter(stats, x="mean", y="std", text="label", size="count",
                         title="Mean Score vs Consistency (lower Std Dev = more consistent)",
                         labels={"mean": "Average Score", "std": "Std Deviation (consistency)"})
        fig.update_traces(textposition="top center")
        st.plotly_chart(fig, width="stretch")

    with tab4:
        st.subheader("Magic Numbers")
        if weeks_remaining == 0:
            st.info("Regular season complete.")
            return

        if median_game:
            standings = combined_standings(reg_df)
            wins_col, losses_col, per_week = "total_wins", "total_losses", 2
        else:
            standings = h2h_standings(reg_df)
            wins_col, losses_col, per_week = "wins", "losses", 1
        games_left = weeks_remaining * per_week
        magic = magic_numbers(standings, wins_col, losses_col, games_left, playoff_spots)

        st.caption(
            f"**Magic #**: wins by this team, or losses by the rival that matters, "
            f"that guarantee a top-{playoff_spots} finish whatever else happens. "
            f"**Elimination #**: this team's losses, or that rival's wins, that "
            f"knock it out. Each team has {games_left} "
            f"{'results (H2H + median)' if median_game else 'games'} left. Both "
            f"assume the points-for tiebreak goes against you, and neither knows "
            f"that rivals still have to play each other, so a team can be safe "
            f"a week before its number reaches zero. The simulation accounts for that."
        )
        status_html = {"Clinched": badge("clinched", "Clinched"),
                       "Eliminated": badge("eliminated", "Eliminated")}
        names, subs, pics = who_columns(magic, manager_map, season, show_mgr, show_team)
        rows = [[who_cell(p_, n_, s_), str(int(r[wins_col])), str(int(r[losses_col])),
                 f"<b>{r['magic_number']}</b>", str(r["elim_number"]),
                 status_html.get(r["status"], esc(r["status"]))]
                for (_, r), n_, s_, p_ in zip(magic.iterrows(), names, subs, pics)]
        html_table([(NAME_HEAD, ""), ("W", "mid"), ("L", "mid"), ("Magic #", "mid"),
                    ("Elimination #", "mid"), ("Status", "")], rows)

        clinched = magic[magic["status"] == "Clinched"]["team_name"].tolist()
        elim = magic[magic["status"] == "Eliminated"]["team_name"].tolist()
        if clinched:
            st.success(f"Playoff spot clinched: {', '.join(clinched)}")
        if elim:
            st.error(f"Eliminated from playoffs: {', '.join(elim)}")
        if not clinched and not elim:
            st.caption("Nobody has clinched or been eliminated yet.")


tab_bracket, tab_projections = st.tabs(["Bracket", "Projections"])
with tab_bracket:
    render_bracket()
with tab_projections:
    render_projections()
