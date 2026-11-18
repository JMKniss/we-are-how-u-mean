"""
The J’Diglett Takeover: Jason's brag tables for the Champmissioner's Dashboard.

A guest tab, not league analysis. Fourteen league-wide tables picked, cut and
ordered by Jason so that he tops nearly all of them, with his rows in gold.
Every number is real and computed from the archive on each load; only the
choice of what to show is partisan. tables() returns them ready for
style.html_table, and the Champmissioner page draws them two to a row.

To take it down: delete this file, and the tab that imports it in
views/6_Champmissioner.py. Nothing else reads it.

The windows are deliberate, and chosen to flatter:
  - nothing before 2018, Jason's first season
  - "the modern era" is 2021 on, the ten managers the league has today
  - playoff berths start at 2022, his title year
  - no table runs past ten rows, and several stop at five
Regular season only unless a table says otherwise, and always the latest
season in the archive, whatever the season selector says.
"""
from __future__ import annotations

import html
import numbers

import pandas as pd

from analysis import draft_value as dv
from analysis.standings import playoff_seeds
from data import archive
from style import rank_cell

ME = "Jason"
FIRST, MODERN, TITLE = 2018, 2021, 2022


def _table(title: str, cols: list[tuple], rows: list[list], top: int = 10) -> dict:
    """cols are (header, kind, format); kind "who" marks the manager column,
    and a row whose manager is ME is gold. Rows are ranked in the order given."""
    out = []
    for n, r in enumerate(rows[:top]):
        gold = "wa-gold" if any(k == "who" and v == ME for v, (_, k, _) in zip(r, cols)) else ""
        cells = [(rank_cell(n + 1), gold, n + 1)]
        for v, (_, k, f) in zip(r, cols):
            if k == "who":
                cells.append((f'<span class="wa-name">{html.escape(str(v))}</span>', gold, str(v)))
            elif isinstance(v, numbers.Real):
                cells.append(((f or "{:,}").format(v), gold, v))
            else:
                cells.append((html.escape(str(v)), gold))
        out.append(cells)
    columns = [("#", "")] + [(h, "" if k == "who" else k) for h, k, _ in cols]
    return {"title": title, "columns": columns, "rows": out}


