---
name: ppm
description: Personal project manager CLI. Use when the user asks about GitHub repos, projects, PRs, local clones, or ticket branch status. Wraps gh CLI with project-aware config.
---

# ppm - Personal Project Manager

CLI for managing GitHub repos, projects, clones, PRs, and ticket branches.

Config: `~/.config/ppm/config.yaml`
Cache: `~/.cache/ppm/`
Run with: `uv run ppm <command>` (from `/home/v/r/ppm`) or `ppm` if installed globally.

## Commands

```bash
# Repos
ppm repos                        # List all GitHub repos (cached 1h)
ppm repos dh                     # Filter by project name
ppm repos splunk                 # Substring/glob filter
ppm repos --refresh              # Bypass cache and re-fetch

# Cloning
ppm clone <repo>                 # Clone to expected path (prompts confirm)
ppm clone <repo> --yes           # Skip confirmation
# Uses SSH on Linux if available, falls back to gh repo clone
# Switches gh auth account to org account (underscore) if needed

# Pull requests
ppm pr <project-or-repo>         # List open PRs grouped by repo → author
# Shows PR number, age (3d, 5mo), branch, title

# Ticket branches
ppm tickets list                 # Show checked-out ticket branches (e.g. AC-1682)
ppm tickets list dh              # Scoped to project or repo pattern
ppm tickets search <query>       # Search cached ticket summaries

# Projects
ppm projects list                # Show configured projects
ppm projects add <name> <prefix> # Add project (e.g. ppm projects add dh dh-)

# Location tracking
ppm here                         # Register current dir as clone location (if non-standard)
ppm here -r                      # Recursively scan child dirs for git repos
```

## Config (`~/.config/ppm/config.yaml`)

```yaml
repos_root: ~/r          # Root dir for clones
zaira: true              # Fetch ticket summaries via zaira CLI

orgs:
  - myorg                # GitHub orgs to include in repo listing

projects:
  foo:
    prefixes:
      - foo-
  bar:
    prefixes:
      - bar-
```

## Key Conventions

- **Expected clone path**: `repos_root / project / repo-name` (e.g. `~/r/foo/foo-core`)
- **Non-standard paths** recorded in `~/.cache/ppm/locations.json` via `ppm here`
- **Path colors**: green = at expected location, yellow = override path recorded
- **Branch column** only shown when a filter is active (too slow for all repos)
- **Ticket IDs** extracted from branch names matching `[A-Z]+-\d+` (e.g. `AC-1682`)
- **Ticket summaries** fetched via `zaira get --min` and cached permanently

## Files

| File | Purpose |
|------|---------|
| `ppm/cli.py` | All commands |
| `ppm/repos.py` | gh repo list fetching |
| `ppm/config.py` | Config loading (ruamel.yaml, preserves comments) |
| `ppm/cache.py` | JSON file cache in `~/.cache/ppm/` |
| `ppm/locations.py` | Local clone path tracking + git helpers |
| `ppm/gh_auth.py` | gh auth account switching + SSH detection |
