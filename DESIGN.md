# Design

## Overview

Each year I keep a Christmas wish list per family. This tool turns those lists into Pinterest boards and retires the previous year's boards so they stop showing up for family members.

## Data layout

Everything under `data/` is personal and gitignored.

```
data/
  groups.toml                 # one table per family board
  lists/
    xmas-list-2026.toml       # items for the year, grouped by family
  images/                     # local images referenced by list items
  state/
    2026.json                 # board IDs, pin IDs, resolved images (written by the tool)
  cache/images/<url-hash>/    # candidate images scraped from item pages
```

Both files are TOML, read with Python's built-in `tomllib` (3.11+).

### groups.toml

```toml
[family]
board_name = "Christmas {year}"
collaborators = ["mom_pins", "bro123"]

[kelley]
board_name = "Christmas {year} (Kelley)"
collaborators = ["mil_pins", "sil_xyz"]
```

Group keys (`family`, `kelley`) are the same names used in the list file. Board names are matched exactly, so `Christmas 2025` never matches `Christmas 2025 (Kelley)`.

### xmas-list-2026.toml

Each `[[group]]` block adds one item to that group's board. `name` becomes the pin title.

```toml
[[family]]
name = "Lego Millennium Falcon"
url = "https://www.lego.com/en-us/product/millennium-falcon-75192"
image = "https://www.lego.com/cdn/.../75192.jpg"

[[family]]
name = "Wool Socks"
url = "https://example.com/socks"
image = "images/socks.jpg"
description = "Size L, any dark color"

[[kelley]]
name = "Cast Iron Skillet"
url = "https://example.com/skillet"
# no image -> `fetch` scrapes candidates and `pick` lets me choose
```

| Key | Required | Notes |
|---|---|---|
| `name` | yes | Pin title |
| `url` | yes | Link the pin points to |
| `image` | no | Image URL, or a path relative to `data/`. If omitted, the image is chosen through `fetch` / `pick` |
| `description` | no | Pin description (size, color, notes) |

A top-level key in the list file that isn't defined in `groups.toml` is an error, so a typo like `[[famly]]` is caught instead of silently creating a new board.

## Commands

| Command | What it does |
|---|---|
| `fetch <year>` | For items without an `image`, download the page and cache candidate images (`og:image`, product images) |
| `pick <year>` | Open a local page of thumbnails per item. The choice is saved to state |
| `rollover <year>` | For the previous year's boards: remove collaborators, then set privacy to secret |
| `sync <year>` | Create each group's board if missing, add its collaborators, and create pins for items not yet pinned |

Annual order: `rollover` → `sync`. Last year's boards are made private before the new ones show up, so family members never see two "Christmas" boards at the same time.

`sync` is idempotent. State records each item's pin ID, so re-running it during the season only pins new items. Every image is resolved to a cached local file and uploaded directly (`image_base64`), so pins don't depend on retailer image URLs staying alive.

## Pinterest API vs. browser automation

| Operation | Mechanism |
|---|---|
| List / create boards | API v5 (`GET` / `POST /v5/boards`) |
| Set board privacy | API v5 (`PATCH /v5/boards/{id}`) |
| Create pins | API v5 (`POST /v5/pins`) |
| Invite / remove collaborators | Playwright (not believed to be in the public API; to be verified) |

Collaborators can still see secret boards, so removing them is required for the old board to disappear from their view while staying visible to me.

## Open questions

- Does Trial access allow creating boards and pins that others can see, or only sandbox / creator-visible content?
- Confirm collaborator management is absent from the v5 API.
- Is a collaborator's username enough to invite them in the UI, or is an email needed?
