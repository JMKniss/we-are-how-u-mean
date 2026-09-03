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
      Seeds 9–10 → Sacko bowl. All playoff weeks cumulative. Lower total = 10th.

    2022 (3-week format): R1 = pw[0] only. Finals = pw[1]+pw[2].
    Sacko = all 3 weeks cumulative.

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

    # Sacko bowl: all playoff weeks cumulative, lower total = 10th
    s0 = team_cum(sacko_ids[0], pw)
    s1 = team_cum(sacko_ids[1], pw)
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
                pf = round(grp["score"].sum(), 2)
                pa = round(grp["opp_score"].sum(), 2)
                games = wins + losses
                season_stats_rows.append({
                    "season": season,
                    "team_id": team_id,
                    "manager": mgr,
                    "reg_wins": wins,
                    "reg_losses": losses,
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

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_trophy, tab_records, tab_mgr_records, tab_seasons, tab_h2h, tab_milestones = st.tabs([
    "🏆 Trophy Case",
    "📊 League Records",
    "👤 Manager Records",
    "📅 Season-by-Season",
    "⚔️ Head to Head",
    "🎯 Milestones",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: TROPHY CASE
# ══════════════════════════════════════════════════════════════════════════════
with tab_trophy:
    st.subheader("Career Summary")

    PLAYOFF_SPOTS = 4          # seeds 1-4 make the championship bracket
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
        games = wins + losses
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

        rows.append({
            "Manager": mgr,
            "Years": year_ranges(g["season"]),
            "W": wins,
            "L": losses,
            "Win%": round(wins / games * 100, 1) if games else 0.0,
            "Playoffs": (int((g["seed"].between(1, PLAYOFF_SPOTS)).sum())
                         + legacy_playoffs.get(mgr, 0)),
            "Finishes": "  ".join(parts),
        })

    career = pd.DataFrame(rows).sort_values("W", ascending=False).reset_index(drop=True)
    career.index = range(1, len(career) + 1)
    st.dataframe(career, use_container_width=True)

    st.caption(
        f"Regular season head-to-head only; median wins are not counted. "
        f"Playoffs counts seasons seeded in the top {PLAYOFF_SPOTS}. "
        f"Finishes: {MEDAL[1]} 1st · {MEDAL[2]} 2nd · {MEDAL[3]} 3rd · {SACKO} last. "
        f"2015 predates the league data, so Mikey's title and Tyler's sacko that "
        f"year are included in Finishes but in no other column."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: LEAGUE RECORDS
# ══════════════════════════════════════════════════════════════════════════════
with tab_records:
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
    st.markdown("#### Single-Season Win Records")

    def wins_record_rows(label, df, col, largest=True):
        rows = tied_extreme(df, col, largest)
        if rows.empty:
            return [{"Record": label, "Manager": "—", "Season": "—", "Wins": "—", "Finish": "—"}]
        lbl = f"{label} (tie)" if len(rows) > 1 else label
        return [{"Record": lbl, "Manager": r["manager"], "Season": str(int(r["season"])),
                 "Wins": int(r[col]), "Finish": finish_label(r["final_standing"])}
                for _, r in rows.iterrows()]

    win_records = pd.DataFrame(
        wins_record_rows("Most Reg Season Wins",   season_stats_df, "reg_wins",  largest=True) +
        wins_record_rows("Fewest Reg Season Wins", season_stats_df, "reg_wins",  largest=False) +
        wins_record_rows("Most Full Season Wins",  season_stats_df, "full_wins", largest=True) +
        wins_record_rows("Fewest Full Season Wins",season_stats_df, "full_wins", largest=False)
    )
    st.dataframe(win_records, hide_index=True, use_container_width=True)

    # ── Scoring season records ─────────────────────────────────────────────
    st.markdown("#### Season Scoring Records (Regular Season Only)")
    scoring_record_specs = [
        ("Highest Total PF",       "pf",         True),
        ("Lowest Total PF",        "pf",         False),
        ("Highest Total PA",       "pa",         True),
        ("Lowest Total PA",        "pa",         False),
        ("Highest Avg PF",         "avg_pf",     True),
        ("Lowest Avg PF",          "avg_pf",     False),
        ("Highest Avg PA",         "avg_pa",     True),
        ("Lowest Avg PA",          "avg_pa",     False),
        ("Highest Total Pt Diff",  "point_diff", True),
        ("Lowest Total Pt Diff",   "point_diff", False),
        ("Highest Avg Pt Diff",    "avg_diff",   True),
        ("Lowest Avg Pt Diff",     "avg_diff",   False),
    ]
    all_scoring_rows = []
    for label, col, largest in scoring_record_specs:
        all_scoring_rows += season_record_rows(label, season_stats_df, col, largest)
    st.dataframe(pd.DataFrame(all_scoring_rows), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: MANAGER RECORDS
# ══════════════════════════════════════════════════════════════════════════════
with tab_mgr_records:
    st.subheader("Best & Worst Season by Manager")
    st.caption("All stats are regular season only unless noted. ⭐ = most extreme across all managers.")

    managers = sorted(season_stats_df["manager"].unique())

    # Column definitions: (display_name, raw_name, src_col, largest)
    # largest=True  → higher raw value is more extreme (e.g. best RegW = max)
    # largest=False → lower raw value is more extreme (e.g. worst RegW = min)
    col_specs = [
        ("Best RegW (Yr)",   "_best_rw",  "reg_wins",    True),
        ("Worst RegW (Yr)",  "_worst_rw", "reg_wins",    False),
        ("Best Full W (Yr)", "_best_fw",  "full_wins",   True),
        ("High PF (Yr)",     "_high_pf",  "pf",          True),
        ("Low PF (Yr)",      "_low_pf",   "pf",          False),
        ("High PA (Yr)",     "_high_pa",  "pa",          True),
        ("Low PA (Yr)",      "_low_pa",   "pa",          False),
        ("High Diff (Yr)",   "_high_pd",  "point_diff",  True),
        ("Low Diff (Yr)",    "_low_pd",   "point_diff",  False),
    ]

    # Build rows with raw numeric values for finding extremes later
    raw_rows = []
    for mgr in managers:
        m_df = season_stats_df[season_stats_df["manager"] == mgr]
        if m_df.empty:
            continue
        row = {"Manager": mgr}
        for disp, raw, src, largest in col_specs:
            best = m_df.nlargest(1, src) if largest else m_df.nsmallest(1, src)
            if not best.empty:
                row[raw] = round(best[src].values[0], 2)
                row[f"{raw}_yr"] = int(best["season"].values[0])
            else:
                row[raw] = None
                row[f"{raw}_yr"] = None
        raw_rows.append(row)

    raw_df = pd.DataFrame(raw_rows)

    # Find the cross-manager extreme for each column
    extremes = {}
    for disp, raw, src, largest in col_specs:
        col_vals = raw_df[raw].dropna()
        if not col_vals.empty:
            extremes[raw] = col_vals.max() if largest else col_vals.min()
        else:
            extremes[raw] = None

    # Build display DataFrame, appending ⭐ to the extreme cell
    display_rows = []
    for _, r in raw_df.iterrows():
        display_row = {"Manager": r["Manager"]}
        for disp, raw, src, largest in col_specs:
            val = r[raw]
            yr = r[f"{raw}_yr"]
            if val is None:
                display_row[disp] = "—"
            else:
                is_int = src in ("reg_wins", "full_wins")
                val_str = f"{int(val)}" if is_int else f"{val:.2f}"
                cell = f"{val_str} ({yr})"
                if extremes.get(raw) is not None and val == extremes[raw]:
                    cell += " ⭐"
                display_row[disp] = cell
        display_rows.append(display_row)

    stat_col_width = 155
    col_config = {disp: st.column_config.TextColumn(disp, width=stat_col_width)
                  for disp, raw, src, largest in col_specs}
    st.dataframe(pd.DataFrame(display_rows), hide_index=True,
                 use_container_width=True, column_config=col_config)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: SEASON-BY-SEASON
# ══════════════════════════════════════════════════════════════════════════════
with tab_seasons:
    st.subheader("Every Manager's Season-by-Season Record")
    st.caption("W/L = regular season H2H. Full W = reg + playoff rounds won. Finish = ESPN final standing.")

    display_cols = {
        "manager": "Manager",
        "season": "Season",
        "reg_wins": "W",
        "reg_losses": "L",
        "playoff_wins": "Playoff W",
        "full_wins": "Full W",
        "pf": "PF",
        "pa": "PA",
        "avg_pf": "Avg PF",
        "avg_diff": "Avg Diff",
        "final_standing": "Finish",
    }
    disp = season_stats_df[list(display_cols.keys())].copy()
    disp = disp.rename(columns=display_cols)
    disp["Season"] = disp["Season"].astype(str)
    disp["Finish"] = disp["Finish"].apply(finish_label)
    disp = disp.sort_values(["Manager", "Season"])

    # Optional filter by manager
    mgr_filter = st.selectbox("Filter by manager", ["All"] + sorted(season_stats_df["manager"].unique()))
    if mgr_filter != "All":
        disp = disp[disp["Manager"] == mgr_filter]

    st.dataframe(disp, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: HEAD TO HEAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_h2h:
    st.subheader("Head-to-Head Manager Records")
    st.caption("Regular season matchups only. Each game counted once per side.")

    # H2H summary table (row manager vs col managers)
    h2h_agg = (
        reg_matchups
        .groupby(["manager", "opp_manager"])
        .agg(
            wins=("outcome", lambda x: (x == "W").sum()),
            losses=("outcome", lambda x: (x == "L").sum()),
            pf=("score", "sum"),
            pa=("opp_score", "sum"),
            games=("outcome", "count"),
        )
        .reset_index()
    )
    h2h_agg["avg_diff"] = ((h2h_agg["pf"] - h2h_agg["pa"]) / h2h_agg["games"]).round(2)
    h2h_agg["record"] = h2h_agg["wins"].astype(str) + "-" + h2h_agg["losses"].astype(str)

    managers_h2h = sorted(h2h_agg["manager"].unique())

    # Select a manager to view their H2H breakdown
    selected_mgr = st.selectbox("View matchups for:", managers_h2h)
    mgr_h2h = h2h_agg[h2h_agg["manager"] == selected_mgr].copy()
    mgr_h2h = mgr_h2h.sort_values("wins", ascending=False)
    disp = mgr_h2h[["opp_manager", "record", "wins", "losses", "games", "avg_diff"]].rename(columns={
        "opp_manager": "Opponent",
        "record": "Record",
        "wins": "W",
        "losses": "L",
        "games": "G",
        "avg_diff": "Avg Margin",
    })
    st.dataframe(disp, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Win Matrix")
    st.caption("Rows = winner, Columns = opponent. Cell = number of times row beat column.")
    matrix = h2h_agg.pivot_table(index="manager", columns="opp_manager",
                                  values="wins", fill_value=0)
    st.dataframe(matrix.astype(int), use_container_width=True)

    st.divider()
    st.subheader("Career Totals (H2H, Regular Season + Playoff Rounds)")

    # Career reg season wins/losses
    career_reg = (
        reg_matchups.groupby("manager")
        .agg(
            reg_wins=("outcome", lambda x: (x == "W").sum()),
            reg_losses=("outcome", lambda x: (x == "L").sum()),
            games=("outcome", "count"),
            pf=("score", "sum"),
            pa=("opp_score", "sum"),
        )
        .reset_index()
    )
    career_reg["avg_pf"] = (career_reg["pf"] / career_reg["games"]).round(2)
    career_reg["win_pct"] = (career_reg["reg_wins"] / career_reg["games"]).round(3)

    career_playoff = (playoff_wins_df.groupby("manager")["playoff_wins"].sum().reset_index()
                      if not playoff_wins_df.empty else pd.DataFrame(columns=["manager", "playoff_wins"]))

    career = career_reg.merge(career_playoff, on="manager", how="left")
    career["playoff_wins"] = career["playoff_wins"].fillna(0).astype(int)
    career["total_wins"] = career["reg_wins"] + career["playoff_wins"]
    career = career.sort_values("total_wins", ascending=False)

    career_disp = career[["manager", "reg_wins", "reg_losses", "playoff_wins", "total_wins",
                           "games", "win_pct", "avg_pf"]].rename(columns={
        "manager": "Manager",
        "reg_wins": "Reg W",
        "reg_losses": "Reg L",
        "playoff_wins": "Playoff W",
        "total_wins": "Total W",
        "games": "Reg Games",
        "win_pct": "Win %",
        "avg_pf": "Avg PF",
    })
    career_disp["Win %"] = career_disp["Win %"].apply(lambda x: f"{x:.1%}")
    st.dataframe(career_disp, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: MILESTONES
# ══════════════════════════════════════════════════════════════════════════════
with tab_milestones:
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
