import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

LEAGUE_ID = 722346
SEASONS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]

# The season the weekly update tracks. Bump this once a year, in September.
CURRENT_SEASON = 2026


def default_season() -> int:
    """
    Newest season that actually holds matchups, for the season picker default.

    Not simply max(SEASONS). A season is listed from the moment it exists on
    ESPN, which is months before week 1, and landing every page on an empty
    season would make the app look broken all summer. So the default follows
    the data and moves to the new season by itself once week 1 is archived.
    """
    try:
        from data import archive
        played = [s for s in archive.seasons_with_data("matchups") if s in SEASONS]
        if played:
            return max(played)
    except Exception:
        pass
    return max(SEASONS)


DEFAULT_SEASON = default_season()

ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

# ── League history ────────────────────────────────────────────────────────────
# Commissioner: Johnny Gullette (2016–2020), Mikey Romar (2021–present)
# Mikey retired as team manager after the 2020 season and became commissioner.
# Kevin Deely took over Mikey's team (team_id=3) starting in 2021.
# Mikey stayed on the ESPN account to perform commissioner functions.
#
# Team 7 ownership: B. Pisarcik (2016–2017) → Kevin/Jason co-managed (2018)
#   → Jason Kniss sole manager (2019–present).
# Team 6 ownership: Mitchell Downing (2016–2017) → Scott Miquelon (2018–present).

# Maps ESPN owner account ID → preferred first name.
# Handles people with multiple ESPN accounts (e.g. Johnny's old vs new account).
OWNER_ID_TO_NAME: dict[str, str] = {
    "{01F49A3C-1637-4029-8149-DBC13F96B3C7}": "Johnny",     # old account, 2016–2022
    "{255A1EFA-F4B5-4FE1-90AF-D0ED3B713DF0}": "Johnny",     # new account, 2023–present
    "{1EFD3F04-30CE-476A-BD3F-0430CE876ADC}": "Tim",
    "{3DDE7D6A-D569-4D2C-9E7D-6AD5693D2CCA}": "Mikey",      # manager 2016–2020; commissioner 2021+
    "{6D28D6E9-2FA9-4D39-A8D6-E92FA9FD39B8}": "David",
    "{9C7796AD-8649-410E-B796-AD8649710E5F}": "Matt",
    "{DD56970C-7653-4D41-8BA6-F3C49DA6BCA2}": "Mitchell",   # 2016–2017 only
    "{CB90A2B3-75BB-4FE4-9AC9-496FD82753E5}": "Scott",
    "{4C19A325-EB2F-45C2-99A3-25EB2F05C212}": "B. Pisarcik", # 2016–2017 only
    "{56785054-8F9E-4A0C-9604-CEAE289D1537}": "Kevin",       # co-managed team 7 in 2018 with Jason
    "{5D972E08-482D-493A-972E-08482DD93A4E}": "Jason",
    "{14FFA6C7-3B37-4203-9067-DFCDB5927905}": "Brian",
    "{C861BA16-6530-4203-A1BA-16653062035A}": "Tyler",
    "{8C1FE5CE-8326-4EA2-9FE5-CE8326AEA226}": "JT",
}

# Per-(season, team_id) overrides for cases where the ESPN account owner
# doesn't reflect who actually managed the team that year.
MANAGER_OVERRIDES: dict[tuple[int, int], str] = {
    # 2018 team 7: Kevin's ESPN account, but co-managed with Jason — attribute to Jason
    (2018, 7): "Jason",
    # 2021+ team 3: Mikey's ESPN account stays for commissioner access, but Kevin is the manager
    (2021, 3): "Kevin",
    (2022, 3): "Kevin",
    (2023, 3): "Kevin",
    (2024, 3): "Kevin",
    (2025, 3): "Kevin",
    (2026, 3): "Kevin",
}


def get_manager_name(season: int, team_id: int, owner_ids: list[str]) -> str:
    """
    Return the preferred first name for the manager of a given team in a given season.
    Checks MANAGER_OVERRIDES first (handles account-sharing / commissioner edge cases),
    then falls back to OWNER_ID_TO_NAME keyed by ESPN account ID.
    """
    override = MANAGER_OVERRIDES.get((season, team_id))
    if override:
        return override
    for oid in owner_ids:
        name = OWNER_ID_TO_NAME.get(oid)
        if name:
            return name
    return "Unknown"


def season_config(season: int) -> dict:
    """
    Return schedule structure for a given season.

    The NFL added a 17th regular season game starting in 2021, which pushed
    fantasy football playoffs one week later:
      - 2020 and earlier: reg season weeks 1-12, playoffs weeks 13-16
      - 2021 and later:   reg season weeks 1-13, playoffs weeks 14-17

    2022 exception: regular season ran through week 14; playoffs were 3 weeks:
      Round 1 = week 15 (1 week), Finals = weeks 16-17, Sacko = weeks 15-17.

    2016 exception: the league ran a 13-week regular season and played into NFL
    week 17, so its playoffs were weeks 14-17 - the same shape as 2021+, five
    years early. ESPN's own scoreboard labels them "Playoff Round 1 (NFL Week
    14 - NFL Week 15)" and "Playoff Round 2 (NFL Week 16 - NFL Week 17)".
    Treating 2016 like its neighbours capped the season at week 16, which
    dropped week 17 entirely and split Round 1 across the two rounds.
    """
    if season == 2016:
        return {
            "reg_season_end": 13,
            "playoff_weeks": [14, 15, 16, 17],
            "total_weeks": 17,
        }
    if season == 2022:
        return {
            "reg_season_end": 14,
            "playoff_weeks": [15, 16, 17],
            "total_weeks": 17,
        }
    elif season >= 2021:
        return {
            "reg_season_end": 13,
            "playoff_weeks": [14, 15, 16, 17],
            "total_weeks": 17,
        }
    else:
        return {
            "reg_season_end": 12,
            "playoff_weeks": [13, 14, 15, 16],
            "total_weeks": 16,
        }


def week_label(season: int, week: int) -> str:
    """
    How a week should be named on screen: "Week 5", or the playoff round.

    Rounds are derived from season_config rather than assumed, because the
    shape has never been constant. Most seasons run two two-week rounds;
    2022 ran a one-week Round 1 and a two-week final. Calling week 15 of 2022
    "Round 1" and week 15 of 2023 "Round 1" would be wrong in one of them.
    """
    cfg = season_config(season)
    pw = cfg["playoff_weeks"]
    if week not in pw:
        return f"Week {week}"

    if len(pw) == 3:                     # 2022: 1-week round 1, 2-week final
        return "Playoff Round 1" if week == pw[0] else "Playoff Round 2"
    # Standard: two weeks per round.
    return "Playoff Round 1" if week in pw[:2] else "Playoff Round 2"
