"""
Draft value: how far a pick beat what that draft slot normally returns.

Everything is per game:

    VOR       = max(0, points per game - replacement points per game)
    expected  = a + b * ln(overall_pick)          fitted on VOR
    value     = VOR - expected

Each piece answers a question the league settled before it was built.

Points are the player's whole regular season, whoever had him and whether or
not he started. A bad week counts as negative and a benched week counts in
full, because the question is whether the pick was good, and lineup and
roster decisions are judged elsewhere (Lineup Efficiency, the waiver tabs). A
player the drafter cut who then went off for someone else was a good pick
badly managed, and the page marks him rather than hiding it. Free-agent weeks
come from player_weeks.csv; rostered weeks from boxscores.

Per game, where a game is any week his NFL team played. Injured, suspended
and inactive weeks count as games at zero points - missing them is part of
what the pick cost - but a bye does not. Totals would mark a player down in
week 7 for a bye everyone takes eventually, and per game is also what makes
12-, 13- and 14-week seasons comparable. A game is a week ESPN's player card
has an entry for: the card records every week the player's team played,
injured weeks included, and nothing for a bye. The card has a rare hole in a
week the player scored, so a rostered week with points counts too. A player
with no NFL team - cut, unsigned - has no games for those weeks either.

VOR measures a player against the last starter at his position, so a
position the league runs deep is worth less per point than a shallow one.
Replacement is the Nth best points per game at the position, N being how many
the league actually starts in a week - counted from the box scores, so the
flex falls wherever managers put it (about 25 RB and 25 WR with one flex,
about 30 each with two). Only players with at least half the season's games
are ranked for it, so a single big afternoon cannot set the bar. A TE who
scores less than the RBs taken next to him can still be worth more: the tenth
TE scores far less than the 25th RB.

Floored at zero. A season below replacement gave the team nothing it could
not have had from the waiver wire, but not less than nothing. Unfloored, the
worst picks were late backup QBs: a QB's replacement is so high that one who
never started read as far worse than any failed RB could, and the Biggest
Busts list filled with McCarthy and Purdy instead of the early picks that
actually let their teams down. Pro Football Reference's VBD and Footballguys'
expected VBD floor at zero for the same reason. Bad weeks still count in
full inside a season; only the season is floored.

One curve for every position, not one per position: "was this a good use of
pick 30" is the question, not "was he a good TE for where TEs go". Checked on
2018-2025, RB and WR sit on the curve through round 10 and early TEs come out
slightly above it, so the single curve does not punish a TE for scoring
differently. Kickers and D/ST are left out entirely: a kicker a little above
the tenth kicker looked like a steal against a curve that expects late picks
to be bench RBs, which rated Younghoe Koo at pick 153 as good as Kelce at 27.

Unweighted across seasons. Fitted season by season the curve barely moves
(2018-2025, no trend), because VOR is measured against each season's own
replacement level and NFL-wide scoring shifts move that too. Weighting recent
seasons would mostly have amplified single-season noise.

Frozen once a season is complete, in draft_value_curves.csv, so a later
season never moves an earlier one's values. A season's curve is fitted on
every season from 2018 through itself, in its own scoring: a half-PPR season
refits the earlier ones as half-PPR from their receptions (config.
reception_points). 2018-2025 were all frozen on the same 2018-2025 fit when
this was built. A season in progress gets a provisional curve from the
completed seasons before it.

Injury games are the regular-season games a player missed hurt - Out or IR
in game_status.csv, which covers his free-agent weeks too - plus the share of
a game each mid-game injury cost. Biggest Busts shows the count, so an injury
season reads as one; it was a Y/N at three games first, but an N read as
"not injured" for a player who had missed two. It explains a bust; it does
not change the value, since the pick still cost what it cost.

2016 and 2017 get nothing: ESPN kept only starters and season totals, so
neither free-agent weeks nor a replacement level can be measured.

Team draft value is a plain sum of a team's pick values, with no further
adjustment for the draft capital it started with. The snake already evens
that out: a team's expected, summed over its QB/RB/WR/TE picks, runs only
18-22, and what spread there is comes from the seat and from how many picks
it spent on kickers and D/ST. Normalising on top would mostly be measuring
the seat. Share is the team's VOR as a percent of the whole draft's, so 10%
is an average draft.

The split falls after round 5 (EARLY_ROUNDS). Over 2018-2025 the share of
picks returning any VOR runs 84, 75, 68, 59 and 56% through the first five
rounds, then 45% in round 6 and never above 50 again; median VOR reaches
zero in round 6, and a changepoint on hit rate lands at pick 55. The early
rounds are where nearly all the value is, so a team total alone is mostly a
verdict on rounds 1-5 and hides what a team found later.

Hindsight rank orders a season's scored picks by VOR, so it puts positions on
the same footing: a QB ranks ahead of a RB only if he beat the last starting
QB by more than the RB beat the last starting RB. Every zero-VOR pick ties at
the first non-hit rank (method="min"). A pick that returned nothing has no
hindsight position, and ordering the zeros among themselves would invent
one. picks_gained, overall pick minus hindsight rank, is only read for hits.

None of it repeats. A manager's team value in one season correlates -0.20
with the next, and no other team measure did better, so the table describes
a draft, not a drafter.
"""
import numpy as np
import pandas as pd

