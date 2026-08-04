#!/usr/bin/env python3
"""
Hot projects fetcher (GitHub + Gitee)

Env vars:
- GITHUB_TOKEN (required for GitHub API)
- GITEE_TOKEN (optional for Gitee API)
- GITEE_API_URL (optional, default https://gitee.com/api/v5)
- TOP_N (default 20)
- DAYS (default 7)
- KEYWORDS (optional, comma-separated)
- ORGS (optional, comma-separated for GitHub)
- GITEE_ORGS (optional, comma-separated for Gitee)
- EXTRA_REPOS (optional, comma-separated, prefix with `gitee:` for gitee entries e.g. gitee:owner/repo)
- EXTRA_REPOS_URL (optional, URL to plaintext list owner/repo (prefix with gitee: if needed))
- PER_SOURCE (default 50)  # how many per keyword/org to fetch
- SORT (default "stars")    # "stars" or "pushed"
- VERBOSE (optional, 1 to enable)
"""
import os
import sys
import requests
import datetime
import time
import json

# Config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    print("GITHUB_TOKEN is required (set by Actions).", file=sys.stderr)
    sys.exit(1)
GITEE_TOKEN = os.getenv("GITEE_TOKEN", "").strip()
GITEE_API = os.getenv("GITEE_API_URL", "https://gitee.com/api/v5").rstrip("/")
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
headers_gitee = {
    "Accept": "application/json",
    "User-Agent": "hot-projects-action"
}
if GITEE_TOKEN:
    # Gitee token is passed as access_token param later or as header 'Private-Token' depending on API;
    # we'll append as query param 'access_token' for search endpoints.
    headers_gitee["Authorization"] = f"token {GITEE_TOKEN}"

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
            "sort": "stars" if SORT == "stars" else "updated",
            "order": "desc"
        }
        debug("GitHub search:", params)
        resp = requests.get(f"{GITHUB_API}/search/repositories", params=params, headers=headers_github, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            results.extend(items)
            if len(items) < per_page:
                break
            page += 1
            time.sleep(0.2)
        else:
            print(f"GitHub search error {resp.status_code}: {resp.text}", file=sys.stderr)
            break
    return results[:max_results]

def get_github_repo(full_name):
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full_name}", headers=headers_github, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"Warning: failed to fetch GitHub repo {full_name}: {resp.status_code}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Warning: exception fetching GitHub repo {full_name}: {e}", file=sys.stderr)
        return None

# ---------- Gitee helpers ----------
def search_gitee(q, max_results):
    """Gitee search: GET /search/repositories?q=...&per_page=...&page=..."""
    results = []
    per_page = 100 if max_results > 100 else max_results
    page = 1
    while len(results) < max_results:
        params = {"q": q, "per_page": per_page, "page": page}
        if GITEE_TOKEN:
            params["access_token"] = GITEE_TOKEN
        debug("Gitee search:", params)
        try:
            resp = requests.get(f"{GITEE_API}/search/repositories", params=params, headers=headers_gitee, timeout=30)
        except Exception as e:
            print(f"Gitee search exception: {e}", file=sys.stderr)
            break
        if resp.status_code == 200:
            data = resp.json()
            # Gitee may return list or dict with 'data'
            items = data.get("data") if isinstance(data, dict) and "data" in data else data
            if not items:
                break
            results.extend(items)
            if len(items) < per_page:
                break
            page += 1
            time.sleep(0.2)
        else:
            print(f"Gitee search error {resp.status_code}: {resp.text}", file=sys.stderr)
            break
    return results[:max_results]

def get_gitee_repo(full_name):
    """full_name like owner/repo"""
    try:
        owner, repo = full_name.split("/", 1)
    except Exception:
        print(f"Invalid gitee repo name: {full_name}", file=sys.stderr)
        return None
    params = {}
    if GITEE_TOKEN:
        params["access_token"] = GITEE_TOKEN
    try:
        resp = requests.get(f"{GITEE_API}/repos/{owner}/{repo}", params=params, headers=headers_gitee, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"Warning: failed to fetch Gitee repo {full_name}: {resp.status_code}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Warning: exception fetching Gitee repo {full_name}: {e}", file=sys.stderr)
        return None

# ---------- normalization ----------
def normalize_github_repo(r):
    return {
        "platform": "github",
        "full_name": r.get("full_name"),
        "html_url": r.get("html_url"),
        "stargazers_count": r.get("stargazers_count", 0) or 0,
        "forks_count": r.get("forks_count", 0) or 0,
        "description": r.get("description") or "",
        "pushed_at": r.get("pushed_at") or r.get("updated_at") or "",
        "topics": r.get("topics") if isinstance(r.get("topics"), list) else []
    }

def normalize_gitee_repo(r):
    # Gitee repo fields vary; attempt to extract canonical fields
    owner = (r.get("owner") or {}).get("login") or (r.get("owner") or {}).get("name") or r.get("namespace") or ""
    name = r.get("path") or r.get("name") or r.get("full_name") or ""
    full_name = f"{owner}/{name}" if owner and name else r.get("full_name") or r.get("path_with_namespace") or name
    html_url = r.get("html_url") or r.get("url") or r.get("html_url")
    # Gitee star/fork field names: may be 'stargazers_count' or 'watchers_count' or 'watchers'
    stars = r.get("stargazers_count") or r.get("watchers_count") or r.get("watchers") or 0
    forks = r.get("forks_count") or r.get("forks") or 0
    pushed = r.get("pushed_at") or r.get("updated_at") or r.get("last_activity_at") or r.get("updated_at")
    # topics on gitee might be in 'topics' or 'tag_list'
    topics = r.get("topics") or r.get("tag_list") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    return {
        "platform": "gitee",
        "full_name": full_name,
        "html_url": html_url,
        "stargazers_count": stars or 0,
        "forks_count": forks or 0,
        "description": r.get("description") or "",
        "pushed_at": pushed or "",
        "topics": topics if isinstance(topics, list) else []
    }

