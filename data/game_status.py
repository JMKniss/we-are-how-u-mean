"""
Whether each rostered player actually played, week by week, at game time.

One row per (season, week, player_id) for every player in that week's
boxscores, with one of seven statuses:

  Healthy          played, and was not knocked out of the game
  Mid-Game Injury  played, was injured during a play, and never returned
                   while his team ran at least MIN_PLAYS_AFTER more plays
  Out              did not play, injured or ill: on that week's injury
                   report, or the 2020-21 COVID list
  IR               did not play, on a medical reserve list: IR, IR with
                   return, PUP, non-football injury or illness
  Suspended        did not play: suspended by the league
  Bye              his team did not play that week
  Inactive         did not play for any other reason: healthy scratch,
                   released, practice squad, left the team

Out and IR mean injury or illness and nothing else, which is the point of
the split: an injury-impact analysis should be able to count them without a
suspension or a healthy scratch leaking in. Illness counts with injury
because the effect on a fantasy team is the same and so is the bad luck -
which matters most in 2020, when the COVID list emptied lineups weekly.

A player hurt with nothing left to play is not a Mid-Game Injury. Garrett
Wilson was "injured during the play" on the Jets' last snap of 2025 week 1,
with 25 seconds left; he never returned because there was nothing to return
to. If an injury like that is real, it shows up as next week's Out.

Why not ESPN. ESPN's injury field is the player's status when you ask, not
when the game was played, so a Tuesday pull stamps last week with this week's
news: a player hurt on Sunday reads OUT for the game he started, and one who
came back reads ACTIVE for the weeks he missed. The only thing that matters
in hindsight is whether he played, and that is an NFL fact, so it comes from
nflverse (via nfl-data-py): weekly rosters for reserve lists and team, snap
counts for who played, play-by-play for who was hurt.

Mid-Game Injury is the hard one. The play-by-play marks it in the text -
"BUF-8-T.Bernard was injured during the play." - with team and jersey, which
the weekly roster turns into a player. Whether he came back is answered two
ways, recorded in the source column:

  participation  nflverse's per-play on-field list. He never appears after
                 the injury play. Exact. Published per finished season, so
                 it covers 2016 up to last year.
  snaps          no touch (pass, rush, target, kick) after the injury play,
                 and no more offensive snaps than his team ran up to it.
                 Checked against participation on 2025: 70 of the 71 real
                 cases, and 4 false alarms out of 74 flagged. Used for the
                 season in progress, until its participation is published -
                 then rebuild the season to make it exact.

A player is only classified once nflverse has published snap counts for his
week, so a Tuesday run before they land adds that week on the next run
instead of guessing.

nfl-data-py is a build-time dependency (requirements-build.txt). Nothing on
the server imports this module; pages read data/archive/game_status.csv.
"""
import re

import pandas as pd

_PARTICIPATION = ("https://github.com/nflverse/nflverse-data/releases/download/"
                  "pbp_participation/pbp_participation_{}.parquet")

# nflverse status_description_abbr codes, read off the players who carry
# them: R01 IR, R48 IR designated to return, R04 PUP, R05 non-football injury,
# R27 non-football illness (Metchie's leukemia, Barmore's blood clots), R49
# the same designated to return. R40 is suspension (Rashee Rice 2025), and
# the roster status SUS says so directly. R59 is the 2020-21 COVID list, and
# R06 is left squad. Every other reserve list is medical, so any other RES
# code is IR - including the generic A01/I01 a few RES rows carry, and
# 2016-2017, whose rows carry no code at all.
_SUSPENDED_CODES = {"R40"}
_ILL_CODES = {"R59"}
_LEFT_SQUAD_CODES = {"R06"}

MIN_PLAYS_AFTER = 3

_INJURED = re.compile(r"([A-Z]{2,3})-(\d{1,2})-[^ ]+? was injured during the play")


def _nfl():
    try:
        import nfl_data_py as nfl
        return nfl
    except ImportError:
        raise ImportError("game status needs nfl-data-py: "
                          "pip install -r requirements-build.txt")


def _participation(season: int) -> pd.DataFrame | None:
    try:
        p = pd.read_parquet(_PARTICIPATION.format(season),
                            columns=["nflverse_game_id", "play_id", "players_on_play"])
    except Exception:
        return None
    return p.rename(columns={"nflverse_game_id": "game_id"})


