"""
Standings: the season's table, and how much of it was luck.

Regular season only throughout; the playoffs are the Playoffs page's. Four
tabs:

Standings - the table, with H2H, median and Vs All records. From 2025 it is
ordered by combined (H2H + median) wins, the official format; before that by
H2H, since median games did not count and ordering on them would rewrite
history. Below it, each manager's weekly scoring rank.

Strength of Schedule - how much opponents scored against each team, how that
compares with what they scored against everyone else, and the swapped-schedule
matrix: every team's real scores played against every other team's schedule.

Luck - wins got minus wins the scores deserved, split into opponent,
schedule, field and median luck so the parts add up with nothing counted
twice (analysis/standings.py, luck_breakdown), with injury luck beside
them: the regular season's actual value lost to injury, in wins
(analysis/health.py, injury_luck), next to the total and never in it. Then
the chance of each week's result given only the score's rank, and how often
each rank met each.

Injury - the same question for injuries. A headline table, ranked by
the share of the team's actual value lost, with games lost and the share of
its draft capital lost beside it - each as points above replacement and as
a share, so one measurement priced two ways reads on one scale, and in the
points a manager thinks in - each team's record under its name as on
Draft Value, and its two biggest losses by draft capital; a separate playoff table for the four playoff teams once
the playoffs start, never folded into the regular season; a player-by-player
detail for one team; and Playoff vs Non-Playoff Teams, the average loss of
each group in the selected season, by the current top four while the
regular season is still being played. The measures, constants and
reasoning, and the What We Checked table that used to sit here, are in
analysis/health.py. 2016-2017 have no game status and no replacement level,
and say so.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
from data.espn_client import get_matchups_df, get_manager_map
from analysis.standings import (
    combined_standings,
    strength_of_schedule, alternate_schedule_standings,
    luck_breakdown, luck_total,
    opponent_vs_own_average,
    swapped_schedule_matrix
)
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import season_selector, require_data, sidebar_display_prefs, who_columns
from branding import page_icon
from analysis import health
from style import (esc, frame, html_table, page_header, player_pic, rank_cell,
                   team_image, who_cell)

st.set_page_config(page_title="Standings", page_icon=page_icon(), layout="wide")
page_header("Standings")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season), get_manager_map(season)

with st.spinner("Loading..."):
    matchups_df, manager_map = load(season)

require_data(matchups_df, season, "matchup data")

cfg = season_config(season)
matchups_df = matchups_df[matchups_df["week"] <= cfg["reg_season_end"]].copy()

# Starting in 2025, combined (H2H + vs median) is the official standings format
official_combined = season >= 2025


NAME_HEAD = "Manager" if show_mgr else "Team"


def pic(team_id):
    """One team's picture: this season's logo, or the manager's helmet."""
    return team_image(season, team_id, manager_map.get(team_id, "?"))


def team_table(df, columns, **kw):
    """A table led by each team's picture and name, in df's order."""
    names, subs, pics = who_columns(df, manager_map, season, show_mgr, show_team)
    out = pd.DataFrame({NAME_HEAD: names})
    for head, values in columns.items():
        out[head] = list(values)
    frame(out, pics=pics, subs=subs, **kw)


def _current_standings(df):
    """
    The standings, each win/loss pair as one record. The frame is already
    sorted, and the rows keep that order, so folding W and L together costs
    nothing.
    """
    def record(w, l):
        return w.astype(int).astype(str) + "-" + l.astype(int).astype(str)

    team_table(df, {
        "Total": record(df["total_wins"], df["total_losses"]),
        "H2H": record(df["wins"], df["losses"]),
        "Median": record(df["median_wins"], df["median_losses"]),
        "Vs All": df["_vs_all"],
        "PF": df["points_for"], "PA": df["points_against"], "Avg": df["avg_score"],
    }, rank=True, cut_after=4, mid=("Total", "H2H", "Median", "Vs All"), num=("PF", "PA", "Avg"))


@st.cache_data(ttl=300)
def load_injury_luck(season):
    return health.injury_luck(season)


tab1, tab4, tab5, tab6 = st.tabs(
    ["Standings", "Strength of Schedule", "Luck", "Injury"])

