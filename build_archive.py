"""
Targeted, non-destructive archive builder.

The archive in data/archive/ is curated: values have been checked by hand and
some were corrected. A refresh must never put that at risk. So this tool has no
"rebuild everything" mode, and it will not touch a season you did not name.

Safety model
------------
1. Only seasons named with --season are touched. Every other season is verified
   unchanged after the write.
2. --update is additive. It adds rows for weeks not yet archived and never
   modifies an existing row. Rows that would change are reported as conflicts
   and skipped unless you pass --force.
3. --rebuild replaces a season outright. If that season already has data it
   requires --force, because that is the operation that can discard curation.
4. Every write is preceded by a timestamped backup in data/archive/_backups/.
5. --dry-run prints the plan and writes nothing.
6. Running with no action prints help. No default mutates data.

Usage
-----
  python build_archive.py --list
  python build_archive.py --season 2026 --update
  python build_archive.py --season 2026 --dataset matchups --update
  python build_archive.py --season 2026 --update --dry-run
  python build_archive.py --season 2019 --rebuild --force
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config import SEASONS          # noqa: E402
import data.espn_client as ec       # noqa: E402

ARCHIVE = Path(__file__).parent / "data" / "archive"
BACKUPS = ARCHIVE / "_backups"

# Columns identifying a row, used to tell a new row from a changed one.
KEYS = {
    "matchups":   ["season", "week", "team_id"],
    "boxscores":  ["season", "week", "team_id", "player_id"],
    "validation": ["season", "week", "team_id", "check_type", "label"],
    "draft":      ["season", "overall_pick"],
    "standings":  ["season", "team_id"],
}

BUILDERS = {
    "matchups":   "get_matchups_df",
    "boxscores":  "get_boxscores_df",
    "draft":      "get_draft_df",
    "standings":  "get_standings_df",
    "validation": "get_validation_df",
}

SORT_HINTS = ("season", "week", "team_id", "overall_pick", "player_id")

# Datasets that hold one row per team per season rather than one row per week.
#
# The additive rule fits a log: a week lands once and never legitimately
# changes. It does not fit a running tally. standings keys on (season,
# team_id), so a team has exactly one row all year and every week's real
# result reads as a conflict against it - which --update skips, and the season
# would sit at 0-0 from the preseason onward while every other dataset filled
# in around it.
#
# So for a season still in progress these are replaced outright each run. Once
# the season is complete they revert to the ordinary rule and a change needs
# --force, because by then the row is history and history is what the archive
# exists to protect.
SNAPSHOT_DATASETS = {"standings"}


def season_complete(season: int) -> bool:
    """True once the archive holds every week the season is meant to have."""
    from config import season_config
    m = load_archive("matchups")
    if m.empty:
        return False
    weeks = m[m["season"] == season]["week"]
    return len(weeks) > 0 and int(weeks.max()) >= season_config(season)["total_weeks"]


def csv_path(name):
    return ARCHIVE / f"{name}.csv"


def file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "-"


def load_archive(name) -> pd.DataFrame:
    p = csv_path(name)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


_freshened: set = set()


def fetch_fresh(name, season) -> pd.DataFrame:
    """Pull from ESPN, bypassing both the archive and the pickle cache."""
    prev = ec.USE_ARCHIVE
    ec.USE_ARCHIVE = False           # else we would just re-read the archive
    try:
        # Clear the pickle once per season, not once per dataset. Doing it per
        # dataset threw away the League object and the memoised box scores that
        # the previous dataset had just downloaded, so a five-dataset update
        # pulled the same season from ESPN five times over.
        if season not in _freshened:
            ec.invalidate_cache(season)
            _freshened.add(season)
        df = getattr(ec, BUILDERS[name])(season)
        if df is None:
            return pd.DataFrame()
        df = df.copy()
        if "season" not in df.columns:
            df.insert(0, "season", season)
        return df
    finally:
        ec.USE_ARCHIVE = prev


def canonical(df: pd.DataFrame) -> pd.DataFrame:
    """
    Values rendered as text, so a CSV round trip cannot look like a change.

    The archive is CSV and ESPN is JSON, and the two disagree about types even
    when they agree about facts. A boolean column holding one NaN reads back as
    object; percent_owned reads back as float where the API gave int. Compared
    with DataFrame.equals, which is strict about dtype, that made every single
    row of a season a conflict: a dry run over 2025 reported 2,704 conflicts
    across 2,704 rows while not one field actually differed.

    That is worse than a cosmetic bug. The weekly update reports conflicts so a
    genuine restatement gets a human look, and a report that cries wolf over
    every row would bury the one line that matters.
    """
    out = pd.DataFrame(index=df.index)
    blank = {"nan", "none", "nat", "<na>", ""}
    for c in df.columns:
        col = df[c]
        if pd.api.types.is_bool_dtype(col):
            out[c] = col.map({True: "True", False: "False"})
        elif pd.api.types.is_numeric_dtype(col):
            out[c] = col.astype(float).round(4).map(
                lambda v: "" if pd.isna(v) else f"{v:.4f}")
        else:
            t = col.astype(str).str.strip()
            out[c] = t.mask(t.str.lower().isin(blank), "")
        out[c] = out[c].fillna("")
    return out


def compare(name, existing, fresh, season):
    """Split fresh rows into new / changed / identical against what is archived."""
    keys = [k for k in KEYS[name] if k in fresh.columns]
    cur = existing[existing["season"] == season] if not existing.empty else pd.DataFrame()
    if cur.empty:
        return fresh, pd.DataFrame(), 0, keys

    cols = [c for c in fresh.columns if c in cur.columns]
    fk = fresh[cols].drop_duplicates(subset=keys).set_index(keys).sort_index()
    ck = cur[cols].drop_duplicates(subset=keys).set_index(keys).sort_index()

    new_idx = fk.index.difference(ck.index)
    both_idx = fk.index.intersection(ck.index)

    new = (fresh.set_index(keys).loc[new_idx].reset_index()[cols]
           if len(new_idx) else pd.DataFrame(columns=cols))

    if len(both_idx):
        # One vectorised comparison over the whole overlap, rather than
        # building two single-row DataFrames per row as this used to.
        a = canonical(fk.loc[both_idx])
        b = canonical(ck.loc[both_idx])
        differs = (a != b).any(axis=1)
        changed = fk.loc[both_idx][differs.values].reset_index()[cols]
        identical_n = int((~differs).sum())
    else:
        changed, identical_n = pd.DataFrame(columns=cols), 0

    return new, changed, identical_n, keys


def sort_frame(df):
    """Canonical row order. Stable across rebuilds so git diffs stay minimal."""
    cols = [c for c in SORT_HINTS if c in df.columns]
    return df.sort_values(cols).reset_index(drop=True) if cols else df.reset_index(drop=True)


def normalise(df, name):
    """Sort by identity keys so two frames compare on content, not row order."""
    keys = [k for k in KEYS[name] if k in df.columns]
    return df.sort_values(keys).reset_index(drop=True) if keys else df.reset_index(drop=True)


def refresh_meta(seasons, dry_run=False):
    """
    Rewrite seasons.json for the named seasons only.

    Nothing used to write this file, so an additive update could add a week of
    matchups while the app went on reporting the old week: archive.current_week
    reads seasons.json, not the CSVs. A new season was worse - absent from
    seasons.json it had no manager_map, so every page fell through to a live
    ESPN call for names it should have had on disk.

    current_week here means the last week the archive holds, not ESPN's open
    scoring period. That is the question the pages are really asking, and it
    cannot run ahead of the data the way ESPN's own counter does.
    """
    from config import season_config, get_manager_name

    path = ARCHIVE / "seasons.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    matchups = load_archive("matchups")

    for season in seasons:
        cfg = season_config(season)
        weeks = (matchups[matchups["season"] == season]["week"]
                 if not matchups.empty else pd.Series(dtype=int))
        entry = {
            "current_week": int(weeks.max()) if len(weeks) else 0,
            "reg_season_end": cfg["reg_season_end"],
            "playoff_weeks": cfg["playoff_weeks"],
            "total_weeks": cfg["total_weeks"],
        }
        try:
            league = ec.get_league(season)
            entry["team_count"] = len(league.teams)
            entry["manager_map"] = {
                str(t.team_id): get_manager_name(
                    season, t.team_id,
                    [o.get("id", "") for o in getattr(t, "owners", [])])
                for t in league.teams
            }
            entry["team_names"] = {
                str(t.team_id): t.team_name.strip() for t in league.teams
            }
        except Exception as e:
            # Names can be refreshed later; the week pointer is the urgent part.
            keep = meta.get(str(season), {})
            for k in ("team_count", "manager_map", "team_names"):
                if k in keep:
                    entry[k] = keep[k]
            print(f"  meta        {season}  names unavailable ({type(e).__name__}), "
                  f"kept previous")

        was = meta.get(str(season), {}).get("current_week")
        meta[str(season)] = entry
        now = entry["current_week"]
        shown = f"{was} -> {now}" if was != now else str(now)
        print(f"  meta        {season}  current_week {shown}")

    if dry_run:
        print("  (dry run - seasons.json not written)")
        return

    ordered = {k: meta[k] for k in sorted(meta)}
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote   seasons.json  {len(ordered)} seasons")


def do_list():
    print(f"archive: {ARCHIVE}")
    for name in BUILDERS:
        df = load_archive(name)
        if df.empty:
            print(f"  {name:11} (absent)")
            continue
        per = df.groupby("season").size()
        print(f"  {name:11} {len(df):7,} rows  seasons {sorted(per.index.tolist())}")
    meta = ARCHIVE / "seasons.json"
    print(f"  seasons.json {'present' if meta.exists() else 'ABSENT'}")
    if BACKUPS.exists():
        n = len(list(BACKUPS.glob('*.csv')))
        print(f"  backups      {n} file(s) in _backups/")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Targeted archive builder. Never touches unnamed seasons.")
    ap.add_argument("--season", type=int, action="append",
                    help="season to act on (repeatable). Required for --update/--rebuild.")
    ap.add_argument("--dataset", action="append", choices=list(BUILDERS),
                    help="limit to these datasets (repeatable). Default: all.")
    ap.add_argument("--update", action="store_true",
                    help="additive: add new rows only, never modify existing ones")
    ap.add_argument("--rebuild", action="store_true",
                    help="replace the named season's rows outright")
    ap.add_argument("--force", action="store_true",
                    help="permit modifying or replacing rows that already exist")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--list", action="store_true", help="show what the archive holds")
    ap.add_argument("--meta", action="store_true",
                    help="refresh seasons.json for the named seasons and exit")
    args = ap.parse_args()

    if args.list:
        return do_list()

    if args.meta and not (args.update or args.rebuild):
        if not args.season:
            print("error: --meta needs --season. It never rewrites every season.")
            return 2
        unknown = [x for x in args.season if x not in SEASONS]
        if unknown:
            print(f"error: {unknown} not in config.SEASONS {SEASONS}")
            return 2
        refresh_meta(sorted(set(args.season)), args.dry_run)
        return 0

    if not (args.update or args.rebuild):
        ap.print_help()
        print("\nNo action requested. Nothing was changed.")
        return 0
    if args.update and args.rebuild:
        print("error: choose --update or --rebuild, not both")
        return 2
    if not args.season:
        print("error: --season is required. This tool never acts on all seasons at once.")
        return 2

    bad = [s for s in args.season if s not in SEASONS]
    if bad:
        print(f"error: {bad} not in config.SEASONS {SEASONS}")
        return 2

    datasets = args.dataset or list(BUILDERS)
    targets = sorted(set(args.season))
    mode = "update" if args.update else "rebuild"

    print(f"mode={mode}  seasons={targets}  datasets={datasets}"
          f"{'  DRY RUN' if args.dry_run else ''}\n")

    before = {n: file_hash(csv_path(n)) for n in BUILDERS}
    untouched_before = {}
    for n in datasets:
        df = load_archive(n)
        if not df.empty:
            untouched_before[n] = df[~df["season"].isin(targets)].reset_index(drop=True)

    planned = {}
    blocked = False

    for name in datasets:
        existing = load_archive(name)
        for season in targets:
            try:
                fresh = fetch_fresh(name, season)
            except Exception as e:
                print(f"  {name:11} {season}  FETCH FAILED {type(e).__name__}: {e}")
                blocked = True
                continue
            if fresh.empty:
                print(f"  {name:11} {season}  no data returned - skipped")
                continue

            new, changed, identical_n, keys = compare(name, existing, fresh, season)
            n_new, n_chg = len(new), len(changed)

            if mode == "update":
                live_snapshot = (name in SNAPSHOT_DATASETS
                                 and not season_complete(season))

                if n_chg and live_snapshot:
                    print(f"  {name:11} {season}  {n_chg} updated, +{n_new} new "
                          f"(running tally, season in progress)")
                    kt = set(changed[keys].apply(tuple, axis=1))
                    mask = existing[keys].apply(tuple, axis=1).isin(kt)
                    keep = existing[~mask].copy()
                    add = pd.concat([new, changed], ignore_index=True)
                elif n_chg and not args.force:
                    first = changed.iloc[0][keys].to_dict()
                    print(f"  {name:11} {season}  +{n_new} new, {n_chg} CONFLICT "
                          f"(archived rows differ) - conflicts skipped")
                    print(f"              keys={keys}  first: {first}")
                    keep, add = existing.copy(), new
                elif n_chg:
                    print(f"  {name:11} {season}  +{n_new} new, {n_chg} changed "
                          f"(--force: applying)")
                    kt = set(changed[keys].apply(tuple, axis=1))
                    mask = existing[keys].apply(tuple, axis=1).isin(kt)
                    keep = existing[~mask].copy()
                    add = pd.concat([new, changed], ignore_index=True)
                else:
                    print(f"  {name:11} {season}  +{n_new} new, {identical_n} unchanged")
                    keep, add = existing.copy(), new

                if add.empty:
                    continue
                merged = pd.concat([keep, add], ignore_index=True)

            else:  # rebuild
                had = 0 if existing.empty else int((existing["season"] == season).sum())
                if had and not args.force:
                    print(f"  {name:11} {season}  REFUSED: {had} rows already archived. "
                          f"Re-run with --force to replace them.")
                    blocked = True
                    continue
                print(f"  {name:11} {season}  replacing {had} rows with {len(fresh)}")
                keep = (existing[existing["season"] != season]
                        if not existing.empty else pd.DataFrame())
                merged = pd.concat([keep, fresh], ignore_index=True)

            planned[name] = sort_frame(merged)
            existing = planned[name]

    if not planned:
        print("\nNo new rows.")
        if not args.dry_run and not blocked:
            # Still refresh the metadata. A week where ESPN adds nothing can
            # still be a week somebody renamed their team, and seasons.json is
            # where the app reads names from.
            print("\nrefreshing seasons.json:")
            refresh_meta(targets)
        return 1 if blocked else 0

    if args.dry_run:
        print("\nDRY RUN - no files written. Planned results:")
        for name, df in planned.items():
            print(f"  {name:11} would become {len(df):,} rows")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    print()
    for name, df in planned.items():
        p = csv_path(name)
        if p.exists():
            b = BACKUPS / f"{name}.{stamp}.csv"
            shutil.copy2(p, b)
            print(f"  backup  _backups/{b.name}")
        df.to_csv(p, index=False)
        print(f"  wrote   {p.name}  {len(df):,} rows")

    print("\nverifying untouched seasons:")
    ok = True
    for name in planned:
        prev = untouched_before.get(name)
        if prev is None or prev.empty:
            continue
        now = load_archive(name)
        now_untouched = now[~now["season"].isin(targets)]
        a = normalise(prev, name)
        b = normalise(now_untouched[prev.columns], name)
        same = a.equals(b)
        print(f"  {name:11} {'unchanged' if same else 'CHANGED - INVESTIGATE'} "
              f"({len(prev):,} rows outside {targets})")
        ok &= bool(same)

    unwritten = [n for n in BUILDERS if n not in planned]
    for n in unwritten:
        if file_hash(csv_path(n)) != before[n]:
            print(f"  {n:11} UNEXPECTEDLY MODIFIED")
            ok = False
    print(f"  {len(unwritten)} untouched file(s) byte-identical")

    if not ok:
        print("\nWARNING: data outside the named seasons differs. "
              "Restore from data/archive/_backups/.")
        return 1

    print("\nrefreshing seasons.json:")
    refresh_meta(targets)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
