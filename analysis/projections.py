"""
Playoff odds and magic numbers.

Two simulators, one tally
-------------------------
Both simulators produce the same thing - a simulated score for every team in
every remaining regular-season week, n_sims times over - and hand it to
_tally(), which plays the fixtures, adds median wins where the season counts
them, breaks ties on points for, and counts who finishes in the top N. They
differ only in where the scores come from.

**Team model** (simulate_team_model). Each team's weekly score is normal
around its own average, but the average is shrunk hard toward the league's.
That is not caution for its own sake. Checked on 2018-2025: after three weeks
a team's average predicts the rest of its season *worse* than the league
average does (MSE 190 vs 110), and the best blend weights the league average
as if it were 7-9 extra games (MSE 100). After five weeks the best weight is
still 7. PRIOR_GAMES = 7 is that result. The simulator also draws each team's
true average once per simulation, rather than fixing it, so a hot start that
is really a hot start and one that is noise both stay possible - fixing it
made every simulated week an independent coin with the same bias and wildly
overstated the certainty.

Backtested on 2018-2025, re-run as each season stood after week N, against
the same simulator with each team's raw mean and standard deviation fixed:

    after week     1      3      5      8      10
    Brier, this   .240   .196   .151   .116   .080
    Brier, raw    .367   .252   .178   .124   .079

The raw version gave 30 teams 99%+ odds, 8 of whom missed the playoffs (six
of those after week 1). This one gave 9, none before week 8, and all 9 made
it. The player model cannot be backtested the same way: it needs a roster
snapshot and ESPN projections as they stood mid-season, and those were
never kept before 2026.

Weekly spread is the league's own: 18% of the league mean, which is the
within-team standard deviation across 2018-2025 (19.9 points on a ~110
average). A team's three-week standard deviation is almost pure noise.

**Player model** (simulate_player_model). Scores are built from the rosters
as they stand: each player draws a score from his own distribution, players
on bye or hurt score nothing, the best legal lineup is picked from whoever is
left, and that is scaled by how close the manager tends to get to his best
lineup. Specifically:

- A player's mean is ESPN's projection - next week's for next week, the
  per-game season projection after that. Blending in his actual average does
  not help: on 2019-2025 rostered weeks, ESPN's weekly projection alone
  predicts the week (MSE 39.7) better than any blend with the player's
  season-to-date average (40.1 at the lightest, 49.0 for the average alone).
- A player's spread is fitted per position from every healthy archived week
  since 2018, as std = a + b * mean (fit_player_spread). Skill players are
  drawn from a gamma, which is right-skewed and never negative, as fantasy
  scores are; kickers and D/ST from a normal, since both can go below zero.
- Injuries are a two-state chain per player, fitted per position from
  game_status (fit_injury_rates): a healthy player misses the next week with
  probability ~4-6% at QB/RB/WR/TE, and a missing one returns with
  probability ~30-40% a week (absences average 2.5-3.5 weeks). OUT starts
  the chain missing; INJURY_RESERVE starts it missing with IR_MIN_WEEKS still
  to serve; QUESTIONABLE / DOUBTFUL are a one-week coin.
- Byes come from the roster snapshot. Each team also carries a waiver-wire
  stand-in at every position (_replacements), so a bye or an injury costs
  the gap to a replacement player, not the whole slot.
- The lineup is the best one available with hindsight, filled slot by slot
  from the most restrictive slot to the least. For eligibility sets that nest
  - QB, RB, WR, TE, K, D/ST, then FLEX - that greedy fill is exactly
  optimal, and it vectorises across every simulation at once where the
  bipartite solver in analysis.efficiency would not.
- That hindsight-best total is multiplied by the manager's lineup efficiency
  this season (actual / hindsight-best, exactly as Lineup Efficiency reports
  it), shrunk toward the league's by EFFICIENCY_PRIOR_WEEKS. Nobody starts
  the hindsight-best lineup every week, and some managers are further from
  it than others.

What the player model cannot see is a real waiver move. Rosters are frozen
at the snapshot, and the stand-ins are generic, so a manager who finds the
next breakout on the wire gets no credit for it in advance; the team model, built on results that already include
every past pickup, does not have that blind spot, which is a reason to read
the two together rather than pick one.

Magic numbers
-------------
magic_numbers() is arithmetic, not simulation. The old version compared each
team with the fifth-placed team's *current* wins and called anyone ahead
"clinched" - so after three weeks every 3-0 team had clinched with ten weeks
to play. A spot is clinched only when fewer than N other teams can still
reach your win total if they win out.
"""
import numpy as np
import pandas as pd