# ── Tab 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Standings")
    df = combined_standings(matchups_df)
    # Record if you had played every other team every week, folded in here so
    # the schedule-free view sits beside the schedule-bound ones.
    _alt = alternate_schedule_standings(matchups_df).set_index("team_id")
    df["_vs_all"] = [
        f"{int(_alt.loc[t, 'alt_wins'])}-"
        f"{int(_alt.loc[t, 'alt_games'] - _alt.loc[t, 'alt_wins'])}"
        if t in _alt.index else "—" for t in df["team_id"]]
    if official_combined:
        st.caption("Two games per week: one H2H matchup and one vs-median. "
                   "Sorted by total wins, which is the official standing from "
                   "2025. Vs All is the record if you had played every other "
                   "team every week, which removes the schedule entirely.")
    else:
        # Median wins were not official before 2025, so the order has to follow
        # head-to-head or the table would rewrite history. The median column is
        # still shown, since the games were played either way.
        df = df.sort_values(["wins", "points_for"], ascending=False)
        st.caption("Head-to-head decided the standings before 2025, so the order "
                   "follows H2H. Median and Vs All are shown for reference "
                   "only; Vs All is the record if you had played every other "
                   "team every week.")
    _current_standings(df)

    st.divider()
    st.subheader("Weekly Scoring Rank")
    st.caption(
        "Where each manager finished on the weekly scoreboard: 1 is the "
        "highest score that week, 10 the lowest. Ties share the better rank. "
        "Rows follow the standings order above."
    )
    rank_src = matchups_df.assign(
        rank=matchups_df.groupby("week")["score"]
        .rank(ascending=False, method="min").astype(int),
        Manager=matchups_df["team_id"].map(manager_map).fillna("?"),
    )
    rank_tbl = rank_src.pivot(index="Manager", columns="week", values="rank")
    rank_tbl.columns = [f"Wk {int(w)}" for w in rank_tbl.columns]
    # keep the row order the same as the standings table above
    order = [manager_map.get(t, "?") for t in df["team_id"]]
    rank_tbl = rank_tbl.reindex([m for m in order if m in rank_tbl.index])
    # average weekly finish, appended after the last week
    rank_tbl["Avg"] = rank_tbl.mean(axis=1).round(1)
    rank_tbl.index.name = ""

    # Result of each week's matchup, same shape, used only to colour the cells.
    outcome_tbl = (rank_src.pivot(index="Manager", columns="week",
                                  values="outcome")
                   .reindex(rank_tbl.index))
    outcome_tbl.columns = [f"Wk {int(w)}" for w in outcome_tbl.columns]
    outcome_tbl["Avg"] = None

    week_cols = [c for c in rank_tbl.columns if c != "Avg"]
    # The weekly grids follow the standings' rows, so their pictures do too.
    tid_by_mgr = {manager_map.get(t, "?"): t for t in df["team_id"]}
    grid_pics = [pic(tid_by_mgr.get(m)) for m in rank_tbl.index]
    # A translucent tint per week from its result, which reads on either
    # theme where the old pastel fills only worked on white.
    tint = {"W": "wa-w", "L": "wa-l", "T": "wa-t"}
    grid_classes = pd.DataFrame({c: [tint.get(o, "") for o in outcome_tbl[c]] for c in week_cols})

    def week_grid(tbl, cell_fmt, avg_fmt):
        g = pd.DataFrame({"Manager": list(tbl.index)})
        for c in tbl.columns:
            g[c] = list(tbl[c])
        frame(g, pics=grid_pics, mid=week_cols, num=("Avg",), classes=grid_classes, compact=True,
              fmt={**{c: cell_fmt for c in week_cols}, "Avg": avg_fmt})

    week_grid(rank_tbl, "{:.0f}", "{:.1f}")


