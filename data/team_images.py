"""
Team pictures: each manager's helmet, and the current season's ESPN logos.
Build-time only - the server never runs this, it serves the files it writes.

    python -m data.team_images --helmets         after changing HELMETS
    python -m data.team_images --logos 2026      what weekly_update.py does

The rule for which picture a page shows is in style.team_image(): the current
season shows the team's own logo where there is one, every past season and
All-Time show the manager's helmet. Old logos are never used - ESPN deletes
many of them (404), and a past season was played under the manager, not under
whatever avatar the team wore that year.

Both land in static/, which Streamlit serves at app/static/. They are files
rather than base64 in the page because an inlined image is re-sent on every
rerun of every page, about 350KB for a ten-helmet table, where a file is
fetched once and kept by the browser.

Helmets are pre-rendered rather than recoloured on request, so the server does
no image work and each helmet is a file in git that can be looked at. The
source is assets/Helmet_Logo.jpg (2253x1916): its shell and facemask are
repainted with their shading kept, the white background made transparent, then
the result shrunk to SIZE and quantized to a 64-colour palette - about a fifth
of the size of a full-colour PNG at no visible cost at 40px.

Logos need the ESPN cookies (an uploaded logo answers 401 without them), which
is the other reason they are fetched here and not by the site. A logo that
will not download keeps the file from the last good run, and a failed fetch
never fails the weekly update: the page falls back to the helmet.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
HELMET_DIR = STATIC / "helmets"
SOURCE = ROOT / "assets" / "Helmet_Logo.jpg"
SIZE = 128            # shown at about 40px, so this is already 3x for sharp screens
COLOURS = 64

# (shell, facemask, favourite team). A manager with a favourite NFL team wears
# its colours. The rest get a plain colour, leaning slightly earthy and muted -
# basic colours, not pastel and not neon. The helmet colour is only the
# picture: it is never the manager's colour anywhere else on the site.
# Adding a favourite team is one line here, then --helmets.
HELMETS = {
    "Jason": ("#003594", "#ffa300", "Rams"),
    "Tyler": ("#0b2265", "#8f969b", "Giants"),
    "Scott": ("#5a1414", "#ffb612", "Commanders"),
    "Brian": ("#fb4f14", "#111111", "Bengals"),
    "Johnny": ("#a63a32", "#ffffff", None),        # brick red
    "Tim": ("#2f6b45", "#ffffff", None),           # forest green
    "Kevin": ("#c4962e", "#111111", None),         # mustard
    "David": ("#5e3f6e", "#ffffff", None),         # plum
    "Matt": ("#2a2a2a", "#ffffff", None),          # charcoal
    "JT": ("#7d858c", "#111111", None),            # slate
    "Mikey": ("#101820", "#a71930", "Falcons"),
    "Mitchell": ("#6f6a3a", "#ffffff", None),      # olive
    "B. Pisarcik": ("#8a6a45", "#111111", None),   # tan
}
UNKNOWN = ("#7a7f8a", "#2b2b2b", None)

SHELL_BASE = (162, 56, 70)    # the source shell's red
MASK_BASE = (52, 36, 47)      # the source facemask's dark purple


def slug(manager: str) -> str:
    """'B. Pisarcik' -> 'b-pisarcik'. The file name for a manager's helmet."""
    return re.sub(r"[^a-z0-9]+", "-", manager.lower()).strip("-") or "unknown"


