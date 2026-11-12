"""
Injury luck: how much of each team the season's injuries took.

Two numbers lead, both the same measurement on two bases: of everything the
team had on the field, the share that sat out injured. Each player-week is
valued in the draft value's per-game VOR units (points per game above the
last starter at the position); a team's loss is that value times the part of
the game lost, summed; its capacity is the value summed over every counted
roster week; the share is loss / capacity.

    games lost          Out or IR = 1, Mid-Game Injury = injury_weight
    draft capital lost  valued at the pick's expected VOR, carried through
                        trades as a cost basis: what the team expected
    actual value lost   valued at what the player was actually worth: what
                        the team was getting

Shown as shares so the two read on one scale - 15% by draft capital and 15%
by actual value mean the same fraction of the team, priced two ways. A team
whose draft share is well above its actual share lost players who were
drafted high and not living up to it; the reverse, players outplaying their
pick.

Each piece answers a question settled in the November 2026 exploration
(Claude outputs/TEAM_HEALTH_RESULTS.md has the tables).

A lost game is read from game_status.csv, which records whether each player
played at game time, from the NFL rather than ESPN. Out and IR are a whole
game; a mid-game injury is the share of the team's offensive plays after he
went down. Bye, Suspended and Inactive are not injuries: a bye everyone
takes, a suspension is the player's doing, and a healthy scratch is the
coach's. Those weeks leave both the loss and the capacity, so a team is not
charged for a bye and not credited with a week's value it could never have
used. A player-week with no status at all is Healthy.

QB, RB, WR and TE only, as in draft value. A kicker or defence has no draft
expectation worth the name - the curve expects late picks to be bench RBs -
and the replacement kicker is a waiver claim away, so losing one costs a
team almost nothing measurable.

Actual value is the player's healthy points per game above replacement, over
his whole season to date, playoffs included, rostered or not: Healthy weeks
only, since a mid-game exit would mark him down for the injury being
measured. Replacement is the draft value rule on healthy PPG - the Nth best
at the position among players with at least half the season's games, N the
league's weekly starters there from the box scores. It is shrunk toward the
draft expectation by K games:

    actual = max(0, (n x (healthy PPG - replacement) + K x expected) / (n + K))

so a player hurt in week 2 is worth roughly what he was drafted to be worth,
and a player with twelve healthy games is worth what he did. K is 5. Anything
from 3 to 12 gives the same ranking of teams; 5 is where rank correlation
with the standings peaks and where the in-season version, which has the
fewest games to go on, stops being starved toward the prior.

Raw actual value lost is never shown as a total. Good teams have more to
lose: over 2018-2025 playoff teams lost 21.1 to the rest's 18.2, and the raw
total correlates -0.09 with points for, i.e. not at all. As a leaderboard it
would rank the strongest rosters as the unluckiest. Divided by the team's
capacity - the same values summed over every counted roster week - it
correlates -0.39 with points for and +0.33 with finish, the best of every
measure tried. Draft capital does not have this problem, because the snake
evens capacity out (ρ 0.15 with points for), so its total and its share rank
teams nearly alike; it is shown as a share only so it sits on the same
scale as actual value. It was a total in VOR-games at first, which read as
a different kind of number from the percent beside it.

Draft capital through trades is a cost basis. A drafted player starts at his
pick's expected VOR (undrafted, 0). In a trade each side's incoming players
are given the basis of what it sent, split in proportion to their own basis
(evenly if all are zero), so a team that traded a first-rounder for a hurt
receiver lost a first-rounder's worth when he sat. Players dropped as part
of a trade take their basis with them. Basis is conserved through every
trade. It moves few teams - ρ 0.99 against letting each player keep his own
pick - but those few by a lot (2022 Tim -8.8, who had acquired his injured
players cheaply; 2024 Brian +7.6, who paid more than their picks), and it is
the right accounting for "what did you lose of what you paid". A trade takes
effect the first week the box scores show a moved player on his new team.

Actual value has no trade handling: a player is worth what he scores
wherever he plays, and "what did injury cost this team on the field" is
answered by the player, not by the price.

The in-season frozen value is the actual formula using only healthy games
before each week, never revised, so week 4's number is what was knowable in
week 4. With a trade ratio it is also scaled by what the manager paid: each
side's incoming players are multiplied by (value sent / value received) at
the trade. 2025 shows what that measures. Tyler got Bucky Irving in week 7
for a player worth a third as much and lost him for five games: plain frozen
says 18.8 lost, the ratio 5.7, because he paid little. Cost basis asks what
you lost of what you paid at the draft, the ratio asks the same priced at
the trade, plain asks what left the field. Unbounded, early-season values
clamp to zero and the ratio ran from 0 to 550, so each player's trade-time
value is floored at FLOOR and one trade's ratio is bounded to [1/RATIO_CAP,
RATIO_CAP]. It correlates no better than plain frozen and is shown only in
What We Checked.

So is the hard minimum: healthy PPG above replacement with no shrinkage,
falling back to the draft expectation under MIN_GAMES games. It ranks teams
almost exactly as the shrunk value does (ρ 0.95), and the shrunk value needs
no cliff at three games.

A season in progress needs no special case. Actual value over the archive
to date is the best current estimate of what each player is worth, and it
converges on the hindsight number as the season completes. Replacement is
the level to date as well.

What We Checked keeps every measure tried on the page, with how each ranks
against points for and the regular-season finish over the completed
seasons, because the league would otherwise ask why games lost is not the
number. The answer is that it is the weakest of them, and that none of them
explains more than about a seventh of the spread in points scored.

2016 and 2017 get nothing: there is no game status for them, and ESPN kept
only starters, so neither a lost game nor a replacement level can be read.
"""
from functools import lru_cache

