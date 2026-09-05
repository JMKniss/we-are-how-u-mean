"""
One-line notes about the matchups being played this week.

Every note is the same sentence:

    **A vs B** is historically the <adjective> matchup <scope>, <detail>.

The adjectives are a fixed set, each backed by a rule over data the app
already computes. A rule either fires with a number behind it or stays quiet;
nothing is written that cannot be pointed at in the archive.

Scope is the honest part. A pair can be the most extreme in league history, or
merely the most extreme of the games being played this week, and those are
different claims - so the sentence says which.

Rules are ranked by how far the pair sits from the league's middle, in
standard deviations, and the top few are shown. At least one always is: if
nothing stands out, the tightest of this week's games is still a true thing to
say about them.
"""
from dataclasses import dataclass

import pandas as pd

# A pair needs some history before "historically" means anything.
MIN_GAMES = 4
# Below this many standard deviations from the middle, a claim is not worth
# making on its own - it only appears if nothing better exists.
INTERESTING_SIGMA = 0.8


@dataclass
class Note:
    text: str
    sigma: float          # how far from the league's middle, for ranking
    rule: str


def pair_key(a: str, b: str) -> tuple:
    """Unordered key, so A-vs-B and B-vs-A are one matchup."""
    return tuple(sorted((a, b)))


def pair_history(all_matchups: pd.DataFrame) -> pd.DataFrame:
    """
    One row per unordered pair of managers, over every regular season game.

    Needs manager and opp_manager columns. Each game appears twice in the
    source, once from each side, so wins are counted from one nominated side
    and the totals are halved where that would otherwise double them.
    """
    df = all_matchups.dropna(subset=["manager", "opp_manager"]).copy()
    df = df[df["manager"] != df["opp_manager"]]
    if df.empty:
        return pd.DataFrame()

    df["_a"] = [min(m, o) for m, o in zip(df["manager"], df["opp_manager"])]
    df["_b"] = [max(m, o) for m, o in zip(df["manager"], df["opp_manager"])]
    # Keep only the row seen from _a's side, so each game is counted once.
    side = df[df["manager"] == df["_a"]].copy()
    side["_margin"] = (side["score"] - side["opp_score"]).abs()
    side["_combined"] = side["score"] + side["opp_score"]

    rows = []
    for (a, b), g in side.groupby(["_a", "_b"]):
        g = g.sort_values(["season", "week"])
        a_wins = int((g["score"] > g["opp_score"]).sum())
        b_wins = int((g["score"] < g["opp_score"]).sum())
        streak_holder, streak = _current_streak(g, a, b)
        rows.append({
            "a": a, "b": b,
            "games": len(g),
            "a_wins": a_wins, "b_wins": b_wins,
            "avg_margin": round(float(g["_margin"].mean()), 2),
            "avg_combined": round(float(g["_combined"].mean()), 2),
            "imbalance": abs(a_wins - b_wins) / len(g),
            "streak_holder": streak_holder,
            "streak": streak,
        })
    return pd.DataFrame(rows)


def _current_streak(g: pd.DataFrame, a: str, b: str) -> tuple:
    """Who has won the most recent consecutive meetings, and how many."""
    winners = ["" if s == o else (a if s > o else b)
               for s, o in zip(g["score"], g["opp_score"])]
    winners = [w for w in winners if w]
    if not winners:
        return "", 0
    last = winners[-1]
    n = 0
    for w in reversed(winners):
        if w != last:
            break
        n += 1
    return last, n


def _sigma(value: float, population: pd.Series) -> float:
    sd = float(population.std())
    if not sd or pd.isna(sd):
        return 0.0
    return abs(value - float(population.mean())) / sd


def _fmt(a: str, b: str, adjective: str, scope: str, detail: str,
         historic: bool = True) -> str:
    """
    Every note is this one sentence, so they read as a set rather than as
    separate ideas. "historically" is dropped for claims about right now - a
    current streak is not a historic fact and saying so would be wrong.
    """
    lead = "is historically the" if historic else "is the"
    return f"**{a} vs {b}** {lead} {adjective} matchup {scope}, {detail}."


# Each rule: (name, adjective, column, pick the largest?, how to describe it)
_RULES = [
    ("tightest",   "tightest",       "avg_margin",   False,
     lambda r: f"decided by {r['avg_margin']:.1f} points on average"),
    ("competitive", "most competitive", "imbalance",  False,
     lambda r: f"split {max(r['a_wins'], r['b_wins'])}-{min(r['a_wins'], r['b_wins'])} "
               f"over {r['games']} meetings"),
    ("onesided",   "most one-sided",  "imbalance",   True,
     lambda r: f"{max(r['a_wins'], r['b_wins'])}-{min(r['a_wins'], r['b_wins'])} in favor of "
               f"{r['a'] if r['a_wins'] >= r['b_wins'] else r['b']}"),
    ("highest",    "highest scoring", "avg_combined", True,
     lambda r: f"{r['avg_combined']:.0f} combined points per meeting"),
    ("lowest",     "lowest scoring",  "avg_combined", False,
     lambda r: f"{r['avg_combined']:.0f} combined points per meeting"),
]


def notes_for_matchups(week_pairs, history: pd.DataFrame, limit: int = 3) -> list:
    """
    Ranked notes for the pairs playing this week.

    week_pairs is an iterable of (manager_a, manager_b). Returns at most
    `limit` Note objects, and never returns an empty list when any pair has
    enough history to say anything about.
    """
    if history.empty or not week_pairs:
        return []

    qualified = history[history["games"] >= MIN_GAMES]
    if qualified.empty:
        return []

    wanted = {pair_key(a, b) for a, b in week_pairs}
    playing = qualified[[pair_key(r.a, r.b) in wanted
                         for r in qualified.itertuples()]]
    if playing.empty:
        return []

    notes = []
    for rule, adjective, column, largest, describe in _RULES:
        best = (playing.nlargest(1, column) if largest
                else playing.nsmallest(1, column))
        row = best.iloc[0]
        # Is this pair the league's extreme too, or only this week's?
        league_best = (qualified.nlargest(1, column) if largest
                       else qualified.nsmallest(1, column)).iloc[0]
        is_league = (league_best["a"], league_best["b"]) == (row["a"], row["b"])
        scope = "in league history" if is_league else "among this week's matchups"
        notes.append(Note(
            text=_fmt(row["a"], row["b"], adjective, scope, describe(row)),
            sigma=_sigma(row[column], qualified[column]),
            rule=rule,
        ))

    # A streak is about now rather than all time, so it gets its own sentence.
    streaks = playing[playing["streak"] >= 3]
    if not streaks.empty:
        r = streaks.nlargest(1, "streak").iloc[0]
        other = r["b"] if r["streak_holder"] == r["a"] else r["a"]
        notes.append(Note(
            text=_fmt(r["streak_holder"], other, "most one-sided", "right now",
                      f"{r['streak_holder']} has won the last {int(r['streak'])}",
                      historic=False),
            sigma=float(r["streak"]) / 2.0,
            rule="streak",
        ))

    # One rule per pair, keeping its strongest claim, so the same two managers
    # are not called out three times in a row.
    notes.sort(key=lambda n: n.sigma, reverse=True)
    seen, kept = set(), []
    for n in notes:
        pair = n.text.split("**")[1]
        if pair in seen:
            continue
        seen.add(pair)
        kept.append(n)

    strong = [n for n in kept if n.sigma >= INTERESTING_SIGMA]
    # Never nothing: if no claim is strong, the tightest game is still true.
    return (strong or kept[:1])[:limit]
