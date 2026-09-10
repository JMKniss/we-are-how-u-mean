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
        st.sidebar.caption("⚠️ At least one must be shown — defaulting to Manager.")
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