import numpy as np
import pandas as pd

from analysis import draft_value as dv
from analysis.standings import playoff_seeds
from config import season_config
from data import archive

POSITIONS = ("QB", "RB", "WR", "TE")   # as draft value; K and D/ST out
K = 5          # shrinkage games toward the draft expectation
FLOOR = 0.5    # a player's value when pricing a trade is never below this
RATIO_CAP = 3  # one trade's ratio is bounded to [1/3, 3]
MIN_GAMES = 3  # the hard-minimum variant, second tier only
INJURED = ("Out", "IR")
NOT_A_GAME = ("Bye", "Suspended", "Inactive")
FIRST_SEASON = dv.FIRST_SEASON


def supported(season: int) -> bool:
    return season >= FIRST_SEASON and archive.has("game_status", season)


def weeks_to_date(season: int) -> int:
    """The last week the archive holds, capped at the season's end."""
    return min(archive.current_week(season) or 0, season_config(season)["total_weeks"])


def _shrunk(n, above, expected, k):
    """The actual-value formula: n games above replacement, k games of prior."""
    return ((n * above + k * expected) / (n + k)).clip(lower=0)


@lru_cache(maxsize=32)
def _player_weeks(season: int, k: int) -> pd.DataFrame:
    cfg = season_config(season)
    reg_end = cfg["reg_season_end"]
    cw = weeks_to_date(season)

    box = archive.get("boxscores", season)
    box = box[(box["week"] <= cw) & box["position"].isin(POSITIONS)].drop_duplicates(
        ["week", "player_id"])
    gs = archive.get("game_status", season)[["week", "player_id", "status", "injury_weight"]]
    card = archive.get("player_weeks", season)
    card = card[(card["week"] <= cw) & card["position"].isin(POSITIONS)]

    # Healthy games, whole season to date, playoffs included, rostered or not.
    healthy = card.merge(gs, on=["week", "player_id"], how="left")
    healthy = healthy[healthy["status"] == "Healthy"]
    hs = healthy.groupby("player_id").agg(points=("points", "sum"), games=("points", "size"))
    hs["ppg"] = hs["points"] / hs["games"]
    hs["position"] = card.drop_duplicates("player_id").set_index("player_id")["position"]

    # Replacement: draft value's rule, on healthy PPG.
    active = box[box["is_active_slot"] & (box["week"] <= reg_end)]
    starters = (active.groupby("week")["position"].value_counts()
                .groupby("position").mean().round().astype(int))
    regulars = hs[hs["games"] >= max(1, min(cw, reg_end) / 2)]
    repl = {}
    for pos in POSITIONS:
        pool = regulars[regulars["position"] == pos]["ppg"].sort_values(ascending=False)
        n = int(starters.get(pos, 10))
        repl[pos] = float(pool.iloc[min(n, len(pool)) - 1]) if len(pool) else 0.0

    picks, _, _ = dv.draft_value(season)
    picks = picks[picks["player_id"] != 0]
    expected = picks.drop_duplicates("player_id").set_index("player_id")["expected"].clip(lower=0)

    d = box[["week", "team_id", "player_id", "player_name", "position", "slot", "points"]].merge(
        gs, on=["week", "player_id"], how="left")
    d["status"] = d["status"].fillna("Healthy")
    d["lost"] = np.select([d["status"].isin(INJURED), d["status"] == "Mid-Game Injury"],
                          [1.0, d["injury_weight"].fillna(0)], 0.0)
    d["counted"] = ~d["status"].isin(NOT_A_GAME)
    d["expected"] = d["player_id"].map(expected).fillna(0.0)
    d["replacement"] = d["position"].map(repl)
    d["healthy_games"] = d["player_id"].map(hs["games"]).fillna(0).astype(int)
    d["healthy_ppg"] = d["player_id"].map(hs["ppg"])
    above = (d["healthy_ppg"] - d["replacement"]).fillna(0.0)
    d["actual"] = _shrunk(d["healthy_games"], above, d["expected"], k)
    d["actual_hard"] = np.where(d["healthy_games"] >= MIN_GAMES, above.clip(lower=0),
                                d["expected"])

    # Frozen: the same formula on the healthy games before this week only.
    cum = healthy[["week", "player_id", "points"]].sort_values("week")
    cum["cum_pts"] = cum.groupby("player_id")["points"].cumsum()
    cum["cum_n"] = cum.groupby("player_id").cumcount() + 1
    d = d.sort_values(["week", "player_id"]).reset_index(drop=True)
    before = pd.merge_asof(d[["week", "player_id"]], cum[["week", "player_id", "cum_pts", "cum_n"]],
                           on="week", by="player_id", allow_exact_matches=False)
    n_w = before["cum_n"].fillna(0)
    above_w = np.where(n_w > 0, before["cum_pts"].fillna(0) / n_w.where(n_w > 0, 1)
                       - d["replacement"], 0.0)
    d["frozen"] = _shrunk(n_w, pd.Series(above_w), d["expected"], k)

    d = _apply_trades(d, season)
    d["reg"] = d["week"] <= reg_end
    d["playoff"] = d["week"].isin(cfg["playoff_weeks"])
    return d