def tables() -> list[dict]:
    m = archive.get("matchups")
    m = m[m["season"] >= FIRST].copy()
    now = int(m["season"].max())
    maps = {int(y): archive.manager_map(int(y)) for y in m["season"].unique()}
    m["mgr"] = [maps[s].get(int(t), "?") for s, t in zip(m["season"], m["team_id"])]
    m["opp"] = [maps[s].get(int(t), "?") if pd.notna(t) else "" for s, t in zip(m["season"], m["opp_id"])]
    g = m.groupby(["season", "week"])["score"]
    m["rank"] = g.rank(ascending=False, method="min")
    m["low"] = g.rank(method="min")
    m["n"] = g.transform("count")
    m["med"] = g.transform("median")
    m["margin"] = m["score"] - m["opp_score"]
    reg = m[~m["is_playoff"].astype(bool)].copy()
    modern = reg[reg["season"] >= MODERN]
    cur = reg[reg["season"] == now]
    managers = sorted(cur["mgr"].unique())
    who, year, mid, num = ("Manager", "who", None), ("Season", "mid", "{}"), "mid", "num"
    out = []

    # Top scorer in consecutive weeks
    tops = reg[(reg["n"] == 10) & (reg["rank"] == 1)].sort_values(["season", "week"])
    runs, run = [], []
    for r in tops.itertuples():
        if run and run[-1].mgr == r.mgr and run[-1].season == r.season and r.week == run[-1].week + 1:
            run.append(r)
        else:
            if len(run) >= 2:
                runs.append(run)
            run = [r]
    if len(run) >= 2:
        runs.append(run)
    rows = sorted(([x[0].mgr, x[0].season, f"{x[0].week}–{x[-1].week}", len(x)] for x in runs),
                  key=lambda r: (-r[3], -r[1]))
    out.append(_table(f"Top Scorer in Consecutive Regular-Season Weeks Since {FIRST}",
                      [who, year, ("Weeks", mid, None), ("In a Row", num, None)], rows))

    # Three-game winning margins, the best stretch of each manager's season
    r3 = reg.sort_values(["season", "team_id", "week"]).copy()
    r3["m3"] = r3.groupby(["season", "team_id"])["margin"].transform(lambda s: s.rolling(3).sum())
    best = r3.dropna(subset=["m3"]).sort_values("m3", ascending=False).drop_duplicates(["season", "mgr"])
    out.append(_table(f"Biggest Three-Game Winning Margins Since {FIRST}",
                      [who, year, ("Weeks", mid, None), ("Combined Margin", num, "{:,.2f}")],
                      [[r.mgr, r.season, f"{r.week - 2}–{r.week}", r.m3] for r in best.head(5).itertuples()], top=5))

    out.append(_table("Biggest Regular-Season Blowouts in the Modern Era",
                      [("Winner", "who", None), year, ("Week", mid, "{}"), ("Score", num, "{:.2f}"),
                       ("Loser", "", None), ("Loser Score", num, "{:.2f}"), ("Margin", num, "{:.2f}")],
                      [[r.mgr, r.season, r.week, r.score, r.opp, r.opp_score, r.margin]
                       for r in modern.nlargest(10, "margin").itertuples()]))

    # Weeks the Champmissioner ranked each manager first
    if archive.has("vlog_power_rankings"):
        pr = archive.get("vlog_power_rankings")
        pr = pr[pr["rank"] == 1].copy()
        pr["mgr"] = [archive.manager_map(int(s)).get(int(t), "?") for s, t in zip(pr["season"], pr["team_id"])]
        t = pd.DataFrame({"all": pr.groupby("mgr").size(), "now": pr[pr["season"] == now].groupby("mgr").size()})
        t = t.reindex(managers).fillna(0).astype(int).sort_values(["all", "now"], ascending=False)
        out.append(_table("Weeks Atop Power Rankings", [who, (str(now), num, None), (f"Since {MODERN}", num, None)],
                          [[k, int(v["now"]), int(v["all"])] for k, v in t.iterrows()]))

    # This season
    t = cur.groupby("mgr")["rank"].agg(first=lambda s: (s == 1).sum(), top2=lambda s: (s <= 2).sum(),
                                       top5=lambda s: (s <= 5).sum())
    t = t.sort_values(["top2", "first", "top5"], ascending=False)
    out.append(_table(f"{now} Weekly Scoring Finishes",
                      [who, ("Top Scorer", num, None), ("Top Two", num, None), ("Top Half", num, None)],
                      [[k, int(v["first"]), int(v["top2"]), int(v["top5"])] for k, v in t.iterrows()], top=5))

    b = archive.get("boxscores", now)
    b = b[b["is_active_slot"].astype(bool)].copy()
    b["mgr"] = [maps[now].get(int(t_), "?") for t_ in b["team_id"]]
    wk = b.groupby(["mgr", "week"]).agg(a=("points", "sum"), p=("projected", "sum")).reset_index()
    wk["d"] = wk["a"] - wk["p"]
    t = wk.groupby("mgr").agg(d=("d", "sum"), beat=("d", lambda s: (s > 0).sum())).sort_values("d", ascending=False)
    out.append(_table(f"{now} Points Against ESPN's Projection",
                      [who, ("Points Over Projection", num, "{:+.1f}"), ("Weeks Beat It", num, None)],
                      [[k, float(v["d"]), int(v["beat"])] for k, v in t.iterrows()]))

    # Seasons ranked against each other
    t = modern.assign(a=modern["score"] > modern["med"]).groupby(["season", "mgr"])["a"].agg(["sum", "size"]).reset_index()
    t["pct"] = t["sum"] / t["size"] * 100
    t = t.sort_values(["pct", "sum"], ascending=False)
    out.append(_table("Most Weeks Above the Median by Season in the Modern Era",
                      [who, year, ("Weeks Above", num, None), ("Rate", num, "{:.0f}%")],
                      [[x["mgr"], int(x["season"]), int(x["sum"]), float(x["pct"])] for _, x in t.head(10).iterrows()]))

    drafts = []
    for y in range(FIRST, now + 1):
        if dv.supported(y):
            d = dv.team_draft_value(y)
            drafts += [(maps[y].get(int(tid), "?"), y, float(v)) for tid, v in zip(d["team_id"], d["value"])]
    drafts.sort(key=lambda r: -r[2])
    out.append(_table(f"Best Drafts Since {FIRST}", [who, year, ("Draft Value", num, "{:+.1f}")],
                      [list(r) for r in drafts[:5]], top=5))

    t = reg.groupby(["season", "mgr"])["score"].mean().reset_index(name="ppg")
    t["lg"] = t.groupby("season")["ppg"].transform("mean")
    t["rel"] = (t["ppg"] / t["lg"] - 1) * 100
    out.append(_table(f"Best Scoring Seasons Against League Average Since {FIRST}",
                      [who, year, ("Per Game", num, "{:.1f}"), ("League Average", num, "{:.1f}"),
                       ("Above Average", num, "{:+.1f}%")],
                      [[r.mgr, r.season, r.ppg, r.lg, r.rel] for r in t.nlargest(5, "rel").itertuples()], top=5))

    # Totals by manager
    if archive.has("vlog_matchups"):
        vm = archive.get("vlog_matchups")
        rows = [(archive.manager_map(int(r.season)).get(int(tid), "?"), r.pick_id == tid)
                for r in vm.itertuples() for tid in (r.team_id, r.opp_id)]
        t = pd.DataFrame(rows, columns=["mgr", "picked"]).groupby("mgr")["picked"].agg(["sum", "size"])
        t["pct"] = t["sum"] / t["size"] * 100
        t = t.sort_values("pct", ascending=False)
        out.append(_table("Champmissioner's Pick", [who, ("Picked to Win", num, None), ("Rate", num, "{:.1f}%")],
                          [[k, int(v["sum"]), float(v["pct"])] for k, v in t.iterrows()]))

    e = modern
    t = e.groupby("mgr").agg(ppg=("score", "mean"), g=("score", "size"), tops=("rank", lambda s: (s == 1).sum()))
    t["above"] = e[e["score"] > e["med"]].groupby("mgr").size()
    t["ap"] = e.assign(a=10 - e["rank"]).groupby("mgr")["a"].sum() / (t["g"] * 9) * 100
    t = t.fillna(0).sort_values("ppg", ascending=False)
    out.append(_table("Regular Season in the Modern Era",
                      [who, ("Per Game", num, "{:.1f}"), ("Vs All Win %", num, "{:.1f}%"),
                       ("Top Scorer Weeks", num, None), ("Weeks Above Median", num, None)],
                      [[k, float(v["ppg"]), float(v["ap"]), int(v["tops"]), int(v["above"])] for k, v in t.iterrows()],
                      top=5))

    seeds = [(maps[y].get(int(tid), "?"), i + 1) for y in range(TITLE, now)
             for i, tid in enumerate(playoff_seeds(y, m[m["season"] == y])[:4])]
    if seeds:
        p = pd.DataFrame(seeds, columns=["mgr", "seed"]).groupby("mgr")["seed"].agg(
            apps="size", one=lambda s: (s == 1).sum())
        p = p.reindex(managers, fill_value=0).sort_values(["apps", "one"], ascending=False)
        out.append(_table(f"Playoff Berths {TITLE}–{now - 1}", [who, ("Playoff Berths", num, None), ("No. 1 Seeds", num, None)],
                          [[k, int(v["apps"]), int(v["one"])] for k, v in p.iterrows()], top=5))

    t = modern[modern["score"] >= 150].groupby("mgr").size().sort_values(ascending=False)
    out.append(_table("150-Point Regular-Season Games in the Modern Era", [who, ("Games", num, None)],
                      [[k, int(v)] for k, v in t.items()], top=5))

    t = m[(m["low"] == 1) & (m["n"] == 10)].groupby("mgr").size().reindex(managers, fill_value=0).sort_values()
    out.append(_table(f"Fascist of the Week Since {FIRST}", [who, ("Times Low Scorer", num, None)],
                      [[k, int(v)] for k, v in t.items()]))
    return out
