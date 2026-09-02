"""
Data Validation — internal data quality page.
Not intended for league sharing. Verifies that our player-sum calculated
scores reconcile with ESPN's reported scores for all weeks and seasons.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
from data.espn_client import get_validation_df, get_manager_map
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import sidebar_display_prefs, prep_display

st.set_page_config(page_title="Data Validation", page_icon="🔧", layout="wide")
st.title("🔧 Data Validation")
st.caption(
    "Internal data quality checks. Verifies our player-sum calculated scores "
    "against ESPN's reported values. Not for league distribution."
)

TOLERANCE = 0.1  # pts — differences within this are rounding, not errors

if "selected_season" not in st.session_state:
    st.session_state["selected_season"] = DEFAULT_SEASON
season = st.sidebar.selectbox(
    "Season", SEASONS,
    index=SEASONS.index(st.session_state["selected_season"])
)
st.session_state["selected_season"] = season
all_seasons = st.sidebar.checkbox("Check all seasons at once", value=False)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=600)
def load_validation(season):
    return get_validation_df(season)

@st.cache_data(ttl=600)
def load_manager_map(season):
    return get_manager_map(season)

# ── Load data ────────────────────────────────────────────────────────────────
seasons_to_check = SEASONS if all_seasons else [season]

with st.spinner("Running validation checks..."):
    dfs = []
    mgr_maps = {}
    for y in seasons_to_check:
        try:
            dfs.append(load_validation(y))
            mgr_maps[y] = load_manager_map(y)
        except Exception as e:
            st.error(f"{y}: failed — {e}")
    val_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

if val_df.empty:
    st.warning("No validation data available.")
    st.stop()

# Build a combined manager_map across all seasons (latest mapping wins for same team_id)
combined_mgr_map = {}
for y in seasons_to_check:
    combined_mgr_map.update(mgr_maps.get(y, {}))

val_df["abs_diff"] = val_df["diff"].abs()
val_df["status"] = val_df["abs_diff"].apply(
    lambda d: "✅ OK" if d <= TOLERANCE else "⚠️ MISMATCH"
)

# ── Summary banner ───────────────────────────────────────────────────────────
total = len(val_df)
mismatches = (val_df["abs_diff"] > TOLERANCE).sum()
ok = total - mismatches

col1, col2, col3, col4 = st.columns(4)
col1.metric("Checks Run", total)
col2.metric("✅ Passed", ok)
col3.metric("⚠️ Mismatches", mismatches, delta=None if mismatches == 0 else f"{mismatches} issues")
col4.metric("Tolerance", f"±{TOLERANCE} pts")

if mismatches == 0:
    st.success("All scores validated. Player sums reconcile with ESPN reported values within tolerance.")
else:
    st.warning(f"{mismatches} discrepancies found exceeding ±{TOLERANCE} pts. Review the Mismatches tab.")

st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["Summary by Check Type", "Regular Season Detail", "Playoff Detail", "Mismatches"])

with tab1:
    st.subheader("Validation Summary by Check Type")
    summary = val_df.groupby(["season", "check_type"]).agg(
        checks=("diff", "count"),
        mismatches=("abs_diff", lambda x: (x > TOLERANCE).sum()),
        avg_diff=("diff", "mean"),
        max_abs_diff=("abs_diff", "max"),
    ).reset_index().round(3)
    summary.columns = ["Season", "Check Type", "Checks", "Mismatches", "Avg Diff", "Max |Diff|"]
    st.dataframe(summary, use_container_width=True, hide_index=True)

    fig = px.bar(
        summary, x="Season", y="Max |Diff|", color="Check Type", barmode="group",
        title="Max Score Discrepancy by Season and Check Type",
        labels={"Max |Diff|": "Max |Diff| (pts)"},
    )
    fig.add_hline(y=TOLERANCE, line_dash="dash", line_color="red",
                  annotation_text=f"Tolerance ({TOLERANCE} pts)")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Regular Season — Player Sum vs ESPN Reported")
    st.caption("Each row is one team-week. Our score = sum of active player points. ESPN score = box_scores team total.")
    reg = val_df[val_df["check_type"] == "regular_season"].copy()
    if reg.empty:
        st.info("No regular season data.")
    else:
        filter_mismatches = st.checkbox("Show mismatches only", key="reg_mismatch")
        if filter_mismatches:
            reg = reg[reg["status"] == "⚠️ MISMATCH"]

        display = prep_display(reg, combined_mgr_map, show_mgr, show_team,
                               cols=["team_name", "season", "week", "our_score", "espn_score", "diff", "status"],
                               headers=["Team", "Season", "Week", "Our Score", "ESPN Score", "Diff", "Status"])

        st.dataframe(
            display.style.apply(
                lambda row: ["background-color: #fff3cd" if row["Status"] == "⚠️ MISMATCH" else "" for _ in row],
                axis=1,
            ),
            use_container_width=True,
            hide_index=True,
        )

        fig = px.histogram(reg, x="diff", nbins=40, title="Distribution of Score Differences (regular season)",
                           labels={"diff": "Our Score − ESPN Score", "count": "Weeks"})
        fig.add_vline(x=0, line_dash="solid", line_color="gray")
        fig.add_vline(x=TOLERANCE, line_dash="dash", line_color="orange", annotation_text="+tol")
        fig.add_vline(x=-TOLERANCE, line_dash="dash", line_color="orange", annotation_text="-tol")
        st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Playoff Reconciliation")
    st.caption(
        "Verifies that our summed individual week scores add up to ESPN's cumulative matchup totals. "
        "Round 1: wk_a + wk_b player sums vs ESPN round total. "
        "Toilet Bowl / Sacko: cumulative weeks vs ESPN total."
    )
    if season == 2022:
        st.info(
            "**2022 note:** The 2022 playoff bracket was managed manually outside ESPN "
            "(the actual structure was wks 14+15 = Round 1, wks 16+17 = Round 2, wks 14–17 = Sacko Bowl). "
            "ESPN did not track the correct playoff pairings, so validation here checks player-sum accuracy "
            "against ESPN's internal cumulative totals rather than the true bracket. "
            "All individual weekly scores are accurate; only the bracket structure is absent from ESPN."
        )
    playoff_types = ["playoff_round1", "playoff_round2", "toilet_bowl"]
    play = val_df[val_df["check_type"].isin(playoff_types)].copy()
    if play.empty:
        st.info("No playoff validation data (season may not have reached playoffs yet).")
    else:
        type_labels = {
            "playoff_round1": "Round 1",
            "playoff_round2": "Round 2",
            "playoff_round3": "Round 3 (non-standard fmt)",
            "toilet_bowl": "Toilet Bowl",
        }
        play["Check"] = play["check_type"].map(type_labels)
        display = prep_display(play, combined_mgr_map, show_mgr, show_team,
                               cols=["team_name", "season", "Check", "our_score", "espn_score", "diff", "status"],
                               headers=["Team", "Season", "Round", "Our Total", "ESPN Total", "Diff", "Status"])
        st.dataframe(
            display.style.apply(
                lambda row: ["background-color: #fff3cd" if row["Status"] == "⚠️ MISMATCH" else "" for _ in row],
                axis=1,
            ),
            use_container_width=True,
            hide_index=True,
        )

        cfg = season_config(season)
        pw = cfg["playoff_weeks"]
        if len(pw) == 3:
            st.info(
                f"**{season} playoff structure:** "
                f"Round 1 = week {pw[0]} (1-week) | "
                f"Finals = weeks {pw[1]}+{pw[2]} | "
                f"Sacko Bowl = weeks {pw[0]}–{pw[2]} cumulative (3 weeks)"
            )
        else:
            st.info(
                f"**{season} playoff structure:** "
                f"Round 1 = weeks {pw[0]}+{pw[1]} | "
                f"Round 2 = weeks {pw[2]}+{pw[3]} | "
                f"Toilet Bowl = weeks {pw[0]}–{pw[3]} cumulative"
            )

with tab4:
    st.subheader("⚠️ All Mismatches")
    mismatches_df = val_df[val_df["abs_diff"] > TOLERANCE].copy()
    if mismatches_df.empty:
        st.success("No mismatches found across all checks.")
    else:
        display = prep_display(mismatches_df.sort_values("abs_diff", ascending=False),
                               combined_mgr_map, show_mgr, show_team,
                               cols=["team_name", "season", "check_type", "week", "our_score", "espn_score", "diff"],
                               headers=["Team", "Season", "Check Type", "Week", "Our Score", "ESPN Score", "Diff"])
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown("**Possible causes of mismatches:**")
        st.markdown("""
- **Stat corrections** — ESPN occasionally adjusts player stats after the week ends (late corrections to boxscores). Our player sum captures the state at time of data pull.
- **D/ST scoring** — some league settings score defense differently; slot filtering may miss edge cases.
- **Flex/IDP slots** — unusual roster configurations may have slot names we're not filtering correctly.
- **Timing** — data pulled mid-week before all stats are finalised.
""")
