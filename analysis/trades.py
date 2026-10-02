"""
Trade grades: what each trade did for each manager in it, week by week.

Every grade is a counterfactual over weeks already played. The question is
always the same: what did this manager's team score with the trade, and what
would it have scored that week if the trade had never happened? Nothing here
projects forward, and nothing values a player in the abstract. A trade is
graded on the weeks the manager actually held what he got, against the
players he gave up, on his own roster.

Two counterfactuals, read side by side, plus one derived from the second:

  OL delta      Optimal lineup. The best lineup the manager could have
  (best)        started from his actual roster that week, minus the best
                lineup from the same roster with the trade undone: received
                players out, sent and trade-dropped players back. Positional
                need, depth, byes, 2-for-1s and cross-position trades are all
                inside that one subtraction. It is the trade's value to this
                roster, however the manager used it.

  ASL delta     Actual started lineup. The same subtraction on the lineup the
  (started)     manager actually started. Each received player who started is
                taken out of his slot, and the slot is refilled with the
                player the manager would most likely have started instead.
                The rest of the lineup stays as he set it. A received player
                who sat on the bench did nothing that week and counts nothing.
                This is the trade's actual impact, lineup decisions included.

  Wins created  From ASL: a game the manager won where the refilled lineup
  Losses caused would have lost is a win created; a game he lost where it
                would have won is a loss caused. Both are counted, never
                netted, because a trade that won two games and lost two is not
                the same as one that touched none. The opponent's score is
                left as it was, even when the opponent was the trade partner;
                each side is graded alone. A regular-season week is a game. A
                playoff round is a game, scored over its weeks on the league's
                own bracket from analysis/standings.py, never ESPN's: the
                two-week rounds summed, 2022's hand-run bracket and three-week
                Sacko Bowl, 2016's ladder where the bottom two met once. A
                round the trade was held for only part of still counts, on
                the delta from the weeks held.

  Expected wins From ASL as well, and without the all-or-nothing of a flip.
  added         Each week, the chance his actual score beats a typical other
                team that week, minus the same chance for the score without
                the trade. The chance is a normal curve centred on the other
                teams' average that week, with the season's usual spread of a
                score around its week's average. A trade that added 30 points
                in a week he won by 40 flips nothing, and this still credits
                it; points that lift a score near the league's middle count
                for more than points on a score far above or below it. Every
                week held counts this way, playoffs included, against that
                week's other scores rather than the playoff opponent, so it
                is the steadier companion to the flips, not a copy of them.
                The all-play share (how many of the other nine teams the score
                beat, as the luck index in analysis/standings.py counts
                expected wins) was tried first and rejected for this: it moves
                in steps of a ninth, so five points could cost a third of a
                win in a week where three teams sat close together and ten
                points earn nothing in a week where none did. Most trades move
                a score by a few points a week, and on those the steps were
                noise: Tim's 2025 Jones and Jacobs trade, +35 points over 14
                weeks, came out at -0.89 wins.

Each delta is given three ways. The total is the points the trade added or
cost over the weeks held. Per week divides by the weeks held, so a trade made
in week 11 can stand next to one made in week 3. Per game played averages the
weeks that count as a game for the trade: every received player still held
played, or at least one of them started. A week a received player missed -
bye, out, IR, inactive, suspended; a mid-game injury counts as played - with
none of the others in the lineup is left out, so it says what the trade added
when it was on the field. "Any received player played" was the rule at first,
and it counted a week the stud was hurt because the throw-in sent to make
room was healthy on the bench. A throw-in who actually started that week did
contribute, so that week still counts.

The refill. The slot goes to whoever had the highest average to date among
the players he sent, the players he dropped to make the trade, and his bench,
all in one pool. Sent players were tried first at one time, and that assumed
every player sent would have started: a manager who trades two bench pieces
for one starter was charged as if both bench pieces would have played. Pooled,
a sent player starts only if he was the best option there was, and a player
cut to make room starts almost never, which is right. "Average to date" is
never that week's score, so a bench player nobody would have started cannot
swing a week with one big game. A player who did not play is never the
refill: an injured or inactive player is a zero on the bench, not in the
lineup. A mid-game injury did play, so he can be the refill and scores what
he scored. Fixed slots are refilled before the flex, so
a sent RB takes the RB slot and leaves the flex to a sent WR. With the pooled
candidates that order gave the same result as the best possible assignment
(the most summed average to date) on every trade in the archive through 2025,
where refilling the flex first changed 18 sides by up to 31 points.

A slot nobody on the roster can fill. Received a kicker, sent none, no kicker
on the bench: the manager would have picked one up. Which free agent is
unknowable, so the slot is worth the replacement level: that week, the lowest
score among each team's players eligible for the slot who played, averaged
over the teams. Onesie positions are volatile enough that this is a fair
substitute without pretending to know the waiver wire. It was worth zero at
first, which credited the trade with the received player's whole score - 64
refilled slots through 2025. The optimal lineup gets the same treatment: a
pool, with or without the trade, short of a position a fixed slot needs is
topped up with a replacement-level player.

No injury adjustment. There was once a "healthy" version of each delta that
replaced a traded player's weeks missed hurt after the trade with his healthy
pace. It was taken out: the grade is what the trade did, and a player who got
hurt after he was bought is part of what the trade did. Per game played is
how to look past the weeks a player missed, without inventing what he would
have scored in them.

The window is the manager's own. It runs from the trade's week while he holds
at least one player he received, and ends the week he holds none, however
that came about. What the other manager did with what he was sent changes
nothing: his received players keep scoring real points wherever they are,
and they are what the counterfactual puts back. A player traded away again
after one week is graded on that week alone. That is a small sample; the
alternative, crediting a trade with a player's whole rest of season after he
was moved again, was considered and rejected because the trade's worth to the
manager is the weeks he had the player. A received player cut before his
first game was never held, and a trade whose received players were all cut
before a game has no weeks and no grade.

The undone roster is kept legal. Putting two sent players back for one
received leaves it one over the season's roster limit. The freed spot went to
whoever was added after the trade, so the cut is the player not in the trade
whose current stint on the roster began latest, and only among players who
arrived the same week does the lower average to date go first. It was the
lowest average to date outright at first, and that cut an injured early
pick stashed on the bench, whose average was low from the injury and not
his worth, while the waiver pickup that had actually taken the spot stayed.
Average to date is a player's points per game played so far this season;
before week 1 it is ESPN's projection for the week, the only forward-looking
number anywhere in here, and the only one available.

Every week the team played counts, playoffs and consolation included, through
whatever the archive holds, so the season in progress grades up to the last
week archived. Points are the box score's for a rostered player and the
player card's for a free agent, so a sent player dropped by his new manager
still scores. 2016 and 2017 have no trades, and a rebuilt trade (inferred
from weekly rosters) grades like any other; the page marks it.

Each manager is graded alone. A grade says nothing about the other side, and
no column compares the two; lopsidedness is a later question.

Stored, not worked out on the page. Grading every trade of every season took
about 23 seconds, on every page load the cache had let go of. The weekly rows
are written to data/archive/trade_grades.csv by build_archive.py at the end
of every run that writes the archive, for the seasons it named, and the pages
read them. Unlike the rest of the archive they are not a record: nothing in
them was checked by hand, and every row is a function of the other files and
of this module. So a season's rows are replaced outright whenever it is
regraded, and regrading every season at once is allowed (--grades with no
--season). Each row carries the GRADES_VERSION it was graded under; bump it
with any change here that alters a grade, and until the seasons are regraded
the pages work the grades out live rather than show stale ones.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from analysis.efficiency import SLOT_ELIGIBILITY, optimal_lineup_points, season_slot_requirements
from analysis.standings import playoff_games
from analysis.transactions import trade_sides
from config import season_config
from data import archive

FIRST_SEASON = 2018
PLAYED = {"Healthy", "Mid-Game Injury"}

# Bump on any change that alters a grade. trade_grades.csv rows carry the
# version they were graded under, and a mismatch is worked out live instead,
# so a page never shows a grade the current rules would not give.
GRADES_VERSION = 1
STORED = "trade_grades"

SIDE_COLS = ["transaction_id", "season", "week", "executed_at", "team_id",
             "receives", "sends", "dropped", "partners", "inferred", "notes",
             "weeks", "games", "first_week", "last_week",
             "best", "best_pw", "best_pgp", "started", "started_pw", "started_pgp",
             "xwins", "wins_flipped", "wins_created", "losses_caused"]
WEEK_COLS = ["transaction_id", "season", "team_id", "week", "played",
             "best", "started", "xwins", "flip", "score", "cf_score", "opp_score"]
# The archive keeps two decimals, which would round a week's change in win
# chance to the hundredth of a win, so it is stored in percentage points.
STORED_COLS = ["season", "transaction_id", "team_id", "week", "played",
               "best", "started", "win_pct", "flip", "score", "cf_score", "opp_score",
               "version"]


def supported(season: int) -> bool:
    return season >= FIRST_SEASON


class _Season:
    """Everything one season's grades read, loaded once."""

    def __init__(self, season: int):
        self.season = season
        self.cfg = season_config(season)
        self.box = archive.get("boxscores", season)
        self.slots = season_slot_requirements(self.box)
        self.roster_limit = int(self.box[self.box["slot"] != "IR"]
                                .groupby(["week", "team_id"]).size().max())
        matchups = archive.get("matchups", season)
        self.matchups = matchups.set_index(["week", "team_id"])
        self.week_scores = {w: g.set_index("team_id")["score"].astype(float)
                            for w, g in matchups.groupby("week")}
        # The season's usual spread of a score around its week's average.
        dev = matchups["score"] - matchups.groupby("week")["score"].transform("mean")
        self.score_sd = float(dev.std()) if len(dev) > 1 else np.nan
        self.playoff_games = {}
        for g in playoff_games(season, matchups):
            self.playoff_games.setdefault(g["team_id"], []).append(g)

        # When each player's current stint on each team began, for the
        # roster-limit cut: the latest arrival is the one who would not be there.
        self.stint_start = {}
        for (team, pid), g in self.box.groupby(["team_id", "player_id"]):
            start = None
            prev = None
            for w in sorted(g["week"]):
                start = w if prev != w - 1 else start
                self.stint_start[(team, pid, w)] = start
                prev = w

        # One points table for the season: the box score where a player was
        # rostered, the player card where he was not. A week with no row is a
        # bye or a week out of the league, worth nothing.
        card = archive.get("player_weeks", season)[["week", "player_id", "player_name", "position", "points"]]
        rostered = self.box[["week", "player_id", "player_name", "position", "points"]]
        pts = pd.concat([rostered, card]).drop_duplicates(["week", "player_id"]).sort_values(["player_id", "week"])
        self.points = pts.set_index(["player_id", "week"])["points"].to_dict()
        self.position = pts.drop_duplicates("player_id").set_index("player_id")["position"].to_dict()
        self.name = pts.drop_duplicates("player_id").set_index("player_id")["player_name"].to_dict()

        # Average to date: each player's game weeks and running total, so the
        # points per game before any week is one lookup.
        self.games = {pid: (g["week"].to_numpy(), g["points"].cumsum().to_numpy())
                      for pid, g in pts.groupby("player_id")}
        self.projected = self.box.set_index(["player_id", "week"])["projected"].to_dict()
        self.last_game = pts.groupby("player_id")["week"].max().to_dict()

        gs = archive.get("game_status", season)
        self.status = gs.set_index(["player_id", "week"])["status"].to_dict()
        self._replacement = {}

    # ── per-player numbers ───────────────────────────────────────────────
    def avg_to_date(self, pid: int, week: int) -> float:
        """Points per game before this week; ESPN's projection when there is no game yet."""
        weeks, totals = self.games.get(pid, (np.array([]), np.array([])))
        n = int(np.searchsorted(weeks, week))
        if n > 0:
            return float(totals[n - 1]) / n
        v = self.projected.get((pid, week), np.nan)
        return 0.0 if pd.isna(v) else float(v)

    def on_bye(self, pid: int, week: int) -> bool:
        return self.status.get((pid, week)) == "Bye" or (
            (pid, week) not in self.points and week <= self.last_game.get(pid, 0))

    def played(self, pid: int, week: int) -> bool:
        """On the field that week; a mid-game injury counts."""
        status = self.status.get((pid, week))
        if status is not None:
            return status in PLAYED
        return (pid, week) in self.points and not self.on_bye(pid, week)

    def win_chance(self, score: float, week: int, team: int) -> float:
        """
        Chance this score beats a typical other team that week: the other
        teams' average that week, the season's usual spread around it.
        """
        others = self.week_scores.get(week)
        if others is None or not self.score_sd > 0:
            return np.nan
        others = others.drop(team, errors="ignore")
        if others.empty:
            return np.nan
        return float(norm.cdf((score - others.mean()) / self.score_sd))

    def replacement(self, slot: str, week: int) -> float:
        """
        What a slot nobody on the roster could fill is worth: that week, the
        lowest score among each team's players eligible for it who played,
        averaged over the teams.
        """
        key = (slot, week)
        if key not in self._replacement:
            eligible = SLOT_ELIGIBILITY.get(slot)
            wk = self.box[(self.box["week"] == week) & (self.box["slot"] != "IR")]
            if eligible is not None:
                wk = wk[wk["position"].isin(eligible)]
            wk = wk[[self.played(p, week) for p in wk["player_id"]]]
            lows = wk.groupby("team_id")["points"].min()
            self._replacement[key] = float(lows.mean()) if len(lows) else 0.0
        return self._replacement[key]


