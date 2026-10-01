"""
The Champmissioner's picks, resolved against the archive.

data/vlog_notes.py reads what he wrote; this decides what it refers to and
builds the three archive datasets the Champmissioner's Dashboard reads:

    vlog_matchups.csv        one row per contest he picked: the two teams, the
                             weeks it ran, and the team he took.
    vlog_romarkables.csv     one row per Romarkable pick: week, position, the
                             player and the fantasy team he was on.
    vlog_power_rankings.csv  one row per team per ranking. week is the week
                             the ranking looks ahead to, so week 1 is the
                             preseason ranking.

Which week
----------
Every section is placed by the games it names, not only by the episode's
title: the five pairings in a regular-season recap or preview match one week
of the schedule. That has agreed with the titles for every episode so far, and
it is there for the one that is copied forward and not renamed. A ranking
belongs to the week its episode previews.

graded holds his own verdict where his recap gave one, and is blank where it
did not. analysis/vlog.py uses it when present and works the result out from
the scores otherwise. His verdict wins because it is his record: a handful of
his calls disagree with the archive by a hundredth of a point, which is the
projection moving between when he looked and when the game kicked off.

Contests, not weeks
-------------------
A playoff round runs two weeks and the sacko four, and he picks the contest,
not each week of it - the same pick repeats in each week's preview, and the
recap grades it once it is over. So a pick is keyed to the contest: the run of
consecutive playoff weeks in which the pair met, either in ESPN's schedule or
in his notes. His notes are needed because ESPN's consolation games are not
the league's: ESPN paired 2021's fifth seed with the sixth, the league played
fifth against eighth, and that is the game he picked. A contest is decided on
the two teams' scores summed over its weeks, whoever ESPN had them facing.

Which pick counts
-----------------
The latest word on a contest wins, and a graded recap outranks any preview.
He sometimes changed a pick off air after recording, and the recap reflects
the pick he actually stood by. Episodes are read in order, so the second
preview of a two-week round replaces the first.

Rows with source "video" were read from the episode itself, for weeks whose
notes were a pre-recording template. The build never produces them; the
archive's merge keeps them.

Names
-----
He writes players the way the league talks about them: "Dak", "Bowersaur",
"JSN", "Bucky". A pick is matched against the players on the two teams in
that matchup that week, at an eligible position, which leaves almost nothing
to be ambiguous about. Where two still fit ("Brown"), the one whose result
agrees with his grade is taken, then the one ESPN projected higher - he picks
starters. NICKNAMES covers the names no rule could find.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from config import season_config
from data import vlog_notes
from data.vlog_notes import Episode

# Names no rule can reach, keyed on what he wrote after norm().
NICKNAMES = {
    "bowersaur": "brock bowers",
    "bowersaurus": "brock bowers",
    "jsn": "jaxon smith njigba",
    "cmc": "christian mccaffrey",
    "tet": "tetairoa mcmillan",
    "arsb": "amon ra st brown",
    "amon ra": "amon ra st brown",
    "zeke": "ezekiel elliott",
    "hollywood": "marquise brown",
    "hunghoe": "younghoe koo",          # a typo he carried for two weeks
    "scary terry": "terry mclaurin",
    "freirmuth": "pat freiermuth",
    "muth": "pat freiermuth",
    "skateboo": "cam skattebo",
    "bill": "jacory croskey merritt",
    "herbert backfill": "khalil herbert",
}

FLEX = {"RB", "WR", "TE"}

MATCHUP_COLS = ["season", "week", "end_week", "team_id", "opp_id", "pick_id",
                "graded", "source"]
RANKING_COLS = ["season", "week", "rank", "team_id", "source"]
ROMARKABLE_COLS = ["season", "week", "position", "player_id", "player_name",
                   "team_id", "graded", "source"]


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    t = re.sub(r"['’.]", "", t.lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _score(written: str, player: str) -> int:
    """How well what he wrote fits a player's name. 0 is no match."""
    w, p = norm(written), norm(player)
    w = NICKNAMES.get(w, w)
    if not w or not p:
        return 0
    words = p.split()
    if w == p:
        return 5
    if w == words[-1]:
        return 4
    if w == words[0]:
        return 3
    ws = w.split()
    if len(ws) > 1 and all(x in words for x in ws):
        return 3
    if len(w) >= 4 and (words[0].startswith(w) or words[-1].startswith(w)
                        or "".join(words).startswith(w)):
        return 2
    return 0


