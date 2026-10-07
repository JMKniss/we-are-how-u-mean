"""
Shared display utilities for name/manager column handling across all pages.

Usage pattern in each page:
    from display_utils import sidebar_display_prefs, prep_display, chart_label

    show_mgr, show_team = sidebar_display_prefs()
    manager_map = get_manager_map(season)

    # For tables:
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "wins", ...],
                           headers=["Team", "W", ...])
    st.dataframe(display, ...)

    # For chart x/y axis (replaces team_name with the right label):
    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    px.bar(df, x="label", ...)
"""

import numpy as np
import pandas as pd
import streamlit as st


def sidebar_display_prefs() -> tuple[bool, bool]:
    """
    Render Manager / Team name toggle checkboxes in the sidebar.
    Persists choices in session state so they survive page navigation.
    Returns (show_manager, show_team).
    """
    if "show_manager" not in st.session_state:
        st.session_state["show_manager"] = True
    if "show_team" not in st.session_state:
        st.session_state["show_team"] = True

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Display columns**")
    show_mgr = st.sidebar.checkbox("Manager name", value=st.session_state["show_manager"])
    show_team = st.sidebar.checkbox("Team name", value=st.session_state["show_team"])
    st.session_state["show_manager"] = show_mgr
    st.session_state["show_team"] = show_team

    # Always show at least one
    if not show_mgr and not show_team:
        st.sidebar.caption(":material/warning: At least one must be shown — defaulting to Manager.")
        show_mgr = True
        st.session_state["show_manager"] = True

    return show_mgr, show_team


def prep_display(
    df: pd.DataFrame,
    manager_map: dict[int, str],
    show_manager: bool,
    show_team: bool,
    cols: list[str],
    headers: list[str],
) -> pd.DataFrame:
    """
    Build a display DataFrame from a source df.

    cols / headers describe the columns you want (excluding Manager/Team —
    include "team_name" in cols and "Team" in headers; this function handles
    prepending Manager and/or dropping Team based on the toggle state).

    The source df must have team_id and team_name columns.
    Manager is always the first column when shown.
    """
    display = df[cols].copy()
    display.columns = list(headers)

    team_col = headers[cols.index("team_name")] if "team_name" in cols else None

    if show_manager:
        managers = df["team_id"].map(manager_map).fillna("?")
        display.insert(0, "Manager", managers.values)

    if not show_team and team_col and team_col in display.columns:
        display = display.drop(columns=[team_col])

    return display


def chart_label(
    df: pd.DataFrame,
    manager_map: dict[int, str],
    show_manager: bool,
    show_team: bool,
) -> pd.Series:
    """
    Returns a Series of display labels for chart axes, one per row.
    Replaces raw team_name with the appropriate label based on toggle state.
    Source df must have team_id and team_name columns.
    """
    mgr = df["team_id"].map(manager_map).fillna("?")
    team = df["team_name"]

    if show_manager and show_team:
        return mgr + " — " + team
    elif show_manager:
        return mgr
    else:
        return team


def name_lines(mgr: str, team: str, show_manager: bool, show_team: bool) -> tuple[str, str]:
    """
    The bold line and the small line under it, for a team picture: manager
    over team with both toggles on, otherwise whichever is shown.
    """
    if show_manager and show_team:
        return mgr, team
    return (mgr, "") if show_manager else (team, "")


def who_columns(df: pd.DataFrame, manager_map: dict[int, str], season: int | None,
                show_manager: bool, show_team: bool) -> tuple[list, list, list]:
    """
    (names, subs, pics) for each row of a frame with team_id and team_name,
    ready for style.frame(pics=..., subs=...). season=None means a view
    across seasons, which always shows the helmet.
    """
    from style import team_image

    names, subs, pics = [], [], []
    for tid, team in zip(df["team_id"], df["team_name"]):
        mgr = manager_map.get(tid, "?")
        main, sub = name_lines(mgr, team, show_manager, show_team)
        names.append(main)
        subs.append(sub)
        pics.append(team_image(season, tid, mgr))
    return names, subs, pics


def season_selector(seasons, default_season):
    """
    The sidebar season picker, identical on every page.

    Kept here because the season list now runs ahead of the data: a season
    appears on ESPN months before week 1, so it has to be selectable before it
    holds anything. Pages pair this with require_data to say so plainly rather
    than rendering empty tables.

    Bound to session state by key rather than driven by index. The two are
    alternatives and mixing them is what made this need two clicks: index was
    read from session state at the top of the run, session state was only
    written at the bottom, so on the rerun a selection triggered, index still
    named the previous season. Streamlit saw the widget's parameters change
    and reset it to index, throwing the click away. The second click stuck
    because by then index had caught up.

    With a key, the widget and session state are the same value, so there is
    nothing to fall out of step. Seed it before the widget - assigning after
    would be writing over what the person just chose.

    But the choice itself lives in "selected_season", which no widget owns,
    and the picker's own key is only a copy. Streamlit deletes a widget's
    session state at the end of any run where that widget was not drawn, and
    every page draws its own picker - so a picker keyed straight to
    "selected_season" lost the season on every page switch, and each page
    landed on the default or on 2016 depending on timing. A plain key
    survives navigation; on_change carries a new pick back into it before
    the rerun reads it.
    """
    if st.session_state.get("selected_season") not in seasons:
        st.session_state["selected_season"] = default_season
    st.session_state["_season_picker"] = st.session_state["selected_season"]

    def _keep():
        st.session_state["selected_season"] = st.session_state["_season_picker"]

    return st.sidebar.selectbox("Season", seasons, key="_season_picker",
                                on_change=_keep)


