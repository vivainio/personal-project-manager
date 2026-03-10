"""ppm CLI entry point."""

import fnmatch
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ppm import cache as cache_module
from ppm import config as config_module
from ppm import gh_auth as gh_auth_module
from ppm import locations as locations_module
from ppm import repos as repos_module

app = typer.Typer(help="Personal project manager", no_args_is_help=True)
projects_app = typer.Typer(help="Manage projects", no_args_is_help=True)
app.add_typer(projects_app, name="projects")


def _version_callback(value: bool) -> None:
    if value:
        version = importlib.metadata.version("personal-project-manager")
        typer.echo(f"ppm {version}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit"
    ),
) -> None:
    pass


console = Console()


def _glob_pat(s: str) -> str:
    return s if "*" in s or "?" in s else f"*{s}*"


def _filter_repos(repo_list: list, value: str, cfg: config_module.Config) -> list:
    """Filter repos by project name (exact) or glob pattern (substring)."""
    project_names = {p.name for p in cfg.projects}
    if value in project_names:
        return [r for r in repo_list if cfg.project_for(r["name"]) == value]
    pat = _glob_pat(value.lower())
    return [r for r in repo_list if fnmatch.fnmatch(r["name"].lower(), pat)]


@app.command()
def repos(
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Bypass cache and re-fetch"),
    forks: bool = typer.Option(False, "--forks", help="Include forked repos"),
    filter: str = typer.Argument(None, help="Project name or search pattern"),
) -> None:
    """List GitHub repositories."""
    cfg = config_module.load()
    if cfg.orgs:
        accounts = gh_auth_module.get_accounts()
        active = gh_auth_module.active_account(accounts)
        if active and "_" not in active.username:
            org_account = next((a for a in accounts if "_" in a.username), None)
            if org_account:
                subprocess.run(["gh", "auth", "switch", "--user", org_account.username], check=True)
                console.print(f"[dim]switched gh account → {org_account.username}[/dim]")

    with console.status("Loading repos..."):
        repo_list = repos_module.get_repos(refresh=refresh)

    if not forks:
        repo_list = [r for r in repo_list if not r["isFork"]]

    project_names = {p.name for p in cfg.projects}
    active_project: str | None = None

    if filter:
        if filter in project_names:
            active_project = filter
        repo_list = _filter_repos(repo_list, filter, cfg)

    show_project_col = bool(cfg.projects) and not active_project
    show_branch = bool(filter)

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Repo", style="bold", no_wrap=True, ratio=3)
    if show_project_col:
        table.add_column("Project", no_wrap=True, ratio=1)
    table.add_column("Path", no_wrap=True, ratio=2)
    if show_branch:
        table.add_column("Branch", no_wrap=True, ratio=2)

    for repo in repo_list:
        name = repo["name"]
        visibility = "[dim]🔒[/dim] " if repo["isPrivate"] else ""
        display_name = f"{visibility}{repo['nameWithOwner']}"
        proj = cfg.project_for(name) or ""

        expected = locations_module.expected_path(name, cfg)
        override = locations_module.get_location(name)
        local_path = override or expected
        exists = local_path.exists()

        if not exists:
            path_str = ""
            branch_str = ""
        else:
            display_path = str(local_path).replace(str(cfg.repos_root), "~/r", 1)
            color = "yellow" if override else "green"
            path_str = f"[{color}]{display_path}[/{color}]"
            branch_str = locations_module.current_branch(local_path) or "" if show_branch else ""

        row = [display_name]
        if show_project_col:
            row.append(f"[cyan]{proj}[/cyan]" if proj else "")
        row.append(path_str)
        if show_branch:
            row.append(branch_str)
        table.add_row(*row)

    console.print(table)
    console.print(f"[dim]{len(repo_list)} repos[/dim]")


def _register_git_dir(git_dir: Path, cfg: config_module.Config) -> None:
    repo_name = locations_module.repo_name_from_remote(git_dir)
    if not repo_name:
        console.print(f"[dim]skip[/dim] {git_dir} (no GitHub remote)")
        return
    expected = locations_module.expected_path(repo_name, cfg)
    if git_dir == expected:
        console.print(f"[dim]ok[/dim]   {repo_name}")
        return
    locations_module.set_location(repo_name, git_dir)
    console.print(f"[green]recorded[/green] [bold]{repo_name}[/bold] → {git_dir}")


