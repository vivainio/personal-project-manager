"""ppm configuration from ~/.config/ppm/config.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path.home() / ".config" / "ppm" / "config.yaml"

DEFAULT_CONFIG = """\
# ppm configuration

# Local directory where repos are cloned
repos_root: ~/r

# GitHub orgs to include when listing repos (in addition to your own account)
orgs:
  - basware

# Associate repos to named projects by repo name prefixes
# projects:
#   dh:
#     prefixes:
#       - dh-
#   som:
#     prefixes:
#       - som-
"""


@dataclass
class Project:
    name: str
    prefixes: list[str]


@dataclass
class Config:
    orgs: list[str] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    repos_root: Path = field(default_factory=lambda: Path("~/r").expanduser())

    def project_for(self, repo_name: str) -> str | None:
        """Return the project name for a repo name, or None if unmatched."""
        for project in self.projects:
            if any(repo_name.startswith(p) for p in project.prefixes):
                return project.name
        return None


def load() -> Config:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_CONFIG)

    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    projects = [
        Project(name=name, prefixes=cfg.get("prefixes", []))
        for name, cfg in (data.get("projects") or {}).items()
    ]
    repos_root = Path(data.get("repos_root", "~/r")).expanduser()
    return Config(orgs=data.get("orgs", []), projects=projects, repos_root=repos_root)
