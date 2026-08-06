#!/usr/bin/env python3
# Debuggable hot-projects script: prints progress, counts, and full tracebacks on error.
import os, sys, requests, datetime, time, json, traceback
from urllib.parse import urlparse

# --- env / config ---
# Note: do NOT print tokens below; we only echo whether they exist.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
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
headers_github = {"Accept":"application/vnd.github+json","Authorization":f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else "", "User-Agent":"hot-projects-action"}
headers_gitee = {"Accept":"application/json","User-Agent":"hot-projects-action"}
if GITEE_TOKEN:
    headers_gitee["Authorization"] = f"token {GITEE_TOKEN}"
headers_gitlab = {"Accept":"application/json","User-Agent":"hot-projects-action"}
if GITLAB_TOKEN:
    headers_gitlab["Authorization"] = f"Bearer {GITLAB_TOKEN}"
headers_libs = {"Accept":"application/json","User-Agent":"hot-projects-action"}

API_SLEEP_ON_ERROR = 2

def log(*args, **kwargs):
    print(*args, **kwargs, flush=True)

def debug(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs, flush=True)

def fetch_url_lines(url):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return [ln.strip() for ln in r.text.splitlines() if ln.strip()]
    except Exception as e:
        log(f"Warning: failed to fetch EXTRA_REPOS_URL {url}: {e}")
        return []

# ----------------- GitHub -----------------
def search_github(query, max_results):
    debug(f"[GitHub] search start: q={query!r} max={max_results}")
    results=[]; per_page=100 if max_results>100 else max_results; page=1
    while len(results)<max_results:
        params={"q":query,"per_page":per_page,"page":page,"sort":"stars" if SORT=="stars" else "updated","order":"desc"}
        resp = requests.get(f"{GITHUB_API}/search/repositories", params=params, headers=headers_github, timeout=30)
        if resp.status_code==200:
            d=resp.json(); items=d.get("items",[])
            results.extend(items)
            if len(items)<per_page: break
            page+=1; time.sleep(0.2)
        else:
            log(f"[GitHub] search error {resp.status_code}: {resp.text}")
            time.sleep(API_SLEEP_ON_ERROR)
            break
    debug(f"[GitHub] search done: found {len(results)}")
    return results[:max_results]

def get_github_repo(full_name):
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full_name}", headers=headers_github, timeout=20)
        if resp.status_code==200: return resp.json()
        debug(f"[GitHub] get repo {full_name} status {resp.status_code}")
        return None
    except Exception as e:
        debug(f"[GitHub] get repo exception {e}")
        return None

def normalize_github_repo(r):
    return {"platform":"github","full_name":r.get("full_name"),"html_url":r.get("html_url"),"stargazers_count":r.get("stargazers_count",0) or 0,"forks_count":r.get("forks_count",0) or 0,"description":r.get("description") or "","pushed_at":r.get("pushed_at") or r.get("updated_at") or "","topics":r.get("topics") if isinstance(r.get("topics"),list) else []}

# ----------------- Gitee -----------------
def search_gitee(q, max_results):
    debug(f"[Gitee] search start: q={q!r} max={max_results}")
    results=[]; per_page=100 if max_results>100 else max_results; page=1
    while len(results)<max_results:
        params={"q":q,"per_page":per_page,"page":page}
        if GITEE_TOKEN: params["access_token"]=GITEE_TOKEN
        try:
            resp = requests.get(f"{GITEE_API}/search/repositories", params=params, headers=headers_gitee, timeout=30)
        except Exception as e:
            log(f"[Gitee] search exception: {e}")
            break
        if resp.status_code==200:
            data=resp.json()
            items = data.get("data") if isinstance(data,dict) and "data" in data else data
            results.extend(items)
            if len(items)<per_page: break
            page+=1; time.sleep(0.2)
        else:
            log(f"[Gitee] search error {resp.status_code}: {resp.text}")
            break
    debug(f"[Gitee] search done: found {len(results)}")
    return results[:max_results]

def get_gitee_repo(full_name):
    try:
        owner,repo = full_name.split("/",1)
    except:
        log(f"[Gitee] invalid name {full_name}")
        return None
    params={}
    if GITEE_TOKEN: params["access_token"]=GITEE_TOKEN
    try:
        resp = requests.get(f"{GITEE_API}/repos/{owner}/{repo}", params=params, headers=headers_gitee, timeout=20)
        if resp.status_code==200: return resp.json()
        debug(f"[Gitee] get repo {full_name} status {resp.status_code}")
        return None
    except Exception as e:
        log(f"[Gitee] get repo exception: {e}")
        return None

