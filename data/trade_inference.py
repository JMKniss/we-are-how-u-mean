"""
Rebuild a finished season's trades from its weekly rosters.

ESPN keeps waiver and free-agent history for past seasons but not trades: the
activity feed is deleted once a season ends, and by then mTransactions2 has
lost the player lists from almost every trade it accepted (2025: 12 of 13).
What survives is enough to work the trades back out:

- boxscores holds every team's full roster, bench and IR included, each week.
- The recorded adds and drops explain most changes from one week's rosters to
  the next. Replaying the moves stamped with week w+1 over week w's rosters
  predicts week w+1's, and for 2025 the prediction is exact everywhere except
  around trades.
- ESPN still keeps the acceptances: which team accepted, when, in which
  scoring period. Those say how many trades each week had and who was in them.

A player who changes roster with no recorded move went by trade. Legs between
two teams in both directions confirm each other; that reciprocity, plus the
count of acceptances that week, is the check. Everything built here is marked
source=inferred, and anything that needed a judgment is explained in `note`.

Built this way for 2018-2025. Checked against the per-team trade counts ESPN
keeps in standings.csv, every team matches in 2020-2024; 2025 differs only by
the hand-entered trade below, which ESPN counts as drops and adds; 2018 only
by a trade of draft picks, which moves no players; 2019 is one trade short
between teams 2 and 6 that neither the rosters nor ESPN's records show.
Drops match ESPN's counts too. Adds run a few high in some seasons with no
pattern found - ESPN's acquisition tally looks like a running count, not a
count of the log.

2016 and 2017 cannot be built. ESPN returns no transactions for them, and
their archived rosters hold starters only, so a player leaving a lineup is
indistinguishable from one leaving a roster.

Evidence read the other way, found in 2025 and confirmed across the rest:

- A drop made as part of a trade is never recorded on its own. It exists only
  inside the trade record, so it shows up here as a player who vanished from a
  roster. Renfrow, Shepard and Purdy - the three drops ESPN still lists inside
  surviving trade records - are each found this way.
- A player who vanishes from one team and is then claimed by another off the
  free-agent pool was dropped, not traded (Allgeier, 2025 week 3: cut by team
  8 to make room in a trade, claimed on waivers by team 5 two days later).
- A player dropped by a team he was never seen on arrived there by trade
  (Boutte, 2025 week 4).
- A player can be traded twice in one week, and only the start and end show
  in the rosters. Pittman went 10 -> 7 -> 2 in 2025 week 9: two 2-for-2 trades
  that read as one one-way move from 10 to 2 until it is split through 7.
- ESPN's acceptance records are not one per trade. In a league with a review
  period (2019, 2022, 2023) every team's vote is a TRADE_UPHOLD or TRADE_VETO
  record filed under the voter's team, and the trade executes days after it
  was accepted, often in the next scoring period. So records are grouped by
  the proposal they point at, only TRADE_ACCEPT names a party to the trade,
  and a proposal may match roster changes up to a week after its last
  record. A veto record is a vote, not a verdict: 2019's Hockenson-for-Diggs
  trade drew one and went through.
- 2018's records point at no proposal at all, so the same trade turns up as
  several unconnected records - and its acceptances are sometimes filed under
  a team that was not in the deal. Records are grouped by the players they
  list instead, and where players are listed they decide who the parties were.
- A trade before week 1 has no earlier roster to show up against, so the
  draft stands in as week 0 (2018 had two: Prater for Boswell, and Julio Jones
  for A.J. Green and Alfred Morris).
- A commissioner can push a trade through as drops and adds. 2025 week 3 had
  a 2-for-8 trade with a veto recorded against it, entered four minutes later as three drops and three
  pickups, one minute apart. Recorded as free-agent moves, but a trade in
  every sense that matters to judging it, so it is rebuilt as one.
"""
from collections import defaultdict

FREE_AGENT_POOL = 0

# A drop by one team and a pickup of the same player by another within this
# long is a trade entered by hand. Waivers hold a dropped player for days, so
# no genuine claim can land this fast.
FORCED_WINDOW_MS = 10 * 60 * 1000


