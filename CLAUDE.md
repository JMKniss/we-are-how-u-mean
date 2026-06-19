# We Are How U Mean — Fantasy Football Analytics App

## What this is
A Streamlit web app for analyzing a 10-team ESPN fantasy football league (ID: 722346).
Pulls all data live from ESPN's API — no manual data entry. Built from scratch in June 2026
to replace a manual Jupyter notebook workflow.

## How to run
```
cd ff_app
streamlit run app.py
```
App runs at http://localhost:8501. Keep the terminal open while using it.

## Project structure
```
ff_app/
├── app.py                  # Streamlit home page / entry point
├── config.py               # League ID, seasons list, credentials (loaded from .env)
├── .env                    # ESPN_S2 and SWID cookies — NOT committed to git
├── requirements.txt
├── data/
│   ├── espn_client.py      # All ESPN API calls + pickle cache
│   └── cache/<year>/       # Cached .pkl files — gitignored, auto-created
├── analysis/
│   ├── standings.py        # H2H, median, combined, SOS, luck index, alternate schedule
│   ├── efficiency.py       # Lineup efficiency, bench waste, top players, proj vs actual
│   └── projections.py      # Monte Carlo playoff simulation, magic numbers
└── pages/
    ├── 1_Dashboard.py
    ├── 2_Standings.py
    ├── 3_Scoring.py
    ├── 4_Lineup_Efficiency.py
    ├── 5_Playoff_Projections.py
    └── 6_Draft_Review.py
```

## Data layer — espn_client.py
- All functions check a local pickle cache before hitting ESPN
- Cache lives at `data/cache/<season>/`. Delete a folder to force a fresh pull
- "Refresh Data" button in every page sidebar calls `invalidate_cache(season)` then reruns
- `get_league(season)` — returns the raw espn-api League object
- `get_matchups_df(season)` — team-level weekly scores and outcomes (W/L/T)
- `get_boxscores_df(season)` — player-level data: points, projected, slot, bench/active
- `get_draft_df(season)` — full draft board with keeper flags
- `get_standings_df(season)` — final standings metadata from ESPN

## ESPN credentials
- 2024 and 2025 are public (no auth needed)
- 2019–2023 require ESPN_S2 and SWID cookies (private league)
- Stored in `.env`, loaded via `python-dotenv` in `config.py`
- Cookies expire periodically — refresh from browser (espn.com → F12 → Application → Cookies)
- SWID: `{5D972E08-482D-493A-972E-08482DD93A4E}` (stable, rarely changes)
- ESPN_S2: changes — update `.env` when old seasons stop loading

## League facts
- League ID: 722346
- Name: "We Are How U Mean"
- Seasons available: 2019–2025 (7 seasons)
- Teams: 10
- Regular season: weeks 1–13 (`REG_SEASON_WEEKS = 13` in config.py)
- Playoffs: weeks 14–17
- Playoff spots: 4

## Key design decisions and why

**Streamlit over Jupyter:** The old workflow required manually entering scores each week into
a notebook. Streamlit gives interactive dropdowns, live charts, and hot-reload editing without
re-running cells.

**Pickle cache over parquet:** espn-api returns Python objects (League, Team, etc.) that
can't be serialized to parquet. Pickle preserves the full object graph.

**espn-api library over raw requests:** Previous attempts at raw ESPN API calls failed due to
cookie/auth complexity and ESPN returning HTML instead of JSON. The library handles all of that.

**Credentials in .env, not hardcoded:** ESPN_S2 expires. Keeping it in .env means updating
one file, not hunting through code. The .gitignore excludes .env* so credentials never hit GitHub.

**Season selector on every page:** Users want to compare seasons. All pages accept a season
param and the sidebar selector is consistent across all pages.

**Luck index formula:** `actual_wins - expected_wins` where expected = score percentile rank
each week. A team scoring in the 80th percentile every week "should" win ~80% of games.
Outperforming that = lucky schedule; underperforming = unlucky.

**Alternate schedule:** For each team, count wins vs every other team every week (N-1 games
per week). Reveals whether a team's record reflects their scoring or their schedule.

**Monte Carlo playoff sim:** Uses each team's mean/std from games played so far. Samples
from a normal distribution for each remaining game. 10,000 sims by default.

## Analysis modules

### standings.py
- `h2h_standings(df)` — standard record, PF, PA, avg score
- `median_standings(df)` — wins/losses vs weekly league median
- `combined_standings(df)` — H2H + median combined (2 games/week)
- `strength_of_schedule(df)` — avg opponent score faced
- `luck_index(df)` — actual wins vs expected wins by score percentile
- `alternate_schedule_standings(df)` — wins if you played everyone every week
- `weekly_scores_wide(df)` — pivot to wide format for charting

### efficiency.py
- `lineup_efficiency(df)` — actual vs optimal score, bench waste, per week and season summary
- `top_players(df, position, top_n)` — leaderboard of player season totals
- `projected_vs_actual(df)` — how often each team beats ESPN's projection

### projections.py
- `simulate_playoffs(df, ...)` — Monte Carlo, returns playoff % per team
- `win_probability_by_score(score, opp_mean, opp_std)` — single-game win prob via normal CDF

## Git workflow
- Main repo: https://github.com/JMKniss/we-are-how-u-mean
- Default branch: master
- Feature branches for changes, PRs to merge into master
- Current branch: feature/ui-improvements

## Pages overview

### 1_Dashboard.py
Current week matchups, quick stat metrics, standings snapshot + luck index side by side,
full weekly scoring line chart with league median overlay.

### 2_Standings.py
Six tabs: H2H | vs Median | Combined | Strength of Schedule | Luck Index | Alternate Schedule.
Each tab has a table + relevant chart.

### 3_Scoring.py
Four tabs: Weekly Trends (multi-team line chart + range band) | Score Distributions (box plot,
histogram with normal fit) | Best & Worst (top/bottom scores, highest-scoring matchups) |
Head-to-Head (any team vs any, H2H matrix).

### 4_Lineup_Efficiency.py
Four tabs: Season Summary | Weekly Efficiency by team | Top Players (filterable by position) |
Projections vs Actual.

### 5_Playoff_Projections.py
Three tabs: Playoff Odds (Monte Carlo) | Score Distribution params | Magic Numbers +
elimination tracker.

### 6_Draft_Review.py
Three tabs: Full Draft Board (snake grid) | Team Draft Summary | Draft Value (scatter,
best value picks, biggest busts).
