# hot-projects
热点项目搜素
# hot-projects

This repository contains a GitHub Actions workflow that runs weekly and finds "hot" GitHub repositories (default: repos with pushes in the last 7 days, sorted by stars).

Configuration (via workflow env or repository secrets):

- TOP_N: number of results (default 20)
- DAYS: lookback window in days (default 7)
- QUERY: extra search qualifiers, e.g. "language:Python" or "org:apache"

How it works

- The action runs every Monday at 09:00 UTC by default.
- It calls the GitHub Search API and writes a Markdown report to `results/hot-projects-YYYY-MM-DD.md`, then commits the report back to the repository.

Manual run

- Go to Actions -> Weekly Hot Projects -> Run workflow

Notes

- Ensure repository Settings -> Actions -> Workflow permissions is set to "Read and write permissions" so the action can commit back to the repo.
