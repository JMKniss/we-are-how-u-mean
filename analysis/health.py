"""
Injury luck: how much of each team the season's injuries took.

Two numbers lead, both the same measurement on two bases: of everything the
team had on the field, the share that sat out injured. Each player-week is
valued in the draft value's per-game VOR units (points per game above the
last starter at the position); a team's loss is that value times the part of
the game lost, summed (a mid-game injury in the lineup is priced differently,
below); its capacity is the value summed over every counted roster week; the
share is loss / capacity.

    games lost          Out or IR = 1, Mid-Game Injury = injury_weight,
                        for players above replacement by draft or by play
    draft capital lost  valued at the pick's expected VOR, carried through
                        trades as a cost basis: what the team expected
    actual value lost   valued at what the player was actually worth: what
                        the team was getting
    injury luck         actual value lost in wins, for the Luck tab: each
                        week's points put back on the score and read as a
                        change in the chance of winning

Each is shown as points and as a share. Points is the VOR-points lost: what
the injured players would have scored above replacement in the games they
missed, which is the number a manager thinks in. The share puts the two on
one scale - 15% by draft capital and 15% by actual value mean the same
fraction of the team, priced two ways. A team
whose draft share is well above its actual share lost players who were
drafted high and not living up to it; the reverse, players outplaying their
pick.

Each piece answers a question settled in the November 2026 exploration
(Claude outputs/TEAM_HEALTH_RESULTS.md has the tables).

A lost game is read from game_status.csv, which records whether each player
played at game time, from the NFL rather than ESPN. Out and IR are a whole
game, valued above replacement, since a replacement-level player stood in
the slot. A mid-game injury in the lineup is different: nobody filled in,
so the loss is his full points, replacement included, times the share of
the team's offensive plays after he went down - capped at the shortfall to
his full-game expectation, and floored at zero. Two players hurt at
halftime are not equally unlucky when one had 12 points by then and the
other none: on an expectation of 14 the first lost his shortfall, 2, the
second the missed half, 7. The cap is what keeps a flop out of the injury
column: an injury cannot cost more than the part of the game it took, nor
the points he had already scored, and a poor half is the other luck
measures' business. Hurt mid-game on the bench he is valued like an Out,
above replacement times the share, since someone stood in the slot. Under
this rule mid-game injuries are about a fifth of actual value lost; priced
above replacement times the share, as they were before, a twentieth. Bye,
Suspended and Inactive are not injuries: a bye everyone
takes, a suspension is the player's doing, and a healthy scratch is the
coach's. Those weeks leave both the loss and the capacity, so a team is not
charged for a bye and not credited with a week's value it could never have
used. A player-week with no status at all is Healthy.

A player dropped while hurt stays charged to the team that dropped him.
Cutting a player out for the season is the sensible move and should not
make the injury disappear from the books, so when a team's last week with
a player is one he lost any of, he is carried on that team, a whole game
lost each week, while he stays Out or IR. The carry ends the week he plays,
is a healthy scratch or suspended, or anyone rosters him, and a bye passes
without counting. His value is the one he left with, basis included. It
adds 30 to 76 regular-season weeks a season. Draft capital gains most from
it, -0.35 to -0.41 against points for.

Games lost counts only starting assets: a player above replacement by his
play (actual value above zero) or by his draft (taken among the first N at
his position, N the league's weekly starters there - the 31st receiver off
the board is a starter, the 40th is not). Either qualifies him, once. The
40th receiver missing a month is not an injury a team felt, and counting
every rostered player made a bench of fringe players look unlucky. The
draft half is a draft rank rather than expected value above zero because
the draft curve gives nearly every pick through round 16 a sliver of
expected value, so that test would have counted everyone drafted. A
drafted starter keeps qualifying after he is traded or dropped. The two
value columns need no such rule, since a player at or below replacement is
worth nothing in them already. Biggest Losses and Team Detail show each
player's own games.

QB, RB, WR and TE only, as in draft value. A kicker or defence has no draft
expectation worth the name - the curve expects late picks to be bench RBs -
and the replacement kicker is a waiver claim away, so losing one costs a
team almost nothing measurable.

Actual value is the player's healthy points per game above replacement, over
his whole season to date, playoffs included, rostered or not: Healthy weeks
only, since a mid-game exit would mark him down for the injury being
measured. Replacement is the draft value rule on healthy PPG - the Nth best
at the position among players with at least half the season's games, N the
league's weekly starters there from the box scores. It is one number per
position for the whole league, never the manager's own bench: valuing a
lost player against whoever replaced him would measure depth, and a deep
roster would look as if its injuries cost less when it had only covered
them. It is blended with the
draft expectation by a logistic in his healthy games:

    w = 1 / (1 + exp(-(n - MIDPOINT) / SLOPE))
    actual = max(0, w x (healthy PPG - replacement) + (1 - w) x expected)

MIDPOINT 4.5, SLOPE 1: one to three games barely move him off his pick (w
0.03, 0.08, 0.18), six or seven settle him on what he did (0.82, 0.92), and
by nine it is all his play. The curve is the league's reading of when a
player's season is known: a hit or a bust shows in four to six games, and
seven games of PPG, noisy as that still is, outranks the pick. Before it
the blend was n / (n + 5), which still weighed a twelve-game player's pick
at 30%; midpoints from 3.5 to 6 rank teams alike, as K from 3 to 12 did.
The floor at zero is replacement value, not nothing: an undrafted player's
expectation is zero above replacement, so a waiver pickup hurt in week 3
is worth replacement plus whatever the curve lets his two weeks say.

Raw actual value lost is never what the table ranks on. Good teams have more
to lose: over 2018-2025 playoff teams lost 25.5 to the rest's 22.3, and the raw
total correlates -0.13 with points for, i.e. hardly at all. As a leaderboard it
would rank the strongest rosters as the unluckiest. Divided by the team's
capacity - the same values summed over every counted roster week - it
correlates -0.39 with points for and +0.31 with finish, the best against
finish of every measure tried. Draft capital does not have this problem, because the snake
evens capacity out (ρ 0.10 with points for), so its total and its share rank
teams nearly alike. Its share is there so it sits on the same scale as
actual value. Both totals were VOR-games at first, a games-weighted per-game
value that read as a different kind of number from the percent beside it,
and that no manager would recognise; points above replacement is the same
thing multiplied out.

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
RATIO_CAP]. It correlates no better than plain frozen and appears only in
What We Checked, below.

So is the hard minimum: healthy PPG above replacement with no shrinkage,
falling back to the draft expectation under MIN_GAMES games. It ranks teams
almost exactly as the blended value does, and the blended value needs no
cliff at three games.

A season in progress needs no special case. Actual value over the archive
to date is the best current estimate of what each player is worth, and it
converges on the hindsight number as the season completes. Replacement is
the level to date as well.

What We Checked: every measure tried, ranked against the standings over the
completed seasons. It was a table on the page and was taken off in November
2026; what_we_checked() still builds it, with a playoff split pooled over
the seasons (the page's Playoff vs Non-Playoff Teams is playoff_split, one
season). As it stood, 2018-2025,
Spearman on within-season z-scores, playoff rate for the least- and
most-injured third of teams:

    measure                           pts for  finish  playoffs least / most
    Games lost                        -0.29   +0.20    29% /  41%
    Draft capital                     -0.42   +0.25    33% /  41%
    Draft capital, no trade handling  -0.44   +0.26    38% /  34%
    Actual value, total               -0.18   +0.09    33% /  50%
    Actual value, share               -0.46   +0.35    42% /  44%
    Actual value, hard minimum        -0.42   +0.30    46% /  41%
    In-season, frozen                 -0.44   +0.30    38% /  47%
    In-season with trade ratio        -0.44   +0.30    33% /  41%

Counted only for starting assets, games lost is respectable, but weighing
each game by what the player was worth does better, and none of them
explains more than about a fifth of the spread in points scored. The
logistic blend and the mid-game rule (November 2026) moved actual value's
share from -0.39 to -0.46 against points for and left the order of the
measures as it was.

Injury luck, on the Luck tab, is actual value lost in wins. Each week's
points lost are added back to the team's score, and the chance of beating a
typical other team that week - a normal curve centred on the other teams'
average, with the season's usual spread of a score around its week's
average, the trade grades' expected wins - is read before and after. The
differences sum to wins lost; luck is the league's average minus the
team's, so a healthy season reads as lucky and the column sums to zero. It
sits beside the luck total, never in it: the total is a chain of
counterfactuals on the opponent's side of the scoreboard that adds up
exactly, and this is one on the team's own. Known to undercount, by the
league's own note: points lost in a week the rest of the roster had
already lost still count toward points for, the first tiebreaker, and a
great player's average understates the explosion weeks he takes with him.
And it is on a different scale from the rest of the tab: the chain counts
whole games won or lost, this counts marginal win chance, which moves at
most about 0.15 per ten points near the middle of a week and almost
nothing in a week lost by thirty. 2026 through week 9: Brian lost 85.7
points, nearly ten a week, and it read -0.56, less than one bad median
week. Kept as is by the league's choice; the first thing to fix when the
luck metric is redefined. Not a boom-bust model.

2016 and 2017 get nothing: there is no game status for them, and ESPN kept
only starters, so neither a lost game nor a replacement level can be read.
"""
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.stats import norm