# ── Tab 4: Strength of Schedule ───────────────────────────────────────────────
with tab4:
    st.subheader("Strength of Schedule")
    st.caption(
        "Avg Opp Score is how much opponents scored against you. "
        "Opp vs Own Avg compares that to what those same opponents managed "
        "against everyone else, excluding the game with you: positive means "
        "they raised their game against you, negative means they tended to "
        "have an off week."
    )
    df = strength_of_schedule(matchups_df)
    # Add team's own scoring stats to compare alongside opponent stats
    own = matchups_df.groupby(["team_id", "team_name"])["score"].agg(
        avg_score="mean", total_score="sum"
    ).reset_index()
    df = df.merge(own[["team_id", "avg_score", "total_score"]], on="team_id", how="left")
    df["opp_vs_own"] = df["team_id"].map(opponent_vs_own_average(matchups_df))
    team_table(df, {
        "Avg Opp Score": df["avg_opp_score"], "Avg Score": df["avg_score"],
        "Opp vs Own Avg": df["opp_vs_own"],
        "Total Opp Score": df["total_opp_score"], "Total Score": df["total_score"],
    }, num=("Avg Opp Score", "Avg Score", "Total Opp Score", "Total Score"),
        signed=("Opp vs Own Avg",),
        fmt={"Avg Opp Score": "{:.2f}", "Avg Score": "{:.2f}", "Opp vs Own Avg": "{:+.2f}",
             "Total Opp Score": "{:,.1f}", "Total Score": "{:,.1f}"})

    st.divider()
    weeks_played = matchups_df["week"].nunique()
    # ── Swapped schedules ─────────────────────────────────────────────────────
    st.subheader("If You Had Played Someone Else's Schedule")
    st.caption(
        "Each cell: H2H wins the **row** manager would have if they had played the "
        "**column** manager's schedule, using their own real weekly scores. "
        "The diagonal is their own schedule, so it equals their actual record. "
        f"Regular season only ({weeks_played} weeks)."
    )

    with st.spinner("Computing swapped schedules..."):
        mat = swapped_schedule_matrix(matchups_df)

    ts = mat.mean(axis=1)   # row average — how well this team does against any schedule
    ss = mat.mean(axis=0)   # column average — how generous this schedule is to anyone

    order = ts.sort_values(ascending=False).index.tolist()
    mat = mat.loc[order, order]
    names = {t: manager_map.get(t, "?") for t in order}

    # Values are formatted as text so integer wins and one-decimal averages can
    # share a column without pandas widening the wins to 9.0.
    rows = []
    for r in order:
        row = {"Manager": names[r]}
        for c in order:
            row[names[c]] = str(int(mat.loc[r, c]))
        row["TS"] = f"{ts[r]:.1f}"
        rows.append(row)
    ss_row = {"Manager": "SS"}
    for c in order:
        ss_row[names[c]] = f"{ss[c]:.1f}"
    ss_row["TS"] = ""
    rows.append(ss_row)

    swap = pd.DataFrame(rows)
    # Their own schedule on the diagonal, and the SS row set apart.
    classes = pd.DataFrame("", index=swap.index, columns=swap.columns)
    for i, r in enumerate(order):
        classes.loc[i, names[r]] = "wa-self wa-strong"
    classes.iloc[-1] = "wa-gold"
    frame(swap, mid=[c for c in swap.columns if c != "Manager"], classes=classes, compact=True,
          pics=[pic(t) for t in order] + [""])
    st.caption(
        "**TS** (Team Strength) = that team's average wins across all 10 schedules. "
        "**SS** (Schedule Strength) = average wins any team would get playing that "
        "schedule, so a **higher SS means an easier schedule**."
    )

