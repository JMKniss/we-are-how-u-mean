import sys, json
sys.path.insert(0, '.')
from data.espn_client import get_league
from espn_api.football.constant import POSITION_MAP

lg = get_league(2018)

week = 1
scoring_period = week
matchup_period = week
for matchup_id in lg.settings.matchup_periods:
    if week in lg.settings.matchup_periods[matchup_id]:
        matchup_period = matchup_id
        break

params = {'view': ['mMatchupScore', 'mScoreboard'], 'scoringPeriodId': scoring_period}
filters = {"schedule": {"filterMatchupPeriodIds": {"value": [matchup_period]}}}
headers = {'x-fantasy-filter': json.dumps(filters)}
data = lg.espn_request.league_get(params=params, headers=headers)
m = data['schedule'][0]

for side in ['home', 'away']:
    s = m[side]
    print(f"\n=== {side.upper()} teamId={s['teamId']} totalPoints={s['totalPoints']} ===")
    print(f"pointsByScoringPeriod: {s.get('pointsByScoringPeriod')}")

    for roster_key in ['rosterForMatchupPeriod', 'rosterForCurrentScoringPeriod']:
        entries = s.get(roster_key, {}).get('entries', [])
        print(f"\n  {roster_key}: {len(entries)} entries")
        for e in entries:
            slot = e.get('lineupSlotId')
            slot_name = POSITION_MAP.get(slot, f"slot_{slot}")
            pid = e.get('playerId')
            pi = e.get('playerPoolEntry', {})
            name = pi.get('player', {}).get('fullName', '?')
            applied = pi.get('appliedStatTotal', 0)
            stats = pi.get('player', {}).get('stats', [])
            stat_summary = [(st.get('scoringPeriodId'), st.get('appliedTotal'), st.get('statSourceId')) for st in stats[:3]]
            print(f"    [{slot_name:12s}] {name:25s}  appliedStatTotal={applied}  stats={stat_summary}")