from analysis import draft_value as dv
from analysis.standings import playoff_seeds
from config import season_config
from data import archive

POSITIONS = ("QB", "RB", "WR", "TE")   # as draft value; K and D/ST out
MIDPOINT = 4.5  # healthy games at which his play and his pick weigh the same
SLOPE = 1.0     # games per step of the logistic; smaller is steeper
CURVE = (MIDPOINT, SLOPE)
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


def _blend(n, above, expected, curve=CURVE):
    """
    The actual-value formula: a logistic in healthy games n weighs what he
    did above replacement against what his pick expected. Floored at zero,
    which is replacement value, not nothing.
    """
    midpoint, slope = curve
    w = 1 / (1 + np.exp(-(np.asarray(n, dtype=float) - midpoint) / slope))
    return (w * above + (1 - w) * expected).clip(lower=0)


def _lost_points(x: pd.DataFrame, col: str) -> np.ndarray:
    """
    Points lost under one value column. Out, IR, or hurt mid-game on the
    bench: the value times the share of the game lost, since a
    replacement-level player stood in his slot. Hurt mid-game in the
    lineup: full points, replacement included, since nobody filled in,
    times the share of the game missed - but never more than the shortfall
    to his full-game expectation, so a player who had his points before he
    went down was not unlucky, and never below zero, since an injury is
    never lucky.
    """
    full = x[col] + x["replacement"]
    capped = np.minimum(full * x["lost"], full - x["points"]).clip(lower=0)
    in_lineup = (x["status"] == "Mid-Game Injury") & x["is_active_slot"]
    return np.where(in_lineup, capped, x[col] * x["lost"])