# ── Tab 5: Luck Index ─────────────────────────────────────────────────────────
with tab5:
    st.subheader("Luck")
    st.caption("Luck is measured in difference in expected wins.")
    lb = luck_breakdown(matchups_df)
    lb.insert(0, "Manager", lb["team_id"].map(manager_map).fillna("?"))

    def small(cols, headers, sort_col):
        t = lb.sort_values(sort_col, ascending=False)
        out = t[["Manager"] + cols].copy()
        out.columns = ["Manager"] + headers
        lucky = [h for h in headers if h in ("Luck", "Points")]
        frame(out, pics=[pic(x) for x in t["team_id"]], compact=True,
              num=[h for h in headers if h not in lucky], signed=lucky,
              fmt={h: ("{:+.2f}" if h in lucky else "{:.2f}") for h in headers})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Schedule luck**")
        st.caption("Which opponents you drew, each taken at their usual level. "
                   "Positive means you drew opponents your scores beat more often "
                   "than they would have beaten the rest of the league.")
        small(["w_form", "w_field", "schedule_luck"],
              ["Schedule Wins", "Expected Wins", "Luck"],
              "schedule_luck")
    with c2:
        st.markdown("**Field luck**")
        st.caption("Your relative performance vs the league's relative performance. "
                   "A positive score means your best performances came when the rest "
                   "of the league scored below average. Negative means your good weeks "
                   "were overshadowed by other teams also doing well.")
        small(["w_field", "w_season", "field_luck"],
              ["Expected Wins", "vs Whole Season", "Luck"],
              "field_luck")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Median luck**")
        st.caption("Median wins you got compared with what your scores usually "
                   "get. Positive means you beat the median when the median was low.")
        small(["median_wins", "xmedian", "median_luck"],
              ["Median Wins", "Expected Wins", "Luck"],
              "median_luck")
    with c4:
        st.markdown("**Opponent form**")
        st.caption("Whether your opponents played above or below their own "
                   "average when they faced you.")
        small(["opp_luck", "opp_form_pts"], ["Luck", "Points"],
              "opp_luck")

    injury = None
    if health.supported(season):
        il = load_injury_luck(season).sort_values("injury_luck", ascending=False)
        c5, _ = st.columns(2)
        with c5:
            st.markdown("**Injury luck**")
            st.caption("Points lost due to injury, and the estimated win chance that "
                       "it cost. Luck is win impact compared to league average.")
            it = pd.DataFrame({"Manager": il["team_id"].map(manager_map).fillna("?").values,
                               "Points Lost": il["points_lost"].values,
                               "Wins Lost": il["wins_lost"].values,
                               "Luck": il["injury_luck"].values})
            frame(it, pics=[pic(x) for x in il["team_id"]], compact=True,
                  num=("Points Lost", "Wins Lost"), signed=("Luck",),
                  fmt={"Points Lost": "{:.1f}", "Wins Lost": "{:.2f}", "Luck": "{:+.2f}"})
        injury = il.set_index("team_id")["injury_luck"]

    st.divider()
    st.markdown("**Cumulative luck**")
    tot = luck_total(lb, official_combined)
    # Columns in the order the tables above appear on the page.
    tot = tot.sort_values("total_luck", ascending=False)
    if injury is not None:
        tot["injury_luck"] = tot["team_id"].map(injury).fillna(0.0).values
    cols = ["Manager", "schedule_luck", "field_luck"]
    heads = ["Manager", "Schedule", "Field"]
    if official_combined:
        cols.append("median_luck")
        heads.append("Median")
    cols.append("opp_luck")
    heads.append("Opponent")
    if injury is not None:
        cols.append("injury_luck")
        heads.append("Injury")
    cols += ["total_luck", "luck_sigma", "luck_label"]
    heads += ["Total", "Rating", ""]
    td = tot[cols].copy()
    td.columns = heads
    td["Rating"] = td["Rating"].map(lambda z: f"{z:+.1f}σ")
    games = [h for h in heads if h not in ("Manager", "Rating", "")]
    frame(td, pics=[pic(x) for x in tot["team_id"]], signed=games, num=("Rating",),
          fmt={h: "{:+.2f}" for h in games})
    st.caption(
        ("Schedule + Field + Median + Opponent, in games. "
         if official_combined else
         "Schedule + Field + Opponent, in games. Median is left out because it "
         "did not count toward the standings before 2025. ")
        + "Schedule, Field and Opponent are steps down a chain, each removing one "
        "kind of luck from the one before, so they add up exactly with nothing "
        "counted twice. Rating divides the total by how much luck varied across the "
        "league this season, so it says how unusual the total is rather than "
        "just how big: a quiet season and a wild one can hand out the same "
        "number of games and mean very different things."
        + (" Injury is the injury luck above, in games. It is in neither the "
           "total nor the rating." if injury is not None else "")
    )

    # ── How likely that result was, given the score ────────────────────────
    st.divider()
    st.subheader("Chance of Result")
    st.caption(
        "How likely the week's result was, given only where the score ranked. "
        "Rank 10 that loses shows 100%: all nine other managers outscored them, "
        "so every possible opponent beats them. Rank 6 that wins shows 44%, "
        "four of the nine being beatable. A low number is a result that needed "
        "the schedule's help."
    )

    n_teams = matchups_df["team_id"].nunique()
    opponents = max(n_teams - 1, 1)

    # Counted from the actual weekly scores rather than from rank arithmetic,
    # so tied scores fall out correctly instead of needing a special case.
    week_scores = {w: g["score"].tolist()
                   for w, g in matchups_df.groupby("week")}

    def chance(row_score, week, result):
        others = list(week_scores.get(week, []))
        # A statement, not a conditional expression: as an expression this
        # evaluates to None, and Streamlit's magic renders every one of them.
        if row_score in others:
            others.remove(row_score)
        if result == "W":
            hits = sum(1 for x in others if x < row_score)
        elif result == "L":
            hits = sum(1 for x in others if x > row_score)
        else:
            hits = sum(1 for x in others if x == row_score)
        return hits / opponents * 100

    chance_src = rank_src.assign(
        chance=[chance(sc, wk, oc) for sc, wk, oc in
                zip(rank_src["score"], rank_src["week"], rank_src["outcome"])])
    chance_tbl = (chance_src.pivot(index="Manager", columns="week",
                                   values="chance")
                  .reindex(rank_tbl.index))
    chance_tbl.columns = [f"Wk {int(w)}" for w in chance_tbl.columns]
    chance_tbl["Avg"] = chance_tbl.mean(axis=1).round(1)
    week_grid(chance_tbl, "{:.0f}%", "{:.1f}%")


    # ── How often each rank met each rank, this season ─────────────────────
    st.divider()
    st.subheader("Rank vs Rank Meetings")
    st.caption(
        f"How often a team scoring at each rank faced a team scoring at another "
        f"in {season}. Only the upper half is shown, since the matrix is "
        "symmetric. Every cell counts matchups and they sum to the season's "
        "total. The all-time version lives on the All-Time Records page."
    )
    rank_lookup = rank_src.set_index(["week", "team_id"])["rank"]
    paired = rank_src.assign(
        opp_rank=[rank_lookup.get((w, o)) for w, o in
                  zip(rank_src["week"], rank_src["opp_id"])]).dropna(
        subset=["opp_rank"])
    meetings = pd.crosstab(paired["rank"], paired["opp_rank"].astype(int))
    # A same-rank meeting drops both its rows in one diagonal cell, so that
    # cell counts double; every other cell already equals matchups.
    for i in meetings.index:
        if i in meetings.columns:
            meetings.loc[i, i] = meetings.loc[i, i] // 2
    # Same reason as the all-time matrix: NA keeps the column one type, so
    # Arrow serialises it instead of Streamlit having to repair it.
    mm_tbl = meetings.astype("Int64").where(
        np.triu(np.ones(meetings.shape, dtype=bool)), pd.NA)
    mm = pd.DataFrame({"vs →": [f"Rank {i}" for i in mm_tbl.index]})
    for c in mm_tbl.columns:
        mm[str(c)] = [("" if pd.isna(v) else int(v)) for v in mm_tbl[c]]
    frame(mm, mid=[str(c) for c in mm_tbl.columns], compact=True)


