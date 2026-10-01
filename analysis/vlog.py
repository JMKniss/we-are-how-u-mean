"""
The Champmissioner's record: his picks graded, and the weekly awards.

Picks come from data/archive/vlog_matchups.csv and vlog_romarkables.csv (see
data/vlog.py for how they are read from his notes). Nothing about a result is
stored there except his own verdict, where his recap gave one; the rest is
decided here from the scores, so a corrected score corrects his record.

A matchup pick is right when the team he took outscored the other over the
contest's weeks - one week in the regular season, a round or the whole sacko
in the playoffs. A contest still running is not graded. A Romarkable pick
hits when the player outscores his ESPN projection.

Awards
------
The top scorer and the bottom scorer of each regular-season week. He stops
handing them out when the playoffs start ("done with captains of the week",
"NO CLIMBER OF THE WEEK"), so playoff weeks have none. The bottom award is the
Fascist of the Week every year; the top one is renamed each season with the
theme, and TOP_TITLES holds those names. Checked against the 104 awards his
notes name, the scores agree with 102. One was a guess in a pre-recording
template ("Tim?"); the other is 2025's last episode naming the sacko loser
the Fascist of the final week, a season verdict rather than the low score.
"""
from __future__ import annotations

import pandas as pd

from config import season_config

# What he called the top scorer each season. Add the new name each September.
TOP_TITLES = {
    2021: "Captain of the Week",
    2022: "Bodybuilder of the Week",
    2023: "Climber of the Week",
    2024: "Eyehole Man",
    2025: "Dungeon Master",
    2026: "Trainer of the Week",
}
BOTTOM_TITLE = "Fascist of the Week"

# The names used where seasons are added together.
TOP_GENERIC = "Top Scorer"
BOTTOM_GENERIC = "Fascist"

POSITIONS = ["QB", "RB", "WR", "TE", "FLEX", "K"]


def top_title(season: int) -> str:
    return TOP_TITLES.get(season, TOP_GENERIC)


def _team_total(matchups: pd.DataFrame, season: int, team_id: int,
                weeks: range) -> float:
    m = matchups[(matchups["season"] == season) & (matchups["team_id"] == team_id)
                 & (matchups["week"].isin(weeks))]
    return float(m["score"].sum())


def grade_matchups(picks: pd.DataFrame, matchups: pd.DataFrame) -> pd.DataFrame:
    """picks with a `correct` column; contests still running are dropped."""
    if picks.empty:
        return picks.assign(correct=pd.Series(dtype=bool))
    rows = []
    for r in picks.itertuples(index=False):
        weeks = range(int(r.week), int(r.end_week) + 1)
        played = set(matchups.loc[matchups["season"] == r.season, "week"])
        if not set(weeks) <= played:
            continue
        if isinstance(r.graded, str) and r.graded in ("hit", "miss"):
            correct = r.graded == "hit"
        else:
            other = r.opp_id if r.pick_id == r.team_id else r.team_id
            mine = _team_total(matchups, r.season, r.pick_id, weeks)
            theirs = _team_total(matchups, r.season, other, weeks)
            correct = mine > theirs
        rows.append({**r._asdict(), "correct": correct})
    return pd.DataFrame(rows)


def grade_romarkables(picks: pd.DataFrame, boxscores: pd.DataFrame) -> pd.DataFrame:
    """picks with a `hit` column, plus the player's points and projection."""
    if picks.empty:
        return picks.assign(hit=pd.Series(dtype=bool))
    box = boxscores[["season", "week", "player_id", "points", "projected"]]
    box = box.drop_duplicates(["season", "week", "player_id"])
    out = picks.merge(box, on=["season", "week", "player_id"], how="left")
    computed = out["points"] > out["projected"]
    graded = out["graded"].where(out["graded"].isin(["hit", "miss"]))
    out["hit"] = graded.map({"hit": True, "miss": False}).fillna(computed).astype(bool)
    return out


def record(correct: pd.Series) -> tuple[int, int]:
    """(right, wrong) from a boolean series."""
    n = int(correct.sum())
    return n, int(len(correct) - n)


def by_position(graded: pd.DataFrame) -> pd.DataFrame:
    """Hits and misses per Romarkable position, in the order he picks them."""
    if graded.empty:
        return pd.DataFrame(columns=["position", "hits", "misses", "pct"])
    g = graded.groupby("position")["hit"].agg(hits="sum", n="count")
    g = g.reindex([p for p in POSITIONS if p in g.index])
    g["misses"] = g["n"] - g["hits"]
    g["pct"] = g["hits"] / g["n"]
    return g.reset_index()[["position", "hits", "misses", "pct"]]


def weekly_awards(matchups: pd.DataFrame, season: int) -> pd.DataFrame:
    """
    One row per regular-season week played: week, top_id, top_score,
    bottom_id, bottom_score. A tie puts every tied team in the award, so a
    week can hold more than one row.
    """
    reg_end = season_config(season)["reg_season_end"]
    m = matchups[(matchups["season"] == season) & (matchups["week"] <= reg_end)]
    rows = []
    for week, g in m.groupby("week"):
        hi, lo = g["score"].max(), g["score"].min()
        for tid in g.loc[g["score"] == hi, "team_id"]:
            rows.append({"season": season, "week": int(week), "award": "top",
                         "team_id": int(tid), "score": float(hi)})
        for tid in g.loc[g["score"] == lo, "team_id"]:
            rows.append({"season": season, "week": int(week), "award": "bottom",
                         "team_id": int(tid), "score": float(lo)})
    return pd.DataFrame(rows, columns=["season", "week", "award", "team_id", "score"])


def award_counts(awards: pd.DataFrame) -> pd.DataFrame:
    """manager, top, bottom: only managers who have won at least one."""
    if awards.empty:
        return pd.DataFrame(columns=["manager", "top", "bottom"])
    c = (awards.groupby(["manager", "award"]).size().unstack(fill_value=0)
         .reindex(columns=["top", "bottom"], fill_value=0))
    c = c[(c["top"] > 0) | (c["bottom"] > 0)]
    return (c.sort_values(["top", "bottom"], ascending=[False, True])
             .reset_index())


# ── Power rankings ───────────────────────────────────────────────────────────
#
# Each episode's ranking looks ahead to the week it previews, so week 1 is the
# preseason ranking and the last one - he stops when the playoffs start - is
# his final word on the regular season. Two things to hold them against: the
# playoff seeds, known once the regular season ends, and the final standings,
# known once the playoffs do. Accuracy is "places off": how far, on average,
# a manager finished from where he ranked them. 0 is perfect; ranking ten
# teams at random averages 3.3.

def ranking_grid(ranks: pd.DataFrame) -> pd.DataFrame:
    """team_id x week, holding each week's rank. A week with no ranking is absent."""
    if ranks.empty:
        return pd.DataFrame()
    return ranks.pivot_table(index="team_id", columns="week", values="rank")


def first_and_last(ranks: pd.DataFrame) -> tuple[dict, dict]:
    """({team_id: preseason rank}, {team_id: final rank})."""
    if ranks.empty:
        return {}, {}
    first, last = ranks["week"].min(), ranks["week"].max()
    pick = lambda w: dict(zip(ranks.loc[ranks["week"] == w, "team_id"],
                              ranks.loc[ranks["week"] == w, "rank"]))
    return pick(first), pick(last)


def places_off(ranked: dict, actual: dict) -> float | None:
    """Mean |ranked - actual| over the teams in both, or None."""
    both = [t for t in ranked if t in actual]
    if not both:
        return None
    return sum(abs(ranked[t] - actual[t]) for t in both) / len(both)