@lru_cache(maxsize=32)
def _player_weeks(season: int, curve: tuple = CURVE) -> pd.DataFrame:
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
    # Drafted as a starter: among the first N taken at his position, N the
    # same weekly starter count that sets replacement.
    picks = picks.drop_duplicates("player_id").sort_values("overall_pick")
    pos_rank = picks.groupby("position").cumcount() + 1
    drafted_starter = pd.Series(
        pos_rank.values <= picks["position"].map(lambda p: int(starters.get(p, 10))).values,
        index=picks["player_id"].values)

    d = box[["week", "team_id", "player_id", "player_name", "position", "slot",
             "is_active_slot", "points"]].merge(
        gs, on=["week", "player_id"], how="left")
    d["status"] = d["status"].fillna("Healthy")
    d["lost"] = np.select([d["status"].isin(INJURED), d["status"] == "Mid-Game Injury"],
                          [1.0, d["injury_weight"].fillna(0)], 0.0)
    d["counted"] = ~d["status"].isin(NOT_A_GAME)
    d["expected"] = d["player_id"].map(expected).fillna(0.0)
    d["drafted_starter"] = d["player_id"].map(drafted_starter).fillna(False).astype(bool)
    d["replacement"] = d["position"].map(repl)
    d["healthy_games"] = d["player_id"].map(hs["games"]).fillna(0).astype(int)
    d["healthy_ppg"] = d["player_id"].map(hs["ppg"])
    above = (d["healthy_ppg"] - d["replacement"]).fillna(0.0)
    d["actual"] = _blend(d["healthy_games"], above, d["expected"], curve)
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
    d["frozen"] = _blend(n_w, pd.Series(above_w), d["expected"], curve)

    d = _apply_trades(d, season)
    d = _carry_dropped(d, gs, cw)
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


