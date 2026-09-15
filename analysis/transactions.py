"""
Waiver moves and trades, reshaped from the archive's one-row-per-player log.

data/archive/transactions.csv stores each player movement once, from one team
to another, with team 0 as the free-agent pool (see get_transactions_df for
why). The pages want the opposite grain: one line per move a manager made, and
one line per side of a trade. These functions fold the log back up without
changing what it says, so the eventual pay-off analysis can start from the
same log rather than from whatever a table happened to show.
"""
import pandas as pd

FREE_AGENT_POOL = 0


def waiver_moves(tx: pd.DataFrame) -> pd.DataFrame:
    """
    One row per waiver claim or free-agent move, oldest first.

    adds and drops are lists of player names, since a claim can add without
    dropping, drop without adding, or (rarely) move more than one of each.
    bid is the FAAB amount on a waiver claim and NA on a free-agent move, which
    is the whole difference between a $0 claim and a free pickup.
    """
    cols = ["transaction_id", "season", "week", "executed_at", "team_id",
            "kind", "bid", "adds", "drops"]
    if tx is None or tx.empty:
        return pd.DataFrame(columns=cols)
    moves = tx[tx["kind"] != "trade"].copy()
    if moves.empty:
        return pd.DataFrame(columns=cols)
    # The manager is whoever the player came to or left; for a claim with both
    # sides those are the same team.
    moves["team_id"] = moves["to_team_id"].where(
        moves["action"] == "add", moves["from_team_id"])

    rows = []
    for tid, g in moves.groupby("transaction_id", sort=False):
        first = g.iloc[0]
        rows.append({
            "transaction_id": tid,
            "season": int(first["season"]),
            "week": int(first["week"]),
            "executed_at": first["executed_at"],
            "team_id": int(g["team_id"].iloc[0]),
            "kind": first["kind"],
            "bid": first["bid"] if first["kind"] == "waiver" else pd.NA,
            "adds": g.loc[g["action"] == "add", "player_name"].tolist(),
            "drops": g.loc[g["action"] == "drop", "player_name"].tolist(),
        })
    out = pd.DataFrame(rows, columns=cols)
    out["bid"] = pd.to_numeric(out["bid"], errors="coerce").astype("Int64")
    return out.sort_values(["executed_at", "transaction_id"], ignore_index=True)


def trade_sides(tx: pd.DataFrame) -> pd.DataFrame:
    """
    One row per team per trade, oldest trade first.

    receives and sends are the players that changed hands; dropped are players
    the team cut to make roster room as part of the deal, which went to the
    free-agent pool rather than to the other side. partners are the other
    team ids in the trade - usually one, but nothing here assumes two teams.
    """
    cols = ["transaction_id", "season", "week", "executed_at", "team_id",
            "receives", "sends", "dropped", "partners"]
    if tx is None or tx.empty:
        return pd.DataFrame(columns=cols)
    trades = tx[tx["kind"] == "trade"]
    if trades.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for tid, g in trades.groupby("transaction_id", sort=False):
        moved = g[g["action"] == "trade"]
        teams = sorted((set(moved["from_team_id"]) | set(moved["to_team_id"]))
                       - {FREE_AGENT_POOL})
        first = g.iloc[0]
        for team in teams:
            rows.append({
                "transaction_id": tid,
                "season": int(first["season"]),
                "week": int(first["week"]),
                "executed_at": first["executed_at"],
                "team_id": int(team),
                "receives": moved.loc[moved["to_team_id"] == team, "player_name"].tolist(),
                "sends": moved.loc[moved["from_team_id"] == team, "player_name"].tolist(),
                "dropped": g.loc[(g["action"] == "drop") & (g["from_team_id"] == team),
                                 "player_name"].tolist(),
                "partners": [t for t in teams if t != team],
            })
    return (pd.DataFrame(rows, columns=cols)
            .sort_values(["executed_at", "transaction_id", "team_id"], ignore_index=True))