def _hex(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def render_helmet(shell_hex: str, mask_hex: str):
    """
    The source helmet repainted. Each pixel keeps its shading: darker than the
    source colour scales the new colour down, lighter blends it toward white,
    so highlights and shadows survive. The facemask is told apart from the
    black outlines by its slight purple, and from the shell's dark edges by
    having little red in it. White, black and the grey padding are left alone.
    The white background is flooded to transparent from the corners.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    im = Image.open(SOURCE).convert("RGB")
    im.thumbnail((SIZE * 3, SIZE * 3), Image.LANCZOS)   # recolour above size, shrink after
    a = np.asarray(im).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    shell = (r >= g) & (r >= b) & (r - np.minimum(g, b) > 18) & (sat > 0.08) & (mx > 90)
    mask = ((mx > 22) & (mx <= 95) & (r - g > 7) & (r - g < 30) & (b - g > 4)
            & (r - b < 15) & ~shell)

    def paint(sel, base, target):
        lb = 0.299 * base[0] + 0.587 * base[1] + 0.114 * base[2]
        t = np.array(_hex(target), float)
        dark = t * np.minimum(lum / lb, 1)[..., None]
        light = t + (255 - t) * np.clip((lum - lb) / (255 - lb), 0, 1)[..., None]
        a[sel] = np.where((lum > lb)[..., None], light, dark)[sel]

    paint(shell, SHELL_BASE, shell_hex)
    paint(mask, MASK_BASE, mask_hex)
    out = Image.fromarray(a.clip(0, 255).astype(np.uint8)).convert("RGBA")
    w, h = out.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(out, xy, (255, 255, 255, 0), thresh=40)
    out.thumbnail((SIZE, SIZE), Image.LANCZOS)
    return out


def _save_small(im, path: Path) -> int:
    """Write a 64-colour PNG, transparency kept. Returns the byte count."""
    from PIL import Image

    q = im.convert("RGBA").quantize(colors=COLOURS, method=Image.Quantize.FASTOCTREE)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    q.save(buf, "PNG", optimize=True)
    path.write_bytes(buf.getvalue())
    return len(buf.getvalue())


def write_helmets() -> None:
    HELMET_DIR.mkdir(parents=True, exist_ok=True)
    for manager, (shell, mask, _) in {**HELMETS, "unknown": UNKNOWN}.items():
        n = _save_small(render_helmet(shell, mask), HELMET_DIR / f"{slug(manager)}.png")
        print(f"  {manager:<12} {n / 1024:5.1f} KB")


def logo_dir(season: int) -> Path:
    return STATIC / "teams" / str(season)


def fetch_logos(season: int) -> int:
    """
    Download this season's team logos into static/teams/<season>/<team_id>.png.
    Returns how many failed. Never raises: a logo is decoration, and the
    weekly update must not fail over one.
    """
    try:
        import requests
        from espn_api.football import League
        from PIL import Image

        from config import ESPN_S2, SWID
    except Exception as e:                      # noqa: BLE001
        print(f"  logos skipped: {e}")
        return 0

    cookies = {"espn_s2": ESPN_S2, "SWID": SWID} if ESPN_S2 and SWID else {}
    try:
        teams = League(league_id=722346, year=season,
                       **({"espn_s2": ESPN_S2, "swid": SWID} if cookies else {})).teams
    except Exception as e:                      # noqa: BLE001
        print(f"  logos skipped, could not reach ESPN: {e}")
        return 0

    failed = 0
    for t in teams:
        dest = logo_dir(season) / f"{t.team_id}.png"
        try:
            r = requests.get(t.logo_url, cookies=cookies, timeout=20)
            r.raise_for_status()
            data = r.content
            if "svg" in r.headers.get("content-type", "") or data.lstrip()[:4] in (b"<svg", b"<?xm"):
                # ESPN's own logo packs are SVG, which PIL cannot open.
                import resvg_py
                data = bytes(resvg_py.svg_to_bytes(svg_string=data.decode("utf-8"), width=SIZE * 2))
            im = Image.open(io.BytesIO(data))
            im.seek(0)                          # an animated logo keeps its first frame
            im = im.convert("RGBA")
            im.thumbnail((SIZE, SIZE), Image.LANCZOS)
            old = dest.read_bytes() if dest.exists() else None
            n = _save_small(im, dest)
            changed = "" if old == dest.read_bytes() else "  (new)"
            print(f"  team {t.team_id:<3} {n / 1024:5.1f} KB{changed}")
        except Exception as e:                  # noqa: BLE001
            failed += 1
            kept = "kept the last one" if dest.exists() else "helmet instead"
            print(f"  team {t.team_id:<3} FAILED ({type(e).__name__}): {kept}")
    return failed


def main() -> int:
    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser(description="Write helmet and team logo images into static/.")
    ap.add_argument("--helmets", action="store_true", help="re-render every helmet")
    ap.add_argument("--logos", type=int, metavar="SEASON", help="download that season's logos")
    args = ap.parse_args()
    if not (args.helmets or args.logos):
        ap.error("say --helmets, --logos SEASON, or both")
    if args.helmets:
        print("helmets:")
        write_helmets()
    if args.logos:
        print(f"logos {args.logos}:")
        fetch_logos(args.logos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