def normalize_gitee_repo(r):
    owner = (r.get("owner") or {}).get("login") or (r.get("owner") or {}).get("name") or r.get("namespace") or ""
    name = r.get("path") or r.get("name") or r.get("full_name") or ""
    full_name = f"{owner}/{name}" if owner and name else r.get("full_name") or r.get("path_with_namespace") or name
    html_url = r.get("html_url") or r.get("url") or ""
    stars = r.get("stargazers_count") or r.get("watchers_count") or r.get("watchers") or 0
    forks = r.get("forks_count") or r.get("forks") or 0
    pushed = r.get("pushed_at") or r.get("updated_at") or r.get("last_activity_at") or ""
    topics = r.get("topics") or r.get("tag_list") or []
    if isinstance(topics,str): topics=[t.strip() for t in topics.split(",") if t.strip()]
    return {"platform":"gitee","full_name":full_name,"html_url":html_url,"stargazers_count":stars or 0,"forks_count":forks or 0,"description":r.get("description") or "","pushed_at":pushed or "","topics":topics if isinstance(topics,list) else []}

# ----------------- GitLab -----------------
def search_gitlab(q, max_results):
    debug(f"[GitLab] search start: q={q!r} max={max_results}")
    results=[]; per_page=100 if max_results>100 else max_results; page=1
    while len(results)<max_results:
        params={"search":q,"per_page":per_page,"page":page}
        try:
            resp = requests.get(f"{GITLAB_API}/projects", params=params, headers=headers_gitlab, timeout=30)
        except Exception as e:
            log(f"[GitLab] search exception: {e}")
            break
        if resp.status_code==200:
            items = resp.json()
            results.extend(items)
            if len(items)<per_page: break
            page+=1; time.sleep(0.2)
        else:
            log(f"[GitLab] search error {resp.status_code}: {resp.text}")
            break
    debug(f"[GitLab] search done: found {len(results)}")
    return results[:max_results]

def normalize_gitlab_repo(r):
    full_name = r.get("path_with_namespace") or r.get("name_with_namespace") or r.get("path")
    html_url = r.get("web_url") or ""
    stars = r.get("star_count") or r.get("stars") or 0
    forks = r.get("forks_count") or r.get("forks") or 0
    pushed = r.get("last_activity_at") or r.get("last_repository_update_at") or ""
    desc = r.get("description") or ""
    topics = r.get("topics") or []
    return {"platform":"gitlab","full_name":full_name,"html_url":html_url,"stargazers_count":stars or 0,"forks_count":forks or 0,"description":desc,"pushed_at":pushed or "","topics":topics if isinstance(topics,list) else []}

# ----------------- Libraries.io -----------------
def search_librariesio(q, max_results):
    debug(f"[Libraries.io] search start: q={q!r} max={max_results}")
    results=[]; per_page=100 if max_results>100 else max_results; page=1
    while len(results)<max_results:
        params={"q":q,"per_page":per_page,"page":page}
        if LIBRARIES_IO_KEY: params["api_key"]=LIBRARIES_IO_KEY
        try:
            resp = requests.get("https://libraries.io/api/search", params=params, headers=headers_libs, timeout=30)
        except Exception as e:
            log(f"[Libraries.io] exception: {e}")
            break
        if resp.status_code==200:
            items = resp.json()
            results.extend(items)
            if len(items)<per_page: break
            page+=1; time.sleep(0.2)
        else:
            log(f"[Libraries.io] error {resp.status_code}: {resp.text}")
            break
    debug(f"[Libraries.io] search done: found {len(results)}")
    return results[:max_results]

