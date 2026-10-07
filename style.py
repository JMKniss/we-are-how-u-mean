"""
The Broadcast look: a TV lower third in black, yellow and red.

Native widgets are themed in .streamlit/config.toml - fonts, colours, square
corners, the black sidebar, and a light and a dark theme. This module is
everything config.toml cannot reach: the page banner, the section tags, the
hand-built tables and cards, the award badges, team pictures, and the bar
chart. app.py calls apply() once, before any page, so every page gets the CSS.

The palette, used the same way everywhere:
  black  #111111  banner, cards, table headers, rank boxes
  yellow #ffcc00  labels, section tags, rank numbers, bar values
  red    #d50a0a  card edges, header underlines, the leading bar, playoff line

Light and dark from one stylesheet. The site follows each viewer's system
setting and can be switched from the menu, and nothing on the page says which
theme is showing - Streamlit sets no attribute, and st.context.theme can be
wrong on first load. So the CSS never asks. The black pieces are black in
both. Everything else takes its greys from the text colour Streamlit has
already set: rules and zebra rows are color-mix() of currentColor, which is
dark grey on the light page and light grey on the dark one. Black pieces carry
a ring of currentColor at low strength, invisible on white and just enough to
lift them off the near-black page. Team pictures get the same, so a black
helmet or a dark logo keeps its edge in dark mode.

Charts take Streamlit's theme (text colours, and chartCategoricalColors for
multi-series), which switches with the page. Only a colour named in the
figure stays fixed, so the bar chart's bars are a charcoal that reads on both.

Team pictures - the rule:
  - the current season: the team's own ESPN logo, or the manager's helmet
    where the logo would not download
  - every past season, and All-Time always: the manager's helmet
Both are files under static/, written by data/team_images.py at build time.
"""
from __future__ import annotations

import html
import numbers
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from branding import mark_url
from config import CURRENT_SEASON
from data.team_images import logo_dir, slug

BLACK, YELLOW, RED = "#111111", "#ffcc00", "#d50a0a"
GREEN = "#1a8f4b"
# The bar colour: black reads as black on white, and still separates from
# the dark theme's #0f0f10 page as a charcoal block.
BAR = "#34343a"
HEAD, BODY = "Anton", "Barlow Semi Condensed"
STATIC = Path(__file__).parent / "static"

esc = html.escape

