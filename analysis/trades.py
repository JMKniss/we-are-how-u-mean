"""
Trade grades: what each trade did for each manager in it, week by week.

Every grade is a counterfactual over weeks already played. The question is
always the same: what did this manager's team score with the trade, and what
would it have scored that week if the trade had never happened? Nothing here
projects forward, and nothing values a player in the abstract. A trade is
graded on the weeks the manager actually held what he got, against the
players he gave up, on his own roster.

Two counterfactuals, read side by side, plus one derived from the second:

  Best lineup   The best lineup the manager could have started from his
                actual roster that week, minus the best lineup from the same
                roster with the trade undone: received players out, sent and
                trade-dropped players back. Positional need, depth, byes,
                2-for-1s and cross-position trades are all inside that one
                subtraction. It is the trade's value to this roster, however
                the manager used it.

  Started       The same subtraction on the lineup the manager actually
                started. Each received player who started is taken out of his
                slot, and the slot is refilled with the player the manager
                would most likely have started instead: one of the players he
                sent if any fits the slot, else his best bench option for it.
                "Most likely" means highest average to date on that day, never
                that week's score, so a bench player nobody would have started
                cannot swing a week with one big game. Fixed slots are refilled
                before the flex. A received player who sat on the bench did
                nothing that week and counts nothing. This is the trade's
                actual impact, lineup decisions included.

  Wins flipped  From Started: a game the manager won where the refilled
                lineup would have lost counts +1, and the reverse -1. A
                regular-season week is a game. A playoff round is a game,
                scored over its weeks on the league's own bracket from
                analysis/standings.py, never ESPN's: the two-week rounds
                summed, 2022's hand-run bracket and three-week Sacko Bowl,
                2016's ladder where the bottom two met once. A round the
                trade was held for only part of still counts, on the delta
                from the weeks held.

Each of the two point columns is given twice, injury inclusive and injury
neutral. Injury neutral replaces a traded player's weeks missed hurt after the
trade with his healthy points per game, so a manager is not charged for a
player who got hurt after he bought him, nor credited for selling one who was
about to. A mid-game injury is paid its missed share at the healthy pace,
from game_status.csv's injury_weight. An injury already on the books when the
trade was made stays: Out or IR the week before the trade means the manager
knew, and that spell is scored as it happened. Only players in the trade are
neutralised, on both sides of the subtraction; everyone else on the roster is
the same with or without the trade. A player with no healthy week in the
season cannot be neutralised and is scored as he was. Suspensions, inactives
and byes are not injuries.

The window is the manager's own. It runs from the trade's week while he holds
at least one player he received, and ends the week he holds none, however
that came about. What the other manager did with what he was sent changes
nothing: his received players keep scoring real points wherever they are,
and they are what the counterfactual puts back. A player traded away again
after one week is graded on that week alone. That is a small sample and the
weeks column says so; the alternative, crediting a trade with a player's
whole rest of season after he was moved again, was considered and rejected
because the trade's worth to the manager is the weeks he had the player. A
received player cut before his first game was never held, and a trade whose
received players were all cut before a game has no weeks and no grade.

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
"""
import numpy as np
import pandas as pd

from analysis.efficiency import SLOT_ELIGIBILITY, optimal_lineup_points, season_slot_requirements
from analysis.standings import playoff_games
from analysis.transactions import trade_sides
from config import season_config
from data import archive

FIRST_SEASON = 2018
INJURED = {"Out", "IR"}

SIDE_COLS = ["transaction_id", "season", "week", "executed_at", "team_id",
             "receives", "sends", "dropped", "partners", "inferred", "notes",
             "weeks", "first_week", "last_week",
             "best", "best_healthy", "started", "started_healthy",
             "wins_flipped", "wins_created", "losses_caused"]
