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
cp .env.example .env                                          # once; add the Pinterest app ID and secret
```

Each year:

```sh
uv run xmas fetch 2026              # cache provided images, scrape candidates for items without one
uv run xmas pick 2026               # choose images in a local browser page (--all to redo existing picks)
uv run xmas rollover 2026 --dry-run # preview, then run without --dry-run: makes the 2025 boards secret
uv run xmas sync 2026 --dry-run     # preview, then run without --dry-run: creates 2026 boards and pins new items
```

`sync` can be re-run any time; it only pins items that aren't pinned yet. It refuses to run while last year's boards are still public.

Pinterest login:

```sh
uv run xmas auth     # one time; the app's redirect URI must be http://localhost:8085/callback
uv run xmas boards   # list boards to check the login works
```

The token is saved to `data/.token.json` and refreshes automatically; re-run `auth` about once a year when it expires.

Collaborators are not yet automated: `rollover` and `sync` print who to remove from and invite to each board.

Personal data lives in `data/` (gitignored); set `XMAS_DATA` to use another location. See [DESIGN.md](DESIGN.md) for the file formats.