CSS = f"""
<style>
/* ---- native elements ---- */
[data-testid="stMain"] [data-testid="stHeading"] h3, .wa-tag {{
  display: inline-block; background: {YELLOW}; color: #111; text-transform: uppercase;
  letter-spacing: .03em; font-size: 1.3rem; line-height: 1.25; padding: .12em 1.7em .08em .5em;
  clip-path: polygon(0 0, 100% 0, calc(100% - .9em) 100%, 0 100%); margin-bottom: .2rem;
}}
[data-testid="stMain"] [data-testid="stHeading"] h3 a {{ display: none; }}
.wa-tag {{ font-family: '{HEAD}', sans-serif; display: inline-flex; align-items: center; gap: .35em; margin: .5rem 0 .3rem; }}
[data-testid="stMetricValue"] {{ font-family: '{HEAD}', sans-serif; }}
[data-testid="stTab"] p {{ font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
[data-testid="stSidebarNav"] a span {{ font-weight: 600; }}
/* Anton is tight in mixed case: at chart-title sizes "Score Distribution by
   Team" ran together. Capitals with a little spacing, a size up, as the bar
   chart's own titles are set. */
[data-testid="stMain"] h4 {{ text-transform: uppercase; letter-spacing: .04em; }}
.stPlotlyChart .gtitle {{ text-transform: uppercase; letter-spacing: .05em; font-size: 18px !important; }}

/* ---- the banner at the top of every page ---- */
.wa-banner {{
  display: flex; align-items: center; gap: 16px; padding: 12px 18px; margin-bottom: 8px;
  background: {BLACK}; color: #fff; border-bottom: 6px solid {YELLOW};
  /* The banner's own text colour is white, so this ring is white: lost on the
     light page, a faint edge on the dark one. */
  box-shadow: 0 0 0 1px color-mix(in srgb, currentColor 14%, transparent);
}}
.wa-banner img {{ height: 54px; width: 54px; flex: none; }}
.wa-kicker {{ font-size: .8rem; letter-spacing: .12em; text-transform: uppercase; color: {YELLOW}; font-weight: 600; }}
.wa-title {{ font-family: '{HEAD}', sans-serif; font-size: 2.3rem; line-height: 1.02; text-transform: uppercase;
  letter-spacing: .015em; color: #fff; }}
.wa-sub {{ font-size: .95rem; color: #d6d6d6; margin-top: 2px; }}

/* ---- cards ---- */
.wa-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; margin: 6px 0 12px; }}
.wa-card {{
  display: flex; gap: 12px; align-items: center; min-width: 0; padding: 9px 26px 9px 12px;
  /* The card leaves its own text colour alone, so currentColor here is the
     page's: the mix is pure black on the light page and a lifted charcoal on
     the dark one, where black would sink into the background. */
  background: color-mix(in srgb, currentColor 10%, {BLACK}); border-left: 6px solid {RED};
  clip-path: polygon(0 0, 100% 0, calc(100% - 14px) 100%, 0 100%);
}}
.wa-card .wa-pic {{ width: 48px; height: 44px; }}
.wa-label {{ font-size: .7rem; letter-spacing: .09em; text-transform: uppercase; color: {YELLOW}; font-weight: 600; }}
.wa-value {{ color: #fff; font-family: '{HEAD}', sans-serif; font-size: 1.75rem; line-height: 1.05; font-variant-numeric: tabular-nums; }}
.wa-cardsub {{ font-size: .82rem; color: #d6d6d6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

/* ---- team pictures: a thin edge of the text colour, for dark pictures on the dark page ---- */
.wa-pic {{ object-fit: contain; flex: none;
  filter: drop-shadow(0 0 .6px color-mix(in srgb, currentColor 55%, transparent)); }}
.wa-card .wa-pic, .wa-banner .wa-pic {{ filter: drop-shadow(0 0 .6px rgba(255,255,255,.6)); }}

/* ---- tables ---- */
.wa-tablewrap {{ overflow-x: auto; margin-bottom: 4px; }}
.wa-table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
.wa-table th {{
  text-align: left; font-family: '{HEAD}', sans-serif; font-weight: 400; font-size: .8rem; text-transform: uppercase;
  letter-spacing: .07em; padding: 7px 10px; background: {BLACK}; color: #fff; border-bottom: 3px solid {RED};
  white-space: nowrap;
}}
.wa-table td {{ padding: 6px 10px; border-bottom: 1px solid color-mix(in srgb, currentColor 13%, transparent);
  vertical-align: middle; }}
.wa-table tbody tr:nth-child(even) {{ background: color-mix(in srgb, currentColor 4%, transparent); }}
.wa-table tr.wa-cut td {{ border-bottom: 2px dashed {RED}; }}
.wa-table .wa-num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.wa-table th.wa-num {{ text-align: right; }}
.wa-rank {{ display: inline-block; min-width: 26px; text-align: center; padding: 1px 4px; background: {BLACK};
  color: {YELLOW}; font-family: '{HEAD}', sans-serif; }}
.wa-who {{ display: flex; align-items: center; gap: 10px; min-width: 0; }}
.wa-who .wa-pic {{ width: 42px; height: 36px; }}
.wa-name {{ font-weight: 700; }}
.wa-head {{ width: 44px; height: 32px; object-fit: cover; object-position: top; flex: none;
  background: color-mix(in srgb, currentColor 8%, transparent); }}
.wa-nfl {{ width: 30px; height: 30px; object-fit: contain; flex: none; margin: 0 7px; }}
.wa-team {{ display: block; font-size: .8rem; opacity: .65; }}
.wa-form {{ white-space: nowrap; }}
.wa-dot {{ display: inline-block; width: 17px; height: 17px; line-height: 17px; font-size: .64rem; text-align: center;
  color: #fff; margin-right: 2px; font-weight: 700; }}
.wa-dot.W {{ background: {GREEN}; }} .wa-dot.L {{ background: {RED}; }} .wa-dot.T {{ background: #777; }}
.wa-cutlabel {{ font-size: .74rem; color: {RED}; letter-spacing: .06em; margin: 2px 0 6px; }}
.wa-pos {{ color: {GREEN}; }} .wa-neg {{ color: {RED}; }}
.wa-table.compact td {{ padding: 4px 7px; font-size: .9rem; }}
.wa-table.compact th {{ padding: 6px 7px; }}
.wa-table td.wa-mid, .wa-table th.wa-mid {{ text-align: center; font-variant-numeric: tabular-nums; white-space: nowrap; }}
/* Result tints: translucent, so they sit on either theme's background. */
.wa-table td.wa-w {{ background: rgba(26, 143, 75, .20); }}
.wa-table td.wa-l {{ background: rgba(213, 10, 10, .15); }}
.wa-table td.wa-t {{ background: rgba(255, 204, 0, .22); }}
.wa-table td.wa-self {{ background: color-mix(in srgb, currentColor 9%, transparent); }}
.wa-table td.wa-gold {{ background: rgba(255, 204, 0, .28); font-weight: 700; }}
.wa-table td.wa-strong {{ font-weight: 700; }}
.wa-table td.wa-muted {{ opacity: .55; }}
.wa-scroll {{ max-height: 560px; overflow-y: auto; }}
.wa-scroll .wa-table th {{ position: sticky; top: 0; z-index: 1; }}

/* ---- matchups ---- */
.wa-matchups {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 8px; margin: 4px 0 8px; }}
.wa-match {{ display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 8px;
  padding: 7px 10px; border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  border-left: 5px solid {RED}; }}
.wa-match .wa-side {{ display: flex; align-items: center; gap: 8px; min-width: 0; }}
.wa-match .wa-side.away {{ flex-direction: row-reverse; text-align: right; }}
.wa-match .wa-pic {{ width: 38px; height: 34px; }}
.wa-match .wa-proj {{ font-family: '{HEAD}', sans-serif; font-size: 1.15rem; white-space: nowrap; font-variant-numeric: tabular-nums;
  background: {BLACK}; color: {YELLOW}; padding: 2px 8px; }}
.wa-match .wa-name, .wa-match .wa-team {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

/* ---- badges, with a Material icon or an emoji ---- */
.wa-badge {{ display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; font-size: .8rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: .04em; vertical-align: middle; }}
.wa-badge.gold {{ background: {YELLOW}; color: #111; }}
.wa-badge.red {{ background: {RED}; color: #fff; }}
.wa-badge.green {{ background: {GREEN}; color: #fff; }}
.wa-badge.black {{ background: {BLACK}; color: #fff; }}
.wa-ic {{ font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal; font-size: 1.15em; line-height: 1;
  letter-spacing: normal; text-transform: none; display: inline-block; white-space: nowrap;
  -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga'; }}
.wa-ic.flip {{ transform: rotate(180deg); }}
.wa-emoji {{ font-size: 1.05em; line-height: 1; }}
</style>
"""


