"""ppm configuration from ~/.config/ppm/config.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path.home() / ".config" / "ppm" / "config.yaml"

DEFAULT_CONFIG = """\
# ppm configuration

# GitHub orgs to include when listing repos (in addition to your own account)
orgs:
  - basware
"""


@dataclass
class Config:
    orgs: list[str] = field(default_factory=list)


def load() -> Config:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_CONFIG)

    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return Config(orgs=data.get("orgs", []))
