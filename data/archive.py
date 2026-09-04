"""
Permanent archive reader — the durable record of league history.

Reads plain CSV from data/archive/. No ESPN API, no cookies, no pickle.
Rebuild it with `python build_archive.py` (needs valid ESPN cookies).

The archive is the source of truth for completed seasons. Files are
human-readable and hand-correctable: if a value is wrong, edit the CSV.
"""
from pathlib import Path
import json
import pandas as pd

ARCHIVE_DIR = Path(__file__).parent / "archive"

DATASETS = ("matchups", "boxscores", "draft", "standings", "validation",
            "draft_order")

_cache: dict[str, pd.DataFrame] = {}
_meta: dict | None = None


def archive_path(name: str) -> Path:
    return ARCHIVE_DIR / f"{name}.csv"


def has(name: str, season: int | None = None) -> bool:
    """True if the archive holds this dataset (optionally for a given season)."""
    if not archive_path(name).exists():
        return False
    if season is None:
        return True
    return season in set(_read(name)["season"].unique())


def _read(name: str) -> pd.DataFrame:
    if name not in _cache:
        p = archive_path(name)
        if not p.exists():
            raise FileNotFoundError(
                f"{p} not found. Rebuild the archive: python build_archive.py"
            )
        _cache[name] = pd.read_csv(p)
    return _cache[name]


def get(name: str, season: int | None = None) -> pd.DataFrame:
    """Return an archived dataset, optionally filtered to one season."""
    df = _read(name)
    if season is not None:
        df = df[df["season"] == season]
    return df.reset_index(drop=True).copy()


def draft_order(season: int) -> list[str]:
    """
    The league's own record of who picked where, as a list of ten managers in
    pick order. Empty strings mark slots nobody recorded.

    Hand-kept rather than derived. ESPN's draft data cannot be trusted for the
    years the league drafted in person and the commissioner re-entered the
    teams afterwards: the rosters come out right but the pick order does not.
    Checked against ESPN for every season, it agrees exactly in 2022, 2023 and
    2024 and disagrees almost completely in 2019, 2020, 2021 and 2025.

    Falls back to an empty list for seasons with no recorded order, 2016 and
    2017, where ESPN's data is all there is.
    """
    try:
        df = get("draft_order", season)
    except FileNotFoundError:
        return []
    if df.empty:
        return []
    df = df.sort_values("pick")
    return ["" if pd.isna(m) else str(m) for m in df["manager"]]


def seasons_meta() -> dict:
    """Per-season metadata: current_week, manager_map, team_names, schedule shape."""
    global _meta
    if _meta is None:
        p = ARCHIVE_DIR / "seasons.json"
        if not p.exists():
            raise FileNotFoundError(
                f"{p} not found. Rebuild the archive: python build_archive.py"
            )
        with open(p, encoding="utf-8") as f:
            _meta = json.load(f)
    return _meta


def archived_seasons() -> list[int]:
    try:
        return sorted(int(s) for s in seasons_meta())
    except FileNotFoundError:
        return []


def manager_map(season: int) -> dict[int, str]:
    """{team_id: manager_name} — JSON keys come back as str, so recast to int."""
    m = seasons_meta().get(str(season), {}).get("manager_map", {})
    return {int(k): v for k, v in m.items()}


def team_names(season: int) -> dict[int, str]:
    m = seasons_meta().get(str(season), {}).get("team_names", {})
    return {int(k): v for k, v in m.items()}


def current_week(season: int) -> int | None:
    v = seasons_meta().get(str(season), {}).get("current_week")
    return int(v) if v is not None else None


def clear():
    """Drop in-process caches so edited CSVs are picked up without a restart."""
    global _meta
    _cache.clear()
    _meta = None