def apply() -> None:
    """Inject the stylesheet. app.py calls this once per run, before the page."""
    st.html(CSS)


# ---------------------------------------------------------------- pictures
def helmet_url(manager: str) -> str:
    name = slug(manager)
    if not (STATIC / "helmets" / f"{name}.png").exists():
        name = "unknown"
    return f"app/static/helmets/{name}.png"


@lru_cache(maxsize=64)
def _logo_exists(season: int, team_id: int) -> bool:
    return (logo_dir(season) / f"{team_id}.png").exists()


def team_image(season: int | None, team_id: int | None, manager: str) -> str:
    """
    The picture for a team: this season's logo where there is one, otherwise
    the manager's helmet. Pass season=None for anything spanning seasons
    (All-Time), which always shows the helmet.
    """
    if season == CURRENT_SEASON and team_id is not None and _logo_exists(season, int(team_id)):
        return f"app/static/teams/{season}/{int(team_id)}.png"
    return helmet_url(manager)


# Player headshots and NFL logos come from ESPN's public image CDN, through its
# resizer, so a headshot is about 7KB rather than the 40KB full image. They
# are the one picture not stored here - there are thousands - and one that
# fails to load hides itself rather than showing a broken icon.
HEADSHOT = "https://a.espncdn.com/combiner/i?img=/i/headshots/nfl/players/full/{}.png&w=96&h=70&cb=1"
NFL_LOGO = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500/{}.png&w=64&h=64"