def _eligible(position: str, pick: str) -> bool:
    return position in FLEX if pick == "FLEX" else position == pick


# ── Contests ─────────────────────────────────────────────────────────────────

def playoff_rounds(season: int) -> list[list[int]]:
    """The league's playoff rounds as lists of weeks: two of two weeks, or
    2022's one-week first round and two-week final."""
    pw = season_config(season)["playoff_weeks"]
    return [pw[:1], pw[1:]] if len(pw) == 3 else [pw[:2], pw[2:]]


def contests(matchups: pd.DataFrame, season: int,
             mentioned: set[tuple[int, int, int]] = frozenset()) -> pd.DataFrame:
    """
    One row per contest: season, week (its first), end_week, team_id, opp_id,
    with team_id < opp_id.

    Regular-season contests are ESPN's schedule, one week each. Playoff
    contests come from his notes alone - mentioned is {(week, team_a,
    team_b)} - because ESPN's consolation pairings are not the league's. A
    pair's run of mentioned weeks is widened to whole rounds, so a round he
    previewed only once is still judged over both its weeks, and a pair
    mentioned across both rounds is the sacko, judged over all of them.
    """
    m = matchups[matchups["season"] == season]
    reg_end = season_config(season)["reg_season_end"]
    rows = [(season, int(w), int(w), int(a), int(b)) for w, a, b
            in m.loc[(m["team_id"] < m["opp_id"]) & (m["week"] <= reg_end),
                     ["week", "team_id", "opp_id"]].itertuples(index=False)]

    rounds = playoff_rounds(season)
    by_pair: dict[tuple, set[int]] = {}
    for w, a, b in mentioned:
        if w > reg_end:
            by_pair.setdefault((min(a, b), max(a, b)), set()).add(w)
    for (a, b), weeks in by_pair.items():
        touched = [r for r in rounds if weeks & set(r)]
        # Rounds run back to back, so the touched rounds are one contest
        # only when every round between them was touched too.
        runs, run = [], []
        for r in rounds:
            if r in touched:
                run.extend(r)
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        rows += [(season, run[0], run[-1], a, b) for run in runs]
    return pd.DataFrame(rows, columns=["season", "week", "end_week",
                                       "team_id", "opp_id"])


def _contest_for(cons: pd.DataFrame, week: int, t1: int, t2: int):
    a, b = min(t1, t2), max(t1, t2)
    hit = cons[(cons["team_id"] == a) & (cons["opp_id"] == b)
               & (cons["week"] <= week) & (cons["end_week"] >= week)]
    return None if hit.empty else hit.iloc[0]


# ── Build ────────────────────────────────────────────────────────────────────

class Report:
    """Things a person should look at. Printed by the build, never shown in the app."""

    def __init__(self):
        self.lines: list[str] = []

    def add(self, msg: str):
        if msg not in self.lines:
            self.lines.append(msg)

    def print(self, label: str):
        for line in self.lines:
            print(f"  {label:11} {line}")


def _pairs_by_week(matchups: pd.DataFrame, schedule: pd.DataFrame | None,
                   season: int) -> dict[int, set[frozenset]]:
    """Every week's games as unordered team pairs: played, then still to come."""
    frames = [matchups[matchups["season"] == season]]
    if schedule is not None and not schedule.empty:
        frames.append(schedule[schedule["season"] == season])
    out: dict[int, set[frozenset]] = {}
    for f in frames:
        for w, a, b in f[["week", "team_id", "opp_id"]].itertuples(index=False):
            out.setdefault(int(w), set()).add(frozenset((int(a), int(b))))
    return out