def _carry_dropped(d: pd.DataFrame, gs: pd.DataFrame, cw: int) -> pd.DataFrame:
    """
    Keep charging a team for a player it let go while he was hurt. When a
    team's last week with a player is one he lost any of, he stays on that
    team's books, Out or IR, every following week until he plays, sits as a
    healthy scratch or suspension, or anyone rosters him. Each carried week
    is his last rostered row with the week and status changed, so his values,
    basis and ratio are the ones he left with. A bye passes without a row.
    """
    d["dropped"] = False
    held = set(zip(d["week"], d["team_id"], d["player_id"]))
    rostered = set(zip(d["week"], d["player_id"]))
    status = gs.set_index(["week", "player_id"])["status"].to_dict()
    ends = d[(d["lost"] > 0) & (d["week"] < cw)
             & np.array([(w + 1, t, p) not in held
                         for w, t, p in zip(d["week"], d["team_id"], d["player_id"])])]
    carried = []
    for _, row in ends.iterrows():
        for week in range(int(row["week"]) + 1, cw + 1):
            s = status.get((week, row["player_id"]))
            if (week, row["player_id"]) in rostered or s not in INJURED + ("Bye",):
                break
            if s == "Bye":
                continue
            r = row.copy()
            r["week"], r["status"], r["lost"], r["points"] = week, s, 1.0, 0.0
            r["slot"], r["counted"], r["dropped"] = "Dropped", True, True
            carried.append(r)
    if carried:
        d = pd.concat([d, pd.DataFrame(carried).astype(d.dtypes.to_dict())],
                      ignore_index=True)
        d = d.sort_values(["week", "player_id"]).reset_index(drop=True)
    return d


def player_weeks(season: int, curve: tuple = CURVE) -> pd.DataFrame:
    """
    One row per rostered QB/RB/WR/TE player-week through the archive's
    current week: who had him, whether and how much of the game he lost,
    and his value per game under every measure (expected, actual,
    actual_hard, frozen, basis, ratio). See the module docstring.
    """
    return _player_weeks(season, curve).copy()


def trade_log(season: int) -> pd.DataFrame:
    """Every trade side's basis and ratio bookkeeping, for checking."""
    log = []
    _apply_trades(_player_weeks(season).drop(columns=["basis", "ratio"]).copy(), season, log)
    return pd.DataFrame(log)


def _window(season: int, window: str, curve: tuple = CURVE) -> pd.DataFrame:
    d = _player_weeks(season, curve)
    x = d[d[window] & d["counted"]]
    if window == "playoff":
        seeds = playoff_seeds(season, archive.get("matchups", season))[:4]
        x = x[x["team_id"].isin(seeds)]
    return x


