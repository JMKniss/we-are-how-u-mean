# We Are How U Mean — Fantasy Football Analytics App

## What this is
A Streamlit web app for a 10-team ESPN fantasy football league (ID: 722346), live at
wearehowumean.com. It reads a committed CSV archive, not ESPN — the only thing that talks
to ESPN is the weekly update, run by hand. Built from scratch in June 2026 to replace a
manual Jupyter notebook workflow.

The legacy notebook analysis lives in a separate repo: https://github.com/JMKniss/fantasy-league-stats

## Start here

Nothing in this file is a snapshot, deliberately. Anything dated would be
wrong within a week and worse than absent, because a stale fact reads as a
current one. To see where the project actually stands:

```
python build_archive.py --list     what the archive holds, season by season
python check.py --quick            do the pages still render
git log --oneline -15              what was done recently, and why
```

Commit messages here carry the reasoning, not just the change. A "why is this
like this" question is usually answered faster by `git log -S<thing>` than by
reading the code around it.

## Verifying a change

`python check.py` renders every page against every season and prints one line
each. Scale it to what changed — a full sweep after a caption edit is wasted
time and wasted context:

| Changed | Run |
|---|---|
| `config.py`, `display_utils.py`, `app.py`, `branding.py`, `data/`, `analysis/` | `python check.py` |
| one page | `python check.py Standings` |
| a caption, a label, a colour | nothing; the file parsing is enough |

It catches the three things that have actually broken this app: an exception
on some seasons but not others, a dataframe Streamlit silently repairs before
serialising, and a page that renders nothing at all.

## Keeping this file current

This is a living document and the only thing that makes a fresh session
productive. Update it in the same commit as the change, never afterwards:

| When you change | Update the section |
|---|---|
| how a season's schedule or playoff shape works | Season quirks |
| where data comes from, or how it is stored | Data storage, Data layer |
| the weekly job, the deploy, the archive's shape | The weekly update, Deployment |
| something you had to think about | Key design decisions — say *why*, not what |
| a page's structure or what it shows | that page's docstring |

Two rules that keep it from rotting:

- **No status notes.** If a fact will be wrong next month, it belongs in git
  or in the archive, not here. "Currently on 2026 week 1" is a bug.
- **Record the reasoning, not the outcome.** The outcome is visible in the
  code. What is expensive to rediscover is why the obvious approach was
  wrong — those notes are what stop a later session re-making a decision that
  has already been paid for.

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
├── config.py               # League ID, seasons list, manager/owner maps, season_config()
├── display_utils.py        # Shared display helpers: sidebar_display_prefs, prep_display, chart_label
├── .env                    # ESPN_S2 and SWID cookies — NOT committed to git
├── requirements.txt
├── data/
│   ├── espn_client.py      # All ESPN API calls + pickle cache
│   ├── legacy_stats.py     # nfl-data-py stats for 2016-2017 seasons
│   ├── trade_inference.py  # rebuilds a finished season's trades from weekly rosters
│   ├── game_status.py      # did each player play, at game time (nflverse; build-time only)
│   └── cache/<year>/       # Cached .pkl files — gitignored, auto-created
├── analysis/
│   ├── standings.py        # H2H, median, combined, SOS, luck index, alternate schedule
│   ├── efficiency.py       # Lineup efficiency, bench waste, top players, proj vs actual
│   ├── projections.py      # Monte Carlo playoff simulation, magic numbers
│   ├── draft_value.py      # Draft value: VOR per game against a frozen per-season curve
│   └── transactions.py     # Waiver moves and trade sides from the transactions log
└── views/
    ├── 1_Dashboard.py
    ├── 2_Standings.py
    ├── 3_Scoring.py
    ├── 4_Lineup_Efficiency.py
    ├── 5_Playoffs.py           # bracket + projections, one page
    ├── 7_Draft_Waivers_Trades.py   # draft tabs + waiver and trade trackers; still /Draft_Review
    ├── 8_Data_Validation.py    # hidden from the nav; /Data_Validation still works
    └── 9_All_Time.py
