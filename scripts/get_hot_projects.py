#!/usr/bin/env python3
import os
import requests
import datetime
import sys

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    print("GITHUB_TOKEN is required (set by Actions).", file=sys.stderr)
    sys.exit(1)

TOP_N = int(os.getenv("TOP_N", "20"))
DAYS = int(os.getenv("DAYS", "7"))
QUERY_EXTRA = os.getenv("QUERY", "").strip()  # e.g. "language:Python" or "org:apache"

since = (datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)).date().isoformat()

# Basic query: repos with recent pushes, sorted by stars
query_parts = [f"pushed:>{since}"]
if QUERY_EXTRA:
    query_parts.append(QUERY_EXTRA)
query = " ".join(query_parts)

params = {
    "q": query,
    "sort": "stars",
    "order": "desc",
    "per_page": TOP_N
}

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"token {GITHUB_TOKEN}",
    "User-Agent": "hot-projects-action"
}

resp = requests.get("https://api.github.com/search/repositories", params=params, headers=headers)
if resp.status_code != 200:
    print("GitHub API error:", resp.status_code, resp.text, file=sys.stderr)
    sys.exit(1)

items = resp.json().get("items", [])[:TOP_N]

out_dir = "results"
os.makedirs(out_dir, exist_ok=True)
today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
out_path = os.path.join(out_dir, f"hot-projects-{today}.md")

with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"# Hot projects for week ending {today} (based on pushed:>{since})\n\n")
    f.write("| # | Repo | Stars | Forks | Description |\n")
    f.write("|---:|---|---:|---:|---|\n")
    for i, r in enumerate(items, start=1):
        name = r.get("full_name")
        stars = r.get("stargazers_count", 0)
        forks = r.get("forks_count", 0)
        desc = (r.get("description") or "").replace("\n", " ").replace("|", "\\|")
        html_url = r.get("html_url")
        f.write(f"| {i} | [{name}]({html_url}) | {stars} | {forks} | {desc} |\n")

print(f"Wrote {out_path} with {len(items)} repositories.")
