"""ppm CLI entry point."""

import fnmatch
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ppm import config as config_module
from ppm import gh_auth as gh_auth_module
from ppm import locations as locations_module
from ppm import repos as repos_module

app = typer.Typer(help="Personal project manager", no_args_is_help=True)
projects_app = typer.Typer(help="Manage projects", no_args_is_help=True)
app.add_typer(projects_app, name="projects")

console = Console()


@app.command()
def repos(
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Bypass cache and re-fetch"),
    forks: bool = typer.Option(False, "--forks", help="Include forked repos"),
    filter: str = typer.Argument(None, help="Project name or search pattern"),
) -> None:
    """List GitHub repositories."""
    with console.status("Loading repos..."):
        cfg = config_module.load()
        repo_list = repos_module.get_repos(refresh=refresh)

    if not forks:
        repo_list = [r for r in repo_list if not r["isFork"]]

    project_names = {p.name for p in cfg.projects}
    active_project: str | None = None

    if filter:
        if filter in project_names:
            active_project = filter
            repo_list = [r for r in repo_list if cfg.project_for(r["name"]) == filter]
        else:
            pat = filter if "*" in filter or "?" in filter else f"*{filter}*"
            repo_list = [r for r in repo_list if fnmatch.fnmatch(r["name"].lower(), pat.lower())]

    show_project_col = bool(cfg.projects) and not active_project

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Repo", style="bold", no_wrap=True, ratio=3)
    if show_project_col:
        table.add_column("Project", no_wrap=True, ratio=1)
    table.add_column("Path", no_wrap=True, ratio=2)
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
            branch_str = locations_module.current_branch(local_path) or ""

        row = [display_name]
        if show_project_col:
            row.append(f"[cyan]{proj}[/cyan]" if proj else "")
        row += [path_str, branch_str]
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


# --- ppm pr ---

@app.command()
def pr(
    project: str = typer.Argument(..., help="Project name"),
) -> None:
    """List open pull requests for all repos in a project."""
    cfg = config_module.load()
    project_names = {p.name for p in cfg.projects}
    if project not in project_names:
        console.print(f"[red]Unknown project '{project}'.[/red]")
        raise typer.Exit(1)

    repo_list = repos_module.get_repos()
    project_repos = [r for r in repo_list if cfg.project_for(r["name"]) == project]

    def fetch(repo: dict) -> tuple[str, dict[str, list[dict]]]:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo["nameWithOwner"],
             "--json", "number,title,author,headRefName"],
            capture_output=True, text=True,
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
                    console.print(f"    [dim]#{p['number']}[/dim]  {p['title']}")
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
    matches = [
        r for r in repo_list
        if r["name"].lower() == name_lower or r["nameWithOwner"].lower() == name_lower
    ]
    if not matches:
        pat = name_lower if "*" in name_lower or "?" in name_lower else f"*{name_lower}*"
        matches = [r for r in repo_list if fnmatch.fnmatch(r["name"].lower(), pat)]

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
    if not gh_auth_module.ensure_org_account(cfg.orgs, repo_owner):
        console.print("[red]No gh account with underscore found for org repos.[/red]")
        raise typer.Exit(1)
    new_active = gh_auth_module.active_account(gh_auth_module.get_accounts())
    if new_active and active and new_active.username != active.username:
        console.print(f"[dim]switched gh account → {new_active.username}[/dim]")

    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "repo", "clone", found["nameWithOwner"], str(target)], check=True)