@app.command()
def here(
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Scan child dirs for git repos"),
) -> None:
    """Register the current directory (or child repos) as local clone locations."""
    cfg = config_module.load()
    cwd = Path.cwd()

    if recursive:
        git_dirs = sorted(p.parent for p in cwd.rglob(".git") if p.is_dir())
        if not git_dirs:
            console.print("[yellow]No git repositories found under current directory.[/yellow]")
            return
        for git_dir in git_dirs:
            _register_git_dir(git_dir, cfg)
        return

    try:
        clone_root = locations_module.cwd_root()
    except Exception:
        console.print("[red]Not inside a git repository.[/red]")
        raise typer.Exit(1)

    _register_git_dir(clone_root, cfg)


def _mv_one(repo_name: str, current: Path, cfg: config_module.Config) -> str | None:
    """Validate and perform a single repo move. Returns error string or None on success."""
    expected = locations_module.expected_path(repo_name, cfg)
    if current == expected:
        return f"{repo_name}: already at canonical path"
    try:
        Path.cwd().relative_to(current)
        return f"{repo_name}: cannot move while inside the repo — cd out first"
    except ValueError:
        pass
    if expected.exists():
        return f"{repo_name}: destination already exists: {expected}"
    expected.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(current), str(expected))
    locations_module.clear_location(repo_name)
    return None


