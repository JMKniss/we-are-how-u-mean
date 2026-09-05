"""
The Tuesday job: fold the week that just finished into the permanent archive.

Run it once a week, after Monday night football has settled:

    python weekly_update.py

It is additive by design. Every week already archived is left exactly as it
was, and only weeks the archive has never seen are added. A week that ESPN has
since restated shows up as a conflict and is reported, not applied - the
archive is the league's record, and a stat correction three weeks later should
not silently rewrite a result everybody already argued about. Pass --force
only when you have looked at the conflict and decided ESPN is right.

What it writes is additive; what it reads is not. Each run pulls the whole
season from ESPN, then compares. That is deliberate: pulling only the new week
would be faster but would never notice ESPN restating week 5, and noticing is
half the point of a weekly check. The whole season costs about half a minute
and no other season on disk is read or touched.

The app itself never calls ESPN. It reads data/archive/*.csv, which is why
this job exists and why nothing else needs cookies.

    python weekly_update.py --dry-run     see what it would add, write nothing
    python weekly_update.py --season 2025 update a season other than the current one
    python weekly_update.py --force       accept ESPN's restatement of a week
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from config import CURRENT_SEASON, SEASONS   # noqa: E402


def run(args, label):
    # Flush before handing the terminal to the child. Without it the parent's
    # own buffered output lands after the child's, and a scheduled run's log
    # reads back in the wrong order - which matters when the log is the only
    # thing you have to work out what a Tuesday morning run did.
    print(f"\n--- {label} ---", flush=True)
    r = subprocess.run([sys.executable, str(HERE / "build_archive.py")] + args)
    sys.stdout.flush()
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    ap.add_argument("--season", type=int, default=CURRENT_SEASON,
                    help=f"season to update (default {CURRENT_SEASON})")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be added, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="apply weeks ESPN has restated, overwriting the archive")
    ap.add_argument("--scheduled", action="store_true",
                    help="marks an unattended run; weekly_update.bat skips its "
                         "final pause so Task Scheduler does not hang on it")
    args = ap.parse_args()

    if args.season not in SEASONS:
        print(f"error: {args.season} is not in config.SEASONS. Add it there first.")
        return 2

    print(f"weekly update  season={args.season}  "
          f"{datetime.now():%Y-%m-%d %H:%M}"
          f"{'  DRY RUN' if args.dry_run else ''}")

    call = ["--season", str(args.season), "--update"]
    if args.dry_run:
        call.append("--dry-run")
    if args.force:
        call.append("--force")

    code = run(call, f"pulling {args.season} from ESPN")
    if code != 0:
        print(f"\nUpdate failed (exit {code}). The archive was not changed, or was "
              f"restored from data/archive/_backups/. Nothing else ran.")
        return code

    # No --meta pass here: build_archive refreshes seasons.json itself, on both
    # the wrote-something and the nothing-new paths.
    run(["--list"], "archive now holds")

    print("\nNext: check the app, then commit the archive so the change is durable.")
    print("\n  git add data/archive")
    print(f'  git commit -m "Archive {args.season} through week {{N}}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
