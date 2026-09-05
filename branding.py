"""
League branding: the browser icon and the title block.

Kept in one place because the browser icon has to be identical on all nine
pages. Each page calls its own st.set_page_config, and page_icon there
overrides whatever app.py set - which is why the pages used to show nine
different emoji in the tab as you moved between them.

Everything degrades to the football emoji when the logo file is missing, so
the app runs the same whether or not assets/ has been filled in.
"""
import base64
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"

# The full square logo, used for the browser tab.
LOGO = ASSETS / "logo.png"
# Just the figure, for setting inline in the title between the words. Falls
# back to the full logo, which reads oddly there because the logo already
# contains the words, but is better than a blank.
LOGO_MARK = ASSETS / "logo-mark.png"

FALLBACK_ICON = "🏈"


def page_icon():
    """What every page passes to set_page_config as page_icon."""
    return str(LOGO) if LOGO.exists() else FALLBACK_ICON


@lru_cache(maxsize=4)
def _data_uri(path_str: str) -> str:
    p = Path(path_str)
    if not p.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def _mark_uri() -> str:
    for candidate in (LOGO_MARK, LOGO):
        if candidate.exists():
            return _data_uri(str(candidate))
    return ""


def title_html(subtitle: str = "") -> str:
    """
    The league name with the figure set between the words, then a subtitle.

    Falls back to plain text when there is no image, so a missing file costs
    the picture and nothing else.
    """
    uri = _mark_uri()
    mark = (
        f'<img src="{uri}" alt="" '
        f'style="height:1.15em;vertical-align:-0.18em;margin:0 0.12em;">'
        if uri else " "
    )
    return f"""
<div style="line-height:1.1;margin:0 0 0.6rem 0;">
  <div style="font-size:2.2rem;font-weight:700;letter-spacing:-0.01em;">
    We Are{mark}How U Mean
  </div>
  {f'<div style="font-size:1.05rem;opacity:0.65;margin-top:0.15rem;">{subtitle}</div>'
   if subtitle else ''}
</div>
"""