@app.command()
def mv(
    repo: str = typer.Argument(None, help="Repo name, '.' to scan subdirs, or omit for current repo"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Move a repo (or subdirectory repos) to their expected canonical paths."""
    cfg = config_module.load()

    if repo == ".":
        cwd = Path.cwd()
        candidates: list[tuple[str, Path]] = []
        for subdir in sorted(cwd.iterdir()):
            if not subdir.is_dir() or not (subdir / ".git").exists():
                continue
            repo_name = locations_module.repo_name_from_remote(subdir)
            if not repo_name:
                continue
            expected = locations_module.expected_path(repo_name, cfg)
            if subdir.resolve() == expected.resolve():
                continue
            candidates.append((repo_name, subdir))

        if not candidates:
            console.print("[dim]No misplaced repos found in subdirectories.[/dim]")
            return

        root_str = str(cfg.repos_root)
        for repo_name, current in candidates:
            expected = locations_module.expected_path(repo_name, cfg)
            display_from = str(current).replace(root_str, "~/r", 1)
            display_to = str(expected).replace(root_str, "~/r", 1)
            if expected.exists():
                console.print(f"[bold]{repo_name}[/bold]  [yellow]{display_from}[/yellow] → [red]destination exists, skip[/red]")
            else:
                console.print(f"[bold]{repo_name}[/bold]  [yellow]{display_from}[/yellow] → [cyan]{display_to}[/cyan]")

        movable = [(n, p) for n, p in candidates if not locations_module.expected_path(n, cfg).exists()]
        if not movable:
            return

        if not yes:
            typer.confirm(f"Move {len(movable)} repo(s)? (--yes to skip)", abort=True)

        for repo_name, current in movable:
            err = _mv_one(repo_name, current, cfg)
            if err:
                console.print(f"[red]{err}[/red]")
            else:
                expected = locations_module.expected_path(repo_name, cfg)
                display_to = str(expected).replace(root_str, "~/r", 1)
                console.print(f"[green]moved[/green] [bold]{repo_name}[/bold] → {display_to}")
        return

    if repo is None:
        try:
            current = locations_module.cwd_root()
            repo_name = locations_module.repo_name_from_remote(current)
        except Exception:
            console.print("[red]Not inside a git repository.[/red]")
            raise typer.Exit(1)
        if not repo_name:
            console.print("[red]Could not determine repo name from git remote.[/red]")
            raise typer.Exit(1)
    else:
        repo_name = repo
        current = locations_module.resolve_path(repo_name, cfg)

    if not current.exists():
        console.print(f"[red]Repo not found locally:[/red] {current}")
        raise typer.Exit(1)

    expected = locations_module.expected_path(repo_name, cfg)
    root_str = str(cfg.repos_root)
    display_from = str(current).replace(root_str, "~/r", 1)
    display_to = str(expected).replace(root_str, "~/r", 1)

    if current == expected:
        console.print(f"[dim]{repo_name} is already at its canonical path.[/dim]")
        return

    try:
        Path.cwd().relative_to(current)
        console.print(f"[red]Cannot move: you are inside the repo.[/red] cd out first.")
        raise typer.Exit(1)
    except ValueError:
        pass

    if expected.exists():
        console.print(f"[red]Destination already exists:[/red] {expected}")
        raise typer.Exit(1)

    console.print(f"  from: [yellow]{display_from}[/yellow]")
    console.print(f"    to: [cyan]{display_to}[/cyan]")

    if not yes:
        typer.confirm("Move? (--yes to skip)", abort=True)

    err = _mv_one(repo_name, current, cfg)
    if err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]moved[/green] [bold]{repo_name}[/bold] → {display_to}")


def _pr_age(created_at: str) -> str:
    created = datetime.fromisoformat(created_at)
    days = (datetime.now(UTC) - created).days
    if days == 0:
        return "today"
    if days == 1:
        return "1d"
    if days < 30:
        return f"{days}d"
    months = days // 30
    return f"{months}mo"


# --- ppm pr ---


@app.command()
def pr(
    target: str = typer.Argument(..., help="Project name or repo name/pattern"),
) -> None:
    """List open pull requests for a project or repo."""
    cfg = config_module.load()
    repo_list = repos_module.get_repos()
    project_names = {p.name for p in cfg.projects}

    project_repos = _filter_repos(repo_list, target, cfg)
    if not project_repos:
        console.print(f"[red]No project or repo found matching '{target}'.[/red]")
        raise typer.Exit(1)

    def fetch(repo: dict) -> tuple[str, dict[str, list[dict]]]:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo["nameWithOwner"],
                "--json",
                "number,title,author,headRefName,createdAt",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return repo["name"], {}
        prs = json.loads(result.stdout)
        by_author: dict[str, list[dict]] = defaultdict(list)
        for p in prs:
            by_author[p["author"]["login"]].append(p)
        return repo["name"], dict(by_author)

    total = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, repo): repo for repo in project_repos}
        for future in as_completed(futures):
            repo_name, by_author = future.result()
            if not by_author:
                continue
            console.print(f"\n[bold cyan]{repo_name}[/bold cyan]")
            for author, prs in by_author.items():
                console.print(f"  [bold]{author}[/bold]")
                for p in prs:
                    age = _pr_age(p["createdAt"])
                    num = f"#{p['number']}"
                    console.print(f"    [dim]{num:<6} {age:<5}[/dim] {p['title']}")
                    total += 1

    console.print(f"\n[dim]{total} open PRs[/dim]")


# --- ppm projects ---


@projects_app.command("list")
def projects_list() -> None:
    """List configured projects."""
    cfg = config_module.load()
    if not cfg.projects:
        console.print("[dim]No projects configured.[/dim]")
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Project", style="bold")
    table.add_column("Prefixes")
    for project in cfg.projects:
        table.add_row(project.name, ", ".join(project.prefixes))
    console.print(table)


@projects_app.command("add")
def projects_add(
    name: str = typer.Argument(..., help="Project name"),
    prefix: str = typer.Argument(..., help="Repo name prefix"),
) -> None:
    """Add a new project."""
    try:
        config_module.add_project(name, prefix)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Added project[/green] [bold]{name}[/bold] (prefix: {prefix})")


@app.command()
def clone(
    repo: str = typer.Argument(..., help="Repo name or owner/repo"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Clone a repo to its expected local path."""
    cfg = config_module.load()

    repo_list = repos_module.get_repos()
    name_lower = repo.lower()

    # Try exact match first, then fall back to substring
    matches = [r for r in repo_list if r["name"].lower() == name_lower or r["nameWithOwner"].lower() == name_lower]
    if not matches:
        matches = [r for r in repo_list if fnmatch.fnmatch(r["name"].lower(), _glob_pat(name_lower))]

    if not matches:
        console.print(f"[red]No repo found matching '{repo}'.[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print("[yellow]Multiple matches — be more specific:[/yellow]")
        for r in matches:
            console.print(f"  {r['nameWithOwner']}")
        raise typer.Exit(1)

    found = matches[0]
    target = locations_module.expected_path(found["name"], cfg)

    if target.exists():
        console.print(f"[yellow]Already exists:[/yellow] {target}")
        raise typer.Exit(1)

    display_target = str(target).replace(str(cfg.repos_root), "~/r", 1)
    console.print(f"  repo: [bold]{found['nameWithOwner']}[/bold]")
    console.print(f"  path: [cyan]{display_target}[/cyan]")

    if not yes:
        typer.confirm("Clone? (--yes to skip)", abort=True)

    repo_owner = found["nameWithOwner"].split("/")[0]
    accounts = gh_auth_module.get_accounts()
    active = gh_auth_module.active_account(accounts)
    if not gh_auth_module.ensure_org_account(cfg.orgs, repo_owner, accounts):
        console.print("[red]No gh account with underscore found for org repos.[/red]")
        raise typer.Exit(1)
    new_active = gh_auth_module.active_account(gh_auth_module.get_accounts())
    if new_active and active and new_active.username != active.username:
        console.print(f"[dim]switched gh account → {new_active.username}[/dim]")

    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = gh_auth_module.clone_cmd(found["nameWithOwner"], str(target))
    console.print(f"[dim]{' '.join(cmd)}[/dim]")
    subprocess.run(cmd, check=True)


_TICKET_RE = re.compile(r"\b([A-Z]{2,}-\d{2,})\b")


def _parse_front_matter(text: str) -> dict[str, str]:
    """Parse YAML front matter from a markdown string. Returns key/value pairs."""
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()[1:]
    result = {}
    for line in lines:
        if line == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _ticket_slug(ticket_id: str, title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return f"{ticket_id}-{slug}.md"


def _save_ticket_to_vault(ticket_id: str, vault: Path, project: str | None = None, title: str | None = None) -> None:
    """Save full ticket content to the Obsidian vault."""
    filename = _ticket_slug(ticket_id, title) if title else f"{ticket_id}.md"
    if project:
        note_path = vault / "projects" / project / "tickets" / filename
    else:
        note_path = vault / "tickets" / filename
    if note_path.exists():
        return
    result = subprocess.run(["zaira", "get", ticket_id], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(result.stdout)


def _zaira_summary(ticket_id: str, vault: Path | None = None, project: str | None = None) -> str | None:
    """Return ticket summary, fetching via zaira and caching permanently."""
    cached: dict[str, str] = cache_module.get("tickets", ttl=10**9) or {}
    if ticket_id in cached:
        if vault:
            _save_ticket_to_vault(ticket_id, vault, project=project, title=cached[ticket_id])
        return cached[ticket_id]
    result = subprocess.run(
        ["zaira", "get", ticket_id, "--min"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    summary = None
    for line in result.stdout.splitlines():
        if line.startswith("summary:"):
            summary = line[len("summary:") :].strip()
            break
    if summary:
        cached[ticket_id] = summary
        cache_module.set("tickets", cached)
    if vault:
        _save_ticket_to_vault(ticket_id, vault, project=project, title=summary)
    return summary


tickets_app = typer.Typer(help="Manage tickets", no_args_is_help=True)
app.add_typer(tickets_app, name="tickets")

specs_app = typer.Typer(help="Manage specs", no_args_is_help=True)
app.add_typer(specs_app, name="specs")


@tickets_app.command("list")
def tickets_list(
    filter: str = typer.Argument(None, help="Project name or repo pattern to scope search"),
) -> None:
    """Show tickets checked out across local repos."""
    cfg = config_module.load()
    repo_list = repos_module.get_repos()

    if filter:
        repo_list = _filter_repos(repo_list, filter, cfg)

    by_ticket: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for repo in repo_list:
        local_path = locations_module.resolve_path(repo["name"], cfg)
        if not local_path.exists():
            continue
        branch = locations_module.current_branch(local_path)
        if not branch:
            continue
        match = _TICKET_RE.search(branch)
        if match:
            ticket = match.group(1).upper()
            by_ticket[ticket].append((repo["name"], branch))

    if not by_ticket:
        console.print("[dim]No checked-out ticket branches found.[/dim]")
        return

    for ticket, entries in sorted(by_ticket.items()):
        first_repo = entries[0][0]
        project = cfg.project_for(first_repo)
        summary = _zaira_summary(ticket, vault=cfg.obsidian_vault, project=project) if cfg.zaira else None
        header = f"[bold cyan]{ticket}[/bold cyan]"
        if summary:
            header += f"  {summary}"
        console.print(header)
        for repo_name, branch in entries:
            console.print(f"  [bold]{repo_name}[/bold]  [dim]{branch}[/dim]")


@tickets_app.command("search")
def tickets_search(
    query: str = typer.Argument(..., help="String to search in cached ticket summaries"),
) -> None:
    """Search cached ticket summaries."""
    cached: dict[str, str] = cache_module.get("tickets", ttl=10**9) or {}
    if not cached:
        console.print("[dim]No tickets in cache yet.[/dim]")
        return

    query_lower = query.lower()
    matches = {
        tid: summary for tid, summary in cached.items() if query_lower in tid.lower() or query_lower in summary.lower()
    }

    if not matches:
        console.print(f"[dim]No cached tickets matching '{query}'.[/dim]")
        return

    for tid, summary in sorted(matches.items()):
        console.print(f"[bold cyan]{tid}[/bold cyan]  {summary}")


def _find_specs_dir(repo_root: Path) -> Path | None:
    """Walk up from cwd to repo root looking for a specs/ directory."""
    current = Path.cwd()
    while True:
        candidate = current / "specs"
        if candidate.exists():
            return candidate.resolve()
        if current == repo_root:
            return None
        current = current.parent


def _parse_spec_file(path: Path) -> dict[str, str]:
    """Extract title, shipped status, and Jira tickets from a spec.md."""
    text = path.read_text()
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not result.get("title") and line.startswith("# "):
            result["title"] = line[2:].strip()
        if line.strip() == "## Shipped":
            result["shipped"] = "1"
    tickets = sorted(set(t.upper() for t in _TICKET_RE.findall(text)))
    if tickets:
        result["tickets"] = " ".join(tickets)
    return result


@specs_app.command("where")
def specs_where() -> None:
    """Show the resolved specs/ directory for the current repo."""
    try:
        repo_root = locations_module.cwd_root()
    except Exception:
        console.print("[red]Not inside a git repository.[/red]")
        raise typer.Exit(1)
    specs_dir = _find_specs_dir(repo_root)
    if not specs_dir:
        console.print("[dim]No specs/ directory found in this repo.[/dim]")
        raise typer.Exit(1)
    console.print(str(specs_dir))


@specs_app.command("list")
def specs_list() -> None:
    """List mspec specs in the current repo."""
    try:
        repo_root = locations_module.cwd_root()
    except Exception:
        console.print("[red]Not inside a git repository.[/red]")
        raise typer.Exit(1)

    specs_dir = _find_specs_dir(repo_root)
    if not specs_dir:
        console.print("[dim]No specs/ directory found in this repo.[/dim]")
        return

    spec_files = sorted(specs_dir.rglob("spec.md"))
    if not spec_files:
        console.print("[dim]No specs found in this repo.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Area", style="dim", no_wrap=True)
    table.add_column("Spec", style="bold", no_wrap=True)
    table.add_column("Title")
    table.add_column("Tickets", style="dim", no_wrap=True)

    parsed = []
    for spec_file in spec_files:
        rel = spec_file.parent.relative_to(specs_dir)
        parts = rel.parts
        area = parts[-2] if len(parts) >= 2 else ""
        spec_name = parts[-1]
        info = _parse_spec_file(spec_file)
        parsed.append((area, spec_name, info.get("title", ""), bool(info.get("shipped")), info.get("tickets", "")))

    for area, spec_name, title, shipped, tickets in sorted(parsed, key=lambda x: not x[3]):
        style = "dim" if shipped else ""
        table.add_row(area, spec_name, title, tickets, style=style)

    console.print(table)


@app.command()
def memo(
    name: str = typer.Argument(..., help="Memo name or path to a markdown file"),
) -> None:
    """Create or open a memo in the Obsidian vault."""
    cfg = config_module.load()
    if not cfg.obsidian_vault:
        console.print("[red]No obsidian_vault configured.[/red]")
        raise typer.Exit(1)

    project: str | None = None
    try:
        repo_root = locations_module.cwd_root()
        repo_name = locations_module.repo_name_from_remote(repo_root)
        if repo_name:
            project = cfg.project_for(repo_name)
    except Exception:
        pass

    source = Path(name)
    if source.is_file() and source.suffix == ".md":
        slug = source.name
    else:
        slug = name if name.endswith(".md") else f"{name}.md"

    stem = slug[: -len(".md")]
    base = cfg.obsidian_vault / "projects" / project / "memos" if project else cfg.obsidian_vault / "memos"
    note_path = base / slug
    source_str = str(source.resolve()) if source.is_file() and source.suffix == ".md" else None

    # Find a matching existing note (same source) or the next free slot
    counter = 1
    candidate = note_path
    while candidate.exists():
        if _parse_front_matter(candidate.read_text()).get("source") == source_str:
            note_path = candidate
            break
        candidate = base / f"{stem}-{counter}.md"
        counter += 1
    else:
        note_path = candidate

    note_path.parent.mkdir(parents=True, exist_ok=True)

    if source.is_file() and source.suffix == ".md":
        content = f"---\nsource: {source_str}\n---\n\n" + source.read_text()
        note_path.write_text(content)
        console.print(f"[green]saved[/green] {note_path}")
        return

    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(note_path)])