def player_pic(player_id, pro_team=None) -> str:
    """A player's headshot; a team defence (negative id) gets its NFL logo."""
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return ""
    if pid > 0:
        src, cls = HEADSHOT.format(pid), "wa-head"
    elif isinstance(pro_team, str) and pro_team.strip() and pro_team.lower() != "nan":
        src, cls = NFL_LOGO.format(esc(pro_team.strip().lower())), "wa-nfl"
    else:
        return ""
    return (f'<img class="{cls}" src="{src}" alt="" loading="lazy" '
            "onerror=\"this.style.visibility='hidden'\">")


def pic(src: str, cls: str = "wa-pic") -> str:
    return f'<img class="{cls}" src="{esc(src)}" alt="" loading="lazy">'


# ---------------------------------------------------------------- headings
def page_header(title: str, kicker: str = "We Are How U Mean", sub: str = "") -> None:
    """The black banner at the top of every page, with the league mark."""
    mark = mark_url()
    img = f'<img src="{mark}" alt="">' if mark else ""
    sub_html = f'<div class="wa-sub">{esc(sub)}</div>' if sub else ""
    st.html(f'<div class="wa-banner">{img}<div><div class="wa-kicker">{esc(kicker)}</div>'
            f'<div class="wa-title">{esc(title)}</div>{sub_html}</div></div>')


# ---------------------------------------------------------------- badges
# Material icon names, or an emoji. "flip" turns the icon upside down, which
# st.badge cannot do - so these are drawn here rather than with st.badge.
BADGES = {
    "top": ("military_tech", "gold", False),          # top scorer, any season without its own
    "trainer": ("electric_bolt", "gold", False),      # 2026's top scorer: the Pokemon year
    "fascist": ("rocket_launch", "red", True),        # bottom scorer: Team Rocket, crashing
    "sacko": ("🚽", "red", False),                      # Material has no toilet
    "champion": ("trophy", "gold", False),
    "clinched": ("verified", "green", False),
    "eliminated": ("block", "red", False),
}


# The top-scorer award is renamed with each season's theme (TOP_TITLES in
# analysis/vlog.py), and its icon can follow. A season not listed gets "top".
TOP_BADGE = {2026: "trainer"}


def top_badge(season: int | None) -> str:
    return TOP_BADGE.get(season, "top")


def icon_html(kind: str) -> str:
    name, _, flip = BADGES[kind]
    if not name.isascii():
        return f'<span class="wa-emoji">{name}</span>'
    return f'<span class="wa-ic{" flip" if flip else ""}">{name}</span>'


def badge(kind: str, text: str) -> str:
    """An award or status badge as HTML: badge("fascist", "Fascist of the Week")."""
    _, tone, _ = BADGES[kind]
    return f'<span class="wa-badge {tone}">{icon_html(kind)}{esc(text)}</span>'


def tag(text: str, kind: str | None = None) -> None:
    """A yellow section tag, like st.subheader but able to carry a badge icon."""
    icon = icon_html(kind) if kind else ""
    st.html(f'<div><span class="wa-tag">{icon}{esc(text)}</span></div>')