def _optimal(pool: pd.DataFrame, s: _Season, week: int) -> float:
    """
    The best lineup from this pool, a fixed slot the pool cannot fill taken
    by a replacement-level player instead of left empty.
    """
    positions = pool["position"].tolist()
    points = pool["points"].tolist()
    for slot, n in s.slots.items():
        eligible = SLOT_ELIGIBILITY.get(slot)
        if eligible is None or len(eligible) != 1:
            continue
        pos = next(iter(eligible))
        short = int(n) - positions.count(pos)
        if short > 0:
            positions += [pos] * short
            points += [s.replacement(slot, week)] * short
    return optimal_lineup_points(positions, points, s.slots)


def _refill(vacated: list, candidates: list, s: _Season, week: int) -> float:
    """
    Points the vacated slots would have scored, each refilled by the
    highest-average eligible candidate not already used, fixed slots first so
    a sent RB takes the RB slot and leaves the flex to a sent WR. candidates
    is one pool of (player_id, points): sent, trade-dropped and bench players
    alike. A player who did not play is not a candidate; a mid-game injury
    played. A slot nobody can fill is worth the replacement level.
    """
    order = sorted(vacated, key=lambda slot: len(SLOT_ELIGIBILITY.get(slot, set())) or 99)
    used = set()
    total = 0.0
    for slot in order:
        eligible = SLOT_ELIGIBILITY.get(slot)
        pool = [(pid, p) for pid, p in candidates
                if pid not in used and s.played(pid, week)
                and (eligible is None or s.position.get(pid) in eligible)]
        if pool:
            best = max(pool, key=lambda c: s.avg_to_date(c[0], week))
            used.add(best[0])
            total += best[1]
        else:
            total += s.replacement(slot, week)
    return total