# ── Tab 6: Injury ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_health(season, window):
    return health.team_health(season, window)


@st.cache_data(ttl=300)
def load_health_detail(season, team_id):
    return health.team_detail(season, team_id)


@st.cache_data(ttl=300)
def load_playoff_split(season):
    return health.playoff_split(season)


def _games(g):
    """Games as the page writes them: 5g, 8.7g."""
    return f"{g:.1f}".rstrip("0").rstrip(".") + "g"


def _records():
    """Each team's official regular-season record, as Draft Value shows it:
    head-to-head before 2025, head-to-head plus the median game from 2025."""
    df = combined_standings(matchups_df)
    pre = "total_" if official_combined else ""
    ties = df["ties"] + (df["median_ties"] if official_combined else 0)
    return {t: f"{int(w)}-{int(l)}" + (f"-{int(x)}" if x else "")
            for t, w, l, x in zip(df["team_id"], df[pre + "wins"], df[pre + "losses"], ties)}


def injury_table(window):
    """
    Teams ranked by actual value lost, each with its record as a third line
    under the name. Both value columns are shares of the team's capacity, so
    they read on one scale.
    """
    t = load_health(season, window).sort_values("actual_share", ascending=False)
    names, subs, pics = who_columns(t, manager_map, season, show_mgr, show_team)
    records = _records()

    def team_cell(tid, name, sub, img):
        rec = records.get(tid)
        cell = who_cell(img, name, sub)
        if not rec:
            return cell
        return cell.replace("</div></div>",
                            f'<span class="wa-team">{esc(rec)}</span></div></div>', 1)

    rows = []
    for i, (r, name, sub, img) in enumerate(zip(t.itertuples(), names, subs, pics)):
        rows.append([
            (rank_cell(i + 1), "", i + 1),
            (team_cell(r.team_id, name, sub, img), "", name),
            (f"{r.games_lost:.1f}", "", r.games_lost),
            (f"{r.draft_capital_lost:.1f}", "", r.draft_capital_lost),
            (f"{r.draft_capital_share:.1f}%", "", r.draft_capital_share),
            (f"{r.actual_lost:.1f}", "", r.actual_lost),
            (f"{r.actual_share:.1f}%", "", r.actual_share),
            esc(", ".join(f"{n} ({_games(g)})" for n, _, g in r.biggest) or "—"),
        ])
    html_table([("#", ""), (NAME_HEAD, ""), ("Games Lost", "num"),
                ("Points", "num"), ("Share", "num"), ("Points", "num"), ("Share", "num"),
                ("Biggest Losses", "")], rows,
               groups=[("", 3), ("Draft Capital Lost", 2), ("Actual Value Lost", 2), ("", 1)])
    return t