# Weight given to the league average, in games, when estimating a team's
# scoring level. Calibrated on 2018-2025; see the module docstring.
PRIOR_GAMES = 7
# Within-team weekly standard deviation as a share of the league mean.
WEEKLY_CV = 0.18

EFFICIENCY_PRIOR_WEEKS = 4
IR_MIN_WEEKS = 3
REPLACEMENT_QUANTILE = 0.2
PLAY_PROB = {"QUESTIONABLE": 0.8, "DAY_TO_DAY": 0.8, "DOUBTFUL": 0.25}
GAMMA_POSITIONS = {"QB", "RB", "WR", "TE"}

# Nesting order for the greedy lineup fill: single-position slots first.
SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
    "K": {"K"}, "D/ST": {"D/ST"},
    "RB/WR": {"RB", "WR"}, "WR/TE": {"WR", "TE"},
    "RB/WR/TE": {"RB", "WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"},
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

def fixtures(matchups_df: pd.DataFrame, schedule_df: pd.DataFrame | None,
             reg_season_end: int) -> pd.DataFrame:
    """
    Every regular-season fixture: week, team_id, opp_id.

    The archived schedule where there is one (the season in progress), the
    played matchups where there is not (every completed season, whose fixtures
    are all in matchups already).
    """
    src = schedule_df if schedule_df is not None and not schedule_df.empty else matchups_df
    f = src[src["week"] <= reg_season_end][["week", "team_id", "opp_id"]]
    return f.drop_duplicates().astype(int).reset_index(drop=True)


def _opp_matrix(fx: pd.DataFrame, weeks: list, team_ids: list) -> np.ndarray:
    """(weeks, teams) array of each team's opponent, as a team index."""
    pos = {t: i for i, t in enumerate(team_ids)}
    opp = np.full((len(weeks), len(team_ids)), -1, dtype=int)
    for wi, w in enumerate(weeks):
        for r in fx[fx["week"] == w].itertuples():
            if r.team_id in pos and r.opp_id in pos:
                opp[wi, pos[r.team_id]] = pos[r.opp_id]
    return opp


# ── Shared tally ─────────────────────────────────────────────────────────────

def _current_record(played: pd.DataFrame, team_ids: list, median_game: bool):
    """Wins, losses and points for from the games already played."""
    p = played.copy()
    p["h2h_w"] = (p["outcome"] == "W").astype(float) + 0.5 * (p["outcome"] == "T")
    wins = p.groupby("team_id")["h2h_w"].sum()
    games = p.groupby("team_id").size()
    if median_game:
        med = p.groupby("week")["score"].transform("median")
        p["med_w"] = (p["score"] > med).astype(float) + 0.5 * (p["score"] == med)
        wins = wins + p.groupby("team_id")["med_w"].sum()
        games = games * 2
    pf = p.groupby("team_id")["score"].sum()
    w = np.array([wins.get(t, 0.0) for t in team_ids])
    g = np.array([games.get(t, 0) for t in team_ids])
    return w, g - w, np.array([pf.get(t, 0.0) for t in team_ids])


def _tally(scores: np.ndarray, opp: np.ndarray, base_wins: np.ndarray,
           base_pf: np.ndarray, median_game: bool, spots: int) -> dict:
    """
    Play the simulated weeks and count the outcomes.

    scores is (sims, weeks, teams). Returns per-team playoff probability,
    expected final wins, and the full seed distribution (teams, seeds).
    """
    n_sims, n_weeks, n_teams = scores.shape
    wins = np.broadcast_to(base_wins, (n_sims, n_teams)).astype(float).copy()
    pf = base_pf + scores.sum(axis=1)

    for w in range(n_weeks):
        s = scores[:, w, :]
        o = opp[w]
        has = o >= 0
        opp_s = np.where(has, s[:, np.clip(o, 0, None)], np.nan)
        wins += np.where(has, (s > opp_s) + 0.5 * (s == opp_s), 0.0)
        if median_game:
            med = np.median(s, axis=1, keepdims=True)
            wins += (s > med) + 0.5 * (s == med)

    # Rank by wins, then points for. Points are continuous, so a tie on both
    # never happens in practice.
    key = wins * 1e6 + pf
    order = np.argsort(-key, axis=1)
    seeds = np.empty_like(order)
    rows = np.arange(n_sims)[:, None]
    seeds[rows, order] = np.arange(n_teams)

    seed_dist = np.stack([(seeds == k).mean(axis=0) for k in range(n_teams)], axis=1)
    return {
        "playoff_pct": (seeds < spots).mean(axis=0) * 100,
        "exp_wins": wins.mean(axis=0),
        "seed_dist": seed_dist,
        "first_pct": (seeds == 0).mean(axis=0) * 100,
    }