# ---------------------------------------------------------------- cards
def cards(items: list[dict]) -> None:
    """A row of black stat cards. Each item: label, value, sub, and optionally img."""
    out = []
    for c in items:
        img = pic(c["img"]) if c.get("img") else ""
        out.append(f'<div class="wa-card">{img}<div style="min-width:0"><div class="wa-label">{esc(c["label"])}</div>'
                   f'<div class="wa-value">{esc(str(c["value"]))}</div>'
                   f'<div class="wa-cardsub">{esc(c.get("sub", ""))}</div></div></div>')
    st.html(f'<div class="wa-cards">{"".join(out)}</div>')


# ---------------------------------------------------------------- tables
def who_cell(img: str, name: str, team: str = "") -> str:
    """A team picture with the manager's name over the team's."""
    team_html = f'<span class="wa-team">{esc(team)}</span>' if team else ""
    img_html = pic(img) if img else ""
    return f'<div class="wa-who">{img_html}<div><span class="wa-name">{esc(name)}</span>{team_html}</div></div>'


def form_cell(outcomes: list[str]) -> str:
    """Recent results as W/L boxes, oldest first."""
    return "".join(f'<span class="wa-dot {o}">{o}</span>' for o in outcomes if o in ("W", "L", "T"))


def rank_cell(n: int) -> str:
    return f'<span class="wa-rank">{n}</span>'


def html_table(columns: list[tuple[str, str]], rows: list[list], cut_after: int | None = None,
               cut_label: str = "playoff line", compact: bool = False, scroll: bool = False) -> None:
    """
    A Broadcast table. columns are (header, kind) with kind "" (left), "num"
    (right) or "mid" (centred). Each cell is HTML already escaped by the
    caller, or (html, extra_class) to tint it. cut_after draws the red dashed
    playoff line under that many rows. scroll caps a long table's height with
    the header pinned.
    """
    head = "".join(f'<th class="wa-{k}">{esc(h)}</th>' if k else f"<th>{esc(h)}</th>" for h, k in columns)
    body = []
    for i, r in enumerate(rows):
        cls = ' class="wa-cut"' if cut_after and i == cut_after - 1 and len(rows) > cut_after else ""
        cells = []
        for v, (_, k) in zip(r, columns):
            v, extra = v if isinstance(v, tuple) else (v, "")
            names = " ".join(n for n in (f"wa-{k}" if k else "", extra) if n)
            cells.append(f'<td class="{names}">{v}</td>' if names else f"<td>{v}</td>")
        body.append(f"<tr{cls}>{''.join(cells)}</tr>")
    note = (f'<div class="wa-cutlabel">- - - {esc(cut_label)}</div>'
            if cut_after and len(rows) > cut_after else "")
    wrap = "wa-tablewrap wa-scroll" if scroll else "wa-tablewrap"
    st.html(f'<div class="{wrap}"><table class="wa-table{" compact" if compact else ""}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>{note}')


def _fmt(v, f: str | None) -> str:
    if v is None or v is pd.NA or (isinstance(v, numbers.Real) and pd.isna(v)):
        return "—"
    if isinstance(v, numbers.Real) and not isinstance(v, bool):
        if f:
            return f.format(v)
        return f"{v:,}" if isinstance(v, numbers.Integral) else f"{v:,.1f}"
    return esc(str(v))


