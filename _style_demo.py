"""
Style demo - not part of the app, and deleted once the restyle lands. The
reference for it: the look the user chose, Broadcast in the Classic palette,
built on real data so every piece can be copied from here.

Run it with the theme flags, so the real app's .streamlit/config.toml stays
untouched until the restyle:

    streamlit run _style_demo.py --server.port 8504 --theme.base light
        --theme.primaryColor "#d50a0a" --theme.baseRadius none
        --theme.font "Roboto Condensed:https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@400;700&display=swap"
        --theme.headingFont "Saira Condensed:https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;800&display=swap"
        --theme.sidebar.backgroundColor "#111111" --theme.sidebar.secondaryBackgroundColor "#222222"
        --theme.sidebar.textColor "#ffffff" --theme.sidebar.primaryColor "#ffcc00"

Those flags are the [theme] and [theme.sidebar] sections the real
config.toml should get.

The look, Broadcast / Classic - a TV lower-third:
  - colours: black #111111 (banner, cards, table headers, bars), yellow
    #ffcc00 (labels, tags, rank numbers, bar values, banner underline), red
    #d50a0a (card edges, header underline, the leading bar, playoff cut line)
  - fonts: Saira Condensed for headings and numbers, Roboto Condensed for text
  - square corners; slanted right edges on cards and the yellow section tags
  - charts: horizontal bars, black, value printed inside in yellow, the leader
    in red with white text, no axis, title in condensed caps
  - tables: custom HTML where looks matter (rank in a black box with yellow
    number, team image, manager over team name, W/L form boxes, red dashed
    playoff line), native st.dataframe where sorting matters
Rejected on the way: Gridiron, Prime Time and other looks; every other
palette, including black-and-yellow variants (lemon, amber, yellow banner,
all-black page, hazard stripes, other third colours).

Team images - the rule:
  - the current season: the team's own ESPN logo, or the helmet where it will
    not load
  - every past season, and All-Time always: the manager's helmet, never an
    old team logo
ESPN's uploaded logos sit behind the league login (401 without the ESPN_S2
and SWID cookies), and an old season's are often deleted outright (404), so
the real app must download the current season's logos at build time and
keep them, not hotlink. Here they are fetched live and inlined.

The helmet is the user's own assets/Helmet_Logo.jpg, repainted per manager
by helmet() below: shell and facemask recoloured with their shading kept,
background made transparent. Colours are in HELMETS: a manager's favourite
NFL team where he has one, otherwise a plain solid colour with a white or
black facemask. Not pastel. The helmet is only the picture - it is not the
manager's colour anywhere else.

Headshots and NFL logos come from ESPN's public image CDN by id
(HEADSHOT, NFL_LOGO below).
"""
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis.standings import combined_standings
from branding import _mark_uri, page_icon
from config import CURRENT_SEASON
from data.espn_client import get_manager_map, get_matchups_df

SEASON = CURRENT_SEASON
HEADSHOT = "https://a.espncdn.com/i/headshots/nfl/players/full/{}.png"
NFL_LOGO = "https://a.espncdn.com/i/teamlogos/nfl/500/{}.png"

st.set_page_config(page_title="Style demo", page_icon=page_icon(), layout="wide")


# ---------------------------------------------------------------- images
# (shell, facemask, favourite team). A manager with a favourite team wears its
# colours; the rest get a plain, solid colour with a white or black facemask.
HELMETS = {
    "Jason": ("#003594", "#ffa300", "Rams"),
    "Tyler": ("#0b2265", "#8f969b", "Giants"),
    "Scott": ("#5a1414", "#ffb612", "Commanders"),
    "Brian": ("#fb4f14", "#111111", "Bengals"),
    "Johnny": ("#c8102e", "#ffffff", None),   # red
    "Tim": ("#00843d", "#ffffff", None),      # green
    "Kevin": ("#ffb612", "#111111", None),    # gold
    "David": ("#4f2683", "#ffffff", None),    # purple
    "Matt": ("#111111", "#ffffff", None),     # black
    "JT": ("#a5acaf", "#111111", None),       # silver
}
HELMET_SRC = "assets/Helmet_Logo.jpg"
SHELL_BASE = (162, 56, 70)    # the source shell's red
MASK_BASE = (52, 36, 47)      # the source facemask's dark purple


