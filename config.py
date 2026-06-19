LEAGUE_ID = 722346
SEASONS = [2024, 2025]
DEFAULT_SEASON = 2025
REG_SEASON_WEEKS = 13   # weeks 1-13 are regular season
PLAYOFF_WEEKS = [14, 15, 16, 17]
TOTAL_WEEKS = 17

# Manager name mapping (team_id -> manager first name)
# espn-api exposes team.owners but names can be spotty; override here if needed
MANAGER_OVERRIDES: dict[int, str] = {}