def _grade_side(side: pd.Series, s: _Season) -> list[dict]:
    """One row per week the manager held something from this trade."""
    team = int(side["team_id"])
    trade_week = int(side["week"])
    received = set(side["receives_ids"])
    gone = list(side["sends_ids"]) + list(side["dropped_ids"])
    traded = received | set(gone)

    rows = []
    for week in range(trade_week, int(s.box["week"].max()) + 1):
        roster = s.box[(s.box["week"] == week) & (s.box["team_id"] == team)]
        if roster.empty or not (set(roster["player_id"]) & received):
            break
        roster = roster[["player_id", "position", "slot", "points", "is_active_slot"]]
        back = pd.DataFrame({
            "player_id": gone,
            "position": [s.position.get(p) for p in gone],
            "slot": "BE",
            "points": [s.points.get((p, week), 0.0) for p in gone],
            "is_active_slot": False,
        })

        row = {"transaction_id": side["transaction_id"], "season": s.season,
               "team_id": team, "week": week}

        # Optimal lineup: the whole roster, with and without the trade. An IR
        # slot does not score.
        active = roster[roster["slot"] != "IR"]
        cf = pd.concat([active[~active["player_id"].isin(received)], back])
        over = len(cf) - s.roster_limit
        if over > 0:
            cuttable = cf[~cf["player_id"].isin(traded)].copy()
            cuttable["arrived"] = [s.stint_start.get((team, p, week), 0) for p in cuttable["player_id"]]
            cuttable["avg"] = [s.avg_to_date(p, week) for p in cuttable["player_id"]]
            cut = (cuttable.sort_values(["arrived", "avg"], ascending=[False, True])
                   .head(over)["player_id"])
            cf = cf[~cf["player_id"].isin(cut)]
        row["best"] = round(_optimal(active, s, week) - _optimal(cf, s, week), 2)

        # Started lineup: received starters out, their slots refilled.
        starters = roster[roster["is_active_slot"]]
        score = round(float(starters["points"].sum()), 2)
        started_received = starters[starters["player_id"].isin(received)]
        bench = roster[roster["slot"] == "BE"]
        candidates = (list(zip(back["player_id"], back["points"]))
                      + list(zip(bench["player_id"], bench["points"])))
        refill = _refill(started_received["slot"].tolist(), candidates, s, week)
        row["started"] = round(float(started_received["points"].sum()) - refill, 2)

        # A game played, for per game played: every received player he still
        # holds played, or one of them was in his starting lineup.
        held = [p for p in roster["player_id"] if p in received]
        row["played"] = (all(s.played(p, week) for p in held)
                         or not started_received.empty)

        # Wins flipped, from the lineup as started: regular season weeks here,
        # playoff rounds below once every held week is graded.
        row["score"] = score
        row["cf_score"] = round(score - row["started"], 2)
        row["opp_score"] = np.nan
        row["flip"] = 0
        official = (float(s.matchups.loc[(week, team), "score"])
                    if (week, team) in s.matchups.index else score)
        row["xwins"] = round(s.win_chance(official, week, team)
                             - s.win_chance(official - row["started"], week, team), 4)
        if week <= s.cfg["reg_season_end"] and (week, team) in s.matchups.index:
            m = s.matchups.loc[(week, team)]
            opp = float(m["opp_score"])
            official = float(m["score"])
            row["opp_score"] = opp
            cf_score = official - row["started"]
            if official > opp and cf_score < opp:
                row["flip"] = 1
            elif official < opp and cf_score > opp:
                row["flip"] = -1
        rows.append(row)

    # Playoff games are rounds, scored over their weeks on the league's own
    # bracket. The trade's effect on the round is its started delta over the
    # weeks it was held, and the flip lands on the last of those weeks.
    by_week = {r["week"]: r for r in rows}
    for g in s.playoff_games.get(team, []):
        held = [by_week[w] for w in g["weeks"] if w in by_week]
        if not held:
            continue
        own = sum(float(s.matchups.loc[(w, team), "score"]) for w in g["weeks"]
                  if (w, team) in s.matchups.index)
        opp = sum(float(s.matchups.loc[(w, g["opp_id"]), "score"]) for w in g["weeks"]
                  if (w, g["opp_id"]) in s.matchups.index)
        cf = own - sum(r["started"] for r in held)
        if own > opp and cf < opp:
            held[-1]["flip"] += 1
        elif own < opp and cf > opp:
            held[-1]["flip"] -= 1
    return rows


