import argparse
import sys

from xmas import fetch, pick
from xmas.config import ConfigError, load_groups, load_items
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

    args = parser.parse_args()
    try:
        items = load_items(args.year, load_groups())
    except ConfigError as e:
        sys.exit(f"error: {e}")
    state = State(args.year)

    if args.command == "fetch":
        print(f"Fetching images for {len(items)} item(s)")
        failures = fetch.run(items, state, refresh=args.refresh)
        sys.exit(1 if failures else 0)
    if args.command == "pick":
        sys.exit(pick.run(args.year, items, state, port=args.port, show_all=args.all))
