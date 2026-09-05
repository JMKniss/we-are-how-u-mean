"""
Draft order correction.

ESPN's draft board cannot be trusted for pick order. In the years the league
drafts in person, the commissioner re-enters the rosters afterwards, which
gets every team's players right and the order they were taken wrong. The
league's own record of who picked where lives in data/archive/draft_order.csv
and is authoritative; see CLAUDE.md.

Checked against ESPN season by season, the recorded order agrees exactly in
2022, 2023 and 2024 and disagrees almost completely in 2019, 2020, 2021 and
2025. 2025 settles which one to believe: ESPN has Matt taking Ja'Marr Chase
at pick 10, where the recorded order has Matt at pick 1. Chase was the
consensus first overall that year, and the rest of the recorded first round
tracks 2025 draft values the same way. ESPN's does not.

What this module changes and what it does not: every team keeps exactly the
players ESPN says it drafted, in the same rounds. Only the seat each team sat
in changes, and with it pick_in_round and overall_pick.
"""
import pandas as pd

from data import archive


def snake_slot(seat: int, rnd: int, n_teams: int) -> int:
    """Where a seat picks in a given round. Odd rounds run forward, even back."""
    return seat if rnd % 2 == 1 else n_teams + 1 - seat


def order_status(draft_df: pd.DataFrame, season: int, manager_map: dict) -> tuple[bool, str]:
    """
    Whether the recorded order can be applied, and why not when it cannot.

    Returns (usable, reason). The reason is written for the page to show, so a
    season falling back to ESPN's order says so rather than quietly differing
    from the season next to it.
    """
    recorded = archive.draft_order(season)
    if not recorded:
        return False, (
            f"No draft order was recorded for {season}, so this is ESPN's own "
            f"order, which is unreliable for the years the league drafted in "
            f"person."
        )
    if any(not m for m in recorded):
        missing = [i + 1 for i, m in enumerate(recorded) if not m]
        return False, (
            f"The {season} draft order is incomplete - picks "
            f"{', '.join(map(str, missing))} were never recorded - so this is "
            f"ESPN's own order."
        )

    managers = {manager_map.get(t) for t in draft_df["team_id"].unique()}
    unknown = [m for m in recorded if m not in managers]
    if unknown:
        return False, (
            f"The recorded {season} order names {', '.join(unknown)}, who did "
            f"not draft that year, so it cannot be applied. Showing ESPN's order."
        )

    # A traded pick breaks the assumption that a seat picks once per round,
    # which is the whole basis for rebuilding the board from a seat list.
    per_round = draft_df.groupby(["team_id", "round"]).size()
    if (per_round != 1).any():
        bad = per_round[per_round != 1]
        rounds = sorted({r for _, r in bad.index})
        return False, (
            f"Picks were traded in {season} (rounds "
            f"{', '.join(map(str, rounds))}), so the board is not a plain "
            f"snake and cannot be rebuilt from a seat list. Showing ESPN's order."
        )
    return True, ""


def apply_recorded_order(draft_df: pd.DataFrame, season: int,
                         manager_map: dict) -> tuple[pd.DataFrame, bool, str]:
    """
    Reseat the draft board onto the league's recorded order.

    Returns (df, applied, note). When it cannot be applied the frame comes back
    untouched, so callers can render either without branching.
    """
    usable, reason = order_status(draft_df, season, manager_map)
    if not usable:
        return draft_df, False, reason

    recorded = archive.draft_order(season)
    n_teams = draft_df["team_id"].nunique()
    seat_by_manager = {m: i + 1 for i, m in enumerate(recorded)}

    df = draft_df.copy()
    df["manager"] = df["team_id"].map(manager_map)
    df["_seat"] = df["manager"].map(seat_by_manager)
    df["pick_in_round"] = [
        snake_slot(s, r, n_teams) for s, r in zip(df["_seat"], df["round"])
    ]
    df["overall_pick"] = (df["round"] - 1) * n_teams + df["pick_in_round"]
    df = df.drop(columns=["_seat"]).sort_values("overall_pick").reset_index(drop=True)

    note = (
        f"Pick order is the league's own record of who sat where, not ESPN's. "
        f"ESPN's board is rebuilt by the commissioner after an in-person draft, "
        f"which gets the rosters right and the order wrong. Every team still "
        f"holds exactly the players ESPN recorded, in the same rounds."
    )
    return df, True, note
