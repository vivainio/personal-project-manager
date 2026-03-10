# ppm — Personal Project Manager

CLI for managing GitHub repos, local clones, pull requests, and ticket branches across multiple organizations and projects.

## Install

```bash
pip install personal-project-manager
```

Or with uv:

```bash
uv tool install personal-project-manager
```

## Quick Start

```bash
ppm repos                  # List all your GitHub repos
ppm repos myproject        # Filter by project name or substring
ppm clone my-repo          # Clone to the right place
ppm pr myproject           # Open PRs across a project
ppm tickets list           # Ticket branches checked out locally
```

## Configuration

On first run, `~/.config/ppm/config.yaml` is created automatically:

```yaml
# Local directory where repos are cloned
repos_root: ~/r

# GitHub orgs to include in repo listing
orgs:
  - myorg

# Associate repos to named projects by repo name prefix
projects:
  foo:
    prefixes:
      - foo-
  bar:
    prefixes:
      - bar-

# Fetch ticket summaries via zaira CLI (optional)
zaira: false
```

Add projects with:

```bash
ppm projects add myproject myproject-
```

## Commands

### `ppm repos [filter]`

List GitHub repos. Shows local clone path (green = expected location, yellow = custom path) and checked-out branch when filtered.

```bash
ppm repos                  # All repos
ppm repos myproject        # Filter by project name
ppm repos splunk           # Substring match
ppm repos "foo*"           # Glob pattern
ppm repos --refresh        # Bypass 1h cache
```

### `ppm clone <repo>`

Clone a repo to its expected path (`repos_root / project / repo-name`). Uses SSH on Linux if available.

```bash
ppm clone my-repo          # Prompts for confirmation
ppm clone my-repo --yes    # Skip prompt
```

### `ppm pr <project-or-repo>`

List open pull requests grouped by repo → author, with PR age.

```bash
ppm pr myproject           # All PRs in a project
ppm pr my-repo             # PRs for a specific repo
```

### `ppm tickets`

Show ticket branches (e.g. `AC-1234`) checked out across local repos.

```bash
ppm tickets list           # All checked-out ticket branches
ppm tickets list myproject # Scoped to project
ppm tickets search cdk     # Search cached ticket summaries
```

### `ppm here`

Register the current directory as the clone location for the detected repo (when it differs from the expected path).

```bash
ppm here                   # Register current repo
ppm here -r                # Recursively scan child dirs
```

### `ppm projects`

```bash
ppm projects list          # Show configured projects
ppm projects add foo foo-  # Add a project
```

## Multiple GitHub Accounts

`ppm` handles multiple `gh` CLI accounts automatically:

- When listing repos or cloning **org repos**, it switches to the account with `_` in the username (corporate account)
- When cloning from a personal account, it uses the account without `_`

## Zaira Integration

If `zaira: true` is set in config, `ppm tickets list` fetches Jira ticket summaries and `ppm tickets search` lets you search them. Summaries are cached permanently in `~/.cache/ppm/tickets.json`.

See [zaira](https://github.com/vivainio/zaira) for setup.