def compute_weekly_grades(season: int) -> pd.DataFrame:
    """weekly_grades worked out from the archive, ignoring trade_grades.csv."""
    if not supported(season) or not archive.has("transactions", season) \
            or not archive.has("boxscores", season):
        return pd.DataFrame(columns=WEEK_COLS)
    sides = trade_sides(archive.get("transactions", season))
    if sides.empty:
        return pd.DataFrame(columns=WEEK_COLS)
    s = _Season(season)
    rows = []
    for _, side in sides.iterrows():
        rows.extend(_grade_side(side, s))
    return pd.DataFrame(rows, columns=WEEK_COLS)


def stored_grades(season: int) -> pd.DataFrame | None:
    """
    This season's weekly grades from trade_grades.csv, or None when the file
    has no rows for it or any row was graded by an older GRADES_VERSION.
    """
    if not archive.has(STORED, season):
        return None
    df = archive.get(STORED, season)
    if df.empty or not (df["version"] == GRADES_VERSION).all():
        return None
    df["xwins"] = df["win_pct"] / 100
    df["played"] = df["played"].astype(bool)
    return df[WEEK_COLS]


def to_store(weekly: pd.DataFrame) -> pd.DataFrame:
    """weekly_grades rows as trade_grades.csv holds them."""
    out = weekly.copy()
    out["win_pct"] = (out["xwins"] * 100).round(2)
    out["version"] = GRADES_VERSION
    return out[STORED_COLS]


