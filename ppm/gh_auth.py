"""GitHub auth helpers using gh CLI."""

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class GhAccount:
    username: str
    active: bool


def get_accounts() -> list[GhAccount]:
    """Parse `gh auth status` and return all authenticated accounts."""
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    accounts = []
    current_user: str | None = None
    for line in output.splitlines():
        m = re.search(r"Logged in to github\.com account (\S+)", line)
        if m:
            current_user = m.group(1)
        if current_user and "Active account: true" in line:
            accounts.append(GhAccount(username=current_user, active=True))
            current_user = None
        elif current_user and "Active account: false" in line:
            accounts.append(GhAccount(username=current_user, active=False))
            current_user = None
    return accounts


def active_account(accounts: list[GhAccount]) -> GhAccount | None:
    return next((a for a in accounts if a.active), None)


def ssh_available() -> bool:
    """Return True if SSH auth to GitHub works (Linux only)."""
    if sys.platform != "linux":
        return False
    result = subprocess.run(
        ["ssh", "-T", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", "git@github.com"],
        capture_output=True,
        text=True,
    )
    return "successfully authenticated" in result.stderr


def clone_cmd(name_with_owner: str, target: str) -> list[str]:
    """Return the best clone command for the current environment."""
    if ssh_available():
        return ["git", "clone", f"git@github.com:{name_with_owner}.git", target]
    return ["gh", "repo", "clone", name_with_owner, target]


def ensure_org_account(orgs: list[str], repo_owner: str, accounts: list[GhAccount] | None = None) -> bool:
    """If repo_owner is a configured org, ensure the underscore account is active.

    Returns True if the account is correct or was switched, False if no suitable account found.
    """
    if repo_owner not in orgs:
        return True

    if accounts is None:
        accounts = get_accounts()
    active = active_account(accounts)

    if active and "_" in active.username:
        return True  # already on the right account

    # Find an account with underscore
    org_account = next((a for a in accounts if "_" in a.username), None)
    if not org_account:
        return False

    subprocess.run(["gh", "auth", "switch", "--user", org_account.username], check=True)
    return True
