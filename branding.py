"""
League branding: the browser icon and the league mark.

Kept in one place because the browser icon has to be identical on all nine
pages. Each page calls its own st.set_page_config, and page_icon there
overrides whatever app.py set - which is why the pages used to show nine
different emoji in the tab as you moved between them.

The mark - the figure on its blue/red field - sits in every page's banner
(style.page_header). It is served from static/ rather than inlined, so the
browser fetches it once instead of with every page render.

Everything degrades when a file is missing: the football emoji for the tab,
and a banner without the picture.
"""
from pathlib import Path

ROOT = Path(__file__).parent

# The full square logo, used for the browser tab.
LOGO = ROOT / "assets" / "logo.png"
# The field stays. Dropping it leaves a white figure on transparency, which is
# invisible against a white page - the MLB mark works precisely because the
# figure is a hole in a block of colour rather than a shape in its own right.
MARK = ROOT / "static" / "brand" / "logo-mark.png"

FALLBACK_ICON = "🏈"


def page_icon():
    """What every page passes to set_page_config as page_icon."""
    return str(LOGO) if LOGO.exists() else FALLBACK_ICON


def mark_url() -> str:
    """The mark's address for an <img>, or "" when the file is missing."""
    return "app/static/brand/logo-mark.png" if MARK.exists() else ""