```

## Where the detail lives

This file holds what no single source file reveals: the season quirks, ESPN's
oddities, the weekly workflow, and why the awkward decisions were made. Detail
that belongs to one file lives in that file's docstring, so it is read when
the file is opened rather than loaded into every session:

| Topic | Read |
|---|---|
| Data layer, read order, caching | `data/espn_client.py` |
| Upcoming fixtures and projections | `get_upcoming_df` in `data/espn_client.py` |
| Waivers, drops, trades: sources, shape, gaps | `get_transactions_df` in `data/espn_client.py` |
| Rebuilding past trades, and the evidence for it | `data/trade_inference.py` |
| Game-time injury status: categories, sources, accuracy | `data/game_status.py` |
| Every player's weekly points, rostered or not | `get_player_weeks_df` in `data/espn_client.py` |
| Draft value: the formula, and why each part is shaped as it is | `analysis/draft_value.py` |
| Matchups-to-watch notes | `analysis/matchup_notes.py` |
| Browser icon and title | `branding.py`, `assets/README.md` |
| Shared page helpers | `display_utils.py` |
| A page's own behaviour | that page's docstring in `views/` |

Keep it that way: when a section here starts describing one file, move it
into that file.

## Deployment — wearehowumean.com on Render

A Render **Web Service**, created by hand in the dashboard. Blueprints
(render.yaml) want a Pro plan, so the settings live here instead of in a file:

| Setting | Value |
|---|---|
| Repository | `JMKniss/we-are-how-u-mean` |
| Branch | `master` |
| Root Directory | *(blank — app.py is at the repo root)* |
| Language | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `streamlit run app.py --server.port $PORT --server.address 0.0.0.0` |
| Health Check Path | `/_stcore/health` |
| Env var | `PYTHON_VERSION` = `3.12.2` |
| Env var | `APP_PASSWORD` = *(set to gate the site; unset means public)* |

Auto-deploy on push is a Web Service feature and is on by default, so the
push-to-deploy loop works exactly as it would have under a blueprint.

**Plan.** Starter, 512MB, always on. Measured peak is 258MB with every page
loaded for every season in one process, which is the worst the caches get -
st.cache_data is global, so more viewers do not multiply it. The free tier is
ruled out by spin-down rather than memory: it sleeps after roughly 15 minutes
idle, and a site checked a few times a week would cold-start almost every
visit.

**The server needs no ESPN credentials.** Every page reads
`data/archive/*.csv`. ESPN_S2 and SWID stay on the machine that runs
`weekly_update.py`, which is the whole reason the archive exists.

**requirements.txt is runtime only.** `requirements-build.txt` adds
nfl-data-py, which supplies 2016-2017 player stats and every season's game
status, and is needed only to build the archive - including the weekly
update, which runs locally. It pins its own pandas and can drag a source build onto the
server for code that never runs there. Locally:

```
pip install -r requirements.txt -r requirements-build.txt
```

**Access.** `auth.py` gates the site behind a shared password, but only when
`APP_PASSWORD` is set in Render's environment. Unset, the site is public.
That keeps the public/private choice in the dashboard rather than in a commit,
and no password ever enters the repo. It is one password for ten people with
no identity behind it - right for keeping scores off the open web, wrong for
anything that matters. Note the GitHub repo is public and the archive is in
it, so a password on the site does not make the data private on its own.

**`.streamlit/config.toml`** sets `toolbarMode = "viewer"`, which hides the
Deploy button and the developer menu, and `showErrorDetails = false`, so a
crash shows the league a plain message instead of a traceback. The detail is
still in Render's logs.

**Weekly rhythm.** Run `weekly_update.py` locally, commit `data/archive` on
`master`, push (see Git workflow for keeping `dev` in step).
The site has the new week about two minutes later.

## The weekly update

The archive is the app's only data source in normal use, so keeping the current
season current is a weekly job rather than something the app does on its own.

```
python weekly_update.py            # the current season, additive
python weekly_update.py --dry-run  # report what it would add, write nothing
```

Or `weekly_update.bat`, which does the same and keeps a log under `logs/`.

**Run it Tuesday, not Monday night.** ESPN restates player points for a day or
two after the games, and Tuesday midday is when the week has settled.

**It only ever adds.** Weeks the archive already holds are left alone. A week
ESPN has since restated is reported as a conflict and skipped, so a stat
correction cannot quietly rewrite a result the league has already argued about.
Pass `--force` when you have looked at the conflict and decided ESPN is right.

**Injury status comes from the NFL, not ESPN.** `game_status.csv` records
whether each rostered player played that week, at game time: Healthy,
Mid-Game Injury, Out, IR, Suspended, Bye, Inactive. It is built from nflverse
by `data/game_status.py`, whose docstring has the rules and the evidence.
ESPN's injury field was dropped from boxscores because it is the status on
the day of the pull: a Tuesday capture stamped a player hurt on Sunday as OUT
for the game he started, and every later pull restated every past week.

The weekly update adds a week's game status once nflverse has published its
snap counts, normally by Tuesday; if they are late, that week lands on the
next run. The season in progress detects mid-game injuries from snaps
(source=snaps, about 95% precise); nflverse publishes exact per-play
participation after the season, so **once a season is over, rebuild it**:

```
python build_archive.py --season 2026 --dataset game_status --rebuild --force
```

A derived-only run like that needs no ESPN cookies and leaves seasons.json
alone.

**It fills in free-agent weeks as it goes.** `player_weeks.csv` covers every
player in the season's box scores, so a player first rostered in week 5 has
his weeks 1-4 added in the same run. Each write prints how ESPN's player card
agrees with the box scores; a line saying they differ is worth a look before
committing.

**Keep it running to the final week, for the trades.** The only ESPN source
that records a trade's players - the league activity feed - is deleted once
the season ends (2025's already answers "does not exist"). Waiver history
stays on ESPN. A finished season's trades can still be rebuilt from its weekly
rosters (`data/trade_inference.py`, marked `source=inferred`), and 2018-2025
were built that way, but that is a deduction checked against ESPN's trade
records, and a weekly capture from the feed is a record. 2016-2017 have no
transactions at all: ESPN kept none, and their rosters are starters only.

**It refreshes `seasons.json` itself.** That file carries `current_week`, which
is what the pages read, plus manager and team names. Nothing used to write it,
so an update could add a week of data while the app went on showing the old one.
`current_week` there means the last week the archive holds - not ESPN's open
scoring period, which from Tuesday morning already names a week nobody played.

### Scheduling it for Tuesday noon

Task Scheduler, run as your own user, "Run only when user is logged on" (the
ESPN cookies live in `ff_app/.env` under your profile):

```
schtasks /create /tn "FF weekly update" /sc weekly /d TUE /st 12:00 /tr "\"C:\Users\jaymi\code-repository\fantasy-football\ff_app\weekly_update.bat\" --scheduled"
```

`--scheduled` tells the batch file to skip its final `pause`, which would
otherwise leave an unattended run waiting on a keypress forever.

The archive is committed to git, so a run is not finished until you commit it:

```
git add data/archive && git commit -m "Archive 2026 through week N"
```

### Starting a new season

1. Add the year to `SEASONS` in `config.py` and bump `CURRENT_SEASON`.
2. Add a `MANAGER_OVERRIDES` entry for any team whose ESPN account owner is not
   the person actually managing it. Team 3 has needed one every year since 2021.
3. Check `season_config()` matches. Read `league.settings.matchup_periods`: 2026
   returns periods 1-13 single-week then 14=[14,15], 15=[16,17], which is the
   2021+ shape already handled.
4. Add the year to `data/archive/draft_order.csv` once the draft happens.
5. If the scoring settings changed, check `reception_points()` in `config.py`.
   Draft value rescores earlier seasons into the new scoring through it, and
   receptions are the only offensive setting it can rescore.

`DEFAULT_SEASON` needs no attention. It follows the data rather than the season
list, so the app stays on the previous season until week 1 is archived - a
season exists on ESPN months before it holds anything, and defaulting to an
empty one would make every page look broken all summer.

## Data storage — archive vs cache

Two distinct layers. Do not conflate them.

**`data/archive/` — the permanent record. Committed to git.**
Plain CSV, one file per dataset with every season stacked (`season` column):
`matchups.csv`, `boxscores.csv`, `draft.csv`, `standings.csv`, `validation.csv`,
`transactions.csv`, `game_status.csv` (from nflverse, not ESPN), `player_weeks.csv`,
plus `seasons.json` (current_week, manager_map, team_names, schedule shape per season).

`player_weeks.csv` is what each player scored every week, rostered or not, with
receptions; `boxscores.csv` is who had him and where he sat. They overlap on
rostered weeks, where boxscores is the authority. It exists because a draft
pick is judged on the player's whole season, free-agent weeks included, and
because receptions let a non-PPR season be rescored to half-PPR. 2018 onward
only - ESPN has no weekly player stats before that.

`draft_value_curves.csv` holds each completed season's draft value curve,
written once by `build_archive.py` the first time a run finds the season
complete, and never rewritten, so a later season cannot re-score an earlier
one. Delete a row only to deliberately refit that season.

This is the source of truth for completed seasons. It is read *before* the pickle
cache and *before* ESPN, so day-to-day use needs no cookies and no network.
Because it is CSV it is readable, diffable, and hand-correctable — if a value is
wrong, edit the cell. Read it via `data/archive.py`.

The archive is curated — some values were checked by hand and corrected — so
refreshes are **targeted, never wholesale**. `build_archive.py` has no
"rebuild everything" mode and will not touch a season you did not name.

```
python build_archive.py --list                            # what is archived
python build_archive.py --season 2026 --update            # weekly: adds new rows only
python build_archive.py --season 2026 --update --dry-run  # preview, writes nothing
python build_archive.py --season 2019 --rebuild --force   # replace ONE season
```

Guarantees:
- `--season` is required. There is no all-seasons mode.
- `--update` is additive. Rows that would *change* are reported as conflicts
  and skipped unless you pass `--force`.
- `--rebuild` refuses to replace an already-archived season without `--force`.
- Every write is backed up to `data/archive/_backups/` (gitignored) first.
- After writing, unnamed seasons are verified unchanged and untouched files
  are checked byte-identical.

Row order is canonical (sorted by identity keys), so a `git diff` after an
update shows only rows that genuinely changed. A weekly update that finds
nothing new writes nothing at all.

Every number is stored to the hundredth (`DECIMALS` in `build_archive.py`),
because ESPN never shows more. A third decimal was either precision the league
never saw (2018's raw projections) or float noise, and either way the archive
disagreed with the site it records.

To correct a single wrong value, edit the CSV directly — that is the point of
using CSV. Do not re-pull to fix one cell.

There is no "Refresh Data" button in the app. Pages read the archive, so a
button that cleared the pickle cache would have done nothing.

**`data/archive/draft_order.csv` — the league's own draft order.**
Hand-kept, one row per (season, pick). Read it with `data.archive.draft_order(year)`.

ESPN's draft data is unreliable for order. The league drafts in person some
years and the commissioner re-enters the teams afterwards, which gets the
rosters right but not the pick order. Checked season by season, ESPN agrees
exactly in 2022, 2023 and 2024, and disagrees almost completely in 2019, 2020,
2021 and 2025. 2016 and 2017 have no recorded order, so ESPN's is all there is.

2018 has two blank slots, picks 5 and 6. Mitchell and B. Pisarcik held them
when the order was set, then left; Jason and Scott took the slots, but which
took which was never recorded. Note that ESPN's own 2018 first round reads as
a plausible real draft by that year's player values, so it may yet be right
and the hand-kept order may be the pre-departure plan.

Verification is in the same spirit as the finishes: playoff order is checked
against `We Are How U Mean Analytics.xlsx`, draft order against this file.

`analysis/draft.py` applies it. `apply_recorded_order()` reseats the board:
every team keeps exactly the players ESPN recorded, in the same rounds, and
only the seat it sat in changes - and with it pick_in_round and overall_pick.
Draft Review calls it before anything reads a pick number, since Best Value and
Biggest Busts both rank on overall_pick and were scoring picks against the
wrong draft position, not just listing them in the wrong order.

It refuses rather than guesses. 2016 and 2017 have no recorded order; 2018 has
two blank seats and also traded picks, which breaks the one-pick-per-seat-per-
round assumption the rebuild rests on. Those seasons fall back to ESPN's order
and the page says so, so a season showing ESPN's order does not silently look
like a season showing the league's.

The proof it is right: 2022, 2023 and 2024 rebuild byte-identical to ESPN, zero
picks moved, which is exactly the three seasons where the recorded order and
ESPN already agreed. 2019, 2020, 2021 and 2025 reseat.

2025 is also what settles which source to believe. ESPN has Matt taking
Ja'Marr Chase at pick 10; the recorded order has Matt at 1. Chase was the
consensus first overall that year, and the rest of the recorded first round
tracks 2025 draft values the same way. ESPN's does not.

One caveat worth knowing. 2019 and 2020 are keeper years, six and five keepers,
all in round 1. The recorded order is applied to them on the reading that it
describes seats rather than live picks - the order was given as a plain snake.
If keepers actually cost a specific round pick and the order described only the
live picks, those two seasons would need different handling.

**`data/cache/` — disposable pickle cache. Gitignored.**
Only relevant when pulling a season not yet archived. Delete freely.
`league.pkl` is the raw espn-api object graph; nothing reads it any more except
`get_current_week()` as a fallback, and pre-archive dataset builds.

`USE_ARCHIVE = False` in `data/espn_client.py` bypasses the archive entirely.

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
- Seasons: 2016–2025 (10 seasons)
- Teams: 10
- Playoff spots: 4

## Data quality by season

| Season | Player-level data | Notes |
|--------|-------------------|-------|
| 2016–2017 | Approximated via nfl-data-py | ~65–77% within 5 pts of ESPN totals; some weeks incomplete due to ESPN API gaps |
| 2018 | ESPN API (rosterForCurrentScoringPeriod) | 100% exact |
| 2019–2025 | ESPN API (box_scores) | 100% exact |

Pages 4 (Lineup Efficiency) and 7 (Draft, Waivers & Trades) show a warning banner when 2016 or 2017
is selected, noting that player data may not be 100% accurate.

## Season quirks

### 2016 — 13-week regular season, playoffs into NFL week 17
The league ran a longer regular season and played a week later than every other
pre-2021 year. ESPN's scoreboard labels the rounds "Playoff Round 1 (NFL Week
14 - NFL Week 15)" and "Playoff Round 2 (NFL Week 16 - NFL Week 17)".

`season_config(2016)` returns `reg_season_end=13`, `playoff_weeks=[14,15,16,17]`,
`total_weeks=17` - the same shape as 2021+, five years early.

Treating it like its neighbours (12-week season, playoffs 13-16) capped the
fetch at week 16, so week 17 was never pulled and Round 1 was split across
both rounds. That produced wrong finishes for six of ten managers, including
handing Tyler a runner-up he did not earn.

2016 also had East/West divisions, which fed seeding, and ran a consolation
ladder rather than a fixed bracket: the bottom two met in Round 1 only and
then played different opponents. The sacko is therefore decided over the weeks
the bottom two actually faced each other, not over all playoff weeks.

Finishes for all ten seasons now match the league's manually kept records
(`We Are How U Mean Analytics.xlsx`, Standings Data tab) 95/95.

### 2022 — manually managed playoff bracket
The league ran a custom playoff bracket outside ESPN with an extra regular season week:
- Regular season: weeks 1–14 (vs weeks 1–13 in all other 2021+ seasons)
- Round 1: week 15 only (1 week), seeded 1v4, 2v3, 5v8, 6v7
- Finals: weeks 16+17 (2-week cumulative, winners and losers from R1)
- Sacko Bowl (seeds 9–10): weeks 15+16+17 (3-week cumulative)

`season_config(2022)` returns `reg_season_end=14` and `playoff_weeks=[15, 16, 17]`.
Playoff validation is skipped for 2022 (ESPN's stored cumulative totals reflect its own
auto-scheduled bracket, not the real one). Regular season validation is exact.

### 2020 and earlier — different playoff schedule
NFL moved to 17-game seasons starting in 2021, shifting fantasy playoffs by one week.
`season_config(season)` handles this: ≤2020 uses wks 13–16 for playoffs; ≥2021 uses wks 14–17.

## Key design decisions and why

**Streamlit over Jupyter:** The old workflow required manually entering scores each week into
a notebook. Streamlit gives interactive dropdowns, live charts, and hot-reload editing without
re-running cells.

**Pickle for the League object, CSV for everything else:** espn-api returns Python
objects (League, Team) that can't be serialized to a table, so `league.pkl` stays pickle.
But every *derived* dataset is a plain DataFrame, so those live in `data/archive/` as CSV.
Pickle is a bad archival format — unreadable without Python, and it embeds espn-api class
definitions, so a library upgrade can make old files unloadable. The archive is the
durable record precisely because it is boring text.

**espn-api library over raw requests:** Previous attempts at raw ESPN API calls failed due to
cookie/auth complexity and ESPN returning HTML instead of JSON. The library handles all of that.

**Credentials in .env, not hardcoded:** ESPN_S2 expires. Keeping it in .env means updating
one file, not hunting through code. The .gitignore excludes .env* so credentials never hit GitHub.

**Season selector on every page:** Users want to compare seasons. All pages accept a season
param and the sidebar selector is consistent across all pages.

**nfl-data-py for 2016–2017 player data:** ESPN's API only returns season-level stats (not
per-week) for those seasons via `rosterForMatchupPeriod`. nfl-data-py (nflfastR) provides
weekly player stats. Skill positions use `fantasy_points` from weekly data; kickers use PBP
FG/PAT tracking; D/ST uses PBP sacks/INTs/TDs/safeties/blocked kicks + schedule PA/YA tiers.
ESPN ID → GSIS ID crosswalk via `nfl.import_ids()`.

**Luck index formula:** `actual_wins - expected_wins` where expected = score percentile rank
each week. A team scoring in the 80th percentile every week "should" win ~80% of games.
Outperforming that = lucky schedule; underperforming = unlucky.

**Alternate schedule:** For each team, count wins vs every other team every week (N-1 games
per week). Reveals whether a team's record reflects their scoring or their schedule.

**Monte Carlo playoff sim:** Uses each team's mean/std from games played so far. Samples
from a normal distribution for each remaining game. 10,000 sims by default.

**3-week vs 4-week playoff format detection:** `len(pw) == 3` identifies the 2022 format.
All playoff display logic (page 6) and validation (espn_client.py) branch on this.

## Git workflow
- Repo: https://github.com/JMKniss/we-are-how-u-mean
- Default branch: `master`. Render deploys every push to it, so **a push to
  `master` is a release** to the league.
- Day-to-day work happens on `dev`. Commit there as often as is useful; pushing
  `dev` backs it up to GitHub and deploys nothing.
- Test on `dev` with `streamlit run app.py` (localhost:8501) — the same app and
  archive the site serves.
- To ship: `python check.py` (full sweep), then
  `git switch master && git merge dev && git push`, then `git switch dev`.
- Never merge or push to `master` unless the user says to ship. Committing on
  `dev` needs no such go-ahead.
- Exception: the weekly archive commit goes straight to `master` (it is data,
  checked by `weekly_update.py`, and the league expects it). Afterwards run
  `git switch dev && git merge master` so `dev` does not fall behind.
- A bad release is undone with `git revert <sha>` on `master` and a push.

Why: before this, every session committed and pushed on `master`, so a
multi-commit session redeployed the site several times and nothing was seen
running before the league saw it.