def frame(df: pd.DataFrame, *, num=(), signed=(), mid=(), fmt: dict | None = None,
          pics: list[str] | None = None, subs: list[str] | None = None, rank: bool = False,
          classes: pd.DataFrame | None = None, cut_after: int | None = None,
          compact: bool = False, scroll: bool = False, pic_col: str | None = None) -> None:
    """
    A DataFrame as a Broadcast table, in the order given.

    num / mid: columns right-aligned / centred. signed: numbers shown with
    their sign, green above zero and red below (also right-aligned). fmt: a
    format string per column ("{:.2f}"); other floats get one decimal.
    pics: a picture per row for the first column (or pic_col), drawn as a
    team picture with subs as the small line under the name; "" for none. rank: a black rank box
    before everything. classes: same shape as df, an extra cell class each
    ("wa-w", "wa-l", "wa-self", "wa-gold"...), or "" for none.
    """
    fmt = fmt or {}
    cols = list(df.columns)
    kinds = [("num" if c in num or c in signed else "mid" if c in mid else "") for c in cols]
    columns = ([("#", "")] if rank else []) + [(str(c), k) for c, k in zip(cols, kinds)]
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        cells = [rank_cell(i + 1)] if rank else []
        for j, c in enumerate(cols):
            v = r[c]
            if c in signed and isinstance(v, numbers.Real) and not pd.isna(v):
                text = (fmt.get(c) or "{:+.1f}").format(v)
                tone = "wa-pos" if v > 0 else ("wa-neg" if v < 0 else "")
                html_ = f'<span class="{tone}">{text}</span>' if tone else text
            elif pics is not None and c == (pic_col or cols[0]):
                html_ = who_cell(pics[i], str(v), subs[i] if subs else "")
            else:
                html_ = _fmt(v, fmt.get(c))
            extra = classes.iloc[i][c] if classes is not None and c in classes.columns else ""
            cells.append((html_, extra) if extra else html_)
        rows.append(cells)
    html_table(columns, rows, cut_after=cut_after, compact=compact, scroll=scroll)


# ---------------------------------------------------------------- charts
def bar_chart(df: pd.DataFrame, value: str, label: str, title: str = "", fmt: str = "{:,.0f}",
              highlight: str = "max") -> go.Figure:
    """
    The Broadcast bar chart: horizontal charcoal bars with the value printed
    inside in yellow, the leader in red with white text, no axis. highlight
    picks the red bar: "max", "min" or None.
    """
    order = df.sort_values(value)
    names, vals = order[label].tolist(), order[value].tolist()
    lead = {"max": len(vals) - 1, "min": 0}.get(highlight)
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", text=[fmt.format(v) for v in vals],
        textposition="inside", insidetextanchor="end", cliponaxis=False,
        marker=dict(color=[RED if i == lead else BAR for i in range(len(vals))], line=dict(width=0)),
        textfont=dict(color=["#ffffff" if i == lead else YELLOW for i in range(len(vals))], size=15, family=HEAD),
        hovertemplate="%{y}: %{x:,.1f}<extra></extra>"))
    fig.update_layout(
        height=36 * len(vals) + (70 if title else 30), margin=dict(l=10, r=10, t=50 if title else 10, b=4),
        bargap=0.16, showlegend=False,
        title=dict(text=title.upper(), x=0, xanchor="left", font=dict(family=HEAD, size=20)) if title else None,
        xaxis=dict(visible=False), yaxis=dict(automargin=True, ticksuffix="  ", showgrid=False))
    return fig


def series_colours() -> list[str]:
    """
    The multi-series colours, in their fixed order: theme.chartCategoricalColors
    from config.toml, so a chart that names its colours uses the same ten as
    one that leaves them to the theme.
    """
    try:
        colours = st.get_option("theme.chartCategoricalColors")
    except Exception:                       # noqa: BLE001
        colours = None
    return list(colours) if colours else ["#2a78d6", "#eb6834", "#1baf7a", "#c98500", "#d55181",
                                          "#008300", "#7a6ad8", "#e34948", "#8c6d46", "#6b7a86"]


# A diverging scale for above/below-zero charts: red, a neutral grey, green.
DIVERGING = [[0, RED], [0.5, "#9a9a9a"], [1, GREEN]]


def show_chart(fig: go.Figure, key: str | None = None) -> None:
    """A chart without Plotly's toolbar, in the site's theme."""
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=key)
