# assets

Source artwork. Files the browser loads live in `static/` instead, which
Streamlit serves at `app/static/` and the browser keeps after the first fetch.
Anything inlined as base64 is re-sent with every page render, by every viewer.

| File | Used for | Notes |
|---|---|---|
| `logo.png` | Browser tab icon, every page | The full logo with the words. 256×256 — the tab renders it at 16px, so there is no point shipping more. `set_page_config` takes it as a path. |
| `logo-figure.png` | Unused fallback | The figure with the field removed. White, so invisible on the light page. |
| `Helmet_Logo.jpg` | Source for every manager's helmet | 2253×1916. Never served. `data/team_images.py` recolours it per manager into `static/helmets/`. |

In `static/`:

| Path | What | Written by |
|---|---|---|
| `brand/logo-mark.png` | The figure on its blue/red field, in every page's banner. 256×256. | by hand |
| `helmets/<manager>.png` | Each manager's helmet, 128px, 64 colours, about 5KB. | `python -m data.team_images --helmets` |
| `teams/<season>/<team_id>.png` | The current season's ESPN logos, same size. | `weekly_update.py` |

`logo.png` and `logo-mark.png` were resized from the originals (1517² and
2048², 371KB and 3.6MB). To replace either, drop in a square PNG under the
same name, resized to 256×256 first.
