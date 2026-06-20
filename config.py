import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

LEAGUE_ID = 722346
SEASONS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
DEFAULT_SEASON = 2025

ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

# Manager name mapping (team_id -> manager first name)
MANAGER_OVERRIDES: dict[int, str] = {}


def season_config(season: int) -> dict:
    """
    Return schedule structure for a given season.

    The NFL added a 17th regular season game starting in 2021, which pushed
    fantasy football playoffs one week later:
      - 2020 and earlier: reg season weeks 1-12, playoffs weeks 13-16
      - 2021 and later:   reg season weeks 1-13, playoffs weeks 14-17

    This function is the single source of truth for that boundary so that
    any season — including pre-2019 data if it becomes available — is handled
    automatically without touching any other code.
    """
    if season >= 2021:
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
