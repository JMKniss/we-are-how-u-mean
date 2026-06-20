"""
Playoff Results — bracket display with individual week and cumulative round scores.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from data.espn_client import get_league, get_matchups_df, get_manager_map, invalidate_cache
from analysis.standings import h2h_standings
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import sidebar_display_prefs, prep_display, chart_label

st.set_page_config(page_title="Playoffs", page_icon="🏆", layout="wide")
st.title("🏆 Playoff Results")

if "selected_season" not in st.session_state:
    st.session_state["selected_season"] = DEFAULT_SEASON
season = st.sidebar.selectbox(
    "Season", SEASONS,
    index=SEASONS.index(st.session_state["selected_season"])
)
st.session_state["selected_season"] = season
if st.sidebar.button("🔄 Refresh Data"):
    invalidate_cache(season)
    st.cache_data.clear()
    st.rerun()
show_mgr, show_team = sidebar_display_prefs()


@st.cache_data(ttl=300)
def load(s):
    return get_league(s), get_matchups_df(s), get_manager_map(s)


with st.spinner("Loading..."):
    league, matchups_df, manager_map = load(season)

cfg = season_config(season)
pw = cfg["playoff_weeks"]
reg_end = cfg["reg_season_end"]
current_week = min(league.current_week, cfg["total_weeks"])

# ── Regular season still in progress ─────────────────────────────────────────
if current_week <= reg_end:
    st.info(
        f"The regular season is underway. "
        f"Playoff data for {season} will become available during playoffs. Obviously."
    )
    st.stop()

# ── Split data ────────────────────────────────────────────────────────────────
reg_df = matchups_df[matchups_df["week"] <= reg_end]
playoff_df = matchups_df[matchups_df["is_playoff"]].copy()

# ── Seedings from regular season standings ────────────────────────────────────
standings = h2h_standings(reg_df).reset_index(drop=True)
standings.insert(0, "seed", range(1, len(standings) + 1))
seed_map = dict(zip(standings["team_id"], standings["seed"]))
name_map = dict(zip(standings["team_id"], standings["team_name"]))


def mgr_label(tid):
    mgr = manager_map.get(tid, "?")
    tname = name_map.get(tid, str(tid))
    if show_mgr and show_team:
        return f"{mgr} — {tname}"
    return mgr if show_mgr else tname


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
        row = {"Team": f"#{seed_map.get(tid, '?')}  {mgr_label(tid)}"}
        for i, w in enumerate(weeks):
            row[f"Wk {w}"] = f"{scrs[i]:.2f}" if scrs[i] is not None else "—"
        row["Total"] = f"{total:.2f}"
        row[" "] = "✅ W" if won else ("❌ L" if all_done else "")
        rows.append(row)

    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ── Regular season seedings table ─────────────────────────────────────────────
st.subheader(f"{season} Regular Season Final Standings")
seed_disp = prep_display(standings, manager_map, show_mgr, show_team,
                         cols=["team_name", "seed", "wins", "losses", "points_for"],
                         headers=["Team", "Seed", "W", "L", "PF"])
seed_disp["PF"] = seed_disp["PF"].round(1)
st.dataframe(seed_disp, hide_index=True, use_container_width=True)

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_champ, tab_consol, tab_sacko = st.tabs([
    "🏆 Championship (Seeds 1–4)",
    "🥈 Consolation (Seeds 5–8)",
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