def _trades(season: int) -> list[pd.DataFrame]:
    """Each trade's moved players, in the order the trades were executed."""
    if not archive.has("transactions", season):
        return []
    tx = archive.get("transactions", season)
    tx = tx[(tx["kind"] == "trade") & (tx["action"] == "trade")].sort_values(
        ["executed_at", "week"])
    return [t for _, t in tx.groupby("transaction_id", sort=False)]


def _apply_trades(d: pd.DataFrame, season: int, log: list | None = None) -> pd.DataFrame:
    """
    Cost basis and trade ratio, chained through every trade. A trade applies
    from the first week, up to two after it was made, that the box scores
    show a moved player on his new team; one never seen there is skipped.
    log, if given, collects each side's bookkeeping for checking.
    """
    d["basis"] = d["expected"]
    d["ratio"] = 1.0
    basis = d.drop_duplicates("player_id").set_index("player_id")["expected"].to_dict()
    ratio = {}
    owner = d.groupby(["player_id", "week"])["team_id"].first()
    for t in _trades(season):
        wk0 = int(t["week"].iloc[0])
        eff = next((w for w in range(wk0, wk0 + 3)
                    if any(owner.get((p, w)) == to
                           for p, to in zip(t["player_id"], t["to_team_id"]))), None)
        if eff is None:
            continue
        frozen = d[d["week"] == eff].set_index("player_id")["frozen"]

        def live(p):
            return float(frozen.get(p, 0.0)) * ratio.get(p, 1.0) if p in frozen.index else 0.0

        new_basis, new_ratio = {}, {}
        for team in set(t["from_team_id"]) | set(t["to_team_id"]):
            sent = list(t[t["from_team_id"] == team]["player_id"])
            got = list(t[t["to_team_id"] == team]["player_id"])
            if not got:
                continue
            sent_basis = sum(basis.get(p, 0.0) for p in sent)
            own = [basis.get(p, 0.0) for p in got]
            total = sum(own)
            for p, b in zip(got, own):
                new_basis[p] = sent_basis * (b / total if total > 0 else 1 / len(got))
            v_sent = sum(max(live(p), FLOOR) for p in sent)
            v_got = sum(max(live(p), FLOOR) for p in got)
            r = min(max(v_sent / v_got, 1 / RATIO_CAP), RATIO_CAP) if v_got > 0 else 1.0
            for p in got:
                new_ratio[p] = ratio.get(p, 1.0) * r
            if log is not None:
                log.append({"season": season, "transaction_id": t["transaction_id"].iloc[0],
                            "week": eff, "team_id": team, "sent": sent, "received": got,
                            "sent_basis": sent_basis,
                            "received_basis": sum(new_basis[p] for p in got),
                            "v_sent": v_sent, "v_received": v_got, "ratio": r})
        basis.update(new_basis)
        ratio.update(new_ratio)
        later = d["week"] >= eff
        for p, b in new_basis.items():
            d.loc[(d["player_id"] == p) & later, "basis"] = b
        for p, f in new_ratio.items():
            d.loc[(d["player_id"] == p) & later, "ratio"] = f
    return d


