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

Evidence read the other way, all of it confirmed on 2025:

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
- A commissioner can push a trade through as drops and adds. 2025 week 3 had
  a vetoed 2-for-8 trade entered four minutes later as three drops and three
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


def infer_trades(season: int, box, moves: list, raw: dict):
    """
    season: the year, for ids and notes.
    box:    the season's boxscores (week, team_id, player_id).
    moves:  recorded adds and drops, dicts with ms, week, action, from_team_id,
            to_team_id, player_id, transaction_id.
    raw:    every mTransactions2 record for the season, keyed by id.

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
    teams_in = {w: set(r.values()) for w, r in rosters.items()}

    accepts = defaultdict(list)          # week -> executed acceptances
    vetoed = {t.get("relatedTransactionId") for t in raw.values()
              if t["type"] == "TRADE_VETO"}
    for t in raw.values():
        if t["type"] in ("TRADE_ACCEPT", "TRADE_UPHOLD") and t.get("teamId"):
            accepts[int(t["scoringPeriodId"])].append(t)
    # A trade reaches ESPN as more than one acceptance record (2025's one
    # complete trade has an acceptance from each side), so count proposals.
    # Keep the record that carries the player list when one of them does.
    for w in accepts:
        kept = {}
        for t in sorted(accepts[w], key=lambda t: (not t.get("items"), _ms(t))):
            kept.setdefault(t.get("relatedTransactionId") or t["id"], t)
        accepts[w] = sorted(kept.values(), key=_ms)

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
        veto = next((t for t in accepts.get(week, [])
                     if t.get("relatedTransactionId") in vetoed
                     and t["teamId"] in c["teams"] and _ms(t) <= start), None)
        tid = (veto["relatedTransactionId"] if veto
               else f"inferred-{season}-w{week}-forced-{'-'.join(map(str, sorted(c['teams'])))}")
        note = ("entered by hand as drops and pickups"
                + (" minutes after ESPN vetoed the same trade" if veto else ""))
        if veto:
            accepts[week] = [t for t in accepts[week] if t is not veto]
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

    # A vetoed trade that was not pushed through never happened.
    for w in accepts:
        accepts[w] = [t for t in accepts[w] if t.get("relatedTransactionId") not in vetoed]

    forced_legs = list(legs)

    # ── Replay each week's recorded moves and compare ────────────────────────
    by_week = defaultdict(list)
    for m in ordered:
        if (m["transaction_id"], m["player_id"]) not in remove:
            by_week[int(m["week"])].append(m)
    for l in forced_legs:
        by_week[l["week"]].append({**l, "forced": True})
    for w in by_week:
        by_week[w].sort(key=lambda m: m["ms"])

    weeks = sorted(rosters)
    unexplained = defaultdict(list)      # week -> (from, to, player_id, why)
    lost = defaultdict(list)             # week -> (team, player_id, why, ms)
    for prev, week in zip(weeks, weeks[1:]):
        pred = dict(rosters[prev])
        for m in by_week.get(week, []):
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
    for week in sorted(set(unexplained) | set(accepts)):
        week_accepts = accepts.get(week, [])
        by_pair = defaultdict(list)
        for was, now, pid, why in unexplained.get(week, []):
            by_pair[frozenset({was, now})].append([was, now, pid, why])

        def two_way(pair):
            return len({l[0] for l in by_pair[pair]}) == 2

        # A one-way pair with too many pairs for the acceptances is a player
        # traded twice: split A -> C through the one team B that traded with
        # both.
        flips = {}
        if len(by_pair) > len(week_accepts):
            for pair in [p for p in by_pair if not two_way(p)]:
                a, c = by_pair[pair][0][0], by_pair[pair][0][1]
                middles = [b for b in {t for p in by_pair for t in p} - {a, c}
                           if frozenset({a, b}) in by_pair and two_way(frozenset({a, b}))
                           and frozenset({b, c}) in by_pair and two_way(frozenset({b, c}))]
                if len(middles) == 1:
                    b = middles[0]
                    for was, now, pid, why in by_pair.pop(pair):
                        by_pair[frozenset({a, b})].append([a, b, pid, f"traded {a}->{b}->{c}"])
                        by_pair[frozenset({b, c})].append([b, c, pid, f"traded {a}->{b}->{c}"])
                    flips[pid] = b
                    notes.append(f"week {week}: player {pid} traded twice, {a} -> {b} -> {c}")

        trades = [{"teams": pair, "legs": by_pair[pair]} for pair in by_pair]

        # Pair each trade with an acceptance: a team in exactly one trade
        # settles its own, then whatever is left.
        pending = list(week_accepts)
        progress = True
        while pending and progress:
            progress = False
            for t in list(pending):
                open_ = [tr for tr in trades if "accept" not in tr and t["teamId"] in tr["teams"]]
                if len(open_) == 1:
                    open_[0]["accept"] = t
                    pending.remove(t)
                    progress = True
        for t in list(pending):
            open_ = [tr for tr in trades if "accept" not in tr and t["teamId"] in tr["teams"]]
            if open_:
                open_[0]["accept"] = t
                pending.remove(t)
        for t in pending:
            notes.append(f"week {week}: ESPN accepted a trade by team {t['teamId']} "
                         f"that the rosters do not show")

        for tr in trades:
            acc = tr.get("accept")
            teams = sorted(tr["teams"])
            tid = (acc.get("relatedTransactionId") or acc["id"]) if acc else \
                f"inferred-{season}-w{week}-{'-'.join(map(str, teams))}"
            ms = _ms(acc) if acc else None
            flipped = [l for l in tr["legs"] if l[3].startswith("traded ")]
            note_bits = []
            if not acc:
                note_bits.append("no ESPN acceptance matched")
            if len({l[0] for l in tr["legs"]}) < 2:
                note_bits.append("one-way")
            if flipped:
                note_bits.append("includes a player traded twice this week")
            items = {(i["type"], i["fromTeamId"], i["toTeamId"], i["playerId"])
                     for i in (acc or {}).get("items", [])}
            # Some acceptances keep only the drop, not the players traded.
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
            if not note_bits:
                notes.append(f"week {week}: trade {teams} matches ESPN's acceptance")
            else:
                notes.append(f"week {week}: trade {teams} - {'; '.join(note_bits)}")

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

    return legs, loose, remove, notes