@st.cache_data
def helmet(manager, size=256):
    """
    assets/Helmet_Logo.jpg with the shell and facemask repainted. Each pixel
    keeps its shading: darker than the source colour scales the new colour
    down, lighter blends it toward white, so highlights and shadows survive.
    The facemask is told apart from the black outlines by its slight purple,
    and from the shell's dark edges by having little red in it. White, black
    and the grey padding are left alone. The white background is flooded to
    transparent from the corners.
    """
    import base64
    import io

    import numpy as np
    from PIL import Image, ImageDraw

    shell_hex, mask_hex, _ = HELMETS.get(manager, ("#7a7f8a", "#2b2b2b", None))
    im = Image.open(HELMET_SRC).convert("RGB")
    im.thumbnail((size, size), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    shell = (r >= g) & (r >= b) & (r - np.minimum(g, b) > 18) & (sat > 0.08) & (mx > 90)
    mask = ((mx > 22) & (mx <= 95) & (r - g > 7) & (r - g < 30) & (b - g > 4) & (r - b < 15)
            & ~shell)

    def paint(sel, base, target):
        lb = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
        t = np.array([int(target[i:i + 2], 16) for i in (1, 3, 5)], float)
        dark = t * np.minimum(lum / lb, 1)[..., None]
        light = t + (255 - t) * np.clip((lum - lb) / (255 - lb), 0, 1)[..., None]
        shade = np.where((lum > lb)[..., None], light, dark)
        a[sel] = shade[sel]

    paint(shell, SHELL_BASE, shell_hex)
    paint(mask, MASK_BASE, mask_hex)
    out = Image.fromarray(a.clip(0, 255).astype(np.uint8)).convert("RGBA")
    w, h = out.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(out, xy, (255, 255, 255, 0), thresh=40)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@st.cache_data
def current_logos():
    """This season's uploaded logos, inlined. A team whose logo will not load is left out."""
    import base64
    import os

    import requests
    from dotenv import load_dotenv
    from espn_api.football import League

    load_dotenv(".env")
    cookies = {"espn_s2": os.getenv("ESPN_S2"), "SWID": os.getenv("SWID")}
    out = {}
    try:
        teams = League(722346, CURRENT_SEASON, espn_s2=cookies["espn_s2"], swid=cookies["SWID"]).teams
    except Exception:
        return out
    for t in teams:
        try:
            r = requests.get(t.logo_url, cookies=cookies, timeout=15)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "image/png").split(";")[0].replace("jpg", "jpeg")
            out[t.team_id] = f"data:{ctype};base64," + base64.b64encode(r.content).decode()
        except Exception:
            pass
    return out


def team_image(season, team_id, manager):
    """The current season shows the team's own logo; every other season, and All-Time, the helmet."""
    if season == CURRENT_SEASON:
        return current_logos().get(team_id) or helmet(manager)
    return helmet(manager)


# ---------------------------------------------------------------- data
@st.cache_data
def load():
    m = get_matchups_df(SEASON)
    m = m[~m["is_playoff"]]
    mgr = get_manager_map(SEASON)
    s = combined_standings(m).reset_index(drop=True)
    s["manager"] = s["team_id"].map(mgr)
    s["form"] = s["team_id"].map(m.sort_values("week").groupby("team_id")["outcome"]
                                  .apply(lambda x: list(x.tail(5))))
    s["weekly"] = s["team_id"].map(m.sort_values("week").groupby("team_id")["score"].apply(list))

    b = pd.read_csv("data/archive/boxscores.csv")
    b = b[(b["season"] == SEASON) & b["week"].isin(m["week"].unique()) & b["is_active_slot"]]
    mvp = (b.groupby(["team_id", "player_id", "player_name", "position", "pro_team"])["points"]
            .sum().reset_index().sort_values("points", ascending=False)
            .groupby("team_id").head(1).set_index("team_id"))
    s = s.join(mvp, on="team_id")
    return s, int(m["week"].max()), mgr


S, LAST_WEEK, MGR = load()
S["logo"] = [team_image(SEASON, t, m) for t, m in zip(S["team_id"], S["manager"])]
S["helmet"] = S["manager"].map(helmet)
S["headshot"] = S["player_id"].map(lambda p: HEADSHOT.format(int(p)))
S["nfl_logo"] = S["pro_team"].map(lambda t: NFL_LOGO.format(str(t).lower()))
MARK = _mark_uri()
LEADER = S.iloc[0]
PF_LEADER = S.loc[S["points_for"].idxmax()]
MVP = S.loc[S["points"].idxmax()]


