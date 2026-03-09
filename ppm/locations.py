"""Cache of non-standard local clone paths for repos."""

import json
import re
import subprocess
from pathlib import Path

from ppm import cache, config

CACHE_KEY = "locations"


def _load() -> dict[str, str]:
    return cache.get(CACHE_KEY, ttl=10**9) or {}


def _save(data: dict[str, str]) -> None:
    cache.set(CACHE_KEY, data)


def set_location(repo_name: str, path: Path) -> None:
    data = _load()
    data[repo_name] = str(path)
    _save(data)


def get_location(repo_name: str) -> Path | None:
    """Return the cached non-standard path, or None if using default."""
    return Path(data[repo_name]) if (data := _load()) and repo_name in data else None


def expected_path(repo_name: str, cfg: config.Config) -> Path:
    """Return the conventional path: repos_root / project / repo-name."""
    project = cfg.project_for(repo_name)
    if project:
        return cfg.repos_root / project / repo_name
    return cfg.repos_root / repo_name


def resolve_path(repo_name: str, cfg: config.Config) -> Path:
    """Return the actual local path (cached override or default convention)."""
    return get_location(repo_name) or expected_path(repo_name, cfg)


def repo_name_from_remote(path: Path) -> str | None:
    """Detect the GitHub repo name from the git remote of the given directory."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
            cwd=path,
        )
        url = result.stdout.strip()
        # Match https://github.com/owner/repo.git or git@github.com:owner/repo.git
        match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
        if match:
            return match.group(1).split("/")[-1]
    except subprocess.CalledProcessError:
        pass
    return None


def cwd_root() -> Path:
    """Return the root of the current git repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())
