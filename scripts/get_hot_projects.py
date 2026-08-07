#!/usr/bin/env python3
"""
Hot projects fetcher (GitHub + Gitee + GitLab + Libraries.io)

Env vars:
- GITHUB_TOKEN (required)
- GITEE_TOKEN (optional)
- GITEE_API_URL (optional, default https://gitee.com/api/v5)
- GITLAB_TOKEN (optional)
- GITLAB_API_URL (optional, default https://gitlab.com/api/v4)
- LIBRARIES_IO_KEY (optional)
- TOP_N (default 20)
- DAYS (default 7)
- KEYWORDS (optional, comma-separated)
- ORGS (optional, comma-separated for GitHub)
- GITEE_ORGS (optional, comma-separated for Gitee)
- EXTRA_REPOS (optional, comma-separated; prefix with gitee: for gitee entries)
- EXTRA_REPOS_URL (optional, URL to plaintext list owner/repo, use gitee:owner/repo for gitee)
- PER_SOURCE (default 50)
- SORT (default "stars")  # "stars" or "pushed"
- VERBOSE (optional, 1 to enable)
"""
import os
import sys
import requests
import datetime
import time
import json
import textwrap
from urllib.parse import urlparse

# ---- config / env ----
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    print("GITHUB_TOKEN is required (set by Actions).", file=sys.stderr)
    sys.exit(1)

GITEE_TOKEN = os.getenv("GITEE_TOKEN", "").strip()
GITEE_API = os.getenv("GITEE_API_URL", "https://gitee.com/api/v5").rstrip("/")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "").strip()
GITLAB_API = os.getenv("GITLAB_API_URL", "https://gitlab.com/api/v4").rstrip("/")
LIBRARIES_IO_KEY = os.getenv("LIBRARIES_IO_KEY", "").strip()

TOP_N = int(os.getenv("TOP_N", "20"))
DAYS = int(os.getenv("DAYS", "7"))
KEYWORDS = [k.strip() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
ORGS = [o.strip() for o in os.getenv("ORGS", "").split(",") if o.strip()]
GITEE_ORGS = [o.strip() for o in os.getenv("GITEE_ORGS", "").split(",") if o.strip()]
EXTRA_REPOS = [r.strip() for r in os.getenv("EXTRA_REPOS", "").split(",") if r.strip()]
EXTRA_REPOS_URL = os.getenv("EXTRA_REPOS_URL", "").strip()
PER_SOURCE = int(os.getenv("PER_SOURCE", "50"))
SORT = os.getenv("SORT", "stars").lower()
VERBOSE = bool(os.getenv("VERBOSE"))

GITHUB_API = "https://api.github.com"

headers_github = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"token {GITHUB_TOKEN}",
    "User-Agent": "hot-projects-action"
}
headers_gitee = {"Accept": "application/json", "User-Agent": "hot-projects-action"}
if GITEE_TOKEN:
    headers_gitee["Authorization"] = f"token {GITEE_TOKEN}"
headers_gitlab = {"Accept": "application/json", "User-Agent": "hot-projects-action"}
if GITLAB_TOKEN:
    headers_gitlab["Authorization"] = f"Bearer {GITLAB_TOKEN}"
headers_libs = {"Accept": "application/json", "User-Agent": "hot-projects-action"}

API_SLEEP_ON_ERROR = 2

def debug(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)

def fetch_url_lines(url):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return [ln.strip() for ln in r.text.splitlines() if ln.strip()]
    except Exception as e:
        print(f"Warning: failed to fetch EXTRA_REPOS_URL {url}: {e}", file=sys.stderr)
        return []

# ---------- GitHub helpers ----------
def search_github(query, max_results):
    results = []
    per_page = 100 if max_results > 100 else max_results
    page = 1
    while len(results) < max_results:
        params = {
            "q": query,
            "per_page": per_page,
            "page": page,
            "sort": "stars" if "stars" in query or SORT == "stars" else "updated",
            "order": "desc"
        }
        debug("SEARCH", params, "query:", query)
        resp = requests.get(f"{GITHUB_API}/search/repositories", params=params, headers=headers_github, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            results.extend(items)
            # break if no more pages
            if len(items) < per_page:
                break
            page += 1
            # avoid hitting rate limits too aggressively
            time.sleep(0.2)
        else:
            print(f"GitHub search error {resp.status_code}: {resp.text}", file=sys.stderr)
            # transient backoff
            time.sleep(API_SLEEP_ON_ERROR)
            break
    return results[:max_results]

def get_repo(full_name):
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full_name}", headers=headers_github, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"Warning: failed to fetch repo {full_name}: {resp.status_code} {resp.text}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Warning: exception fetching repo {full_name}: {e}", file=sys.stderr)
        return None

