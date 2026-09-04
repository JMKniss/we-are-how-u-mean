"""
All-Time Records — cross-season stats, records, and manager history.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
from data.espn_client import get_matchups_df, get_manager_map
from analysis.standings import h2h_standings, combined_standings
from config import SEASONS, season_config
from display_utils import sidebar_display_prefs

st.set_page_config(page_title="All-Time Records", page_icon="📜", layout="wide")
st.title("📜 All-Time Records")

show_mgr, show_team = sidebar_display_prefs()

# ── 2015 hardcoded ────────────────────────────────────────────────────────────
LEGACY_2015 = {"champion": "Mikey", "sacko": "Tyler"}

# ── Ordinal helper ────────────────────────────────────────────────────────────
def ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


def finish_label(standing) -> str:
    if standing is None or (isinstance(standing, float) and np.isnan(standing)):
        return "—"
    s = int(standing)
    if s == 0:
        return "—"
    if s == 1:
        return "🏆 Champ"
    if s == 10:
        return "🚽 Sacko"
    return ordinal(s)


PLAYOFF_SPOTS = 4   # seeds 1-4 make the championship bracket

# ── Playoff wins by finish position ──────────────────────────────────────────
# Win R1 + win R2 = 2; win R1 only = 1; lose R1 + win R2 consolation = 1; etc.
PLAYOFF_WINS_BY_FINISH = {1: 2, 2: 1, 3: 1, 4: 0, 5: 2, 6: 1, 7: 1, 8: 0, 9: 1, 10: 0}


def compute_season_finish_map(season: int, season_df: pd.DataFrame) -> dict:
    """
    Reconstruct final standings (1–10) from matchup data using pure seed-based
    bracket logic. Returns {team_id: finish_int}, or {} if playoffs are incomplete.

    Bracket structure (all seasons except 2022):
      Seeds 1–4  → Championship. R1: 1v4, 2v3. R2: winners vs winners, losers vs losers.
      Seeds 5–8  → Consolation.  R1: 5v8, 6v7. R2: same.
      Seeds 9–10 → Sacko. Compared over the weeks they actually played each
                    other. Lower total finishes last.

    2022 (3-week format): R1 = pw[0] only. Finals = pw[1]+pw[2].
    2016: playoffs ran weeks 14–17 after a 13-week regular season, and the
    bottom two met in Round 1 only, under a consolation ladder.

    Played-week detection: checks which playoff weeks have actual data rather
    than trusting total_weeks from config — guards against seasons where the
    final NFL week wasn't played.
    """
    cfg = season_config(season)
    pw = cfg["playoff_weeks"]
    reg_end = cfg["reg_season_end"]
    three_week = len(pw) == 3

    reg_df = season_df[season_df["week"] <= reg_end]
    # 2025+: playoff seeding uses combined (H2H + median) standings
    standings = (combined_standings(reg_df) if season >= 2025 else h2h_standings(reg_df)).reset_index(drop=True)
    all_ids = list(standings["team_id"])

    if len(all_ids) < 10:
        return {}

    playoff_df = season_df[season_df["is_playoff"]]
    played_pw = set(playoff_df["week"].unique())

    # Seed groups (index 0 = seed 1, etc.)
    champ_ids = all_ids[:4]
    consol_ids = all_ids[4:8]
    sacko_ids = all_ids[8:10]

    # R1 pairs — always seed-based: highest vs lowest in each group
    champ_r1_pairs = [(champ_ids[0], champ_ids[3]), (champ_ids[1], champ_ids[2])]
    consol_r1_pairs = [(consol_ids[0], consol_ids[3]), (consol_ids[1], consol_ids[2])]

    r1_weeks = [pw[0]] if three_week else [pw[0], pw[1]]
    r2_weeks = [pw[1], pw[2]] if three_week else [pw[2], pw[3]]

    # R1 is complete when its last week has data; same for R2
    if r1_weeks[-1] not in played_pw:
        return {}
    if r2_weeks[-1] not in played_pw:
        return {}

    def team_cum(tid, weeks):
        total = 0.0
        for w in weeks:
            r = playoff_df[(playoff_df["team_id"] == tid) & (playoff_df["week"] == w)]
            if not r.empty:
                total += float(r["score"].values[0])
        return total

    def play_round(t1, t2, weeks):
        s1, s2 = team_cum(t1, weeks), team_cum(t2, weeks)
        return (t1, t2) if s1 >= s2 else (t2, t1)  # (winner, loser)

    # R1 results
    champ_r1 = [play_round(t1, t2, r1_weeks) for t1, t2 in champ_r1_pairs]
    consol_r1 = [play_round(t1, t2, r1_weeks) for t1, t2 in consol_r1_pairs]

    champ_w = [w for w, l in champ_r1]
    champ_l = [l for w, l in champ_r1]
    consol_w = [w for w, l in consol_r1]
    consol_l = [l for w, l in consol_r1]

    # R2 results
    first,  second  = play_round(champ_w[0],  champ_w[1],  r2_weeks)
    third,  fourth  = play_round(champ_l[0],  champ_l[1],  r2_weeks)
    fifth,  sixth   = play_round(consol_w[0], consol_w[1], r2_weeks)
    seventh, eighth = play_round(consol_l[0], consol_l[1], r2_weeks)

    # Sacko: compare only over the weeks the bottom two actually faced each
    # other. That is every playoff week in most seasons, but 2016 ran a
    # consolation ladder where they met in Round 1 only and then played
    # different opponents, so summing all four weeks compared scores from
    # games against other teams.
    sacko_weeks = [
        w for w in pw
        if not playoff_df[(playoff_df["team_id"] == sacko_ids[0])
                          & (playoff_df["week"] == w)
                          & (playoff_df["opp_id"] == sacko_ids[1])].empty
    ]
    if not sacko_weeks:
        sacko_weeks = pw
    s0 = team_cum(sacko_ids[0], sacko_weeks)
    s1 = team_cum(sacko_ids[1], sacko_weeks)
    ninth  = sacko_ids[0] if s0 > s1 else sacko_ids[1]
    tenth  = sacko_ids[1] if ninth == sacko_ids[0] else sacko_ids[0]

    return {
        first: 1, second: 2, third: 3, fourth: 4,
        fifth: 5, sixth: 6, seventh: 7, eighth: 8,
        ninth: 9, tenth: 10,
    }


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_all_seasons():
    """
    Returns (all_matchups_df, season_stats_df, failed_seasons).
    all_matchups_df: every game row across all seasons with 'manager'/'opp_manager' columns.
    season_stats_df: one row per (season, manager) with reg-season aggregates + final_standing.
    """
    all_matchups, season_stats_rows, failed = [], [], []

    for season in SEASONS:
        try:
            matchups = get_matchups_df(season)
            mgr_map = get_manager_map(season)
            cfg = season_config(season)
            reg_end = cfg["reg_season_end"]

            m = matchups.copy()
            m["manager"] = m["team_id"].map(mgr_map)
            m["opp_manager"] = m["opp_id"].map(mgr_map)
            all_matchups.append(m)

            finish_map = compute_season_finish_map(season, m)  # {team_id: 1-10}

            reg_df = m[m["week"] <= reg_end]
            # Regular season seed, using the same basis as playoff seeding:
            # combined (H2H + median) from 2025, H2H before that.
            seed_order = (combined_standings(reg_df) if season >= 2025
                          else h2h_standings(reg_df)).reset_index(drop=True)
            seed_map = {t: i + 1 for i, t in enumerate(seed_order["team_id"])}
            for team_id, grp in reg_df.groupby("team_id"):
                mgr = mgr_map.get(team_id, "?")
                final_standing = finish_map.get(team_id, 0)
                wins = int((grp["outcome"] == "W").sum())
                losses = int((grp["outcome"] == "L").sum())
                ties = int((grp["outcome"] == "T").sum())
                pf = round(grp["score"].sum(), 2)
                pa = round(grp["opp_score"].sum(), 2)
                games = wins + losses
                season_stats_rows.append({
                    "season": season,
                    "team_id": team_id,
                    "manager": mgr,
                    "reg_wins": wins,
                    "reg_losses": losses,
                    "reg_ties": ties,
                    "pf": pf,
                    "pa": pa,
                    "avg_pf": round(pf / games, 2) if games > 0 else 0.0,
                    "avg_pa": round(pa / games, 2) if games > 0 else 0.0,
                    "point_diff": round(pf - pa, 2),
                    "avg_diff": round((pf - pa) / games, 2) if games > 0 else 0.0,
                    "final_standing": final_standing,
                    "seed": seed_map.get(team_id, 0),
                })
        except Exception as e:
            failed.append((season, str(e)))

    matchups_df = pd.concat(all_matchups, ignore_index=True) if all_matchups else pd.DataFrame()
    season_stats_df = pd.DataFrame(season_stats_rows)
    return matchups_df, season_stats_df, failed


@st.cache_data(ttl=300)
def compute_playoff_round_wins(_all_matchups_df):
    """
    Returns DataFrame {season, manager, playoff_wins}.
    Derives win counts from compute_season_finish_map via PLAYOFF_WINS_BY_FINISH,
    so the bracket logic is identical to the finish computation.
    """
    rows = []
    for season in SEASONS:
        s_df = _all_matchups_df[_all_matchups_df["season"] == season]
        if s_df.empty:
            continue

        finish_map = compute_season_finish_map(season, s_df)  # {team_id: 1-10}
        if not finish_map:
            continue

        mgr_map_local = (s_df[["team_id", "manager"]].drop_duplicates()
                         .set_index("team_id")["manager"].to_dict())

        for tid, finish in finish_map.items():
            rows.append({
                "season": season,
                "manager": mgr_map_local.get(tid, "?"),
                "playoff_wins": PLAYOFF_WINS_BY_FINISH.get(finish, 0),
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["season", "manager", "playoff_wins"])


# ── Load ──────────────────────────────────────────────────────────────────────
with st.spinner("Loading all seasons... this may take a moment on first load."):
    all_matchups_df, season_stats_df, failed_seasons = load_all_seasons()
    playoff_wins_df = compute_playoff_round_wins(all_matchups_df)

if failed_seasons:
    with st.expander(f"⚠️ {len(failed_seasons)} season(s) failed to load"):
        for s, err in failed_seasons:
            st.caption(f"{s}: {err}")

if all_matchups_df.empty or season_stats_df.empty:
    st.error("No data loaded.")
    st.stop()

# ── Derived frames ────────────────────────────────────────────────────────────
reg_matchups = all_matchups_df[~all_matchups_df["is_playoff"]].copy()
# One row per matchup (winner's perspective) — for differential records
reg_matchups_win_side = reg_matchups[reg_matchups["outcome"] == "W"].copy()
reg_matchups_win_side["margin"] = reg_matchups_win_side["score"] - reg_matchups_win_side["opp_score"]

# Merge playoff wins into season stats
if not playoff_wins_df.empty:
    season_stats_df = season_stats_df.merge(
        playoff_wins_df, on=["season", "manager"], how="left"
    )
    season_stats_df["playoff_wins"] = season_stats_df["playoff_wins"].fillna(0).astype(int)
else:
    season_stats_df["playoff_wins"] = 0

season_stats_df["full_wins"] = season_stats_df["reg_wins"] + season_stats_df["playoff_wins"]

# ── Active vs Legacy view ─────────────────────────────────────────────────────
# "Active" means a manager who played in the most recent season with data.
# Filtering is applied to the SUBJECT of every table, never to opponents, so an
# active manager keeps every game they played - including games against people
# who have since left. Whole seasons are never dropped; a record simply passes
# to the next holder if the top one is no longer active.
LATEST_SEASON = int(season_stats_df["season"].max())
ACTIVE_MANAGERS = set(
    season_stats_df.loc[season_stats_df["season"] == LATEST_SEASON, "manager"]
)

VIEW_ACTIVE = "Active Managers Only"
VIEW_LEGACY = "Legacy"
if "alltime_view" not in st.session_state:
    st.session_state["alltime_view"] = VIEW_ACTIVE


VIEW_TAB_KEYS = ("trophy", "records", "mgr", "h2h", "milestones")


def _view_changed(changed_key: str):
    """
    Push one tab's new choice to the shared value and to every other tab.

    Streamlit renders all tabs on every run, so each needs its own widget key.
    Syncing them inline would clobber the click that caused the run - the
    freshly set widget value would be overwritten before the widget redrew.
    Doing it in on_change avoids that, because the callback fires after the
    interaction is recorded and before the rerun.
    """
    val = st.session_state[changed_key]
    st.session_state["alltime_view"] = val
    for tk in VIEW_TAB_KEYS:
        st.session_state[f"alltime_view_{tk}"] = val


def view_toggle(tab_key: str):
    """Render the Active/Legacy switch at the top of a tab."""
    k = f"alltime_view_{tab_key}"
    if k not in st.session_state:
        st.session_state[k] = st.session_state["alltime_view"]
    st.radio("View", [VIEW_ACTIVE, VIEW_LEGACY], key=k, horizontal=True,
             label_visibility="collapsed",
             on_change=_view_changed, args=(k,))
    if st.session_state["alltime_view"] == VIEW_ACTIVE:
        st.caption("Showing only records involving currently active managers.")


active_only = st.session_state["alltime_view"] == VIEW_ACTIVE
if active_only:
    season_stats_df = season_stats_df[
        season_stats_df["manager"].isin(ACTIVE_MANAGERS)].copy()
    all_matchups_df = all_matchups_df[
        all_matchups_df["manager"].isin(ACTIVE_MANAGERS)].copy()
    reg_matchups = reg_matchups[
        reg_matchups["manager"].isin(ACTIVE_MANAGERS)].copy()
    reg_matchups_win_side = reg_matchups_win_side[
        reg_matchups_win_side["manager"].isin(ACTIVE_MANAGERS)].copy()
    if not playoff_wins_df.empty:
        playoff_wins_df = playoff_wins_df[
            playoff_wins_df["manager"].isin(ACTIVE_MANAGERS)].copy()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_trophy, tab_records, tab_mgr_records, tab_h2h, tab_milestones = st.tabs([
    "🏆 Trophy Case",
    "📊 League Records",
    "👤 Manager Records",
    "⚔️ Head to Head",
    "🎯 Milestones",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: TROPHY CASE
# ══════════════════════════════════════════════════════════════════════════════
with tab_trophy:
    view_toggle("trophy")
    st.subheader("Career Summary")

    MEDAL = {1: "🏆", 2: "🥈", 3: "🥉"}   # trophy, silver, bronze
    SACKO = "🚽"                                          # toilet

    def year_ranges(years):
        """[2016,2017,2019,2020,2021] -> '2016-2017, 2019-2021'."""
        ys = sorted({int(y) for y in years})
        if not ys:
            return ""
        spans, start_y, prev = [], ys[0], ys[0]
        for y in ys[1:]:
            if y == prev + 1:
                prev = y
                continue
            spans.append((start_y, prev))
            start_y = prev = y
        spans.append((start_y, prev))
        return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in spans)

    # Last place is whatever the largest finish that season was, rather than a
    # hardcoded 10, so a season with a different team count still works.
    last_by_season = (season_stats_df[season_stats_df["final_standing"] > 0]
                      .groupby("season")["final_standing"].max().to_dict())

    # 2015 predates the data. Its champion and sacko are known, and are counted
    # here only: that season contributes no games, years or percentages.
    # Winning it also means making that season's playoffs, so the champion gets
    # a playoff appearance too - otherwise a manager could show more trophies
    # than appearances, which cannot happen (1st through 4th are all top-four
    # seeds). The sacko finished last and gets no appearance.
    tally = {LEGACY_2015["champion"]: {1: 1},
             LEGACY_2015["sacko"]: {"last": 1}}
    legacy_playoffs = {LEGACY_2015["champion"]: 1}

    rows = []
    for mgr, g in season_stats_df.groupby("manager"):
        wins = int(g["reg_wins"].sum())
        losses = int(g["reg_losses"].sum())
        ties = int(g["reg_ties"].sum()) if "reg_ties" in g.columns else 0
        decided = wins + losses          # win% denominator, ties excluded
        games = decided + ties           # games actually played
        counts = dict(tally.get(mgr, {}))
        for _, r in g.iterrows():
            fin = int(r["final_standing"])
            if fin == 0:
                continue
            if fin == last_by_season.get(int(r["season"])):
                counts["last"] = counts.get("last", 0) + 1
            elif fin in MEDAL:
                counts[fin] = counts.get(fin, 0) + 1

        parts = []
        for key in (1, 2, 3, "last"):
            n = counts.get(key, 0)
            if not n:
                continue
            sym = SACKO if key == "last" else MEDAL[key]
            parts.append(sym if n == 1 else f"{sym}x{n}")

        record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
        rows.append({
            "_wins": wins,           # sort key only; dropped before display
            "Manager": mgr,
            "Years": year_ranges(g["season"]),
            "Games": games,
            "Record": record,
            "Win%": round(wins / decided * 100, 1) if decided else 0.0,
            "Playoffs": (int((g["seed"].between(1, PLAYOFF_SPOTS)).sum())
                         + legacy_playoffs.get(mgr, 0)),
            "Finishes": "  ".join(parts),
        })

    # Ordered by career wins as before; the column itself is now folded into
    # Record, so the raw value is kept only to sort by and then dropped.
    career = (pd.DataFrame(rows)
              .sort_values("_wins", ascending=False)
              .drop(columns="_wins")
              .reset_index(drop=True))
    career.index = range(1, len(career) + 1)
    st.dataframe(career, use_container_width=True)

    # 2015 has no game data, so its champion and sacko show up in Finishes only.
    # Name only the ones actually on screen, since Active view may hide them.
    _shown = set(career["Manager"])
    _bits = []
    if LEGACY_2015["champion"] in _shown:
        _bits.append(f"{LEGACY_2015['champion']}'s title")
    if LEGACY_2015["sacko"] in _shown:
        _bits.append(f"{LEGACY_2015['sacko']}'s sacko")
    legacy_2015_note = (
        f" 2015 predates the league data, so {' and '.join(_bits)} that year "
        f"{'are' if len(_bits) > 1 else 'is'} included in Finishes but in no "
        f"other column." if _bits else ""
    )
    st.caption(
        f"Regular season head-to-head only; median wins are not counted. "
        f"Win% excludes ties, which the record still shows. "
        f"Playoffs counts seasons seeded in the top {PLAYOFF_SPOTS}. "
        f"Finishes: {MEDAL[1]} 1st · {MEDAL[2]} 2nd · {MEDAL[3]} 3rd · {SACKO} last. "
        + legacy_2015_note
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: LEAGUE RECORDS
# ══════════════════════════════════════════════════════════════════════════════
with tab_records:
    view_toggle("records")
    st.subheader("League Records")

    def record_row(label, df_row, val_col, fmt="{:.2f}"):
        if df_row.empty:
            return {"Record": label, "Manager": "—", "Season": "—", "Week": "—", "Value": "—"}
        r = df_row.iloc[0]
        return {
            "Record": label,
            "Manager": r.get("manager", "—"),
            "Season": str(int(r["season"])) if "season" in r else "—",
            "Week": str(int(r["week"])) if "week" in r else "—",
            "Value": fmt.format(r[val_col]),
        }

    def tied_extreme(df, col, largest=True):
        """Return all rows tied at the max (largest=True) or min value of col."""
        if df.empty:
            return df
        val = df[col].max() if largest else df[col].min()
        return df[df[col] == val]

    def season_record_rows(label, df, col, largest=True, fmt="{:.2f}"):
        rows = tied_extreme(df, col, largest)
        if rows.empty:
            return [{"Record": label, "Manager": "—", "Season": "—", "Value": "—"}]
        lbl = f"{label} (tie)" if len(rows) > 1 else label
        return [{"Record": lbl, "Manager": r["manager"],
                 "Season": str(int(r["season"])), "Value": fmt.format(r[col])}
                for _, r in rows.iterrows()]

    # ── Weekly scoring records ─────────────────────────────────────────────
    st.markdown("#### Weekly Scoring")
    all_scores = reg_matchups.dropna(subset=["score"]).copy()
    high_val = all_scores["score"].max()
    low_val = all_scores["score"].min()
    high_rows = all_scores[all_scores["score"] == high_val]
    low_rows = all_scores[all_scores["score"] == low_val]

    high_lbl = "All-Time High Score (tie)" if len(high_rows) > 1 else "All-Time High Score"
    low_lbl = "All-Time Low Score (tie)" if len(low_rows) > 1 else "All-Time Low Score"
    weekly_records = []
    for _, r in high_rows.iterrows():
        weekly_records.append({"Record": high_lbl, "Manager": r["manager"],
                                "Season": str(int(r["season"])), "Week": str(int(r["week"])),
                                "Score": f"{r['score']:.2f}"})
    for _, r in low_rows.iterrows():
        weekly_records.append({"Record": low_lbl, "Manager": r["manager"],
                                "Season": str(int(r["season"])), "Week": str(int(r["week"])),
                                "Score": f"{r['score']:.2f}"})
    st.dataframe(pd.DataFrame(weekly_records), hide_index=True, use_container_width=True)

    # ── Scoring season records ─────────────────────────────────────────────
    st.markdown("#### Season Scoring Records (Regular Season Only)")
    # Per-game records first, then totals, each kept as its own block.
    scoring_record_specs = [
        ("Highest PF per Game", "avg_pf", True),
        ("Lowest PF per Game",  "avg_pf", False),
        ("Highest PA per Game", "avg_pa", True),
        ("Lowest PA per Game",  "avg_pa", False),
        ("Highest Total PF",    "pf",     True),
        ("Lowest Total PF",     "pf",     False),
        ("Highest Total PA",    "pa",     True),
        ("Lowest Total PA",     "pa",     False),
    ]
    all_scoring_rows = []
    for label, col, largest in scoring_record_specs:
        all_scoring_rows += season_record_rows(label, season_stats_df, col, largest)
    st.dataframe(pd.DataFrame(all_scoring_rows), hide_index=True, use_container_width=True)

    st.markdown("#### Single-Season Win Records")

    def wins_record_rows(label, df, col, largest=True):
        rows = tied_extreme(df, col, largest)
        if rows.empty:
            return [{"Record": label, "Manager": "—", "Season": "—",
                     "Wins": "—", "Finish": "—"}]
        lbl = f"{label} (tie)" if len(rows) > 1 else label
        return [{"Record": lbl, "Manager": r["manager"], "Season": str(int(r["season"])),
                 "Wins": int(r[col]), "Finish": finish_label(r["final_standing"])}
                for _, r in rows.iterrows()]

    win_records = pd.DataFrame(
        wins_record_rows("Most Reg Season Wins",   season_stats_df, "reg_wins", largest=True) +
        wins_record_rows("Fewest Reg Season Wins", season_stats_df, "reg_wins", largest=False)
    )
    st.dataframe(win_records, hide_index=True, use_container_width=True)

    # A perfect season is winning out and then taking the title; a perfect
    # disaster is losing out and then finishing last. Both are computed rather
    # than asserted, so the caption stays honest if either ever happens.
    _ws = season_stats_df.copy()
    _ws["games"] = _ws["reg_wins"] + _ws["reg_losses"]
    _last = (_ws[_ws["final_standing"] > 0]
             .groupby("season")["final_standing"].max().to_dict())
    _is_last = _ws.apply(
        lambda r: r["final_standing"] == _last.get(int(r["season"]), -1), axis=1)

    perfect = _ws[(_ws["games"] > 0) & (_ws["reg_wins"] == _ws["games"])
                  & (_ws["final_standing"] == 1)]
    disaster = _ws[(_ws["games"] > 0) & (_ws["reg_wins"] == 0) & _is_last]

    def _who(df):
        return ", ".join(f"{r.manager} ({int(r.season)})" for r in df.itertuples())

    if perfect.empty and disaster.empty:
        caption = ("There has never been a perfect season, nor a perfect "
                   "disaster through the playoffs.")
    elif perfect.empty:
        caption = (f"There has never been a perfect season. Perfect disasters: "
                   f"{_who(disaster)}.")
    elif disaster.empty:
        caption = (f"Perfect seasons: {_who(perfect)}. There has never been a "
                   f"perfect disaster through the playoffs.")
    else:
        caption = f"Perfect seasons: {_who(perfect)}. Perfect disasters: {_who(disaster)}."

    st.caption(caption)

    # ── Matchup differential records ───────────────────────────────────────
    st.markdown("#### Matchup Differentials (Regular Season)")
    def diff_rows(label, df, largest=True):
        rows = tied_extreme(df, "margin", largest)
        if rows.empty:
            return [{"Record": label, "Winner": "—", "Loser": "—",
                     "Winner Score": "—", "Loser Score": "—", "Margin": "—",
                     "Season": "—", "Week": "—"}]
        lbl = f"{label} (tie)" if len(rows) > 1 else label
        return [{"Record": lbl, "Winner": r["manager"], "Loser": r["opp_manager"],
                 "Winner Score": f"{r['score']:.2f}", "Loser Score": f"{r['opp_score']:.2f}",
                 "Margin": f"{r['margin']:.2f}", "Season": str(int(r["season"])),
                 "Week": str(int(r["week"]))}
                for _, r in rows.iterrows()]

    diff_records = pd.DataFrame(
        diff_rows("Biggest Win Margin", reg_matchups_win_side, largest=True) +
        diff_rows("Closest Game", reg_matchups_win_side, largest=False)
    )
    st.dataframe(diff_records, hide_index=True, use_container_width=True)

    # ── Win records ────────────────────────────────────────────────────────

    # ── Milestone records ──────────────────────────────────────────────────
    st.markdown("#### Milestone Records")

    # Career games in chronological order. Every row is a week actually played,
    # ties included, so "weeks" and games are the same thing here.
    _cg = reg_matchups.sort_values(["manager", "season", "week"]).copy()
    _cg["career_game"] = _cg.groupby("manager").cumcount() + 1
    _cg["cum_w"] = _cg.groupby("manager")["outcome"].transform(
        lambda x: (x == "W").cumsum())
    _cg["cum_l"] = _cg.groupby("manager")["outcome"].transform(
        lambda x: (x == "L").cumsum())

    # Playoff appearances accrue per season, so the cost is the career games
    # played up to the end of the season the milestone was reached in.
    _se = season_stats_df.sort_values(["manager", "season"]).copy()
    if "reg_ties" not in _se.columns:
        _se["reg_ties"] = 0
    _se["_games"] = _se["reg_wins"] + _se["reg_losses"] + _se["reg_ties"]
    _se["_made"] = _se["seed"].between(1, PLAYOFF_SPOTS).astype(int)
    _se["cum_made"] = _se.groupby("manager")["_made"].cumsum()
    _se["cum_games"] = _se.groupby("manager")["_games"].cumsum()

    def _fastest(df, cond_col, target, cost_col):
        """Fewest games taken by any manager to reach `target` of cond_col."""
        hit = df[df[cond_col] >= target]
        if hit.empty:
            return None, []
        per = hit.groupby("manager")[cost_col].min()
        best = int(per.min())
        return best, sorted(per[per == best].index.tolist())

    milestone_specs = (
        [(f"{n} Wins",   _cg, "cum_w", n, "career_game") for n in (25, 50, 75)]
        + [(f"{n} Losses", _cg, "cum_l", n, "career_game") for n in (25, 50, 75)]
        + [("5 Playoff Appearances", _se, "cum_made", 5, "cum_games")]
    )

    milestone_rows = []
    for label, frame, col, target, cost in milestone_specs:
        weeks, who = _fastest(frame, col, target, cost)
        if weeks is None:
            milestone_rows.append({"Fastest To": label, "Manager": "—",
                                   "Weeks to Achieve": "not yet reached"})
        else:
            milestone_rows.append({
                "Fastest To": label + (" (tie)" if len(who) > 1 else ""),
                "Manager": ", ".join(who),
                "Weeks to Achieve": str(weeks),
            })
    st.dataframe(pd.DataFrame(milestone_rows), hide_index=True,
                 use_container_width=True)
    st.caption(
        "Weeks counts regular season games played, ties included. Playoff "
        f"appearances are seasons seeded in the top {PLAYOFF_SPOTS}, counted at "
        "the end of the season they were earned, so 2015 does not count."
    )



# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: MANAGER RECORDS
# ══════════════════════════════════════════════════════════════════════════════
with tab_mgr_records:
    view_toggle("mgr")
    st.subheader("Best & Worst Season by Manager")
    st.caption(
        "Regular season only. Records rank by win percentage, not win count, "
        "because season length has varied from 12 to 14 games. "
        "⭐ = most extreme across all managers."
    )

    st_df = season_stats_df.copy()
    if "reg_ties" not in st_df.columns:
        st_df["reg_ties"] = 0
    st_df["games"] = st_df["reg_wins"] + st_df["reg_losses"] + st_df["reg_ties"]
    # Ties count as half a win, so a 6-5-2 season is not ranked as if it were 6-5.
    st_df["win_pct"] = ((st_df["reg_wins"] + 0.5 * st_df["reg_ties"])
                        / st_df["games"].replace(0, np.nan))

    def record_str(r):
        base = f"{int(r['reg_wins'])}-{int(r['reg_losses'])}"
        if int(r["reg_ties"]):
            base += f"-{int(r['reg_ties'])}"
        return base

    # (display, key, source column, higher-is-more-extreme)
    col_specs = [
        ("Best Record",  "_best_rec",  "win_pct",  True),
        ("Worst Record", "_worst_rec", "win_pct",  False),
        ("High PF/G",    "_high_pf",   "avg_pf",   True),
        ("Low PF/G",     "_low_pf",    "avg_pf",   False),
        ("High PA/G",    "_high_pa",   "avg_pa",   True),
        ("Low PA/G",     "_low_pa",    "avg_pa",   False),
        ("High Diff/G",  "_high_pd",   "avg_diff", True),
        ("Low Diff/G",   "_low_pd",    "avg_diff", False),
    ]

    managers = sorted(st_df["manager"].unique())
    raw_rows = []
    for mgr in managers:
        m_df = st_df[st_df["manager"] == mgr]
        if m_df.empty:
            continue
        row = {"Manager": mgr}
        for disp, key, src, largest in col_specs:
            pick = m_df.nlargest(1, src) if largest else m_df.nsmallest(1, src)
            if pick.empty or pd.isna(pick[src].values[0]):
                row[key] = row[f"{key}_txt"] = row[f"{key}_yr"] = None
                continue
            r = pick.iloc[0]
            row[key] = round(float(r[src]), 4)
            row[f"{key}_yr"] = int(r["season"])
            row[f"{key}_txt"] = (record_str(r) if src == "win_pct"
                                 else f"{float(r[src]):.2f}")

        # Best and worst finish, with a count when it happened more than once.
        placed = m_df[m_df["final_standing"] > 0]["final_standing"]
        if placed.empty:
            row["Best Finish"] = row["Worst Finish"] = "—"
        else:
            for label, pos in (("Best Finish", int(placed.min())),
                               ("Worst Finish", int(placed.max()))):
                n = int((placed == pos).sum())
                row[label] = ordinal(pos) + (f" x{n}" if n > 1 else "")
        raw_rows.append(row)

    raw_df = pd.DataFrame(raw_rows)

    extremes = {}
    for disp, key, src, largest in col_specs:
        vals = raw_df[key].dropna()
        extremes[key] = (vals.max() if largest else vals.min()) if not vals.empty else None

    display_rows = []
    for _, r in raw_df.iterrows():
        out = {"Manager": r["Manager"]}
        for disp, key, src, largest in col_specs:
            if r[key] is None:
                out[disp] = "—"
                continue
            cell = f"{r[f'{key}_txt']} ({r[f'{key}_yr']})"
            if extremes[key] is not None and r[key] == extremes[key]:
                cell += " ⭐"
            out[disp] = cell
        # Finish columns are categorical and several managers share a best of
        # 1st, so starring them would mark half the table. Left unmarked.
        out["Best Finish"] = r["Best Finish"]
        out["Worst Finish"] = r["Worst Finish"]
        display_rows.append(out)

    col_config = {disp: st.column_config.TextColumn(disp, width=150)
                  for disp, key, src, largest in col_specs}
    st.dataframe(pd.DataFrame(display_rows), hide_index=True,
                 use_container_width=True, column_config=col_config)

    st.divider()

    # ── One manager's season-by-season record ──────────────────────────────
    st.subheader("Season by Season")
    pick = st.selectbox("Manager", sorted(st_df["manager"].unique()),
                        key="season_by_season_mgr")
    m_df = st_df[st_df["manager"] == pick].sort_values("season")

    # Ties are excluded from every calculation here, so win% is W/(W+L) and the
    # average row averages wins and losses only.
    def win_pct(w, l):
        return round(w / (w + l) * 100, 1) if (w + l) else 0.0

    season_rows = []
    for _, r in m_df.iterrows():
        g = int(r["reg_wins"]) + int(r["reg_losses"]) + int(r.get("reg_ties", 0))
        made = 1 <= int(r["seed"]) <= PLAYOFF_SPOTS if r["seed"] else False
        season_rows.append({
            "Season": str(int(r["season"])),
            "Record": record_str(r),
            "Win%": win_pct(int(r["reg_wins"]), int(r["reg_losses"])),
            "Playoffs": "✅" if made else "❌",
            "PF (/g)": f"{r['pf']:.1f} ({r['pf'] / g:.1f})" if g else "—",
            "PA (/g)": f"{r['pa']:.1f} ({r['pa'] / g:.1f})" if g else "—",
            "Avg Diff": round(float(r["avg_diff"]), 2),
            "Finish": finish_label(r["final_standing"]),
        })

    if season_rows:
        n = len(m_df)
        aw, al = m_df["reg_wins"].mean(), m_df["reg_losses"].mean()
        tot_g = (m_df["reg_wins"] + m_df["reg_losses"] + m_df.get("reg_ties", 0)).sum()
        placed = m_df[m_df["final_standing"] > 0]["final_standing"]
        made_n = int(sum(1 for _, r in m_df.iterrows()
                         if r["seed"] and 1 <= int(r["seed"]) <= PLAYOFF_SPOTS))
        avg_row = {
            "Season": "Average",
            "Record": f"{aw:.1f} W, {al:.1f} L",
            "Win%": win_pct(aw, al),
            "Playoffs": f"{made_n} of {n}",
            "PF (/g)": f"{m_df['pf'].mean():.1f} ({m_df['pf'].sum() / tot_g:.1f})" if tot_g else "—",
            "PA (/g)": f"{m_df['pa'].mean():.1f} ({m_df['pa'].sum() / tot_g:.1f})" if tot_g else "—",
            "Avg Diff": round(float(m_df["avg_diff"].mean()), 2),
            "Finish": f"{placed.mean():.1f}" if not placed.empty else "—",
        }
        # Average sits last, and is bolded so it reads as a summary rather than
        # another season. Needs jinja2 >= 3.1.5 for the pandas Styler.
        season_table = pd.DataFrame(season_rows + [avg_row])
        avg_idx = len(season_table) - 1
        styled = season_table.style.apply(
            lambda row: ["font-weight: bold"] * len(row)
            if row.name == avg_idx else [""] * len(row),
            axis=1,
        # A Styler bypasses Streamlit's default number rendering, so the
        # numeric columns must be formatted explicitly or they print as
        # 30.800000 instead of 30.8.
        ).format({"Win%": "{:.1f}", "Avg Diff": "{:.2f}"})
        st.dataframe(styled, hide_index=True, use_container_width=True)
        st.caption(
            f"{pick}, {n} season{'s' if n != 1 else ''}. Ties are excluded from "
            "win% and from the average row. Playoffs marks a top-"
            f"{PLAYOFF_SPOTS} seed. Finish on the Average row is the mean placing."
        )



# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: HEAD TO HEAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_h2h:
    view_toggle("h2h")
    # In Active view the opponent axis is filtered as well as the subject, so
    # the matrix and each breakdown show only managers still in the league.
    h2h_src = reg_matchups
    if active_only:
        h2h_src = h2h_src[h2h_src["opp_manager"].isin(ACTIVE_MANAGERS)]

    # |score - opp_score| per game. Distinct from the signed differential:
    # alternating blowouts average out to nearly zero signed, while the games
    # themselves were nowhere near close. Matt and Scott sit at +0.1 signed
    # across 11 games, yet swing by 33.6 on average.
    h2h_src = h2h_src.assign(
        _absmar=(h2h_src["score"] - h2h_src["opp_score"]).abs())

    h2h_agg = (
        h2h_src
        .groupby(["manager", "opp_manager"])
        .agg(
            wins=("outcome", lambda x: (x == "W").sum()),
            losses=("outcome", lambda x: (x == "L").sum()),
            pf=("score", "sum"),
            pa=("opp_score", "sum"),
            games=("outcome", "count"),
            absmar=("_absmar", "mean"),
        )
        .reset_index()
    )
    h2h_agg["avg_diff"] = ((h2h_agg["pf"] - h2h_agg["pa"]) / h2h_agg["games"]).round(2)
    h2h_agg["record"] = h2h_agg["wins"].astype(str) + "-" + h2h_agg["losses"].astype(str)

    st.subheader("Record Matrix")
    st.caption("Rows = manager, Columns = opponent. Cell = the row manager's "
               "record against that opponent.")
    # pivot rather than pivot_table: the values are strings and each
    # manager/opponent pair appears once, so nothing needs aggregating.
    matrix = (h2h_agg.pivot(index="manager", columns="opp_manager",
                            values="record")
              .fillna("—"))
    matrix.index.name = "vs →"
    st.dataframe(matrix, use_container_width=True)

    st.divider()
    st.subheader("Head-to-Head Records")
    st.caption(
        "Regular season matchups only. Avg Diff is signed, so it says who is "
        "ahead. Avg Margin ignores the sign, so it says how close the games "
        f"were - the league average is {reg_matchups.eval('abs(score - opp_score)').mean():.1f}."
    )

    managers_h2h = sorted(h2h_agg["manager"].unique())
    selected_mgr = st.selectbox("View matchups for:", managers_h2h)
    mgr_h2h = (h2h_agg[h2h_agg["manager"] == selected_mgr]
               .sort_values("wins", ascending=False))
    mgr_h2h = mgr_h2h.assign(
        avg_pf=(mgr_h2h["pf"] / mgr_h2h["games"]).round(1),
        avg_pa=(mgr_h2h["pa"] / mgr_h2h["games"]).round(1),
    )
    mgr_h2h = mgr_h2h.assign(absmar=mgr_h2h["absmar"].round(1))
    disp = mgr_h2h[["opp_manager", "games", "record",
                    "avg_pf", "avg_pa", "avg_diff", "absmar"]].rename(columns={
        "opp_manager": "Opponent",
        "games": "Games Played",
        "record": "Record",
        "avg_pf": "Avg PF",
        "avg_pa": "Avg PA",
        "avg_diff": "Avg Diff",      # signed: who is ahead, and by how much
        "absmar": "Avg Margin",      # unsigned: how close the games actually are
    })
    st.dataframe(disp, hide_index=True, use_container_width=True)

    MIN_MEETINGS = 8   # ~5 seasons of history; below this the picks are noise

    st.subheader("Noteworthy Matchups")
    st.caption(
        "Most Played is whoever you have faced most. The rest need at least "
        f"{MIN_MEETINGS} meetings, so a hot streak over two games cannot claim "
        "a title. Tightest uses the unsigned margin, so alternating blowouts "
        "do not masquerade as close games."
    )

    profile_rows = []
    for mgr in sorted(h2h_agg["manager"].unique()):
        d = h2h_agg[h2h_agg["manager"] == mgr]
        q = d[d["games"] >= MIN_MEETINGS]
        row = {"Manager": mgr}

        mp = d.loc[d["games"].idxmax()] if len(d) else None
        row["Most Played"] = f"{mp.opp_manager} ({int(mp.games)})" if mp is not None else "—"

        if len(q):
            # balance: closest to even, ties broken by who has been met more
            q = q.assign(_bal=1 - 2 * (q["wins"] / q["games"] - 0.5).abs())
            bal = q.sort_values(["_bal", "games"], ascending=[False, False]).iloc[0]
            tight = q.sort_values("absmar").iloc[0]
            wp = q["wins"] / q["games"]
            nem = q.loc[wp.idxmin()]
            vic = q.loc[wp.idxmax()]
            row["Most Balanced"] = f"{bal.opp_manager} ({int(bal.wins)}-{int(bal.losses)})"
            row["Tightest"] = f"{tight.opp_manager} ({tight.absmar:.1f})"
            row["Bully"] = f"{nem.opp_manager} ({int(nem.wins)}-{int(nem.losses)})"
            row["Bully-ee"] = f"{vic.opp_manager} ({int(vic.wins)}-{int(vic.losses)})"
        else:
            for c in ("Most Balanced", "Tightest", "Bully", "Bully-ee"):
                row[c] = "—"
        profile_rows.append(row)

    st.dataframe(pd.DataFrame(profile_rows), hide_index=True,
                 use_container_width=True)

    st.divider()
    st.divider()
    st.subheader("Every Matchup")
    st.caption("Regular season only.")

    _opts = sorted(h2h_src["manager"].unique())
    c1, c2 = st.columns(2)
    with c1:
        mgr_a = st.selectbox("Manager A", _opts, key="every_a")
    with c2:
        _b_opts = [m for m in _opts if m != mgr_a] or _opts
        mgr_b = st.selectbox("Manager B", _b_opts, key="every_b")

    if mgr_a == mgr_b:
        st.info("Pick two different managers.")
    else:
        meet = (h2h_src[(h2h_src["manager"] == mgr_a)
                        & (h2h_src["opp_manager"] == mgr_b)]
                .sort_values(["season", "week"]))
        if meet.empty:
            st.info(f"{mgr_a} and {mgr_b} have never met in the regular season.")
        else:
            a_w = int((meet["outcome"] == "W").sum())
            b_w = int((meet["outcome"] == "L").sum())
            tied = int((meet["outcome"] == "T").sum())

            games = []
            for r in meet.itertuples():
                if r.score > r.opp_score:
                    winner = mgr_a
                elif r.opp_score > r.score:
                    winner = mgr_b
                else:
                    winner = "Tie"
                games.append({
                    "Year": str(int(r.season)),
                    "Week": int(r.week),
                    mgr_a: f"{r.score:.2f}",
                    mgr_b: f"{r.opp_score:.2f}",
                    "Winner": winner,
                })
            st.dataframe(pd.DataFrame(games), hide_index=True,
                         use_container_width=True)
            summary = f"{mgr_a} leads {a_w}-{b_w}" if a_w > b_w else (
                f"{mgr_b} leads {b_w}-{a_w}" if b_w > a_w else
                f"All square at {a_w}-{b_w}")
            st.caption(
                f"{len(meet)} meeting{'s' if len(meet) != 1 else ''}. {summary}"
                + (f", with {tied} tie{'s' if tied != 1 else ''}." if tied else ".")
            )



# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: MILESTONES
# ══════════════════════════════════════════════════════════════════════════════
with tab_milestones:
    view_toggle("milestones")
    st.subheader("Win & Loss Milestones")
    st.caption(
        "Regular season only. Numbers show career game # (game played) when each milestone was reached. "
        "— = not yet reached."
    )

    # Sort all reg season games by season then week (career chronological order)
    career_games = (
        reg_matchups
        .sort_values(["manager", "season", "week"])
        .copy()
    )
    career_games["career_game"] = career_games.groupby("manager").cumcount() + 1
    career_games["cum_wins"] = career_games.groupby("manager")["outcome"].transform(
        lambda x: (x == "W").cumsum()
    )
    career_games["cum_losses"] = career_games.groupby("manager")["outcome"].transform(
        lambda x: (x == "L").cumsum()
    )

    max_wins = int(career_games["cum_wins"].max())
    max_losses = int(career_games["cum_losses"].max())
    win_milestones = list(range(25, max_wins + 1, 25))
    loss_milestones = list(range(25, max_losses + 1, 25))

    def milestone_table(cumcol, milestones, label):
        rows = []
        for mgr in sorted(career_games["manager"].unique()):
            m_df = career_games[career_games["manager"] == mgr]
            row = {"Manager": mgr}
            for ms in milestones:
                hit = m_df[m_df[cumcol] >= ms]
                # Rendered as text: a column mixing ints with the em-dash
                # placeholder is an object column, which Arrow cannot serialise
                # and Streamlit then fails to display.
                row[f"{ms} {label}"] = (
                    str(int(hit["career_game"].min())) if not hit.empty else "—"
                )
            rows.append(row)
        return pd.DataFrame(rows)

    st.markdown("#### Wins")
    if win_milestones:
        win_table = milestone_table("cum_wins", win_milestones, "W")
        st.dataframe(win_table, hide_index=True, use_container_width=True)
    else:
        st.info("Not enough wins recorded yet.")

    st.markdown("#### Losses")
    if loss_milestones:
        loss_table = milestone_table("cum_losses", loss_milestones, "L")
        st.dataframe(loss_table, hide_index=True, use_container_width=True)
    else:
        st.info("Not enough losses recorded yet.")