def place(ep: Episode, by_week: dict[int, set[frozenset]],
          team_of: dict[str, int], report: Report):
    """
    Set each section's week from the games it talks about.

    The title says which week an episode recaps and previews, and it is
    nearly always right, but notes are copied forward and edited in a hurry.
    The games settle it: the five pairings he lists match exactly one week of
    the schedule, or a few weeks when pairs repeat, in which case the one
    nearest the title wins. Only the regular season is placed this way:
    ESPN's playoff pairings are not the league's (2022's week-16 schedule
    matches none of the real final), so playoff sections keep the title's week.
    """
    reg_end = season_config(ep.season)["reg_season_end"]
    by_week = {w: ps for w, ps in by_week.items() if w <= reg_end}
    for section in ("recap", "preview"):
        mus = [m for m in ep.matchups if m.section == section]
        pairs = {frozenset((team_of.get(m.first), team_of.get(m.second)))
                 for m in mus}
        pairs = {p for p in pairs if None not in p}
        if len(pairs) < 3 or mus[0].week > reg_end:
            continue
        expected = mus[0].week
        overlap = {w: len(pairs & ps) for w, ps in by_week.items()}
        best = max(overlap.values(), default=0)
        if best < len(pairs) - 1:
            continue
        week = min((w for w, n in overlap.items() if n == best),
                   key=lambda w: (abs(w - expected), w))
        shift = week - expected
        if not shift:
            continue
        report.add(f"{ep.path.name}: its {section} is week {week} by the games "
                   f"listed, not week {expected} by its title - using {week}")
        for m in mus:
            m.week += shift
        for p in ep.players:
            if p.section == section:
                p.week += shift


def _ranking_week(ep: Episode) -> int:
    """The week a ranking looks ahead to: the episode's preview week."""
    pre = [m.week for m in ep.matchups if m.section == "preview"]
    if pre:
        return pre[0]
    rec = [m.week for m in ep.matchups if m.section == "recap"]
    return rec[0] + 1 if rec else ep.week


