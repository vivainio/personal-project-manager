"""ppm CLI entry point."""

import typer
from rich.console import Console
from rich.table import Table

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
) -> None:
    """List GitHub repositories."""
    with console.status("Loading repos..."):
        repo_list = repos_module.get_repos(refresh=refresh)

    if not forks:
        repo_list = [r for r in repo_list if not r["isFork"]]

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Repo", style="bold", no_wrap=True, ratio=3)
    table.add_column("Language", no_wrap=True, ratio=1)
    table.add_column("Updated", no_wrap=True, width=11)
    table.add_column("Description", ratio=3)

    for repo in repo_list:
        lang = (repo["primaryLanguage"] or {}).get("name", "")
        updated = repo["updatedAt"][:10]
        visibility = "[dim]🔒[/dim] " if repo["isPrivate"] else ""
        name = f"{visibility}{repo['nameWithOwner']}"
        table.add_row(name, lang, updated, repo["description"] or "")

    console.print(table)
    console.print(f"[dim]{len(repo_list)} repos[/dim]")
