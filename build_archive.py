"""
Backfill every ESPN dataset for every season and write a permanent,
human-readable archive to data/archive/.

Run:  python build_archive.py
The archive is the durable record; data/cache/ stays a disposable cache.
"""
import sys, json, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from config import SEASONS, season_config
from data.espn_client import (
    get_league, get_matchups_df, get_boxscores_df,
    get_draft_df, get_standings_df, get_validation_df, get_manager_map,
)

ARCHIVE = Path(__file__).parent / "data" / "archive"
ARCHIVE.mkdir(parents=True, exist_ok=True)

BUILDERS = {
    "matchups":   get_matchups_df,
    "boxscores":  get_boxscores_df,
    "draft":      get_draft_df,
    "standings":  get_standings_df,
    "validation": get_validation_df,
}

frames = {name: [] for name in BUILDERS}
meta = {}
report = []

for season in SEASONS:
    print(f"\n=== {season} ===", flush=True)

    # ── metadata (replaces the only things league.pkl was used for) ──
    try:
        league = get_league(season)
        mgr_map = get_manager_map(season)
        cfg = season_config(season)
        meta[str(season)] = {
            "current_week": int(league.current_week),
            "reg_season_end": cfg["reg_season_end"],
            "playoff_weeks": cfg["playoff_weeks"],
            "total_weeks": cfg["total_weeks"],
            "team_count": len(league.teams),
            "manager_map": {str(k): v for k, v in mgr_map.items()},
            "team_names": {str(t.team_id): t.team_name.strip() for t in league.teams},
        }
        print(f"  meta         OK  current_week={league.current_week}", flush=True)
    except Exception as e:
        report.append((season, "meta", f"FAIL {type(e).__name__}: {e}"))
        print(f"  meta         FAIL {e}", flush=True)

    # ── datasets ──
    for name, fn in BUILDERS.items():
        try:
            df = fn(season)
            if df is None or df.empty:
                report.append((season, name, "EMPTY"))
                print(f"  {name:12} EMPTY", flush=True)
                continue
            if "season" not in df.columns:
                df = df.copy()
                df.insert(0, "season", season)
            frames[name].append(df)
            report.append((season, name, f"OK rows={len(df)}"))
            print(f"  {name:12} OK  rows={len(df)}", flush=True)
        except Exception as e:
            report.append((season, name, f"FAIL {type(e).__name__}: {e}"))
            print(f"  {name:12} FAIL {type(e).__name__}: {e}", flush=True)
            traceback.print_exc(limit=1)

# ── write archive ──
print("\n=== writing archive ===", flush=True)
for name, parts in frames.items():
    if not parts:
        print(f"  {name:12} SKIPPED (no data)", flush=True)
        continue
    combined = pd.concat(parts, ignore_index=True)
    out = ARCHIVE / f"{name}.csv"
    combined.to_csv(out, index=False)
    kb = out.stat().st_size / 1024
    print(f"  {out.name:18} {len(combined):7,} rows  {kb:8.0f} KB  "
          f"seasons={sorted(combined['season'].unique().tolist())}", flush=True)

with open(ARCHIVE / "seasons.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2)
print(f"  seasons.json       {len(meta)} seasons", flush=True)

# ── summary ──
fails = [r for r in report if not r[2].startswith("OK")]
print(f"\n=== summary: {len(report)-len(fails)} ok, {len(fails)} not ok ===", flush=True)
for season, name, status in fails:
    print(f"  {season} {name:12} {status}", flush=True)