def build(season: int, matchups: pd.DataFrame, boxscores: pd.DataFrame,
          managers: dict[int, str], eps: list[Episode] | None = None,
          report: Report | None = None,
          schedule: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """{dataset name: rows} for one season, from its notes."""
    report = report if report is not None else Report()
    eps = vlog_notes.episodes(season) if eps is None else eps
    team_of = {v: k for k, v in managers.items()}
    played = set(matchups.loc[matchups["season"] == season, "week"])
    by_week = _pairs_by_week(matchups, schedule, season)
    for ep in eps:
        place(ep, by_week, team_of, report)
    box = boxscores[(boxscores["season"] == season)
                    & (boxscores["position"] != "D/ST")]

    mentioned = set()
    for ep in eps:
        for mu in ep.matchups:
            t1, t2 = team_of.get(mu.first), team_of.get(mu.second)
            if t1 is not None and t2 is not None:
                mentioned.add((mu.week, t1, t2))
    cons = contests(matchups, season, mentioned)

    picks: dict[tuple, dict] = {}       # (first week, team_id, opp_id) -> row
    players: dict[tuple, dict] = {}     # (week, position) -> row
    rankings: dict[int, list[str]] = {} # week it looks ahead to -> managers

    for ep in eps:
        if ep.rankings:
            rankings[_ranking_week(ep)] = ep.rankings

    for ep in eps:
        for mu in ep.matchups:
            if mu.week not in played:
                continue
            t1, t2 = team_of.get(mu.first), team_of.get(mu.second)
            if t1 is None or t2 is None:
                report.add(f"wk {mu.week}: no team for {mu.first} or {mu.second}: {mu.line}")
                continue
            c = _contest_for(cons, mu.week, t1, t2)
            if c is None:
                report.add(f"wk {mu.week}: {mu.first} and {mu.second} did not play: {mu.line}")
                continue
            key = (int(c["week"]), int(c["team_id"]), int(c["opp_id"]))
            if mu.section == "recap":
                if mu.grade == "na":
                    # He struck the pick from his record.
                    picks.pop(key, None)
                    continue
                if mu.grade not in ("hit", "miss"):
                    continue
                pick, graded, source = (t1 if mu.grade == "hit" else t2), mu.grade, _source(ep, "recap")
            else:
                if picks.get(key, {}).get("graded"):
                    continue
                pick, graded, source = t1, None, _source(ep, "preview")
            picks[key] = {"season": season, "week": key[0],
                          "end_week": int(c["end_week"]), "team_id": key[1],
                          "opp_id": key[2], "pick_id": pick,
                          "graded": graded, "source": source}

        for pl in ep.players:
            if pl.week not in played:
                continue
            key = (pl.week, pl.position)
            prior = players.get(key)
            if pl.section == "preview" and prior and prior["source"] != "preview":
                continue
            if pl.section == "recap" and pl.grade == "na":
                # Struck from his record - 2022 week 17's Josh Allen, whose
                # game was cancelled.
                players.pop(key, None)
                continue
            teams = None
            if pl.matchup is not None:
                teams = {team_of.get(pl.matchup.first), team_of.get(pl.matchup.second)}
            grade = pl.grade if pl.section == "recap" and pl.grade in ("hit", "miss") else None
            found = _resolve(box, pl.week, pl.position, pl.name, teams, grade, report)
            if isinstance(found, str):
                report.add(f"wk {pl.week} {pl.position} '{pl.name}': {found}  [{ep.path.name}]")
                continue
            players[key] = {"season": season, "week": pl.week,
                            "position": pl.position,
                            "player_id": int(found["player_id"]),
                            "player_name": found["player_name"],
                            "team_id": int(found["team_id"]),
                            "graded": grade,
                            "source": _source(ep, pl.section)}

    ranks = [{"season": season, "week": w, "rank": i + 1,
              "team_id": team_of[m], "source": "notes"}
             for w, order in sorted(rankings.items())
             for i, m in enumerate(order) if m in team_of]
    return {
        "vlog_matchups": pd.DataFrame(list(picks.values()), columns=MATCHUP_COLS),
        "vlog_romarkables": pd.DataFrame(list(players.values()), columns=ROMARKABLE_COLS),
        "vlog_power_rankings": pd.DataFrame(ranks, columns=RANKING_COLS),
    }


def _source(ep: Episode, section: str) -> str:
    """recap or preview from his notes; video when read from the episode."""
    return "video" if ep.transcribed else section


def _resolve(box: pd.DataFrame, week: int, position: str, written: str,
             teams: set | None, grade: str | None, report: Report):
    """The boxscore row he meant, or a string saying why there is none."""
    if "/" in written:
        # "Stroud/Daniels": whichever of the two the manager started.
        found = [_resolve(box, week, position, w, teams, grade, report)
                 for w in written.split("/")]
        found = [f for f in found if not isinstance(f, str)]
        started = [f for f in found if bool(f["is_active_slot"])]
        if len(started) == 1:
            return started[0]
        if not found:
            return "neither name matches"
        return f"cannot tell which of {written} he meant ({len(started)} started)"
    wk = box[box["week"] == week]
    wk = wk[wk["position"].map(lambda p: _eligible(p, position))]
    pools = []
    if teams and None not in teams:
        pools.append(wk[wk["team_id"].isin(teams)])
    pools.append(wk)
    for pool in pools:
        scores = pool["player_name"].map(lambda n: _score(written, n))
        best = scores.max() if len(scores) else 0
        if not best:
            continue
        hits = pool[scores == best].drop_duplicates("player_id")
        if len(hits) == 1:
            return hits.iloc[0]
        narrowed = hits
        if grade:
            agree = hits[(hits["points"] > hits["projected"]) == (grade == "hit")]
            if len(agree):
                narrowed = agree
        chosen = narrowed.sort_values("projected", ascending=False).iloc[0]
        others = ", ".join(n for n in hits["player_name"] if n != chosen["player_name"])
        report.add(f"wk {week} {position} '{written}': took {chosen['player_name']} "
                   f"over {others}")
        return chosen
    return "no rostered player matches"