from analysis.draft import apply_recorded_order
from config import reception_points, season_config
from data import archive

FIRST_SEASON = 2018
POSITIONS = ("QB", "RB", "WR", "TE")
EARLY_ROUNDS = 5
CURVES = archive.ARCHIVE_DIR / "draft_value_curves.csv"


def supported(season: int) -> bool:
    return season >= FIRST_SEASON


def regular_weeks(season: int) -> int:
    """Regular-season weeks played so far."""
    cw = archive.current_week(season) or 0
    return min(cw, season_config(season)["reg_season_end"])


def season_totals(season: int, rec_pts: float | None = None) -> pd.DataFrame:
    """
    Every player's regular season: points, games, points per game.

    rec_pts rescores the season as if receptions were worth that many points,
    which is how a non-PPR season joins a half-PPR season's curve fit.
    """
    weeks = regular_weeks(season)
    box = archive.get("boxscores", season)
    box = box[box["week"] <= weeks].drop_duplicates(["week", "player_id"])
    card = archive.get("player_weeks", season)
    card = card[card["week"] <= weeks]

    rostered = box[["week", "player_id", "player_name", "position", "points"]].merge(
        card[["week", "player_id", "receptions"]], on=["week", "player_id"],
        how="left", indicator=True)
    rostered["game"] = (rostered["_merge"] == "both") | (rostered["points"] != 0)
    rostered = rostered.drop(columns="_merge")
    seen = pd.MultiIndex.from_frame(rostered[["week", "player_id"]])
    free = card[~pd.MultiIndex.from_frame(card[["week", "player_id"]]).isin(seen)].copy()
    free["game"] = True
    weekly = pd.concat([rostered, free[rostered.columns]], ignore_index=True)
    weekly["receptions"] = weekly["receptions"].fillna(0)

    extra = (reception_points(season) if rec_pts is None else rec_pts) - reception_points(season)
    weekly["points"] = weekly["points"] + extra * weekly["receptions"]
    out = (weekly.groupby("player_id")
           .agg(player_name=("player_name", "first"), position=("position", "first"),
                points=("points", "sum"), games=("game", "sum"))
           .reset_index())
    out["ppg"] = (out["points"] / out["games"].where(out["games"] > 0)).fillna(0.0)
    return out


def replacement_levels(season: int, totals: pd.DataFrame) -> dict:
    """Points per game of the last starter at each position."""
    box = archive.get("boxscores", season)
    box = box[(box["week"] <= regular_weeks(season)) & box["is_active_slot"]]
    starters = (box.groupby("week")["position"].value_counts()
                .groupby("position").mean().round().astype(int))
    regulars = totals[totals["games"] >= max(1, regular_weeks(season) / 2)]
    out = {}
    for pos in POSITIONS:
        pool = regulars[regulars["position"] == pos]["ppg"].sort_values(ascending=False)
        n = int(starters.get(pos, 10))
        out[pos] = float(pool.iloc[min(n, len(pool)) - 1]) if len(pool) else 0.0
    return out


def _draft(season: int) -> pd.DataFrame:
    """The draft in the league's recorded order, as the page shows it."""
    draft = archive.get("draft", season)
    draft, _, _ = apply_recorded_order(draft, season, archive.manager_map(season))
    return draft


def pick_vor(season: int, rec_pts: float | None = None, draft: pd.DataFrame | None = None
             ) -> pd.DataFrame:
    """Every QB/RB/WR/TE pick with games, points per game, replacement and VOR."""
    totals = season_totals(season, rec_pts)
    repl = replacement_levels(season, totals)
    draft = _draft(season) if draft is None else draft
    # The draft carries names, not ids; names are unique within a season.
    by_name = totals.drop_duplicates("player_name").set_index("player_name")
    picks = draft.copy()
    picks["position"] = picks["player_name"].map(by_name["position"])
    for c in ("player_id", "points", "games", "ppg"):
        picks[c] = picks["player_name"].map(by_name[c]).fillna(0)
    picks["games"] = picks["games"].astype(int)
    picks = picks[picks["position"].isin(POSITIONS)].copy()
    picks["replacement"] = picks["position"].map(repl)
    picks["vor"] = (picks["ppg"] - picks["replacement"]).clip(lower=0)
    return picks


def fit_curve(seasons: list[int], rec_pts: float) -> dict:
    """Least-squares a + b*ln(pick) on VOR per game across the given seasons."""
    picks = pd.concat([pick_vor(s, rec_pts) for s in seasons], ignore_index=True)
    slope, intercept = np.polyfit(np.log(picks["overall_pick"]), picks["vor"], 1)
    return {"intercept": round(float(intercept), 4), "slope": round(float(slope), 4),
            "reception_points": rec_pts,
            "fitted_on": f"{min(seasons)}-{max(seasons)}", "picks": len(picks)}