WEEK_COLS = ["transaction_id", "season", "team_id", "week",
             "best", "best_healthy", "started", "started_healthy",
             "flip", "score", "cf_score", "opp_score"]


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
        self.weight = gs.set_index(["player_id", "week"])["injury_weight"].to_dict()
        healthy = gs[gs["status"] == "Healthy"][["player_id", "week"]].copy()
        healthy["points"] = [self.points.get((p, w), 0.0) for p, w in zip(healthy["player_id"], healthy["week"])]
        self.healthy_ppg = healthy.groupby("player_id")["points"].mean().to_dict()

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

    def known_injury_until(self, pid: int, trade_week: int) -> int:
        """
        Last week of an injury spell already underway when the trade was made,
        or 0 when the player was not hurt the week before.
        """
        if self.status.get((pid, trade_week - 1)) not in INJURED:
            return 0
        w = trade_week
        while self.status.get((pid, w)) in INJURED:
            w += 1
        return w - 1

    def healthy_points(self, pid: int, week: int, known_until: int) -> float:
        """The player's points that week with any injury after the trade undone."""
        actual = self.points.get((pid, week), 0.0)
        ppg = self.healthy_ppg.get(pid)
        if ppg is None or week <= known_until:
            return actual
        status = self.status.get((pid, week))
        if status in INJURED:
            return ppg
        if status == "Mid-Game Injury":
            share = self.weight.get((pid, week))
            return actual + (0.0 if pd.isna(share) else float(share) * ppg)
        return actual


def _optimal(pool: pd.DataFrame, slots: dict, col: str) -> float:
    return optimal_lineup_points(pool["position"].tolist(), pool[col].tolist(), slots)


def _refill(vacated: list, candidates: list, s: _Season, week: int, col: str) -> float:
    """
    Points the vacated slots would have scored, each refilled by the
    highest-average eligible candidate not already used. Fixed slots first so
    a sent RB takes the RB slot and leaves the flex to a sent WR, not the
    other way round. candidates is a list of (player_id, points, from_trade),
    trade players tried before bench players for every slot.
    """
    order = sorted(vacated, key=lambda slot: len(SLOT_ELIGIBILITY.get(slot, set())) or 99)
    used = set()
    total = 0.0
    for slot in order:
        eligible = SLOT_ELIGIBILITY.get(slot)
        best = None
        for from_trade in (True, False):
            pool = [(pid, p) for pid, p, ft in candidates
                    if ft == from_trade and pid not in used and not s.on_bye(pid, week)
                    and (eligible is None or s.position.get(pid) in eligible)]
            if pool:
                best = max(pool, key=lambda c: s.avg_to_date(c[0], week))
                break
        if best is not None:
            used.add(best[0])
            total += best[1]
    return total


def _grade_side(side: pd.Series, s: _Season) -> list[dict]:
    """One row per week the manager held something from this trade."""
    team = int(side["team_id"])
    trade_week = int(side["week"])
    received = set(side["receives_ids"])
    gone = list(side["sends_ids"]) + list(side["dropped_ids"])
    traded = received | set(gone)
    known = {pid: s.known_injury_until(pid, trade_week) for pid in traded}

    rows = []
    for week in range(trade_week, int(s.box["week"].max()) + 1):
        roster = s.box[(s.box["week"] == week) & (s.box["team_id"] == team)]
        if roster.empty or not (set(roster["player_id"]) & received):
            break
        roster = roster[["player_id", "position", "slot", "points", "is_active_slot"]].copy()
        roster["healthy"] = [s.healthy_points(p, week, known[p]) if p in traded else pt
                             for p, pt in zip(roster["player_id"], roster["points"])]
        back = pd.DataFrame({
            "player_id": gone,
            "position": [s.position.get(p) for p in gone],
            "slot": "BE",
            "points": [s.points.get((p, week), 0.0) for p in gone],
            "is_active_slot": False,
        })
        back["healthy"] = [s.healthy_points(p, week, known[p]) for p in gone]

        row = {"transaction_id": side["transaction_id"], "season": s.season,
               "team_id": team, "week": week}

        # Best lineup: the whole roster, with and without the trade.
        for col, key in (("points", "best"), ("healthy", "best_healthy")):
            # An IR slot does not score, unless it holds a received player whose
            # injury is being undone.
            undone = roster["player_id"].isin(received) if col == "healthy" else False
            active = roster[(roster["slot"] != "IR") | undone]
            cf = pd.concat([active[~active["player_id"].isin(received)], back])
            over = len(cf) - s.roster_limit
            if over > 0:
                cuttable = cf[~cf["player_id"].isin(traded)].copy()
                cuttable["arrived"] = [s.stint_start.get((team, p, week), 0) for p in cuttable["player_id"]]
                cuttable["avg"] = [s.avg_to_date(p, week) for p in cuttable["player_id"]]
                cut = (cuttable.sort_values(["arrived", "avg"], ascending=[False, True])
                       .head(over)["player_id"])
                cf = cf[~cf["player_id"].isin(cut)]
            row[key] = round(_optimal(active, s.slots, col) - _optimal(cf, s.slots, col), 2)

        # Started lineup: received starters out, their slots refilled.
        starters = roster[roster["is_active_slot"]]
        score = round(float(starters["points"].sum()), 2)
        started_received = starters[starters["player_id"].isin(received)]
        vacated = started_received["slot"].tolist()
        bench = roster[roster["slot"] == "BE"]
        for col, key in (("points", "started"), ("healthy", "started_healthy")):
            candidates = ([(p, pt, True) for p, pt in zip(back["player_id"], back[col])]
                          + [(p, pt, False) for p, pt in zip(bench["player_id"], bench[col])])
            refill = _refill(vacated, candidates, s, week, col)
            row[key] = round(float(started_received[col].sum()) - refill, 2)

        # Wins flipped, from the lineup as started: regular season weeks here,
        # playoff rounds below once every held week is graded.
        row["score"] = score
        row["cf_score"] = round(score - row["started"], 2)
        row["opp_score"] = np.nan
        row["flip"] = 0
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