def normalize_librariesio_item(item):
    repo_url = item.get("repository_url") or item.get("homepage") or ""
    owner_repo = ""
    if repo_url:
        p = urlparse(repo_url); host=p.netloc.lower(); path=p.path.strip("/")
        if "github.com" in host and path:
            owner_repo="/".join(path.split("/")[:2])
            return {"platform":"github","full_name":owner_repo,"html_url":repo_url,"stargazers_count":item.get("stars") or 0,"forks_count":item.get("forks") or 0,"description":item.get("description") or "","pushed_at":item.get("repository_created_at") or "","topics":[]}
        if "gitee.com" in host and path:
            owner_repo="/".join(path.split("/")[:2])
            return {"platform":"gitee","full_name":owner_repo,"html_url":repo_url,"stargazers_count":item.get("stars") or 0,"forks_count":item.get("forks") or 0,"description":item.get("description") or "","pushed_at":item.get("repository_created_at") or "","topics":[]}
    return {"platform":"librariesio","full_name":item.get("name") or item.get("project_name") or repo_url,"html_url":repo_url,"stargazers_count":item.get("stars") or 0,"forks_count":item.get("forks") or 0,"description":item.get("description") or "","pushed_at":"","topics":[]}

# ----------------- collector -----------------
def collect_candidates():
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)).date().isoformat()
    candidates = {}
    log(f"Searching since {since}; TOP_N={TOP_N}; PER_SOURCE={PER_SOURCE}")
    if not KEYWORDS and not ORGS and not GITEE_ORGS and not EXTRA_REPOS and not EXTRA_REPOS_URL:
        log("Warning: no KEYWORDS/ORGS/EXTRA_REPOS configured — likely no results. Set KEYWORDS to something like 'AI agent' to test.")
    # GitHub keywords
    for kw in KEYWORDS:
        q=f'pushed:>{since} {kw}'
        try:
            items = search_github(q, PER_SOURCE)
            log(f"[GitHub] keyword '{kw}' -> {len(items)}")
            for r in items: candidates[f"github:{r.get('full_name')}"]=normalize_github_repo(r)
        except Exception:
            log(f"[GitHub] exception for keyword {kw}:\n{traceback.format_exc()}")

    # GitHub orgs
    for org in ORGS:
        q=f'org:{org} pushed:>{since}'
        try:
            items=search_github(q, PER_SOURCE)
            log(f"[GitHub] org '{org}' -> {len(items)}")
            for r in items: candidates[f"github:{r.get('full_name')}"]=normalize_github_repo(r)
        except Exception:
            log(f"[GitHub] exception for org {org}:\n{traceback.format_exc()}")

    # Gitee keywords
    for kw in KEYWORDS:
        try:
            items=search_gitee(f'{kw} pushed:>{since}', PER_SOURCE)
            log(f"[Gitee] keyword '{kw}' -> {len(items)}")
            for r in items: candidates[f"gitee:{normalize_gitee_repo(r).get('full_name')}"]=normalize_gitee_repo(r)
        except Exception:
            log(f"[Gitee] exception for keyword {kw}:\n{traceback.format_exc()}")

    # Gitee orgs
    for org in GITEE_ORGS:
        try:
            items=search_gitee(f'owner:{org}', PER_SOURCE)
            log(f"[Gitee] org '{org}' -> {len(items)}")
            for r in items: candidates[f"gitee:{normalize_gitee_repo(r).get('full_name')}"]=normalize_gitee_repo(r)
        except Exception:
            log(f"[Gitee] exception for org {org}:\n{traceback.format_exc()}")

    # GitLab keywords
    for kw in KEYWORDS:
        try:
            items=search_gitlab(kw, PER_SOURCE)
            log(f"[GitLab] keyword '{kw}' -> {len(items)}")
            for r in items: candidates[f"gitlab:{normalize_gitlab_repo(r).get('full_name')}"]=normalize_gitlab_repo(r)
        except Exception:
            log(f"[GitLab] exception for keyword {kw}:\n{traceback.format_exc()}")

    # Libraries.io
    for kw in KEYWORDS:
        try:
            items=search_librariesio(kw, PER_SOURCE)
            log(f"[Libraries.io] keyword '{kw}' -> {len(items)}")
            for it in items:
                nr=normalize_librariesio_item(it)
                candidates[f"{nr.get('platform')}:{nr.get('full_name')}"]=nr
        except Exception:
            log(f"[Libraries.io] exception for keyword {kw}:\n{traceback.format_exc()}")

    # EXTRA repos direct
    for repo in EXTRA_REPOS:
        try:
            if repo.startswith("gitee:"):
                r=get_gitee_repo(repo.split("gitee:",1)[1])
                if r: candidates[f"gitee:{normalize_gitee_repo(r).get('full_name')}"]=normalize_gitee_repo(r)
            elif "/" in repo:
                r=get_github_repo(repo)
                if r: candidates[f"github:{normalize_github_repo(r).get('full_name')}"]=normalize_github_repo(r)
        except Exception:
            log(f"Exception fetching EXTRA_REPO {repo}:\n{traceback.format_exc()}")

    # EXTRA_REPOS_URL
    if EXTRA_REPOS_URL:
        for ln in fetch_url_lines(EXTRA_REPOS_URL):
            try:
                if ln.startswith("gitee:"):
                    fullname = ln.split("gitee:",1)[1]; r=get_gitee_repo(fullname)
                    if r: candidates[f"gitee:{normalize_gitee_repo(r).get('full_name')}"]=normalize_gitee_repo(r)
                elif "/" in ln:
                    r=get_github_repo(ln)
                    if r: candidates[f"github:{normalize_github_repo(r).get('full_name')}"]=normalize_github_repo(r)
            except Exception:
                log(f"Exception fetching from EXTRA_REPOS_URL line {ln}:\n{traceback.format_exc()}")

    return list(candidates.values())

