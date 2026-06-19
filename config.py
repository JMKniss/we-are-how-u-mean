import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

LEAGUE_ID = 722346
SEASONS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
DEFAULT_SEASON = 2025
REG_SEASON_WEEKS = 13
PLAYOFF_WEEKS = [14, 15, 16, 17]
TOTAL_WEEKS = 17

ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

# Manager name mapping (team_id -> manager first name)
MANAGER_OVERRIDES: dict[int, str] = {}