def _result_frame(team_ids, names, base_w, base_l, t: dict) -> pd.DataFrame:
    return pd.DataFrame({
        "team_id": team_ids,
        "team_name": [names[t_] for t_ in team_ids],
        "current_wins": base_w,
        "current_losses": base_l,
        "exp_wins": t["exp_wins"].round(1),
        "playoff_pct": t["playoff_pct"].round(1),
        "first_pct": t["first_pct"].round(1),
    })


def _setup(matchups_df, fx, reg_season_end, through_week):
    played = matchups_df[matchups_df["week"] <= min(reg_season_end, through_week)]
    team_ids = sorted(set(fx["team_id"]) | set(played["team_id"]))
    names = (matchups_df.drop_duplicates("team_id", keep="last")
             .set_index("team_id")["team_name"].to_dict())
    done = set(played["week"])
    weeks = [w for w in range(1, reg_season_end + 1) if w not in done]
    return played, team_ids, names, weeks


# ── Team model ───────────────────────────────────────────────────────────────

def simulate_team_model(
    matchups_df: pd.DataFrame,
    fx: pd.DataFrame,
    reg_season_end: int,
    median_game: bool,
    playoff_spots: int = 4,
    n_simulations: int = 10_000,
    through_week: int = 99,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Playoff odds from each team's scoring, shrunk toward the league's.

    through_week replays the season as it stood after that week, which is
    how the odds-by-week chart is drawn.
    """
    rng = np.random.default_rng(seed)
    played, team_ids, names, weeks = _setup(matchups_df, fx, reg_season_end, through_week)
    base_w, base_l, base_pf = _current_record(played, team_ids, median_game)

    league_mean = played["score"].mean() if not played.empty else 100.0
    sigma = WEEKLY_CV * league_mean
    stats = played.groupby("team_id")["score"].agg(["sum", "count"])
    n = np.array([stats["count"].get(t, 0) for t in team_ids], dtype=float)
    tot = np.array([stats["sum"].get(t, 0.0) for t in team_ids])
    post_mean = (tot + PRIOR_GAMES * league_mean) / (n + PRIOR_GAMES)
    post_sd = sigma / np.sqrt(n + PRIOR_GAMES)

    n_t = len(team_ids)
    true_mean = rng.normal(post_mean, post_sd, size=(n_simulations, n_t))
    scores = rng.normal(true_mean[:, None, :], sigma,
                        size=(n_simulations, len(weeks), n_t))
    scores = np.maximum(scores, 0)

    opp = _opp_matrix(fx, weeks, team_ids)
    t = _tally(scores, opp, base_w, base_pf, median_game, playoff_spots)
    out = _result_frame(team_ids, names, base_w, base_l, t)
    out["proj_mean"] = post_mean.round(1)
    out["seed_dist"] = list(t["seed_dist"])
    return out.sort_values(["playoff_pct", "exp_wins"], ascending=False).reset_index(drop=True)


def odds_by_week(matchups_df, fx, reg_season_end, median_game,
                 playoff_spots=4, n_simulations=4000) -> pd.DataFrame:
    """Team-model playoff odds after each completed week, for the trend chart."""
    played_weeks = sorted(w for w in matchups_df["week"].unique() if w <= reg_season_end)
    frames = []
    for w in [0] + played_weeks:
        r = simulate_team_model(matchups_df, fx, reg_season_end, median_game,
                                playoff_spots, n_simulations, through_week=w)
        frames.append(r[["team_id", "team_name", "playoff_pct"]].assign(after_week=w))
    return pd.concat(frames, ignore_index=True)


# ── Player model ─────────────────────────────────────────────────────────────

def fit_player_spread(player_weeks: pd.DataFrame, game_status: pd.DataFrame) -> dict:
    """
    {position: (a, b)} with weekly std = a + b * mean, from healthy weeks of
    player-seasons with at least 8 such weeks and a mean of 4+ points.
    """
    x = player_weeks.merge(game_status[["season", "week", "player_id", "status"]],
                           on=["season", "week", "player_id"])
    x = x[x["status"] == "Healthy"]
    g = x.groupby(["season", "player_id", "position"])["points"].agg(["mean", "std", "count"])
    g = g[(g["count"] >= 8) & (g["mean"] >= 4)].reset_index()
    fit = {}
    for pos, gg in g.groupby("position"):
        if len(gg) >= 20:
            b, a = np.polyfit(gg["mean"], gg["std"], 1)
            fit[pos] = (float(max(a, 0)), float(max(b, 0)))
    return fit


def fit_injury_rates(boxscores: pd.DataFrame, game_status: pd.DataFrame) -> dict:
    """
    {position: (p_miss, p_return)} for rostered players, bye weeks excluded.

    p_miss: a player who played misses the next week. p_return: a player who
    missed plays the next. Missing means Out, IR, Suspended or Inactive.
    """
    gs = game_status[game_status["status"] != "Bye"]
    ros = boxscores[["season", "week", "player_id", "position"]].drop_duplicates()
    r = gs.merge(ros, on=["season", "week", "player_id"]).sort_values(
        ["season", "player_id", "week"])
    r["miss"] = r["status"].isin({"Out", "IR", "Suspended", "Inactive"})
    r["nxt"] = r.groupby(["season", "player_id"])["miss"].shift(-1)
    r = r.dropna(subset=["nxt"])
    rates = {}
    for pos, gg in r.groupby("position"):
        healthy, missing = gg[~gg["miss"]], gg[gg["miss"]]
        p_miss = float(healthy["nxt"].mean()) if len(healthy) else 0.0
        p_ret = 1 - float(missing["nxt"].mean()) if len(missing) >= 10 else 0.35
        rates[pos] = (p_miss, p_ret)
    return rates


def _greedy_lineup(pts: np.ndarray, pos: np.ndarray, slot_counts: dict) -> np.ndarray:
    """
    Best lineup total for every simulation and team at once.

    pts is (sims, teams, players), with -inf for padding; pos is (teams,
    players) of position strings. Slots are filled most restrictive first.
    """
    slots = [s for s in slot_counts if s in SLOT_ELIGIBILITY]
    slots.sort(key=lambda s: len(SLOT_ELIGIBILITY[s]))
    avail = pts.copy()
    total = np.zeros(pts.shape[:2])
    for slot in slots:
        elig = np.isin(pos, list(SLOT_ELIGIBILITY[slot]))[None, :, :]
        for _ in range(int(slot_counts[slot])):
            cand = np.where(elig, avail, -np.inf)
            idx = cand.argmax(axis=2)
            best = np.take_along_axis(cand, idx[..., None], axis=2)[..., 0]
            total += np.where(np.isfinite(best), best, 0.0)
            np.put_along_axis(avail, idx[..., None], -np.inf, axis=2)
    return total


def simulate_player_model(
    matchups_df: pd.DataFrame,
    fx: pd.DataFrame,
    rosters: pd.DataFrame,
    reg_season_end: int,
    median_game: bool,
    slot_counts: dict,
    spread: dict,
    injury: dict,
    efficiency: dict,
    playoff_spots: int = 4,
    n_simulations: int = 5_000,
    seed: int = 7,
) -> pd.DataFrame:
    """
    Playoff odds from the rosters: player projections, byes, injuries.

    efficiency is {team_id: fraction of the hindsight-best lineup the manager
    is expected to start}. See the module docstring for every other input.
    """
    rng = np.random.default_rng(seed)
    played, team_ids, names, weeks = _setup(matchups_df, fx, reg_season_end, 99)
    base_w, base_l, base_pf = _current_record(played, team_ids, median_game)
    n_t = len(team_ids)
    tpos = {t: i for i, t in enumerate(team_ids)}

    r = rosters[rosters["team_id"].isin(tpos)].copy()
    r = pd.concat([r, _replacements(r, team_ids)], ignore_index=True)
    width = int(r.groupby("team_id").size().max())
    shape = (n_t, width)
    real = np.zeros(shape, bool)
    posn = np.full(shape, "", dtype=object)
    mu_avg = np.zeros(shape)
    mu_next = np.zeros(shape)
    bye = np.zeros(shape, int)
    status = np.full(shape, "", dtype=object)
    for t, g in r.groupby("team_id"):
        i = tpos[t]
        k = len(g)
        real[i, :k] = True
        posn[i, :k] = g["position"].values
        mu_avg[i, :k] = g["proj_avg"].fillna(0).clip(lower=0).values
        nxt = g["proj_next"].where(g["proj_next"].notna(), g["proj_avg"]).fillna(0)
        mu_next[i, :k] = nxt.clip(lower=0).values
        bye[i, :k] = g["bye_week"].fillna(0).astype(int).values
        status[i, :k] = g["injury_status"].fillna("").values
    proj_week = int(r["proj_week"].iloc[0]) if "proj_week" in r and len(r) else (weeks[0] if weeks else 0)

    a = np.vectorize(lambda p: spread.get(p, (3.0, 0.4))[0])(posn)
    b = np.vectorize(lambda p: spread.get(p, (3.0, 0.4))[1])(posn)
    p_miss = np.vectorize(lambda p: injury.get(p, (0.05, 0.35))[0])(posn).astype(float)
    p_miss = np.where(status == "REPLACEMENT", 0.0, p_miss)
    p_ret = np.vectorize(lambda p: injury.get(p, (0.05, 0.35))[1])(posn).astype(float)
    gamma_pos = np.isin(posn, list(GAMMA_POSITIONS))
    eff = np.array([efficiency.get(t, 0.85) for t in team_ids])
    standin = status == "REPLACEMENT"
    dedicated = {p_: int(n) for p_, n in slot_counts.items()
                 if len(SLOT_ELIGIBILITY.get(p_, ())) == 1}

    # Injury state per simulation: weeks still to serve (IR) and missing flag.
    missing = np.broadcast_to(np.isin(status, ["OUT", "INJURY_RESERVE", "SUSPENSION"]),
                              (n_simulations,) + shape).copy()
    must_sit = np.broadcast_to(np.where(status == "INJURY_RESERVE", IR_MIN_WEEKS, 0),
                               (n_simulations,) + shape).copy()
    one_week_prob = np.vectorize(lambda s: PLAY_PROB.get(s, 1.0))(status).astype(float)

    scores = np.zeros((n_simulations, len(weeks), n_t))
    for wi, w in enumerate(weeks):
        mu = mu_next if w == proj_week else mu_avg
        sd = np.maximum(a + b * mu, 0.5)
        shape_k = np.where(mu > 0, (mu / sd) ** 2, 1.0)
        scale = np.where(mu > 0, sd ** 2 / np.maximum(mu, 1e-6), 0.0)
        g_draw = rng.gamma(shape_k, scale, size=(n_simulations,) + shape)
        n_draw = rng.normal(mu, sd, size=(n_simulations,) + shape)
        pts = np.where(gamma_pos, g_draw, n_draw)
        pts = np.where(mu > 0, pts, 0.0)

        plays = ~missing & (bye != w)
        if wi == 0:
            plays &= rng.random((n_simulations,) + shape) < one_week_prob
        # A stand-in is picked up only when a position's own slots cannot be
        # filled from the roster - a bye or injury at K, D/ST, QB, a thin RB room.
        plays &= ~standin
        for p_, need in dedicated.items():
            at_pos = real & ~standin & (posn == p_)
            short = (plays & at_pos).sum(axis=2) < need
            plays |= short[..., None] & standin & (posn == p_)
        pts = np.where(plays, pts, 0.0)
        pts = np.where(real, pts, -np.inf)

        scores[:, wi, :] = _greedy_lineup(pts, posn, slot_counts) * eff

        # Advance the injury chain to next week.
        u = rng.random((n_simulations,) + shape)
        must_sit = np.maximum(must_sit - 1, 0)
        newly_hurt = ~missing & (bye != w) & (u < p_miss)
        back = missing & (must_sit == 0) & (u < p_ret)
        missing = (missing | newly_hurt) & ~back

    opp = _opp_matrix(fx, weeks, team_ids)
    t = _tally(scores, opp, base_w, base_pf, median_game, playoff_spots)
    out = _result_frame(team_ids, names, base_w, base_l, t)
    out["proj_mean"] = (scores.mean(axis=(0, 1)) if len(weeks) else np.zeros(n_t)).round(1)
    out["seed_dist"] = list(t["seed_dist"])
    return out.sort_values(["playoff_pct", "exp_wins"], ascending=False).reset_index(drop=True)


def _replacements(rosters: pd.DataFrame, team_ids: list) -> pd.DataFrame:
    """
    One waiver-wire stand-in per position per team: never on bye, never hurt,
    projected at REPLACEMENT_QUANTILE of the rostered players at that position,
    and only in play in a week the team cannot fill that position's own slots.

    Without them a frozen roster turns every bye into a zero. A team carrying
    one kicker scored nothing at K in his bye week, and the simulated league
    lost ten points a week once byes began - points no real manager gives up,
    because he picks someone up. The quantile is a rostered bench player's
    level, which is roughly what the wire offers in a ten-team league.

    Offered every week instead, a stand-in inflated every team by ten points:
    the best lineup with hindsight kept finding the week a waiver player
    out-scored the flex, which no manager can pick in advance.
    """
    rows = []
    for pos, g in rosters[rosters["proj_avg"] > 0].groupby("position"):
        level = float(g["proj_avg"].quantile(REPLACEMENT_QUANTILE))
        for t in team_ids:
            rows.append({"team_id": t, "position": pos, "proj_avg": level,
                         "proj_next": level, "bye_week": 0,
                         "injury_status": "REPLACEMENT"})
    return pd.DataFrame(rows)


def team_efficiency(eff_weeks: pd.DataFrame) -> dict:
    """
    {team_id: expected actual / hindsight-best}, each team's season so far
    shrunk toward the league's by EFFICIENCY_PRIOR_WEEKS.
    """
    e = eff_weeks.dropna(subset=["efficiency_pct"])
    if e.empty:
        return {}
    ratio = e["actual_score"] / e["optimal_score"]
    league = float(ratio.mean())
    g = ratio.groupby(e["team_id"]).agg(["sum", "count"])
    return ((g["sum"] + EFFICIENCY_PRIOR_WEEKS * league)
            / (g["count"] + EFFICIENCY_PRIOR_WEEKS)).to_dict()


# ── Magic numbers ────────────────────────────────────────────────────────────

def magic_numbers(standings: pd.DataFrame, wins_col: str, losses_col: str,
                  games_left: int, spots: int) -> pd.DataFrame:
    """
    Clinch and elimination numbers, by arithmetic alone.

    games_left is the number of wins still available to each team (weeks
    remaining, doubled when the median game counts).

    Clinch: a team is in once fewer than `spots` other teams can still reach
    its win total. Take the other teams' maximum possible wins, sorted; the
    spots-th highest is the team that has to be shut out. The magic number is
    how many of (our wins + that team's losses) put us strictly clear of its
    ceiling. Strictly, because the points-for tiebreak cannot be counted on.

    Elimination: out once `spots` other teams already have more wins than we
    can reach. The elimination number is how many of (our losses + the
    spots-th placed other team's wins) make that true.

    Both are conservative in the usual way: they ignore that rivals still play
    each other, so a team can be clinched a week before the number says so.
    The simulation is where that shows up.
    """
    s = standings.copy()
    w = s[wins_col].to_numpy(float)
    ceiling = w + games_left
    magic, elim = [], []
    for i in range(len(s)):
        others_ceiling = np.sort(np.delete(ceiling, i))[::-1]
        others_now = np.sort(np.delete(w, i))[::-1]
        if len(others_ceiling) < spots:
            magic.append(0)
            elim.append(np.nan)
            continue
        threat = others_ceiling[spots - 1]
        magic.append(max(0, int(np.floor(threat - w[i])) + 1))
        rival = others_now[spots - 1]
        elim.append(max(0, int(np.floor(ceiling[i] - rival)) + 1))
    s["magic_number"] = magic
    s["elim_number"] = elim
    s["games_left"] = games_left
    s["status"] = np.where(s["magic_number"] == 0, "Clinched",
                           np.where(s["elim_number"] == 0, "Eliminated", "Alive"))
    return s
