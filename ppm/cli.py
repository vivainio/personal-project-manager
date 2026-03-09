"""ppm CLI entry point."""

import fnmatch
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ppm import config as config_module
from ppm import locations as locations_module
from ppm import repos as repos_module

app = typer.Typer(help="Personal project manager", no_args_is_help=True)


@app.callback()
def main() -> None:
    pass


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
    table.add_column("Language", no_wrap=True, ratio=1)
    table.add_column("Updated", no_wrap=True, width=11)
    table.add_column("Path", no_wrap=True, ratio=2)
    table.add_column("Description", ratio=3)

    for repo in repo_list:
        name = repo["name"]
        lang = (repo["primaryLanguage"] or {}).get("name", "")
        updated = repo["updatedAt"][:10]
        visibility = "[dim]🔒[/dim] " if repo["isPrivate"] else ""
        display_name = f"{visibility}{repo['nameWithOwner']}"
        proj = cfg.project_for(name) or ""

        expected = locations_module.expected_path(name, cfg)
        override = locations_module.get_location(name)
        local_path = override or expected
        exists = local_path.exists()

        if not exists:
            path_str = ""
        elif override:
            path_str = f"[yellow]{local_path}[/yellow]"
        else:
            path_str = f"[green]{local_path}[/green]"

        row = [display_name]
        if show_project_col:
            row.append(f"[cyan]{proj}[/cyan]" if proj else "")
        row += [lang, updated, path_str, repo["description"] or ""]
        table.add_row(*row)

    console.print(table)
    console.print(f"[dim]{len(repo_list)} repos[/dim]")


def _register_git_dir(git_dir: Path, cfg: config_module.Config) -> None:
    """Register a single git directory if its path differs from the expected convention."""
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