def weekly_grades(season: int) -> pd.DataFrame:
    """One row per trade, manager and week held: the four deltas and the flip."""
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


def trade_grades(season: int) -> pd.DataFrame:
    """
    One row per trade per manager: the trade as the tracker shows it, plus
    the weeks held and the four summed deltas and wins flipped. Trades with
    no weeks held carry zeros and weeks == 0.
    """
    if not supported(season) or not archive.has("transactions", season):
        return pd.DataFrame(columns=SIDE_COLS)
    sides = trade_sides(archive.get("transactions", season))
    if sides.empty:
        return pd.DataFrame(columns=SIDE_COLS)
    weekly = weekly_grades(season)
    if weekly.empty:
        agg = pd.DataFrame(columns=["transaction_id", "team_id"])
    else:
        agg = (weekly.groupby(["transaction_id", "team_id"])
               .agg(weeks=("week", "size"), first_week=("week", "min"), last_week=("week", "max"),
                    best=("best", "sum"), best_healthy=("best_healthy", "sum"),
                    started=("started", "sum"), started_healthy=("started_healthy", "sum"),
                    wins_flipped=("flip", "sum"),
                    wins_created=("flip", lambda f: int((f > 0).sum())),
                    losses_caused=("flip", lambda f: int((f < 0).sum())))
               .reset_index())
    out = sides.merge(agg, on=["transaction_id", "team_id"], how="left")
    for c in ("weeks", "wins_flipped", "wins_created", "losses_caused"):
        out[c] = out[c].fillna(0).astype(int)
    for c in ("best", "best_healthy", "started", "started_healthy"):
        out[c] = out[c].fillna(0.0).round(2)
    out["first_week"] = out["first_week"].astype("Int64")
    out["last_week"] = out["last_week"].astype("Int64")
    return out[SIDE_COLS]


def manager_summary(grades: pd.DataFrame, manager_map: dict[int, str]) -> pd.DataFrame:
    """
    One row per manager with at least one trade: trades, weeks, the four
    sums and wins flipped, and an up-even-down record on the best-lineup
    delta. Good is a trade that added to the best lineup over the weeks held,
    at all; the size is in the points.
    """
    cols = ["team_id", "manager", "trades", "weeks", "up", "even", "down",
            "best", "best_healthy", "started", "started_healthy", "wins_flipped"]
    if grades.empty:
        return pd.DataFrame(columns=cols)
    g = grades.copy()
    g["up"] = g["best"] > 0
    g["down"] = g["best"] < 0
    g["even"] = g["best"] == 0
    out = (g.groupby("team_id")
           .agg(trades=("transaction_id", "nunique"), weeks=("weeks", "sum"),
                up=("up", "sum"), even=("even", "sum"), down=("down", "sum"),
                best=("best", "sum"), best_healthy=("best_healthy", "sum"),
                started=("started", "sum"), started_healthy=("started_healthy", "sum"),
                wins_flipped=("wins_flipped", "sum"))
           .reset_index())
    out["manager"] = out["team_id"].map(manager_map)
    for c in ("up", "even", "down"):
        out[c] = out[c].astype(int)
    return out[cols].sort_values("best", ascending=False, ignore_index=True)
