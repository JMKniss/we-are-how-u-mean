"""
Render the pages and report anything broken. One line per page.

    python check.py                 every page, every season
    python check.py --quick         every page, three seasons
    python check.py Standings       one page, every season
    python check.py Standings 2026  one page, one season

Exists so verification is a command rather than a bespoke script written from
scratch each time, and so its output is short enough to read. It catches the
three things that have actually broken this app: an exception on some season
but not others, a dataframe Streamlit has to repair before it can serialise
it, and a page that renders nothing at all.

Scale the check to the change. Shared code - config, display_utils, app,
data/, analysis/ - touches every page, so run the lot. A change to one page
needs that page. A caption or a label needs neither.
"""
import argparse
import io
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))


class _Quiet:
    """A stderr wrapper that drops lines containing any of the given phrases."""

    def __init__(self, stream, *drop):
        self._stream = stream
        self._drop = drop

    def write(self, text):
        if any(d in text for d in self._drop):
            return len(text)
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


# Installed before importing streamlit, not after. Bare AppTest runs have no
# ScriptRunContext and Streamlit says so on every page render, two lines each,
# which buries the actual result. Setting the logger level does not hold -
# Streamlit reconfigures its own logging when AppTest initialises - and its log
# handler captures whatever sys.stderr is at import time, so the swap has to
# happen first or the first two warnings escape.
sys.stderr = _Quiet(sys.stderr, "missing ScriptRunContext")

from streamlit.testing.v1 import AppTest          # noqa: E402
from config import SEASONS                        # noqa: E402

VIEWS = sorted(Path("views").glob("*.py"))
QUICK = [SEASONS[0], SEASONS[-2], SEASONS[-1]]
REPAIR = "Serialization of dataframe to Arrow table was unsuccessful"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", help="substring of a page name")
    ap.add_argument("season", nargs="?", type=int)
    ap.add_argument("--quick", action="store_true", help="three seasons, not all")
    args = ap.parse_args()

    pages = [p for p in VIEWS if not args.page or args.page.lower() in p.name.lower()]
    if not pages:
        print(f"no page matching {args.page!r}. have: "
              f"{', '.join(p.stem.split('_', 1)[1] for p in VIEWS)}")
        return 2
    seasons = ([args.season] if args.season
               else QUICK if args.quick else SEASONS)

    # Streamlit logs the Arrow repair rather than raising it, so it has to be
    # caught off the log or it goes unnoticed - which is how it went unnoticed.
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger().addHandler(handler)
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).addHandler(handler)

    problems = []
    for page in pages:
        cells = []
        for season in seasons:
            buf.truncate(0)
            buf.seek(0)
            at = AppTest.from_file(str(page), default_timeout=600)
            at.session_state["selected_season"] = season
            try:
                at.run()
            except Exception as e:
                cells.append(f"{season}:CRASH")
                problems.append((page.name, season, f"{type(e).__name__}: {e}"))
                continue
            repairs = buf.getvalue().count(REPAIR)
            errors = [f"{x.type}: {x.message}" for x in at.exception]
            if errors:
                cells.append(f"{season}:ERR")
                problems.append((page.name, season, errors[0]))
            elif repairs:
                cells.append(f"{season}:arrow")
                problems.append((page.name, season, f"{repairs} Arrow repair(s)"))
            elif not (at.dataframe or at.info or at.warning or at.markdown):
                cells.append(f"{season}:EMPTY")
                problems.append((page.name, season, "rendered nothing"))
            else:
                cells.append(f"{season}:ok")
            # All-Time reads every season itself; one run covers it.
            if page.name.startswith("9_"):
                break
        print(f"{page.name:26} " + " ".join(cells), flush=True)

    print()
    if not problems:
        print("CLEAN")
        return 0
    print(f"{len(problems)} problem(s):")
    for name, season, detail in problems:
        print(f"  {name} @ {season}: {detail[:300]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
