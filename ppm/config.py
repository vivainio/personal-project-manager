"""ppm configuration from ~/.config/ppm/config.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

CONFIG_PATH = Path.home() / ".config" / "ppm" / "config.yaml"

DEFAULT_CONFIG = """\
# ppm configuration

# Local directory where repos are cloned
repos_root: ~/r

# GitHub orgs to include when listing repos (in addition to your own account)
# orgs:
#   - myorg

# Associate repos to named projects by repo name prefixes
# projects:
#   foo:
#     prefixes:
#       - foo-
#   bar:
#     prefixes:
#       - bar-
"""

_yaml = YAML()
_yaml.preserve_quotes = True


@dataclass
class Project:
    name: str
    prefixes: list[str]


@dataclass
class Config:
    orgs: list[str] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    repos_root: Path = field(default_factory=lambda: Path("~/r").expanduser())
    zaira: bool = False

    def project_for(self, repo_name: str) -> str | None:
        """Return the project name for a repo name, or None if unmatched."""
        for project in self.projects:
            if any(repo_name.startswith(p) for p in project.prefixes):
                return project.name
        return None


def _read() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_CONFIG)
    return _yaml.load(CONFIG_PATH) or {}


def _write(data: dict) -> None:
    with CONFIG_PATH.open("w") as f:
        _yaml.dump(data, f)


def add_project(name: str, prefix: str) -> None:
    """Add a new project entry to the config file, preserving comments."""
    data = _read()
    projects = data.setdefault("projects", {})
    if name in projects:
        raise ValueError(f"Project '{name}' already exists")
    projects[name] = {"prefixes": [prefix]}
    _write(data)


def load() -> Config:
    data = _read()
    projects = [
        Project(name=name, prefixes=list(cfg.get("prefixes", []))) for name, cfg in (data.get("projects") or {}).items()
    ]
    repos_root = Path(str(data.get("repos_root", "~/r"))).expanduser()
    return Config(
        orgs=list(data.get("orgs", [])),
        projects=projects,
        repos_root=repos_root,
        zaira=bool(data.get("zaira", False)),
    )