def require_data(df, season, what="data"):
    """
    Stop the page with a plain explanation when a season holds nothing yet.

    Without this, an unstarted season reaches the analysis code as an empty
    frame with no columns and the page dies on a KeyError - which reads as the
    site being broken rather than the season not having started.
    """
    if df is not None and not df.empty:
        return
    st.info(
        f"No {what} for {season} yet. The season page fills in from week 1, "
        f"and updates every Tuesday once the week is final."
    )
    st.stop()


# ── trade grades ─────────────────────────────────────────────────────────
# Both trade pages show the same columns under the same headers, and the same
# note explaining them, so they are defined once here.
TRADE_GRADE_GROUPS = [
    ("Optimal Lineup Change", [("best", "Total", "%+.1f"), ("best_pw", "Per Week", "%+.1f"),
                               ("best_pgp", "Per Game Played", "%+.1f")]),
    ("Actual Starting Lineup Change", [("started", "Total", "%+.1f"), ("started_pw", "Per Week", "%+.1f"),
                                       ("started_pgp", "Per Game Played", "%+.1f")]),
    ("Wins and Losses", [("wins_created", "Wins Created", None),
                         ("losses_caused", "Losses Caused", None),
                         ("xwins", "Expected Wins Added", "%+.2f")]),
]


def trade_grade_table(front: pd.DataFrame, grades: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    A trade grade table with grouped headers: front's columns (already named
    for display) under a blank parent, then each group's columns from grades,
    which shares front's index. Returns the table and its column_config.

    Streamlit takes no column_config by name for grouped columns, so the
    formats are keyed by position, and position 0 is the index even when it
    is hidden.
    """
    parts, header, formats = [front], [("", c) for c in front.columns], {}
    for group, cols in TRADE_GRADE_GROUPS:
        for key, label, fmt in cols:
            if fmt:
                formats[len(header) + 1] = st.column_config.NumberColumn(format=fmt)
            parts.append(grades[key].rename(label))
            header.append((group, label))
    table = pd.concat(parts, axis=1)
    table.columns = pd.MultiIndex.from_tuples(header)
    return table, formats


def show_trade_grades(table: pd.DataFrame, pics: list[str] | None = None,
                      scroll: bool = False) -> None:
    """
    A table from trade_grade_table, drawn as a sortable Broadcast table with
    its group labels as a header row. The grades are signed, green up and
    red down, and sort by their raw values. pics, one per row, go beside the
    first Manager or Team column; without them a Manager column gets the
    manager's helmet.
    """
    from style import esc, helmet_url, html_table, who_cell

    fmts = {(g, label): f.replace("%", "{:") + "}" if f else None
            for g, cols in TRADE_GRADE_GROUPS for _, label, f in cols}
    keys = list(table.columns)
    name_col = next((k for k in keys if k[0] == "" and k[1] in ("Manager", "Team")), None)
    if pics is None and name_col and name_col[1] == "Manager":
        pics = [helmet_url(m) for m in table[name_col]]

    rows = []
    for i, (_, r) in enumerate(table.iterrows()):
        cells = []
        for k in keys:
            v = r[k]
            if k in fmts and isinstance(v, (int, float, np.number)) and not pd.isna(v):
                f = fmts[k]
                text = f.format(v) if f else f"{int(v)}"
                tone = "wa-pos" if f and v > 0 else ("wa-neg" if f and v < 0 else "")
                cells.append((f'<span class="{tone}">{text}</span>' if tone else text, "", float(v)))
            elif k == name_col and pics is not None:
                cells.append((who_cell(pics[i], str(v)), "", str(v)))
            else:
                cells.append(esc("—" if pd.isna(v) else str(v)))
        rows.append(cells)
    columns = [(k[1], "num" if k in fmts else "") for k in keys]
    groups, prev = [], None
    for k in keys:
        if groups and k[0] == prev:
            groups[-1] = (prev, groups[-1][1] + 1)
        else:
            groups.append((k[0], 1))
            prev = k[0]
    html_table(columns, rows, compact=True, scroll=scroll, groups=groups)


TRADE_GRADE_NOTE = """
Reading the table: Trade analysis based on change to the named manager's
performance, and does not consider how it worked out for the manager on the
other side of trades. Weeks that manager held at least one player received in
it are counted.

- **Up-Even-Down**. Trades that increased, didn't change, or decreased the
  optimal lineup score.
- **Optimal Lineup Change** The best lineup the roster could have started with
  the trade, minus the best it could have started without it. What the trade did
  for the roster, not affected by start/sit decisions. **These columns represent
  trade value.**
- **Actual Starting Lineup Change:** Points actually scored minus the expected
  score without the trade. Unlike Optimal Lineup, this does account for
  Start/Sit decisions. **These columns represent real impact.**
- **Total** is over all weeks traded for players were held. **Per Week** divides
  by the weeks held, so an early trade and a late trade can be compared. **Per
  Game Played** counts only weeks where traded for players were healthy and not
  on bye, so missed games don't look like a bad trade decision.
- **Wins Created and Losses Caused:** Games won that would have been lost
  without the trade, and vice versa, against the opponent's actual score.
  Includes playoffs.
- **Expected Wins Added:** cumulative increase or decrease in your odds of
  winning as a result of trades. Basically ignores your actual matchup, looks at
  what you scored, what you would have scored w/o the trade, everyone else's
  score across the league, and how your scores compare.

Hypothetical lineups if the trade had not been made are based on the assumption
the manager would have started the player on the bench (or given away in the
trade) with the highest ppg up to that point in place of the traded for
player(s).

Trade data goes back to 2018 and is updated each week.
"""