def frozen_curves() -> pd.DataFrame:
    return pd.read_csv(CURVES) if CURVES.exists() else pd.DataFrame()


def season_complete(season: int) -> bool:
    return (archive.current_week(season) or 0) >= season_config(season)["total_weeks"]


def curve_for(season: int) -> tuple[dict, bool]:
    """(curve, frozen). A season not yet frozen gets a provisional fit."""
    frozen = frozen_curves()
    if not frozen.empty and season in set(frozen["season"]):
        return frozen[frozen["season"] == season].iloc[0].to_dict(), True
    done = [s for s in archive.archived_seasons()
            if FIRST_SEASON <= s < season and season_complete(s)]
    fit_on = done or [season]
    return fit_curve(fit_on, reception_points(season)), False


def freeze(season: int, fit_seasons: list[int] | None = None) -> bool:
    """Write a completed season's curve once. Never overwrites. True if written."""
    if not supported(season) or not season_complete(season):
        return False
    frozen = frozen_curves()
    if not frozen.empty and season in set(frozen["season"]):
        return False
    fit_seasons = fit_seasons or list(range(FIRST_SEASON, season + 1))
    row = {"season": season, **fit_curve(fit_seasons, reception_points(season))}
    out = pd.concat([frozen, pd.DataFrame([row])], ignore_index=True).sort_values("season")
    out.to_csv(CURVES, index=False)
    return True


def injury_games(season: int) -> pd.Series:
    """Regular-season games each player missed injured, by player_id."""
    if not archive.has("game_status", season):
        return pd.Series(dtype=float)
    gs = archive.get("game_status", season)
    gs = gs[gs["week"] <= regular_weeks(season)]
    missed = gs["status"].isin(["Out", "IR"]).astype(float)
    missed += gs["injury_weight"].where(gs["status"] == "Mid-Game Injury", 0).fillna(0)
    return missed.groupby(gs["player_id"]).sum()


def draft_value(season: int, draft: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict, bool]:
    """
    Each QB/RB/WR/TE pick's value per game against its season's curve.

    Returns (picks, curve, frozen). Adds expected, value, injury_games,
    dropped - whether the drafting team cut him at any point that season -
    and the hindsight columns: hind_rank, hind_round and picks_gained.
    """
    curve, frozen = curve_for(season)
    picks = pick_vor(season, draft=draft)
    picks["expected"] = curve["intercept"] + curve["slope"] * np.log(picks["overall_pick"])
    picks["value"] = picks["vor"] - picks["expected"]
    picks["hind_rank"] = picks["vor"].rank(ascending=False, method="min").astype(int)
    picks["hind_round"] = (picks["hind_rank"] - 1) // 10 + 1
    picks["picks_gained"] = picks["overall_pick"] - picks["hind_rank"]
    picks["injury_games"] = picks["player_id"].map(injury_games(season)).fillna(0.0)

    tx = archive.get("transactions", season) if archive.has("transactions", season) else pd.DataFrame()
    if tx.empty:
        picks["dropped"] = False
    else:
        drops = tx[tx["action"] == "drop"]
        cut = set(zip(drops["player_name"], drops["from_team_id"]))
        picks["dropped"] = [(p, t) in cut for p, t in zip(picks["player_name"], picks["team_id"])]
    return picks, curve, frozen


def team_draft_value(season: int) -> pd.DataFrame:
    """
    One row per team: summed value, share of the draft's VOR, hits, the
    early/late split at EARLY_ROUNDS, and its best-value and best-hindsight
    picks. Ranking is left to the caller.

    Best hindsight is taken from the hits the drafter kept all season. A
    player he cut found his value somewhere else, so it is not the draft's
    best find for that team; hind_rank itself still ranks every pick.
    """
    picks, _, _ = draft_value(season)
    by_team = picks.groupby("team_id")
    early = picks["round"] <= EARLY_ROUNDS
    out = pd.DataFrame({
        "value": by_team["value"].sum(),
        "share": by_team["vor"].sum() / picks["vor"].sum() * 100,
        "hits": (picks["vor"] > 0).groupby(picks["team_id"]).sum(),
        "scored": by_team.size(),
        "early_value": picks["value"].where(early, 0).groupby(picks["team_id"]).sum(),
        "late_value": picks["value"].where(~early, 0).groupby(picks["team_id"]).sum(),
    })
    best = picks.loc[by_team["value"].idxmax(), ["team_id", "player_id", "player_name",
                                                  "round", "value", "dropped"]]
    out = out.join(best.set_index("team_id").add_prefix("best_value_"))
    hits = picks[(picks["vor"] > 0) & ~picks["dropped"]]
    hind = hits.loc[hits.groupby("team_id")["picks_gained"].idxmax(),
                    ["team_id", "player_id", "player_name", "round", "hind_round",
                     "picks_gained", "dropped"]]
    out = out.join(hind.set_index("team_id").add_prefix("best_hind_"))
    out["manager"] = out.index.map(archive.manager_map(season))
    return out.reset_index()