def img(src, cls):
    if not isinstance(src, str) or not src:
        return f'<span class="{cls} blank"></span>'
    return f'<img class="{cls}" src="{html.escape(src)}" onerror="this.style.visibility=\'hidden\'">'


def ink_on(hex_colour):
    """Black or white, whichever reads on this background."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#111111" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff"


# ---------------------------------------------------------------- classic
# Broadcast, Classic palette: black bars, yellow highlight, red accent.
BLACK, YELLOW, RED = "#111111", "#ffcc00", "#d50a0a"
HEAD, BODY = "Saira Condensed", "Roboto Condensed"

_m = get_matchups_df(SEASON)
_m = _m[~_m["is_playoff"]]
BEST = _m.loc[_m["score"].idxmax()]

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;800&family=Roboto+Condensed:wght@400;700&display=swap');
.bc {{ color:#111; font-family:'{BODY}',sans-serif; }}
.bc .banner {{ display:flex; align-items:center; gap:16px; padding:14px 20px; background:{BLACK}; color:#fff;
               border-bottom:6px solid {YELLOW}; }}
.bc .banner img {{ height:58px; }}
.bc .kicker {{ font-size:.82rem; letter-spacing:.1em; text-transform:uppercase; color:{YELLOW}; }}
.bc .title {{ font-family:'{HEAD}',sans-serif; font-size:2.3rem; line-height:1; text-transform:uppercase;
              letter-spacing:.02em; font-weight:800; }}
.bc .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:14px 0 6px; }}
.bc .card {{ padding:10px 14px; display:flex; gap:12px; align-items:center; background:{BLACK}; color:#fff;
             border-left:6px solid {RED}; clip-path:polygon(0 0,100% 0,95% 100%,0 100%); }}
.bc .card .pic {{ width:50px; height:50px; object-fit:contain; flex:none; }}
.bc .label {{ font-size:.7rem; letter-spacing:.08em; text-transform:uppercase; color:{YELLOW}; }}
.bc .value {{ font-family:'{HEAD}',sans-serif; font-size:1.7rem; font-weight:800; line-height:1.05; }}
.bc .sub {{ font-size:.8rem; opacity:.85; }}
.bc .tag {{ font-family:'{HEAD}',sans-serif; font-size:1.2rem; text-transform:uppercase; letter-spacing:.04em;
            font-weight:800; background:{YELLOW}; color:#111; display:inline-block;
            padding:2px 26px 2px 12px; margin:6px 0 8px; clip-path:polygon(0 0,100% 0,90% 100%,0 100%); }}
.bc table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
.bc th {{ text-align:left; font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; padding:8px 10px;
          color:#fff; background:{BLACK}; border-bottom:3px solid {RED}; font-family:'{HEAD}',sans-serif; }}
.bc td {{ padding:6px 10px; border-bottom:1px solid #e2e2e2; vertical-align:middle; }}
.bc tbody tr:nth-child(even) {{ background:#f5f5f5; }}
.bc tr.cut td {{ border-bottom:2px dashed {RED}; }}
.bc .cutlabel {{ font-size:.72rem; color:{RED}; letter-spacing:.06em; margin-top:3px; }}
.bc .rank {{ display:inline-block; min-width:26px; text-align:center; font-weight:800; padding:1px 4px;
             font-family:'{HEAD}',sans-serif; background:{BLACK}; color:{YELLOW}; }}
.bc .who {{ display:flex; align-items:center; gap:10px; }}
.bc .tlogo {{ width:44px; height:38px; object-fit:contain; flex:none; }}
.bc .team {{ font-size:.78rem; opacity:.65; }}
.bc .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.bc td:last-child {{ white-space:nowrap; }}
.bc .dot {{ display:inline-block; width:16px; height:16px; line-height:16px; font-size:.62rem; text-align:center;
            color:#fff; margin-right:2px; font-weight:700; }}
.bc .dot.W {{ background:#1a8f4b; }} .bc .dot.L {{ background:{RED}; }}
.bc .head {{ width:54px; height:40px; object-fit:cover; object-position:top; background:#eee; }}
.bc .nfl {{ width:26px; height:26px; }}
.bc .bar {{ background:#e6e6e6; height:8px; width:90px; display:inline-block; vertical-align:middle; margin-right:6px; }}
.bc .bar span {{ display:block; height:8px; background:{BLACK}; }}
"""