def player_weeks(season: int, k: int = K) -> pd.DataFrame:
    """
    One row per rostered QB/RB/WR/TE player-week through the archive's
    current week: who had him, whether and how much of the game he lost,
    and his value per game under every measure (expected, actual,
    actual_hard, frozen, basis, ratio). See the module docstring.
    """
    return _player_weeks(season, k).copy()


def trade_log(season: int) -> pd.DataFrame:
    """Every trade side's basis and ratio bookkeeping, for checking."""
    log = []
    _apply_trades(_player_weeks(season, K).drop(columns=["basis", "ratio"]).copy(), season, log)
    return pd.DataFrame(log)


def _window(season: int, window: str, k: int) -> pd.DataFrame:
    d = _player_weeks(season, k)
    x = d[d[window] & d["counted"]]
    if window == "playoff":
        seeds = playoff_seeds(season, archive.get("matchups", season))[:4]
        x = x[x["team_id"].isin(seeds)]
    return x


def team_health(season: int, window: str = "reg", k: int = K) -> pd.DataFrame:
    """
    One row per team over the regular season ("reg") or the playoff weeks
    ("playoff", the four seeds only). Totals are VOR-games; shares are
    percents of the team's capacity under the same measure. biggest is up to
    two (player_name, player_id, games_lost) by draft capital lost: the
    players the team expected most from and lost, which reads as the injury
    story of a season more plainly than actual value, where a hurt star who
    was having a down year drops out of the list.
    """
    x = _window(season, window, k).copy()
    x["frozen_ratio"] = x["frozen"] * x["ratio"]
    g = x.groupby("team_id")

    def lost(col):
        return (x[col] * x["lost"]).groupby(x["team_id"]).sum()

    def share(col):
        return lost(col) / g[col].sum().replace(0, np.nan) * 100

    out = pd.DataFrame({
        "games_lost": g["lost"].sum(),
        "draft_capital_lost": lost("basis"),
        "draft_capital_capacity": g["basis"].sum(),
        "draft_capital_share": share("basis"),
        "draft_capital_naive": lost("expected"),
        "draft_capital_naive_share": share("expected"),
        "actual_lost": lost("actual"),
        "actual_capacity": g["actual"].sum(),
        "actual_share": share("actual"),
        "actual_hard_share": share("actual_hard"),
        "frozen_share": share("frozen"),
        "frozen_ratio_share": share("frozen_ratio"),
    })
    x["draft_lost"] = x["basis"] * x["lost"]
    per = (x.groupby(["team_id", "player_id"])
           .agg(player_name=("player_name", "first"), games=("lost", "sum"),
                value=("draft_lost", "sum"))
           .reset_index())
    per = per[per["value"] > 0].sort_values(["team_id", "value"], ascending=[True, False])
    out["biggest"] = pd.Series({
        tid: [(r.player_name, r.player_id, r.games) for r in grp.head(2).itertuples()]
        for tid, grp in per.groupby("team_id")})
    out["biggest"] = out["biggest"].apply(lambda v: v if isinstance(v, list) else [])
    out["manager"] = out.index.map(archive.manager_map(season))
    names = archive.team_names(season)
    out["team_name"] = out.index.map(lambda t: names.get(t, ""))
    return out.reset_index()