def team_health(season: int, window: str = "reg", curve: tuple = CURVE) -> pd.DataFrame:
    """
    One row per team over the regular season ("reg") or the playoff weeks
    ("playoff", the four seeds only). Totals are points lost; shares are
    percents of the team's capacity under the same measure. biggest is up to
    two (player_name, player_id, games_lost) by draft capital lost: the
    players the team expected most from and lost, which reads as the injury
    story of a season more plainly than actual value, where a hurt star who
    was having a down year drops out of the list.
    """
    x = _window(season, window, curve).copy()
    x["frozen_ratio"] = x["frozen"] * x["ratio"]
    g = x.groupby("team_id")

    def lost(col):
        return pd.Series(_lost_points(x, col), index=x.index).groupby(x["team_id"]).sum()

    def share(col):
        return lost(col) / g[col].sum().replace(0, np.nan) * 100

    out = pd.DataFrame({
        "games_lost": x["lost"].where((x["actual"] > 0) | x["drafted_starter"], 0.0)
                      .groupby(x["team_id"]).sum(),
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
    x["draft_lost"] = _lost_points(x, "basis")
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
    x = _window(season, window)
    x = x[x["team_id"] == team_id].copy()
    draft_cap, actual_cap = x["basis"].sum(), x["actual"].sum()
    x = x[x["lost"] > 0]
    x["actual_lost"] = _lost_points(x, "actual")
    x["draft_lost"] = _lost_points(x, "basis")
    out = (x.groupby("player_id")
           .agg(player_name=("player_name", "first"), position=("position", "first"),
                games_lost=("lost", "sum"), actual=("actual", "first"),
                expected=("expected", "first"), basis=("basis", "last"),
                actual_lost=("actual_lost", "sum"), draft_capital_lost=("draft_lost", "sum"))
           .reset_index())
    out["draft_capital_share"] = out["draft_capital_lost"] / draft_cap * 100 if draft_cap else 0.0
    out["actual_share"] = out["actual_lost"] / actual_cap * 100 if actual_cap else 0.0
    return out.sort_values("draft_capital_lost", ascending=False).reset_index(drop=True)


def injury_luck(season: int) -> pd.DataFrame:
    """
    One row per team: regular-season actual value lost, in points and in
    games, and the luck it amounts to. Each week's points lost are added
    back to the team's score, and the chance of beating a typical other
    team that week - a normal curve centred on the other teams' average,
    with the season's usual spread of a score around its week's average, as
    the trade grades count expected wins - is read before and after. The
    difference, summed over the weeks, is wins lost. Luck is the league's
    average wins lost minus the team's, so a healthy team reads as lucky
    and the column sums to zero.
    """
    x = _window(season, "reg")
    lost = (pd.Series(_lost_points(x, "actual"), index=x.index)
            .groupby([x["team_id"], x["week"]]).sum())
    m = archive.get("matchups", season)
    m = m[m["week"] <= min(weeks_to_date(season), season_config(season)["reg_season_end"])]
    week_mean = m.groupby("week")["score"].transform("mean")
    n = m.groupby("week")["score"].transform("size")
    others = (week_mean * n - m["score"]) / (n - 1).replace(0, np.nan)
    sd = float((m["score"] - week_mean).std()) if len(m) > 1 else 0.0
    pts = pd.Series([float(lost.get((t, w), 0.0)) for t, w in zip(m["team_id"], m["week"])],
                    index=m.index)
    if sd > 0:
        gain = norm.cdf((m["score"] + pts - others) / sd) - norm.cdf((m["score"] - others) / sd)
    else:
        gain = np.zeros(len(m))
    out = pd.DataFrame({
        "points_lost": pts.groupby(m["team_id"]).sum(),
        "wins_lost": pd.Series(gain, index=m.index).fillna(0.0).groupby(m["team_id"]).sum()})
    out["injury_luck"] = out["wins_lost"].mean() - out["wins_lost"]
    out["manager"] = out.index.map(archive.manager_map(season))
    return out.reset_index()


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


def playoff_split(season: int) -> pd.DataFrame:
    """
    Mean regular-season games lost, actual value lost and its share for the
    season's four playoff seeds and the rest. Before the regular season ends
    the seeds are the current top four, so in_progress is set and the page
    labels the groups as positions rather than results.
    """
    t = team_health(season, "reg").set_index("team_id")
    m = archive.get("matchups", season)
    t["playoffs"] = t.index.isin(playoff_seeds(season, m)[:4])
    out = (t.groupby("playoffs")[["games_lost", "actual_lost", "actual_share"]].mean()
           .reindex([True, False]))
    out.attrs["in_progress"] = weeks_to_date(season) < season_config(season)["reg_season_end"]
    return out


MEASURES = [
    ("Games lost", "1 per game, players above replacement by draft or play",
     "games_lost"),
    ("Draft capital", "the pick's expected VOR, cost basis through trades",
     "draft_capital_share"),
    ("Draft capital, no trade handling", "the pick's expected VOR, player keeps it",
     "draft_capital_naive_share"),
    ("Actual value, total", "healthy PPG above replacement, blended with the pick by games played",
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


def what_we_checked(seasons, curve: tuple = CURVE) -> tuple[pd.DataFrame, pd.DataFrame]:
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
        t = team_health(s, "reg", curve).set_index("team_id").join(season_outcomes(s))
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