def broadcast_chart(df, value, label, title):
    """The Broadcast bar chart: black bars, yellow values, the leader in red."""
    order = df.sort_values(value)
    names, vals = order[label].tolist(), order[value].tolist()
    top = len(vals) - 1
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", text=[f"{v:,.0f}" for v in vals],
        textposition="inside", insidetextanchor="end",
        marker=dict(color=[RED if i == top else BLACK for i in range(len(vals))], line=dict(width=0)),
        textfont=dict(color=["#fff" if i == top else YELLOW for i in range(len(vals))], size=16, family=HEAD)))
    fig.update_layout(
        height=44 * len(vals) + 60, margin=dict(l=10, r=10, t=46, b=4), bargap=0.15,
        showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        title=dict(text=f"<b>{title.upper()}</b>", x=0, xanchor="left",
                   font=dict(family=HEAD, size=22, color="#111")),
        font=dict(family=BODY, color="#111", size=14),
        xaxis=dict(visible=False), yaxis=dict(automargin=True, ticksuffix="  "))
    return fig


def standings_html():
    rows = []
    for i, r in S.iterrows():
        dots = "".join(f'<span class="dot {o}">{o}</span>' for o in r["form"])
        cut = ' class="cut"' if i == 3 else ""
        rows.append(
            f'<tr{cut}><td><span class="rank">{i + 1}</span></td>'
            f'<td><div class="who">{img(r["logo"], "tlogo")}<div><b>{r["manager"]}</b><br>'
            f'<span class="team">{html.escape(r["team_name"])}</span></div></div></td>'
            f'<td><b>{int(r["total_wins"])}-{int(r["total_losses"])}</b></td>'
            f'<td>{int(r["wins"])}-{int(r["losses"])}</td>'
            f'<td class="num">{r["points_for"]:,.1f}</td><td class="num">{r["points_against"]:,.1f}</td>'
            f'<td>{dots}</td></tr>')
    return ('<div class="bc"><div class="tag">Standings</div><table><thead><tr><th>#</th><th>Manager</th>'
            '<th>Total</th><th>H2H</th><th class="num">PF</th><th class="num">PA</th><th>Last 5</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            '<div class="cutlabel">- - - playoff line</div></div>')


# ---------------------------------------------------------------- page
st.html(f"<style>{CSS}</style>")
if MARK:
    st.logo(MARK, size="large")

with st.sidebar:
    st.selectbox("Season", [SEASON, SEASON - 1, SEASON - 2], key="season")
    st.checkbox("Show manager names", value=True, key="mgr")
    st.checkbox("Show team names", value=True, key="team")
    st.caption("The sidebar is themed too: black, with the condensed fonts.")

mark = f'<img src="{MARK}">' if MARK else ""
best_logo = S.loc[S["team_id"] == BEST.team_id, "logo"].iloc[0]
st.html(f"""
<div class="bc">
  <div class="banner">{mark}<div>
    <div class="kicker">{SEASON} season · week {LAST_WEEK}</div>
    <div class="title">We Are How U Mean</div></div></div>
  <div class="cards">
    <div class="card">{img(LEADER.logo, "pic")}<div><div class="label">Best record</div>
      <div class="value">{int(LEADER.total_wins)}-{int(LEADER.total_losses)}</div><div class="sub">{LEADER.manager}</div></div></div>
    <div class="card">{img(PF_LEADER.logo, "pic")}<div><div class="label">Points for</div>
      <div class="value">{PF_LEADER.points_for:,.0f}</div><div class="sub">{PF_LEADER.manager}</div></div></div>
    <div class="card">{img(best_logo, "pic")}<div><div class="label">Best week</div>
      <div class="value">{BEST.score:.1f}</div><div class="sub">{MGR[BEST.team_id]}, week {BEST.week}</div></div></div>
    <div class="card">{img(MVP.headshot, "pic")}<div><div class="label">Top player</div>
      <div class="value">{MVP.points:.0f}</div><div class="sub">{MVP.player_name}</div></div></div>
  </div>
</div>""")

tab_home, tab_img, tab_native = st.tabs(["Standings", "Team images", "Native widgets"])

with tab_home:
    st.html(standings_html())
    left, right = st.columns(2, gap="large")
    with left:
        st.plotly_chart(broadcast_chart(S, "points_for", "manager", "Points for"), theme=None,
                        config={"displayModeBar": False}, key="pf")
    with right:
        avg = S.assign(avg=S["points_for"] / LAST_WEEK)
        st.plotly_chart(broadcast_chart(avg.nlargest(5, "avg"), "avg", "manager", "Points per week, top five"),
                        theme=None, config={"displayModeBar": False}, key="ppw")

with tab_img:
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        rows = "".join(
            f'<tr><td><span class="rank">{i + 1}</span></td>'
            f'<td><div class="who">{img(r["logo"], "tlogo")}<div><b>{r["manager"]}</b><br>'
            f'<span class="team">{html.escape(r["team_name"])}</span></div></div></td>'
            f'<td><span class="bar"><span style="width:{r["total_win_pct"] * 100:.0f}%"></span></span>'
            f'{r["total_win_pct"]:.0%}</td>'
            f'<td><div class="who">{img(r["headshot"], "head")}{img(r["nfl_logo"], "nfl")}<div>'
            f'<b>{html.escape(r["player_name"])}</b><br><span class="team">'
            f'{r["position"]} · {r["points"]:.1f} pts</span></div></div></td></tr>'
            for i, r in S.iterrows())
        st.html(f'<div class="bc"><div class="tag">Current season</div>'
                f'<table><thead><tr><th>#</th><th>Team</th><th>Win %</th><th>Team MVP</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>')
        st.caption("Each team's ESPN logo where it loads; the manager's helmet where it does not.")
    with c2:
        rows = "".join(
            f'<tr><td><div class="who">{img(helmet(m), "tlogo")}<b>{m}</b></div></td>'
            f'<td>{team or "-"}</td></tr>'
            for m, (_, _, team) in sorted(HELMETS.items(), key=lambda kv: (kv[1][2] is None, kv[0])))
        st.html(f'<div class="bc"><div class="tag">Past seasons and All-Time</div>'
                f'<table><thead><tr><th>Manager</th><th>Favourite team</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>')

with tab_native:
    st.caption("Streamlit's own widgets, coloured by the theme rather than by CSS. "
               "They keep sorting, fullscreen and the rest.")
    st.subheader("Metric tiles")
    cols = st.columns(4)
    for col, (_, r) in zip(cols, S.head(4).iterrows()):
        w = r["weekly"]
        col.metric(r["manager"], f"{w[-1]:.1f}", f"{w[-1] - w[-2]:+.1f} vs last week",
                   border=True, chart_data=w, chart_type="bar")

    st.subheader("Native table with images")
    df = pd.DataFrame({
        "": S["logo"], "Manager": S["manager"], "Team": S["team_name"],
        "Record": S["total_wins"].astype(int).astype(str) + "-" + S["total_losses"].astype(int).astype(str),
        "Win %": S["total_win_pct"], "PF": S["points_for"], "Weekly": S["weekly"],
        "MVP": S["headshot"], "Player": S["player_name"],
    })
    st.dataframe(df, hide_index=True, row_height=46, column_config={
        "": st.column_config.ImageColumn(width="small"),
        "Win %": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "PF": st.column_config.NumberColumn(format="%.1f"),
        "Weekly": st.column_config.BarChartColumn("Weekly scores"),
        "MVP": st.column_config.ImageColumn(width="small"),
    })

    st.subheader("Badges, selectors, buttons")
    b = st.columns(5)
    b[0].badge("Clinched", icon=":material/verified:", color="green")
    b[1].badge("Eliminated", icon=":material/block:", color="red")
    b[2].badge("On the bubble", icon=":material/trending_flat:", color="orange")
    b[3].badge("Hot streak", icon=":material/local_fire_department:", color="yellow")
    b[4].badge("Champion", icon=":material/emoji_events:", color="yellow")
    st.segmented_control("View", ["H2H", "Median", "Combined"], default="Combined", key="seg")
    st.pills("Managers", sorted(MGR.values()), selection_mode="multi", key="pills")
    st.button("A button", type="primary")