def weekly_grades(season: int) -> pd.DataFrame:
    """
    One row per trade, manager and week held: the two deltas, the change in
    win chance, and the flip. Read from trade_grades.csv when it holds this
    season at the current GRADES_VERSION, otherwise worked out here.
    """
    stored = stored_grades(season)
    return stored if stored is not None else compute_weekly_grades(season)


def add_rates(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Per week and per game played for both deltas. Per week is the total over
    weeks held. Per game played needs the deltas summed over played weeks
    only, best_played and started_played, which a frame of summed sides
    carries through; a trade with no game played has none.
    """
    for k in ("best", "started"):
        frame[f"{k}_pw"] = (frame[k] / frame["weeks"].where(frame["weeks"] > 0)).round(2)
        frame[f"{k}_pgp"] = (frame[f"{k}_played"] / frame["games"].where(frame["games"] > 0)).round(2)
    return frame


def trade_grades(season: int) -> pd.DataFrame:
    """
    One row per trade per manager: the trade as the tracker shows it, plus
    the weeks held, the games a received player played, each delta as a
    total, per week and per game played, and wins flipped. Trades with no
    weeks held carry zeros, weeks == 0, and no rates.
    """
    if not supported(season) or not archive.has("transactions", season):
        return pd.DataFrame(columns=SIDE_COLS)
    sides = trade_sides(archive.get("transactions", season))
    if sides.empty:
        return pd.DataFrame(columns=SIDE_COLS)
    weekly = weekly_grades(season)
    if weekly.empty:
        # No week held yet: a trade made in the week not yet archived. It
        # still needs every column, at zero, or the page has nothing to show.
        agg = pd.DataFrame(columns=["transaction_id", "team_id", "weeks", "games",
                                    "first_week", "last_week", "best", "best_played",
                                    "started", "started_played", "xwins", "wins_flipped",
                                    "wins_created", "losses_caused"])
    else:
        weekly = weekly.assign(best_played=weekly["best"].where(weekly["played"], 0.0),
                               started_played=weekly["started"].where(weekly["played"], 0.0))
        agg = (weekly.groupby(["transaction_id", "team_id"])
               .agg(weeks=("week", "size"), games=("played", "sum"),
                    first_week=("week", "min"), last_week=("week", "max"),
                    best=("best", "sum"), best_played=("best_played", "sum"),
                    started=("started", "sum"), started_played=("started_played", "sum"),
                    xwins=("xwins", "sum"), wins_flipped=("flip", "sum"),
                    wins_created=("flip", lambda f: int((f > 0).sum())),
                    losses_caused=("flip", lambda f: int((f < 0).sum())))
               .reset_index())
    out = sides.merge(agg, on=["transaction_id", "team_id"], how="left")
    for c in ("weeks", "games", "wins_flipped", "wins_created", "losses_caused"):
        out[c] = out[c].fillna(0).astype(int)
    for c in ("best", "best_played", "started", "started_played", "xwins"):
        out[c] = out[c].fillna(0.0).round(2)
    out["first_week"] = out["first_week"].astype("Int64")
    out["last_week"] = out["last_week"].astype("Int64")
    return add_rates(out)[SIDE_COLS + ["best_played", "started_played"]]


def summarise(grades: pd.DataFrame) -> pd.Series:
    """
    Any group of graded sides - a manager's season, his career - as one row:
    totals summed, rates taken over all the weeks and games in the group, and
    an up-even-down record on the optimal lineup delta. Up is a trade that
    added to the optimal lineup over the weeks held, at all; the size is in
    the points.
    """
    t = grades[["weeks", "games", "best", "best_played", "started", "started_played",
                "xwins", "wins_created", "losses_caused", "wins_flipped"]].sum()
    out = pd.Series({
        "trades": grades["transaction_id"].nunique(),
        # A trade with no week held yet has no grade, not an even one.
        "up": int(((grades["best"] > 0) & (grades["weeks"] > 0)).sum()),
        "even": int(((grades["best"] == 0) & (grades["weeks"] > 0)).sum()),
        "down": int(((grades["best"] < 0) & (grades["weeks"] > 0)).sum()),
        **t.to_dict(),
    })
    for k in ("best", "started"):
        out[f"{k}_pw"] = round(out[k] / out["weeks"], 2) if out["weeks"] else np.nan
        out[f"{k}_pgp"] = round(out[f"{k}_played"] / out["games"], 2) if out["games"] else np.nan
    return out


def manager_summary(grades: pd.DataFrame, manager_map: dict[int, str]) -> pd.DataFrame:
    """One row per manager with at least one trade, from summarise()."""
    cols = ["team_id", "manager", "trades", "up", "even", "down",
            "best", "best_pw", "best_pgp", "started", "started_pw", "started_pgp",
            "xwins", "wins_created", "losses_caused", "wins_flipped"]
    if grades.empty:
        return pd.DataFrame(columns=cols)
    out = grades.groupby("team_id").apply(summarise, include_groups=False).reset_index()
    out["manager"] = out["team_id"].map(manager_map)
    for c in ("trades", "up", "even", "down", "wins_created", "losses_caused", "wins_flipped"):
        out[c] = out[c].astype(int)
    return out[cols].sort_values("best", ascending=False, ignore_index=True)
