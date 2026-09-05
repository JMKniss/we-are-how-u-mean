# assets

League artwork. `branding.py` reads these; everything falls back to the
football emoji if they go missing.

| File | Used for | Notes |
|---|---|---|
| `logo.png` | Browser tab icon, every page | The full logo with the words. 256×256 — the tab renders it at 16px, so there is no point shipping more. |
| `logo-mark.png` | Set inline in the page title, between "We Are" and "How U Mean" | The figure on its blue/red field. 256×256. |
| `logo-figure.png` | Unused fallback | The same figure with the field removed. Kept for a dark background only: the figure is white, so on the light theme it is invisible. |

Both `logo.png` and `logo-mark.png` were resized here from the originals
(1517² and 2048², 371KB and 3.6MB). The mark especially had to shrink — it is
base64'd into the HTML of every page render, so its file size is paid on every
single page load, by every viewer.

To replace any of them: drop in a new PNG under the same name, square, and
resize to 256×256 first.