def team_detail(season: int, team_id: int, window: str = "reg") -> pd.DataFrame:
    """
    One row per player who lost any of a game for this team in the window:
    his position, games lost, what he was worth per game by his pick (basis)
    and by his play (actual), and the share of the team's capacity lost with
    him under each. The shares sum to the team's draft_capital_share and
    actual_share in team_health.
    """
    x = _window(season, window, K)
    x = x[x["team_id"] == team_id].copy()
    draft_cap, actual_cap = x["basis"].sum(), x["actual"].sum()
    x = x[x["lost"] > 0]
    x["actual_lost"] = x["actual"] * x["lost"]
    x["draft_lost"] = x["basis"] * x["lost"]
    out = (x.groupby("player_id")
           .agg(player_name=("player_name", "first"), position=("position", "first"),
                games_lost=("lost", "sum"), actual=("actual", "first"),
                expected=("expected", "first"), basis=("basis", "last"),
                actual_lost=("actual_lost", "sum"), draft_capital_lost=("draft_lost", "sum"))
           .reset_index())
    out["draft_capital_share"] = out["draft_capital_lost"] / draft_cap * 100 if draft_cap else 0.0
    out["actual_share"] = out["actual_lost"] / actual_cap * 100 if actual_cap else 0.0
    return out.sort_values("draft_capital_lost", ascending=False).reset_index(drop=True)


def season_outcomes(season: int) -> pd.DataFrame:
    """Regular-season wins, points for, rank (wins then points) and playoffs made."""
    m = archive.get("matchups", season)
    reg = m[m["week"] <= season_config(season)["reg_season_end"]]
    out = pd.DataFrame({"wins": (reg["outcome"] == "W").groupby(reg["team_id"]).sum(),
                        "pf": reg["score"].groupby(reg["team_id"]).sum()})
    order = out.sort_values(["wins", "pf"], ascending=False).index
    out["reg_rank"] = pd.Series(range(1, len(order) + 1), index=order)
    seeds = playoff_seeds(season, m)
    out["playoffs"] = out.index.isin(seeds[:4])
    return out


MEASURES = [
    ("Games lost", "1", "games_lost"),
    ("Draft capital", "the pick's expected VOR, cost basis through trades",
     "draft_capital_share"),
    ("Draft capital, no trade handling", "the pick's expected VOR, player keeps it",
     "draft_capital_naive_share"),
    ("Actual value, total", "healthy PPG above replacement, shrunk toward the pick",
     "actual_lost"),
    ("Actual value, share", "the same, as a share of the team's total", "actual_share"),
    ("Actual value, hard minimum",
     "healthy PPG above replacement, draft expected under 3 games; share", "actual_hard_share"),
    ("In-season, frozen", "games played before that week only, never revised; share",
     "frozen_share"),
    ("In-season with trade ratio", "frozen, scaled by what the manager paid at the trade; share",
     "frozen_ratio_share"),
]


def checked_seasons(seasons) -> list[int]:
    """Completed seasons with game status, which is what What We Checked covers."""
    return [s for s in seasons if supported(s) and dv.season_complete(s)]


def what_we_checked(seasons, k: int = K) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    (measures, playoff_split) over the completed seasons among those given.

    measures: one row per entry in MEASURES, with Spearman ρ against points
    for and against regular-season rank, both on within-season z-scores
    pooled across seasons, and the playoff rate of the least- and
    most-injured within-season thirds (percentile rank ≤ 1/3, > 2/3).

    playoff_split: mean games lost, actual value lost and its share for
    teams that made the playoffs and teams that missed.
    """
    rows = []
    for s in checked_seasons(seasons):
        t = team_health(s, "reg", k).set_index("team_id").join(season_outcomes(s))
        t["season"] = s
        rows.append(t)
    pooled = pd.concat(rows)

    def z(col):
        g = pooled.groupby("season")[col]
        return (pooled[col] - g.transform("mean")) / g.transform("std")

    pf_z, rank_z = z("pf"), z("reg_rank")
    out = []
    for name, value_at, col in MEASURES:
        mz = z(col)
        pct = pooled.groupby("season")[col].rank(pct=True)
        out.append({
            "measure": name, "value_at": value_at,
            "rho_pf": mz.corr(pf_z, method="spearman"),
            "rho_rank": mz.corr(rank_z, method="spearman"),
            "playoffs_least": pooled.loc[pct <= 1 / 3, "playoffs"].mean() * 100,
            "playoffs_most": pooled.loc[pct > 2 / 3, "playoffs"].mean() * 100,
        })
    measures = pd.DataFrame(out)

    split = (pooled.groupby("playoffs")[["games_lost", "actual_lost", "actual_share"]].mean()
             .rename(index={True: "Made the playoffs", False: "Missed"})
             .reindex(["Made the playoffs", "Missed"]))
    split.attrs["first"], split.attrs["last"] = min(pooled["season"]), max(pooled["season"])
    measures.attrs.update(split.attrs)
    return measures, split.reset_index(names="group")
