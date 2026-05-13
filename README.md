# Claude Code Changelog Visualizer

Static page that visualizes the [Claude Code public changelog](https://code.claude.com/docs/en/changelog) — KPI cards, release timeline bar chart, calendar heatmap, and a filterable release list.

The page is rebuilt **daily at 13:00 Asia/Shanghai (05:00 UTC)** by a GitHub Actions workflow that fetches the changelog, parses it, and deploys to GitHub Pages.

## One-time setup

1. **Create a new repo** on GitHub (public or private — Pages works for both on Free for public repos, requires Pro/Team for private).

2. **Push this folder as the repo root.**
   ```bash
   cd claude-code-changelog-viz
   git init -b main
   git add .
   git commit -m "Initial visualizer"
   git remote add origin git@github.com:<you>/<repo>.git
   git push -u origin main
   ```

3. **Enable GitHub Pages**, source = **GitHub Actions**:
   `Settings → Pages → Build and deployment → Source: GitHub Actions`

4. The push to `main` triggers the first build. Watch it in **Actions**. When the workflow finishes, your team URL is at the top of that page (looks like `https://<you>.github.io/<repo>/`).

That's it — from here on, the cron runs daily and updates the page automatically.

## Repo layout

```
claude-code-changelog-viz/
├── template.html              # The visual design (with `<script src="data.js">` placeholder)
├── scripts/build.py           # Fetches changelog, parses it, injects data into template
├── .github/workflows/update.yml  # Daily cron + Pages deploy
└── README.md
```

The build writes `dist/index.html` (deployed page) plus `dist/data.json` (raw data, in case anyone wants to consume it directly).

## Local development

```bash
python3 scripts/build.py
open dist/index.html
```

No dependencies — pure Python stdlib.

## Changing the cron time

Edit the `cron:` line in `.github/workflows/update.yml`. GitHub Actions uses **UTC**. Some quick references:

| Your local time (daily) | Cron (UTC) |
|---|---|
| 13:00 Asia/Shanghai / Singapore (UTC+8) | `0 5 * * *` |
| 13:00 Europe/London (UTC+0/+1)          | `0 13 * * *` (winter) / `0 12 * * *` (summer) |
| 13:00 America/New_York (UTC-5/-4)        | `0 18 * * *` (winter) / `0 17 * * *` (summer) |
| 13:00 America/Los_Angeles (UTC-8/-7)     | `0 21 * * *` (winter) / `0 20 * * *` (summer) |

> GitHub's scheduled workflows can drift a few minutes under load — if exact timing matters, use a self-hosted runner or an external scheduler.

## Manual rebuild

In the repo's **Actions** tab, pick "Build & deploy changelog visualizer" and click **Run workflow**.

## Troubleshooting

- **Empty page / "0 releases":** the upstream HTML structure changed. Run `python3 scripts/build.py` locally to see the parser output; tweak `parse_releases()` in `scripts/build.py`.
- **Pages 404 right after enabling:** wait for the first workflow run to complete and re-check.
- **Private repo Pages disabled:** GitHub Pages on private repos requires Pro/Team/Enterprise. Either make the repo public or upgrade the plan.