def _ms(t) -> int:
    return int(t.get("processDate") or t.get("proposedDate"))


def infer_trades(season: int, box, moves: list, raw: dict, week0: dict | None = None):
    """
    season: the year, for ids and notes.
    box:    the season's boxscores (week, team_id, player_id).
    moves:  recorded adds and drops, dicts with ms, week, action, from_team_id,
            to_team_id, player_id, transaction_id.
    raw:    every mTransactions2 record for the season, keyed by id.
    week0:  {player_id: team_id} as drafted, keepers included - the rosters
            before week 1. Optional; without it preseason trades go unseen.

    Returns (legs, drops, remove, notes):
      legs   - trade rows: dicts with week, ms, transaction_id, action
               ("trade" or "drop"), from_team_id, to_team_id, player_id,
               source, note
      drops  - drops found outside any trade, same shape
      remove - (transaction_id, player_id) of recorded moves that were really
               part of a trade entered by hand
      notes  - report lines for the build output
    """
    notes, legs, loose = [], [], []

    rosters = {int(w): dict(zip(g["player_id"].astype(int), g["team_id"].astype(int)))
               for w, g in box.groupby("week")}
    if week0:
        rosters[0] = dict(week0)
    teams_in = {w: set(r.values()) for w, r in rosters.items()}

    # One entry per trade proposal ESPN still has any record of.
    proposals = {}
    for t in raw.values():
        if t["type"] not in ("TRADE_ACCEPT", "TRADE_UPHOLD", "TRADE_VETO"):
            continue
        # A trade of draft picks moves no players. Left in, it has no player
        # list to rule it out and fits any trade at all - 2018's pick swap
        # between 2 and 3 claimed the Julio Jones trade that way.
        if t.get("items") and all(i["type"] == "DRAFT_TRADE" for i in t["items"]):
            continue
        listed = frozenset((i["fromTeamId"], i["toTeamId"], i["playerId"])
                           for i in t.get("items", []) if i["type"] == "TRADE")
        rel = t.get("relatedTransactionId") or listed or t["id"]
        p = proposals.setdefault(rel, {"id": rel if isinstance(rel, str) else t["id"],
                                       "parties": set(), "items": set(),
                                       "weeks": set(), "ms": [], "vetoes": 0,
                                       "executed": False, "used": False})
        if not isinstance(rel, str) or rel == t["id"]:
            p["id"] = min(p["id"], t["id"])     # stable: the same record every run
        p["weeks"].add(int(t["scoringPeriodId"]))
        p["ms"].append(_ms(t))
        p["executed"] |= t.get("status") == "EXECUTED"
        # Only an acceptance names a party. teamId on an uphold or veto is the
        # team that voted, and 2018 files some acceptances under -2**31.
        if t["type"] == "TRADE_ACCEPT" and (t.get("teamId") or 0) > 0:
            p["parties"].add(int(t["teamId"]))
        p["vetoes"] += t["type"] == "TRADE_VETO"
        for rec in (t, raw.get(rel) or {}):
            p["items"] |= {(i["type"], i["fromTeamId"], i["toTeamId"], i["playerId"])
                           for i in rec.get("items", []) if i["type"] in ("TRADE", "DROP")}

    def item_teams(p):
        return {x for i in p["items"] if i[0] == "TRADE" for x in i[1:3]}

    def fits(p, teams, week):
        if p["used"] or not (min(p["weeks"]) <= week <= max(p["weeks"]) + 1):
            return False
        if item_teams(p):
            return item_teams(p) == set(teams)
        return not p["parties"] or p["parties"] <= set(teams)

    # ── Trades entered by hand as drops and pickups ──────────────────────────
    ordered = sorted(moves, key=lambda m: m["ms"])
    remove, forced_by_week = set(), defaultdict(list)
    pairs = []
    for d in ordered:
        if d["action"] != "drop":
            continue
        for a in ordered:
            if (a["action"] == "add" and a["player_id"] == d["player_id"]
                    and a["to_team_id"] != d["from_team_id"]
                    and 0 <= a["ms"] - d["ms"] <= FORCED_WINDOW_MS):
                pairs.append((d, a))
                break
    clusters = []
    for d, a in pairs:
        team_pair = frozenset({d["from_team_id"], a["to_team_id"]})
        for c in clusters:
            if c["teams"] == team_pair and d["ms"] - c["last"] <= FORCED_WINDOW_MS:
                c["pairs"].append((d, a))
                c["last"] = max(c["last"], a["ms"])
                break
        else:
            clusters.append({"teams": team_pair, "pairs": [(d, a)], "last": a["ms"]})

    for c in clusters:
        d0, a0 = c["pairs"][0]
        week, start = int(a0["week"]), d0["ms"]
        directions = {(d["from_team_id"], a["to_team_id"]) for d, a in c["pairs"]}
        if len(directions) < 2:
            continue          # one-way: a fast re-claim, not a trade
        veto = next((p for p in proposals.values()
                     if p["vetoes"] and fits(p, c["teams"], week) and min(p["ms"]) <= start),
                    None)
        tid = (veto["id"] if veto
               else f"inferred-{season}-w{week}-forced-{'-'.join(map(str, sorted(c['teams'])))}")
        note = ("entered by hand as drops and pickups"
                + (" minutes after a veto was recorded against the same trade" if veto else ""))
        if veto:
            veto["used"] = True
        paired = set()
        for d, a in c["pairs"]:
            paired |= {(d["transaction_id"], d["player_id"]), (a["transaction_id"], a["player_id"])}
            legs.append(dict(week=week, ms=d["ms"], transaction_id=tid, action="trade",
                             from_team_id=d["from_team_id"], to_team_id=a["to_team_id"],
                             player_id=d["player_id"], source="inferred", note=note))
        # Any other drop by either team inside the burst made room for the deal.
        for m in ordered:
            key = (m["transaction_id"], m["player_id"])
            if (m["action"] == "drop" and key not in paired
                    and m["from_team_id"] in c["teams"]
                    and start - FORCED_WINDOW_MS <= m["ms"] <= c["last"] + FORCED_WINDOW_MS):
                paired.add(key)
                legs.append(dict(week=week, ms=m["ms"], transaction_id=tid, action="drop",
                                 from_team_id=m["from_team_id"], to_team_id=FREE_AGENT_POOL,
                                 player_id=m["player_id"], source="inferred", note=note))
        remove |= paired
        forced_by_week[week].append(tid)
        notes.append(f"week {week}: trade {sorted(c['teams'])} {note}")

    forced_legs = list(legs)

    # ── Replay each week's recorded moves and compare ────────────────────────
    by_week = defaultdict(list)
    for m in ordered:
        if (m["transaction_id"], m["player_id"]) not in remove:
            by_week[max(int(m["week"]), 1)].append(m)
    for l in forced_legs:
        by_week[l["week"]].append({**l, "forced": True})
    for w in by_week:
        by_week[w].sort(key=lambda m: m["ms"])

    weeks = sorted(rosters)
    # Keeper years have moves in August, before the draft. Replayed over the
    # drafted rosters they undo picks: 2019's team 3 dropped Roethlisberger
    # on August 14 and team 1 drafted him weeks later.
    drafted_at = max((_ms(t) for t in raw.values() if t["type"] == "DRAFT"), default=0)
    unexplained = defaultdict(list)      # week -> (from, to, player_id, why)
    lost = defaultdict(list)             # week -> (team, player_id, why, ms)
    for prev, week in zip(weeks, weeks[1:]):
        pred = dict(rosters[prev])
        for m in by_week.get(week, []):
            if prev == 0 and m["ms"] < drafted_at:
                continue
            pid = m["player_id"]
            if m.get("forced"):
                if m["action"] == "trade":
                    pred[pid] = m["to_team_id"]
                else:
                    pred.pop(pid, None)
                continue
            if m["action"] == "add":
                holder = pred.get(pid)
                if holder not in (None, m["to_team_id"]):
                    lost[week].append((holder, pid, "claimed by another team", m["ms"]))
                pred[pid] = m["to_team_id"]
            else:
                holder = pred.get(pid)
                if holder is None:
                    notes.append(f"week {week}: player {pid} dropped by team "
                                 f"{m['from_team_id']} but never seen on a roster")
                elif holder != m["from_team_id"]:
                    unexplained[week].append((holder, m["from_team_id"], pid,
                                              "dropped by a team he was not on"))
                pred.pop(pid, None)

        actual = dict(rosters[week])
        # A team with no box score this week (a playoff bye) keeps its roster.
        for pid, team in pred.items():
            if team not in teams_in[week] and pid not in actual:
                actual[pid] = team
        for pid in set(pred) | set(actual):
            was, now = pred.get(pid), actual.get(pid)
            if was == now:
                continue
            if was and now:
                unexplained[week].append((was, now, pid, "changed roster"))
            elif was:
                lost[week].append((was, pid, "left the roster", None))
            else:
                notes.append(f"week {week}: player {pid} appeared on team {now} "
                             f"with no recorded add")

    # ── Group each week's legs into trades ───────────────────────────────────
    for week in sorted(set(unexplained) | set(lost)):
        by_pair = defaultdict(list)
        for was, now, pid, why in unexplained.get(week, []):
            by_pair[frozenset({was, now})].append([was, now, pid, why])

        def two_way(pair):
            return len({l[0] for l in by_pair[pair]}) == 2

        def open_proposals():
            return [p for p in proposals.values()
                    if not p["used"] and min(p["weeks"]) <= week <= max(p["weeks"]) + 1]

        # More team pairs than proposals means a player was traded twice and
        # only his first and last teams show: split A -> C through the one
        # team B that dealt with both. B's own deals need not be two-way
        # before the split - Barkley (2023, 3 -> 2 -> 8) was the only thing 3
        # sent to 2.
        #
        # Often more than one split fits the graph. 2023 week 10 could be
        # Barkley 3 -> 2 -> 8 or Hubbard and Herbert 2 -> 8 -> 3, and 2024
        # week 11 Robinson 2 -> 7 -> 4 or Reed and Allen 7 -> 4 -> 2. Take the
        # split that agrees with the most players ESPN's trade records still
        # name, then the one that moves the fewest players: a double trade is
        # the unusual event, so assume as little of it as the rosters allow.
        recorded_legs = {i[1:] for p in open_proposals() for i in p["items"] if i[0] == "TRADE"}
        while len(by_pair) > len(open_proposals()):
            options = []
            for pair in [p for p in by_pair if not two_way(p)]:
                a, c = by_pair[pair][0][0], by_pair[pair][0][1]
                for b in {t for p in by_pair for t in p} - {a, c}:
                    if frozenset({a, b}) in by_pair and frozenset({b, c}) in by_pair:
                        pids = [l[2] for l in by_pair[pair]]
                        agree = sum(((a, b, pid) in recorded_legs) + ((b, c, pid) in recorded_legs)
                                    - ((a, c, pid) in recorded_legs) for pid in pids)
                        options.append((-agree, len(pids), pair, a, b, c))
            if not options:
                break
            _, _, pair, a, b, c = min(options, key=lambda o: o[:2])
            for was, now, pid, why in by_pair.pop(pair):
                by_pair[frozenset({a, b})].append([a, b, pid, f"traded {a}->{b}->{c}"])
                by_pair[frozenset({b, c})].append([b, c, pid, f"traded {a}->{b}->{c}"])
                notes.append(f"week {week}: player {pid} traded twice, {a} -> {b} -> {c}")

        trades = [{"teams": pair, "legs": by_pair[pair]} for pair in by_pair]

        # Pair trades with proposals. The trade with the fewest proposals that
        # fit settles first; ties go to the proposal whose recorded players
        # match, then to the earliest.
        def rank(p, tr):
            mine = {("TRADE", l[0], l[1], l[2]) for l in tr["legs"]}
            recorded = {i for i in p["items"] if i[0] == "TRADE"}
            fit = 0 if recorded == mine else 1 if not recorded else 2
            return (fit, min(p["ms"]))

        pending = list(trades)
        while pending:
            options = {id(tr): sorted((p for p in proposals.values()
                                       if fits(p, tr["teams"], week)),
                                      key=lambda p: rank(p, tr)) for tr in pending}
            tr = min(pending, key=lambda tr: len(options[id(tr)]) or 99)
            if options[id(tr)]:
                tr["proposal"] = options[id(tr)][0]
                tr["proposal"]["used"] = True
            pending.remove(tr)

        for tr in trades:
            prop = tr.get("proposal")
            teams = sorted(tr["teams"])
            tid = prop["id"] if prop else f"inferred-{season}-w{week}-{'-'.join(map(str, teams))}"
            # A trade under review executes after its last vote.
            ms = max(prop["ms"]) if prop else None
            note_bits = []
            if not prop:
                note_bits.append("no ESPN trade record matched")
            if len({l[0] for l in tr["legs"]}) < 2:
                note_bits.append("one-way")
            if any(l[3].startswith("traded ") for l in tr["legs"]):
                note_bits.append("includes a player traded twice this week")
            items = prop["items"] if prop else set()
            # Some records keep only the drop, not the players traded.
            recorded = {i for i in items if i[0] == "TRADE"}
            if recorded:
                mine = {("TRADE", l[0], l[1], l[2]) for l in tr["legs"]}
                if recorded != mine:
                    note_bits.append("differs from ESPN's trade record")
            tr["tid"], tr["ms"] = tid, ms
            tr["recorded_drops"] = {i[3] for i in items if i[0] == "DROP"}
            for was, now, pid, why in tr["legs"]:
                legs.append(dict(week=week, ms=ms, transaction_id=tid, action="trade",
                                 from_team_id=was, to_team_id=now, player_id=pid,
                                 source="espn" if recorded and not note_bits else "inferred",
                                 note="; ".join(note_bits)))
            notes.append(f"week {week}: trade {teams} "
                         + ("matches an ESPN trade record" if not note_bits
                            else "- " + "; ".join(note_bits)))

        # ── Drops that made room ────────────────────────────────────────────
        for team, pid, why, claimed_ms in lost.get(week, []):
            mine = [tr for tr in trades if team in tr["teams"]]
            named = [tr for tr in mine if pid in tr.get("recorded_drops", set())]
            if not named and len(mine) > 1:
                named = [tr for tr in mine
                         if sum(l[1] == team for l in tr["legs"])
                         > sum(l[0] == team for l in tr["legs"])]
            tr = named[0] if len(named) == 1 else (mine[0] if len(mine) == 1 else None)
            if tr:
                legs.append(dict(week=week, ms=tr["ms"], transaction_id=tr["tid"],
                                 action="drop", from_team_id=team,
                                 to_team_id=FREE_AGENT_POOL, player_id=pid,
                                 source="espn" if pid in tr.get("recorded_drops", set()) else "inferred",
                                 note="" if pid in tr.get("recorded_drops", set())
                                 else "drop not recorded by ESPN; made room in the trade"))
            else:
                loose.append(dict(week=week, ms=claimed_ms, action="drop",
                                  transaction_id=f"inferred-{season}-w{week}-drop-{team}-{pid}",
                                  from_team_id=team, to_team_id=FREE_AGENT_POOL,
                                  player_id=pid, source="inferred",
                                  note=f"drop not recorded by ESPN; player {why}"))
                notes.append(f"week {week}: player {pid} {why} team {team} "
                             f"with no recorded drop and no trade to explain it")

    for p in proposals.values():
        if p["executed"] and not p["used"] and item_teams(p):
            notes.append(f"weeks {sorted(p['weeks'])}: ESPN executed a trade between "
                         f"{sorted(item_teams(p))} that the rosters do not show")

    return legs, loose, remove, notes
