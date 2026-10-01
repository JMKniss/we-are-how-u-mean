"""
Reads the Romarkable Vlog's show notes: the Champmissioner's picks, as he wrote them.

The Champmissioner records a vlog most weeks and keeps a .txt of notes for each episode.
They arrive in a shared Google Drive folder synced to this machine, at
VLOG_DIR in .env - one folder per season, one file per episode. Nothing here
runs on the server; data/vlog.py turns what this reads into
data/archive/vlog_picks.csv, which is what the app reads.

Three things are read: who he picks to win each matchup, his Romarkable
players (one per position each week, a hit when the player beats ESPN's
projection), and his power rankings. The rest of the show - awards, his
special player, matchup of the week - is content, not record. Top and bottom
scorer come from the scores.

Which week a section means
--------------------------
Episode N recaps week N-1 and previews week N. That is the first reading, and
data/vlog.py then checks it against the games each section lists (place()).
The first reading is taken from the episode's own title rather than the
section headers, because the headers are
copied forward and not always updated: 2023's Week 15 and 16 episodes both
recap under a "Week 13 Matchup Results" header. The title is trusted over the
file name, too - 2025's "Week 15.txt" is an early draft of Week 16 and its
title says so. "Week 17+18" (2024's finale) recaps weeks 16 and 17, and its
Romarkable lines carry one pick for each ("Kyler (hit) / Daniels (hit)").

What a line means
-----------------
Only two shapes are read, and they hold across every season's format:

    Matt over Tyler (hit)                    a matchup; (hit), [miss], = hit
    -Romarkable QB: Dak (smash)              a player, under its matchup

A recap line lists the result winner first, so a graded one says what he
picked: the winner on a hit, the loser on a miss. An ungraded recap line says
nothing about his pick - 2021 never graded them, an unfinished two-week round
says TBD, and some episodes' notes are a template written before recording,
every line ending in "?", with the picks made on camera. "(N/A)" marks a week
he made no picks for. A preview line ending in "?" is undecided and skipped.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

POSITIONS = ("QB", "RB", "WR", "TE", "FLEX", "K")

# How he writes each manager. Two-person teams go by either name or both.
MANAGER_ALIASES = {
    "johnny": "Johnny", "john": "Johnny", "aaron": "Johnny",
    "johnny/aaron": "Johnny", "john/aaron": "Johnny", "aaron/johnny": "Johnny",
    "brian": "Brian", "josh": "Brian", "brian/josh": "Brian",
    "josh/brian": "Brian",
    "tim": "Tim", "kevin": "Kevin", "david": "David", "matt": "Matt",
    "scott": "Scott", "jason": "Jason", "tyler": "Tyler", "jt": "JT",
}

_GRADE = re.compile(r"\b(hit|smash|miss|tbd|n/a)\b", re.I)
_TITLE = re.compile(r"Romarkable Vlog\s*-\s*Week\s*([\d+&\s]+)", re.I)
_SECTION = re.compile(
    r"^(?:playoff\s+)?(?:(?:week|round)\s*[\d+&\s]+?\s*)?(?:matchup\s*)?"
    r"(results|predictions|status)\b", re.I)
_SECTION_END = re.compile(
    r"^(power rankings|standings|final standings|conclusion|trade|waiver|"
    r"intro|media day|play round|season highlights|survey)", re.I)
_RANKINGS = re.compile(r"^(?:preseason\s+|final\s+)?power rankings\b", re.I)
_ROMARKABLE = re.compile(
    r"romarkab?k?le\s+(QB|RB|WR|TE|FLEX|K)\b(?:\s+of\s+the\s+week)?\s*[:=]\s*(.+)$",
    re.I)


def notes_dir() -> Path | None:
    p = os.getenv("VLOG_DIR")
    return Path(p) if p else None


def manager(text: str) -> str | None:
    return MANAGER_ALIASES.get(re.sub(r"\s+", "", text.strip().lower()))


def _grade(text: str) -> str | None:
    if text.rstrip().endswith("?"):
        return None
    m = _GRADE.search(text)
    if not m:
        return None
    g = m.group(1).lower()
    return {"smash": "hit", "tbd": None, "n/a": "na"}.get(g, g)


def _numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", text or "")]


@dataclass
class Matchup:
    week: int               # game week the line is about
    section: str            # "recap" or "preview"
    first: str              # manager written first: the winner, in a recap
    second: str
    grade: str | None       # recap only: hit / miss / na, or None if ungraded
    line: str
    players: list = field(default_factory=list)


@dataclass
class Player:
    week: int
    section: str
    position: str
    name: str
    grade: str | None
    line: str
    matchup: Matchup | None


@dataclass
class Episode:
    season: int
    path: Path
    weeks: list[int]         # the episode's own number(s), from its title
    matchups: list[Matchup]
    players: list[Player]
    rankings: list[str] = field(default_factory=list)   # managers, 1st first
    transcribed: bool = False

    @property
    def week(self) -> int:
        return self.weeks[0]


def _matchup_line(line: str) -> tuple[str, str, str] | None:
    """(first, second, rest) when the line is 'A over B ...' between managers."""
    parts = re.split(r"\bover\b", line, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    left = re.findall(r"[A-Za-z/]+", parts[0])
    right = re.match(r"[\s*\d()]*([A-Za-z/]+)(.*)$", parts[1])
    if not left or not right:
        return None
    a, b = manager(left[-1]), manager(right.group(1))
    if not a or not b or a == b:
        return None
    return a, b, right.group(2)


def parse(path: Path, season: int) -> Episode:
    text = path.read_text(encoding="utf-8", errors="replace")
    # A few files have two documents run together where a newline was lost
    # ("Conclusion = thanks!Romarkable Vlog - Week 2"). Split them back apart;
    # only the first is read.
    text = re.sub(r"(?<=\S)(Romarkable Vlog\s*-\s*Week)", r"\n\1", text)
    lines = text.splitlines()

    title = next((m for m in map(_TITLE.search, lines) if m), None)
    weeks = _numbers(title.group(1)) if title else []
    weeks = weeks or _numbers(path.stem)[:1] or [0]

    matchups, players, rankings = [], [], []
    section, sec_weeks, current = None, [], None
    seen_title = False
    ranking = None              # the list being read, while inside one
    ranking_ended = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _TITLE.search(line):
            if seen_title:
                break
            seen_title = True
            continue

        # Power rankings: one manager per line, best first, in whatever
        # dress the season wore - "1) Jason", "Jason*", "1) Tim (CLINCHED)".
        # 2025 writes last week's order and this week's side by side,
        # "1) David —> David", and the new one is on the right. A list
        # followed by "^UPDATE" is a template copied from last week and
        # redone on camera, so it is not his ranking for the week.
        if ranking_ended:
            ranking_ended = False
            if line.startswith("^") and "update" in line.lower():
                rankings = []
                continue
        if _RANKINGS.match(line):
            ranking, rankings = [], []
            section, current = None, None
            continue
        if ranking is not None:
            if line.startswith(("-", "—", "^")):
                continue
            text = re.split(r"—>|->|→", line)[-1]
            m = re.match(r"[\s\d().*]*([A-Za-z/]+)", text)
            who = manager(m.group(1)) if m else None
            if who:
                if who not in ranking:
                    ranking.append(who)
                if len(ranking) == len(set(MANAGER_ALIASES.values())):
                    rankings, ranking, ranking_ended = ranking, None, True
                continue
            ranking = None
        s = _SECTION.match(line)
        if s and " over " not in line.lower():
            kind = s.group(1).lower()
            section = "preview" if kind == "predictions" else "recap"
            sec_weeks = (weeks if section == "preview"
                         else [w - 1 for w in weeks])
            current = None
            continue
        if section is None:
            continue
        if _SECTION_END.match(line):
            section, current = None, None
            continue

        r = _ROMARKABLE.search(line)
        if r:
            pos = r.group(1).upper()
            body = r.group(2).strip()
            # "Kyler (hit) / Daniels (hit)": one pick for each week of a
            # two-week episode. A bare "Stroud/Daniels" is one pick between
            # two players - "whichever one Tyler ends up starting", as he put
            # it in 2024 - and stays one name for data/vlog.py to settle.
            if re.search(r"\)\s*/\s*\S", body):
                parts = re.split(r"(?<=\))\s*/\s*", body)
            else:
                parts = [body]
            for i, part in enumerate(parts):
                name = re.sub(r"\s*[(\[].*$", "", part).strip(" -.,")
                # 2021 sometimes grades without brackets: "Andrews miss".
                name = re.sub(r"\s+(hit|miss|smash)\b.*$", "", name, flags=re.I)
                if not name or "?" in name or name.upper() in ("N/A", "TBD"):
                    continue
                week = sec_weeks[min(i, len(sec_weeks) - 1)]
                p = Player(week, section, pos, name, _grade(part), line, current)
                players.append(p)
                if current is not None:
                    current.players.append(p)
            continue

        m = _matchup_line(line)
        if m:
            a, b, rest = m
            undecided = line.rstrip().endswith("?")
            current = Matchup(sec_weeks[0], section, a, b,
                              _grade(rest) if section == "recap" else None,
                              line)
            if not (section == "preview" and undecided):
                matchups.append(current)

    return Episode(season, path, weeks, matchups, players, rankings)


# Picks taken from the episodes themselves, in his format, for the few weeks
# his notes leave out: a pre-recording template, a pick left undecided, a
# guest host. Each file says where in which video it came from. They are read
# after his notes for the same episode, so they fill a gap or settle an
# undecided pick, and a later recap in his notes still outranks them.
TRANSCRIBED = Path(__file__).parent / "vlog_transcribed"


def episodes(season: int, root: Path | None = None) -> list[Episode]:
    """Every episode of a season, in the order he recorded them."""
    root = root or notes_dir()
    eps = []
    for folder, transcribed in ((root, False), (TRANSCRIBED, True)):
        if folder is None or not (folder / str(season)).is_dir():
            continue
        for p in (folder / str(season)).glob("*.txt"):
            ep = parse(p, season)
            ep.transcribed = transcribed
            eps.append(ep)
    return sorted(eps, key=lambda e: (e.week, e.transcribed, e.path.name))