# ---------- collector ----------
def collect_candidates():
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)).date().isoformat()
    candidates = {}  # key: platform:full_name -> normalized repo
    # 1) GitHub keywords
    for kw in KEYWORDS:
        q = f'pushed:>{since} {kw}'
        debug("GitHub keyword query:", q)
        items = search_github(q, PER_SOURCE)
        for r in items:
            nr = normalize_github_repo(r)
            key = f"github:{nr.get('full_name')}"
            candidates[key] = nr
        debug(f"GitHub found {len(items)} for '{kw}'")

    # 2) GitHub orgs
    for org in ORGS:
        q = f'org:{org} pushed:>{since}'
        debug("GitHub org query:", q)
        items = search_github(q, PER_SOURCE)
        for r in items:
            nr = normalize_github_repo(r)
            key = f"github:{nr.get('full_name')}"
            candidates[key] = nr
        debug(f"GitHub found {len(items)} for org '{org}'")

    # 3) Gitee keywords
    for kw in KEYWORDS:
        q = f'{kw} pushed:>{since}'  # Gitee search treats q as free text; keep pushed term helps narrow results
        debug("Gitee keyword query:", q)
        items = search_gitee(q, PER_SOURCE)
        for r in items:
            nr = normalize_gitee_repo(r)
            key = f"gitee:{nr.get('full_name')}"
            candidates[key] = nr
        debug(f"Gitee found {len(items)} for '{kw}'")

    # 4) Gitee orgs
    for org in GITEE_ORGS:
        q = f'owner:{org}'
        debug("Gitee org query:", q)
        items = search_gitee(q, PER_SOURCE)
        for r in items:
            nr = normalize_gitee_repo(r)
            key = f"gitee:{nr.get('full_name')}"
            candidates[key] = nr
        debug(f"Gitee found {len(items)} for org '{org}'")

    # 5) EXTRA_REPOS (could include gitee: prefix)
    for repo in EXTRA_REPOS:
        if repo.startswith("gitee:"):
            fullname = repo.split("gitee:", 1)[1]
            r = get_gitee_repo(fullname)
            if r:
                nr = normalize_gitee_repo(r)
                candidates[f"gitee:{nr.get('full_name')}"] = nr
        else:
            r = get_github_repo(repo)
            if r:
                nr = normalize_github_repo(r)
                candidates[f"github:{nr.get('full_name')}"] = nr

    # 6) EXTRA_REPOS_URL
    if EXTRA_REPOS_URL:
        lines = fetch_url_lines(EXTRA_REPOS_URL)
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            if ln.startswith("gitee:"):
                fullname = ln.split("gitee:", 1)[1]
                r = get_gitee_repo(fullname)
                if r:
                    nr = normalize_gitee_repo(r)
                    candidates[f"gitee:{nr.get('full_name')}"] = nr
            elif "/" in ln:
                # assume GitHub by default if no prefix
                r = get_github_repo(ln)
                if r:
                    nr = normalize_github_repo(r)
                    candidates[f"github:{nr.get('full_name')}"] = nr

    return list(candidates.values())

# ---------- sort / select / output ----------
def sort_and_select(repos):
    def key_fn(r):
        stars = r.get("stargazers_count", 0) or 0
        pushed = r.get("pushed_at") or ""
        if SORT == "pushed":
            return (pushed, stars)
        else:
            return (stars, pushed)
    reverse = True
    sorted_repos = sorted(repos, key=key_fn, reverse=reverse)
    return sorted_repos[:TOP_N]

def format_markdown(repos, since, today):
    lines = []
    lines.append(f"# Hot projects for week ending {today} (based on pushed:>{since})\n")
    lines.append("| # | Platform | Repo | Stars | Forks | Last Push | Description | Topics |")
    lines.append("|---:|---|---|---:|---:|---|---|---|")
    for i, r in enumerate(repos, start=1):
        platform = r.get("platform", "github")
        name = r.get("full_name")
        stars = r.get("stargazers_count", 0)
        forks = r.get("forks_count", 0)
        desc = (r.get("description") or "").replace("\n", " ").replace("|", "\\|")
        html_url = r.get("html_url") or ""
        pushed = (r.get("pushed_at") or "")[:19].replace("T", " ") if r.get("pushed_at") else ""
        topics = ", ".join(r.get("topics", [])) if isinstance(r.get("topics", list)) else ""
        lines.append(f"| {i} | {platform} | [{name}]({html_url}) | {stars} | {forks} | {pushed} | {desc} | {topics} |")
    return "\n".join(lines)

def main():
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)).date().isoformat()
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    os.makedirs("results", exist_ok=True)

    print("Collecting candidates from GitHub and Gitee...")
    repos = collect_candidates()
    if not repos:
        print("No repositories found with current filters.", file=sys.stderr)
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
