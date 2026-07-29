# Pontoon Saloon — Sales Rep Dashboard

Live sales dashboard built **hourly** from GoHighLevel (read-only) and deployed to
GitHub Pages for embedding in GHL/Stannect.

- `refresh.py` — pulls users + Sales Pipeline opportunities, builds `dashboard.html`.
- `dashboard_template.html` — the UI (data injected at build time).
- `activity.py` — optional heavier Conversations pull (rep messaging); not used by the hourly build.
- `.github/workflows/refresh.yml` — hourly build + Pages deploy.

`dashboard.html` and all data are git-ignored — no data or token is ever committed.

## Activate
1. Settings → Secrets and variables → Actions → new secret `GHL_PIT` = GHL Private Integration Token (read-only: Opportunities + Users View).
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions → run the workflow. Embed the printed `…github.io` URL in a GHL custom/iframe widget.

Config via env: `GHL_PIT` (required), `GHL_LOCATION_ID`, `GHL_PIPELINE_ID`.
