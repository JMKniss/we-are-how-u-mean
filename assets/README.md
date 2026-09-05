# assets

Drop the league logo here. Nothing else needs changing — `branding.py` picks
it up, and every page falls back to the football emoji while it is absent.

| File | Used for | Notes |
|---|---|---|
| `logo.png` | Browser tab icon, on every page | Square. Keep it small — 256×256 is plenty; the tab renders it at 16px. |
| `logo-mark.png` | The figure set between the words in the page title | Optional. Just the silhouette, transparent background. Without it the title falls back to `logo.png`, which reads oddly there because that image already contains the words. |
