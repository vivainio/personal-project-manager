"""GitHub repository listing via gh CLI with caching."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypedDict

from ppm import cache, config

CACHE_KEY = "repos"
GH_FIELDS = "name,nameWithOwner,description,url,isPrivate,isFork,updatedAt,primaryLanguage"


class Repo(TypedDict):
    name: str
    nameWithOwner: str
    description: str
    url: str
    isPrivate: bool
    isFork: bool
    updatedAt: str
    primaryLanguage: dict | None


def _gh_repo_list(owner: str | None = None, limit: int = 1000) -> list[Repo]:
    cmd = ["gh", "repo", "list"]
    if owner:
        cmd.append(owner)
    cmd += ["--limit", str(limit), "--json", GH_FIELDS]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fetch_repos(limit: int = 1000) -> list[Repo]:
    cfg = config.load()
    owners: list[str | None] = [None, *cfg.orgs]
    fetch = partial(_gh_repo_list, limit=limit)
    with ThreadPoolExecutor(max_workers=len(owners)) as pool:
        results = pool.map(fetch, owners)
    return [repo for batch in results for repo in batch]


def get_repos(refresh: bool = False) -> list[Repo]:
    if not refresh:
        cached = cache.get(CACHE_KEY, ttl=7 * 24 * 3600)
        if cached is not None:
            return cached
    repos = fetch_repos()
    cache.set(CACHE_KEY, repos)
    return repos