with tab6:
    st.subheader("Injury Impact")
    if not health.supported(season):
        st.info("There is not enough preserved data to perform this analysis. "
                f"Injury status and replacement level are not available for {season}.")
    else:
        st.caption(
            "Measure of games and value (~ points) lost to injury. Games lost counts "
            "start-worthy players. Draft Capital looks at expected points based on draft "
            "position. Actual Value looks at PPG in games played. Share is value lost as a "
            "percent of the team's total."
        )
        weeks = health.weeks_to_date(season)
        if weeks < cfg["reg_season_end"]:
            st.caption(f"Through week {weeks}. Actual value uses the games played so far "
                       "and settles as the season goes.")
        reg_health = injury_table("reg")

        if weeks >= cfg["playoff_weeks"][0]:
            st.divider()
            st.subheader("Playoff Injury Impact")
            st.caption("Injuries in the playoff weeks, for the four teams that played "
                       "them. Kept apart from the regular season, which decided who got here.")
            injury_table("playoff")

        # ── One team's injuries, player by player ─────────────────────────────
        st.divider()
        st.subheader("Team Detail")
        st.caption("Every injured player from every team.")
        by_mgr = dict(zip(reg_health["manager"], reg_health["team_id"]))
        mgr = st.selectbox("Manager", sorted(by_mgr), key="injury_manager")
        detail = load_health_detail(season, int(by_mgr[mgr]))
        if detail.empty:
            st.info(f"{mgr} lost nobody to injury.")
        else:
            def player_cell(pid, name, pos):
                return (f'<div class="wa-who">{player_pic(pid)}<div>'
                        f'<span class="wa-name">{esc(name)}</span>'
                        f'<span class="wa-team">{esc(pos)}</span></div></div>')

            html_table(
                [("Player", ""), ("Games Lost", "num"),
                 ("Per Game", "num"), ("Points", "num"), ("Share", "num"),
                 ("Per Game", "num"), ("Points", "num"), ("Share", "num")],
                [[(player_cell(r.player_id, r.player_name, r.position), "", r.player_name),
                  (f"{r.games_lost:.1f}", "", r.games_lost),
                  (f"{r.basis:.2f}", "", r.basis),
                  (f"{r.draft_capital_lost:.1f}", "", r.draft_capital_lost),
                  (f"{r.draft_capital_share:.1f}%", "", r.draft_capital_share),
                  (f"{r.actual:.2f}", "", r.actual),
                  (f"{r.actual_lost:.1f}", "", r.actual_lost),
                  (f"{r.actual_share:.1f}%", "", r.actual_share)]
                 for r in detail.itertuples()],
                groups=[("", 2), ("Draft Capital", 3), ("Actual Value", 3)])

        # ── Playoff teams against the rest ────────────────────────────────────
        st.divider()
        st.subheader("Playoff vs Non-Playoff Teams")
        split = load_playoff_split(season)
        groups = (["In playoff position", "Outside"] if split.attrs["in_progress"]
                  else ["Made the playoffs", "Missed"])
        frame(pd.DataFrame({
            "": groups,
            "Games lost": split["games_lost"],
            "Actual value lost, total": split["actual_lost"],
            "Actual value lost, share": split["actual_share"],
        }), num=("Games lost", "Actual value lost, total", "Actual value lost, share"),
            fmt={"Games lost": "{:.1f}", "Actual value lost, total": "{:.1f}",
                 "Actual value lost, share": "{:.1f}%"}, compact=True, sortable=False)
