import argparse
import sys

from xmas import auth, boards, fetch, pick
from xmas.config import ConfigError, load_groups, load_items
from xmas.pinterest import Client, PinterestError
from xmas.state import State


def main() -> None:
    parser = argparse.ArgumentParser(prog="xmas", description="Manage yearly Christmas wish-list boards on Pinterest.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="cache item images and scrape candidates for items without one")
    p_fetch.add_argument("year", type=int)
    p_fetch.add_argument("--refresh", action="store_true", help="re-download images and re-scrape pages even if cached")

    p_pick = sub.add_parser("pick", help="choose images for items from scraped candidates")
    p_pick.add_argument("year", type=int)
    p_pick.add_argument("--all", action="store_true", help="include items that already have a pick")
    p_pick.add_argument("--port", type=int, default=8086)

    p_auth = sub.add_parser("auth", help="log in to Pinterest (one time; refreshes automatically after)")
    p_auth.add_argument("--port", type=int, default=auth.DEFAULT_PORT)

    sub.add_parser("boards", help="list your Pinterest boards (checks that login works)")

    p_rollover = sub.add_parser("rollover", help="make last year's boards secret")
    p_rollover.add_argument("year", type=int, help="the new year; boards for year - 1 are retired")
    p_rollover.add_argument("--dry-run", action="store_true", help="show what would change without changing anything")

    p_sync = sub.add_parser("sync", help="create this year's boards and pin new items")
    p_sync.add_argument("year", type=int)
    p_sync.add_argument("--dry-run", action="store_true", help="show what would change without changing anything")
    p_sync.add_argument("--skip-rollover-check", action="store_true", help="don't require last year's boards to be secret")

    args = parser.parse_args()
    try:
        sys.exit(_run(args))
    except (ConfigError, PinterestError) as e:
        sys.exit(f"error: {e}")


def _run(args) -> int:
    if args.command == "auth":
        return auth.run(port=args.port)
    if args.command == "boards":
        for b in sorted(Client().boards(), key=lambda b: b.get("name", "")):
            print(f"  {b.get('privacy', '?'):8} {b.get('pin_count', '?'):>4} pins  {b.get('name')}")
        return 0

    groups = load_groups()
    if args.command == "rollover":
        return boards.rollover(args.year, groups, dry_run=args.dry_run)

    items = load_items(args.year, groups)
    state = State(args.year)
    if args.command == "fetch":
        print(f"Fetching images for {len(items)} item(s)")
        return 1 if fetch.run(items, state, refresh=args.refresh) else 0
    if args.command == "pick":
        return pick.run(args.year, items, state, port=args.port, show_all=args.all)
    if args.command == "sync":
        return boards.sync(args.year, groups, items, state, dry_run=args.dry_run, skip_rollover_check=args.skip_rollover_check)
    return 1