def sort_and_select(repos):
    def key_fn(r):
        stars = r.get("stargazers_count",0) or 0
        pushed = r.get("pushed_at") or ""
        return (pushed, stars) if SORT=="pushed" else (stars, pushed)
    sorted_repos = sorted(repos, key=key_fn, reverse=True)
    return sorted_repos[:TOP_N]

def format_markdown(repos, since, today):
    lines=[]
    lines.append(f"# Hot projects for week ending {today} (based on pushed:>{since})\n")
    lines.append("| # | Platform | Repo | Stars | Forks | Last Push | Description | Topics |")
    lines.append("|---:|---|---|---:|---:|---|---|---|")
    if not repos:
        lines.append("| - | - | No repositories found with current filters | - | - | - | - | - |")
    for i,r in enumerate(repos, start=1):
        platform=r.get("platform","github")
        name=r.get("full_name") or ""
        stars=r.get("stargazers_count",0)
        forks=r.get("forks_count",0)
        desc=(r.get("description") or "").replace("\n"," ").replace("|","\\|")
        url=r.get("html_url") or ""
        pushed=(r.get("pushed_at") or "")[:19].replace("T"," ") if r.get("pushed_at") else ""
        topics=", ".join(r.get("topics",[])) if isinstance(r.get("topics",list)) else ""
        lines.append(f"| {i} | {platform} | [{name}]({url}) | {stars} | {forks} | {pushed} | {desc} | {topics} |")
    return "\n".join(lines)

def main():
    try:
        since=(datetime.datetime.utcnow()-datetime.timedelta(days=DAYS)).date().isoformat()
        today=datetime.datetime.utcnow().strftime("%Y-%m-%d")
        os.makedirs("results", exist_ok=True)
        log("ENV summary: TOP_N=%s DAYS=%s KEYWORDS=%s ORGS=%s GITEE_ORGS=%s EXTRA_REPOS=%s PER_SOURCE=%s SORT=%s VERBOSE=%s" %
            (TOP_N, DAYS, KEYWORDS, ORGS, GITEE_ORGS, EXTRA_REPOS, PER_SOURCE, SORT, VERBOSE))
        log("Token present: GITHUB=%s GITEE=%s GITLAB=%s LIBS=%s" % (bool(GITHUB_TOKEN), bool(GITEE_TOKEN), bool(GITLAB_TOKEN), bool(LIBRARIES_IO_KEY)))

        repos = collect_candidates()
        log(f"Total unique candidates collected: {len(repos)}")
        final = sort_and_select(repos)
        log(f"Selected top {len(final)} repositories (TOP_N={TOP_N})")
        md = format_markdown(final, since, today)
        md_path = os.path.join("results", f"hot-projects-{today}.md")
        with open(md_path, "w", encoding="utf-8") as f: f.write(md)
        json_path = os.path.join("results", f"hot-projects-{today}.json")
        with open(json_path, "w", encoding="utf-8") as f: json.dump(final, f, indent=2, ensure_ascii=False)
        log(f"Wrote {md_path} and {json_path}")
    except Exception:
        log("Unhandled exception in main():\n" + traceback.format_exc())
        raise

if __name__ == "__main__":
    main()