def get_game_status_df(season: int, boxscores: pd.DataFrame) -> pd.DataFrame:
    nfl = _nfl()
    box = boxscores[boxscores["season"] == season]
    if box.empty:
        return pd.DataFrame()

    ros = nfl.import_weekly_rosters([season])
    ros = ros[ros["game_type"] == "REG"].copy()
    ros["espn_id"] = pd.to_numeric(ros["espn_id"], errors="coerce")
    ros["jersey"] = pd.to_numeric(ros["jersey_number"], errors="coerce")

    snaps = nfl.import_snap_counts([season])
    snaps = snaps[snaps["game_type"] == "REG"].copy()
    published = set(snaps["week"].astype(int))

    pbp = nfl.import_pbp_data([season], downcast=True, columns=[
        "game_id", "week", "play_id", "desc", "posteam", "play_type", "season_type",
        "passer_player_id", "rusher_player_id", "receiver_player_id", "kicker_player_id"])
    pbp = pbp[pbp["season_type"] == "REG"]
    inj = nfl.import_injuries([season])
    inj = inj[inj["game_type"] == "REG"]
    on_report = set(zip(inj["week"].astype(int), inj["gsis_id"]))

    sched = nfl.import_schedules([season])
    sched = sched[sched["game_type"] == "REG"]
    teams_playing = {w: set(g["home_team"]) | set(g["away_team"])
                     for w, g in sched.groupby("week")}

    # ESPN id -> NFL (gsis) id: the rosters first, the full id table for the rest.
    ids = nfl.import_ids()[["espn_id", "gsis_id", "pfr_id"]]
    ids["espn_id"] = pd.to_numeric(ids["espn_id"], errors="coerce")
    espn_to_gsis = ids.dropna(subset=["espn_id", "gsis_id"]).drop_duplicates("espn_id")
    espn_to_gsis = dict(zip(espn_to_gsis["espn_id"].astype(int), espn_to_gsis["gsis_id"]))
    r = ros.dropna(subset=["espn_id"]).drop_duplicates("espn_id")
    espn_to_gsis.update(dict(zip(r["espn_id"].astype(int), r["player_id"])))

    pfr_to_gsis = dict(zip(ids.dropna(subset=["pfr_id", "gsis_id"])["pfr_id"],
                           ids.dropna(subset=["pfr_id", "gsis_id"])["gsis_id"]))
    r = ros.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id")
    pfr_to_gsis.update(dict(zip(r["pfr_id"], r["player_id"])))
    snaps["gsis"] = snaps["pfr_player_id"].map(pfr_to_gsis)
    snaps["total"] = snaps[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1)
    snap_of = {(int(w), g): (t, o) for w, g, t, o in
               snaps[["week", "gsis", "total", "offense_snaps"]].dropna(subset=["gsis"])
               .itertuples(index=False)}

    ros_of = {(int(w), g): (t, s, c) for w, g, t, s, c in
              ros[["week", "player_id", "team", "status", "status_description_abbr"]]
              .itertuples(index=False)}
    # The weekly roster has no rows for a team's bye week, so a player on bye
    # has no team that week. Borrow it from his nearest week, earlier first.
    weeks_of = ros.groupby("player_id")["week"].apply(lambda w: sorted(set(w.astype(int))))

    def team_in(week, gsis):
        if (week, gsis) in ros_of:
            return ros_of[(week, gsis)][0]
        ws = weeks_of.get(gsis, [])
        if not ws:
            return None
        near = min(ws, key=lambda w: (abs(w - week), w > week))
        return ros_of[(near, gsis)][0]

    touch = pbp.melt(id_vars=["game_id", "play_id"],
                     value_vars=["passer_player_id", "rusher_player_id",
                                 "receiver_player_id", "kicker_player_id"],
                     value_name="gsis").dropna(subset=["gsis"])
    last_touch = touch.groupby(["game_id", "gsis"])["play_id"].max().to_dict()
    touch = touch.merge(pbp[["game_id", "week"]].drop_duplicates(), on="game_id")
    touched = set(zip(touch["week"].astype(int), touch["gsis"]))

    # Injured during a play: (week, gsis) -> (game_id, play_id of his last injury)
    events = []
    for g, w, pid, d in pbp[["game_id", "week", "play_id", "desc"]].itertuples(index=False):
        for team, jersey in _INJURED.findall(d or ""):
            events.append((g, int(w), pid, team, int(jersey)))
    ev = pd.DataFrame(events, columns=["game_id", "week", "play_id", "team", "jersey"])
    ev = ev.merge(ros[["week", "team", "jersey", "player_id"]],
                  on=["week", "team", "jersey"], how="inner")
    ev = ev.sort_values("play_id").groupby(["week", "player_id"]).last()
    injured = {k: (r.game_id, r.play_id, r.team) for k, r in ev.iterrows()}

    part = _participation(season)
    last_on = None
    if part is not None:
        it_to_gsis = dict(zip(ros["gsis_it_id"].astype(str), ros["player_id"])) \
            if "gsis_it_id" in ros else {}
        p = part.assign(pid=part["players_on_play"].str.split(";")).explode("pid")
        p = p[p["pid"].fillna("") != ""]
        p["gsis"] = p["pid"].where(p["pid"].str.startswith("00-"), p["pid"].map(it_to_gsis))
        last_on = p.groupby(["game_id", "gsis"])["play_id"].max().to_dict()
        part_games = set(part["game_id"])

    offense = pbp[pbp["play_type"].isin(["pass", "run", "qb_kneel", "qb_spike", "no_play"])]
    off_plays = {k: g["play_id"].to_numpy() for k, g in offense.groupby(["game_id", "posteam"])}

    def no_return(week, gsis):
        game, play, team = injured[(week, gsis)]
        if int((off_plays.get((game, team), []) > play).sum()) < MIN_PLAYS_AFTER:
            return False, "participation" if last_on is not None else "snaps"
        if last_on is not None and game in part_games:
            return last_on.get((game, gsis), -1) <= play, "participation"
        if last_touch.get((game, gsis), -1) > play:
            return False, "snaps"
        _, off_snaps = snap_of.get((week, gsis), (0, 0))
        before = int((off_plays.get((game, team), []) <= play).sum())
        return (off_snaps or 0) <= before, "snaps"

    # team_desc lists every abbreviation a franchise has had (Rams: STL, LA,
    # LAR), so keep only the one that played this season.
    season_teams = set().union(*teams_playing.values())
    team_desc = nfl.import_team_desc()
    nick = {n.lower(): a for n, a in zip(team_desc["team_nick"], team_desc["team_abbr"])
            if a in season_teams}

    rows = []
    players = box[["week", "player_id", "player_name", "points"]] \
        .drop_duplicates(["week", "player_id"])
    for week, pid, name, pts in players.itertuples(index=False):
        week = int(week)
        if week not in published:
            continue
        source = "participation" if last_on is not None else "snaps"
        if pid < 0:                                   # D/ST: plays unless on bye
            team = nick.get(str(name).replace(" D/ST", "").strip().lower())
            status = "Bye" if team and team not in teams_playing.get(week, set()) \
                else "Healthy"
            rows.append((season, week, pid, name, status, source))
            continue

        gsis = espn_to_gsis.get(int(pid))
        snapped, _ = snap_of.get((week, gsis), (0, 0))
        played = (snapped or 0) > 0 or (week, gsis) in touched or (pts or 0) != 0
        _, rstat, code = ros_of.get((week, gsis), (None, None, None))
        team = team_in(week, gsis)

        if played:
            status = "Healthy"
            if (week, gsis) in injured:
                gone, source = no_return(week, gsis)
                status = "Mid-Game Injury" if gone else "Healthy"
        elif team and team not in teams_playing.get(week, set()):
            status = "Bye"
        elif rstat == "SUS" or code in _SUSPENDED_CODES:
            status = "Suspended"
        elif code in _ILL_CODES:
            status = "Out"
        elif rstat == "RES" and code not in _LEFT_SQUAD_CODES:
            status = "IR"
        elif (week, gsis) in on_report:
            status = "Out"
        else:
            status = "Inactive"
        rows.append((season, week, pid, name, status, source))

    return pd.DataFrame(rows, columns=["season", "week", "player_id", "player_name",
                                       "status", "source"])