def collect_candidates():
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)).date().isoformat()
    candidates = {}  # full_name -> repo dict (dedup)
    # 1) Keywords
    for kw in KEYWORDS:
        # If keyword contains spaces or special chars, keep it quoted if needed.
        # We search for pushed since and the keyword (which matches name/desc/readme)
        query = f'pushed:>{since} {kw}'
        debug("Running keyword query:", query)
        items = search_github(query, PER_SOURCE)
        for r in items:
            candidates[r.get("full_name")] = r
        debug(f"Found {len(items)} for keyword '{kw}'")

    # 2) Orgs
    for org in ORGS:
        query = f'org:{org} pushed:>{since}'
        debug("Running org query:", query)
        items = search_github(query, PER_SOURCE)
        for r in items:
            candidates[r.get("full_name")] = r
        debug(f"Found {len(items)} for org '{org}'")

    # 3) Extra repos provided directly
    for repo_full in EXTRA_REPOS:
        debug("Adding extra repo:", repo_full)
        r = get_repo(repo_full)
        if r:
            candidates[r.get("full_name")] = r

    # 4) Extra repos from URL
    if EXTRA_REPOS_URL:
        lines = fetch_url_lines(EXTRA_REPOS_URL)
        for ln in lines:
            if "/" in ln:
                r = get_repo(ln)
                if r:
                    candidates[r.get("full_name")] = r

    return list(candidates.values())

def sort_and_select(repos):
    # normalize fields and sort
    def key_fn(r):
        stars = r.get("stargazers_count", 0) or 0
        pushed = r.get("pushed_at") or ""
        # primary sort: stars or pushed depending on SORT
        if SORT == "pushed":
            # use pushed datetime string directly (ISO8601), larger = newer
            return (pushed, stars)
        else:
            return (stars, pushed)
    reverse = True  # desc
    sorted_repos = sorted(repos, key=key_fn, reverse=reverse)
    return sorted_repos[:TOP_N]

def format_markdown(repos, since, today):
    """
    Produce a more readable Markdown output:
    - A compact summary table (Rank, Repo, Stars, Forks, Last Push, Topics)
    - A detailed section with numbered entries: description, full topics, and metadata
    """
    wrapper = textwrap.TextWrapper(width=100)
    lines = []
    lines.append(f"# Hot projects for week ending {today} (based on pushed:>{since})\n")

    # Summary table header
    lines.append("## Summary\n")
    lines.append("| # | Repo | Stars | Forks | Last Push | Topics |")
    lines.append("|---:|---|---:|---:|---|---|")
    for i, r in enumerate(repos, start=1):
        name = r.get("full_name") or ""
        html_url = r.get("html_url") or ""
        stars = r.get("stargazers_count", 0)
        forks = r.get("forks_count", 0)
        pushed = (r.get("pushed_at") or "")[:19].replace("T", " ") if r.get("pushed_at") else ""
        topics = ", ".join((r.get("topics") or [])[:5]) if isinstance(r.get("topics"), list) else ""
        lines.append(f"| {i} | [{name}]({html_url}) | {stars} | {forks} | {pushed} | {topics} |")

    # Details section
    lines.append("\n## Details\n")
    for i, r in enumerate(repos, start=1):
        name = r.get("full_name") or ""
        html_url = r.get("html_url") or ""
        stars = r.get("stargazers_count", 0)
        forks = r.get("forks_count", 0)
        pushed = (r.get("pushed_at") or "")[:19].replace("T", " ") if r.get("pushed_at") else ""
        topics_list = r.get("topics") or []
        topics = ", ".join(topics_list) if isinstance(topics_list, list) else str(topics_list)
        desc = (r.get("description") or "").strip()
        # Wrap description for readability
        desc_wrapped = "\n".join(wrapper.fill(par) for par in desc.splitlines()) if desc else "(no description)"

        lines.append(f"### {i}. [{name}]({html_url})\n")
        lines.append(f"- Stars: **{stars}**  ")
        lines.append(f"- Forks: {forks}  ")
        lines.append(f"- Last push: {pushed}  ")
        if topics:
            lines.append(f"- Topics: {topics}  ")
        lines.append("\n**Description**:\n")
        lines.append(desc_wrapped)
        lines.append("\n---\n")

    return "\n".join(lines)


def main():
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)).date().isoformat()
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    os.makedirs("results", exist_ok=True)

    print("Collecting candidates... (this may take some seconds)")
    repos = collect_candidates()
    if not repos:
        print("No repositories found with current filters.", file=sys.stderr)
        # still create an empty report
    else:
        print(f"Collected {len(repos)} unique candidate repositories")

    final = sort_and_select(repos)
    print(f"Selected top {len(final)} repositories (TOP_N={TOP_N})")

    md = format_markdown(final, since, today)
    md_path = os.path.join("results", f"hot-projects-{today}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    json_path = os.path.join("results", f"hot-projects-{today}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)

    print(f"Wrote {md_path} and {json_path}")

if __name__ == "__main__":
    main()
