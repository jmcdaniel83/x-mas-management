# x-mas-management

A personal tool for managing my yearly Christmas wish-list boards on Pinterest.

Each year it:

- creates a new board for the current year's Christmas list
- sets the previous year's board to secret so it no longer shows on my profile

It uses the [Pinterest API v5](https://developers.pinterest.com/docs/api/v5/) and only accesses the account of its author.

See [PRIVACY.md](PRIVACY.md) for the privacy policy.

## Usage

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
cp examples/groups.toml data/groups.toml                      # once; fill in collaborators
cp examples/xmas-list.toml data/lists/xmas-list-2026.toml     # each year
uv run xmas fetch 2026     # cache provided images, scrape candidates for items without one
uv run xmas pick 2026      # choose images in a local browser page (--all to redo existing picks)
```

Personal data lives in `data/` (gitignored); set `XMAS_DATA` to use another location. See [DESIGN.md](DESIGN.md) for the file formats.
