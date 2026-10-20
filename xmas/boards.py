"""Yearly board operations: `rollover` retires last year's boards, `sync` builds this year's."""

from xmas.config import Group, Item
from xmas.pinterest import Client, PinterestError, has_token
from xmas.state import State

SECRET = "SECRET"


class Remote:
    """Pinterest access for one command run. With dry_run, nothing is written; without a login, nothing is read either."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.client = Client() if has_token() or not dry_run else None
        self._boards = self.client.boards() if self.client else None

    @property
    def offline(self) -> bool:
        return self._boards is None

    def find(self, name: str) -> list[dict]:
        return [b for b in self._boards or [] if b.get("name") == name]

    def by_id(self, board_id: str) -> dict | None:
        return next((b for b in self._boards or [] if b.get("id") == board_id), None)


def _collaborator_note(action: str, group: Group, board_name: str) -> None:
    if group.collaborators:
        names = ", ".join(group.collaborators)
        print(f"    ! {action} collaborators on \"{board_name}\" by hand for now: {names}")


def rollover(year: int, groups: dict[str, Group], dry_run: bool) -> int:
    remote = Remote(dry_run)
    prefix = "[dry run] " if dry_run else ""
    if remote.offline:
        print(f"{prefix}Not logged in, so existing boards can't be checked. Showing the plan only.")
    errors = 0
    for group in groups.values():
        name = group.board_name(year - 1)
        print(f"  [{group.key}] \"{name}\"")
        if remote.offline:
            print("    would set to secret if it exists and is public")
            _collaborator_note("remove", group, name)
            continue

        matches = remote.find(name)
        if not matches:
            print("    no board with this name, nothing to do")
            continue
        if len(matches) > 1:
            errors += 1
            print(f"    ERROR: {len(matches)} boards share this name; rename one so the right board is changed")
            continue

        board = matches[0]
        _collaborator_note("remove", group, name)
        if board.get("privacy") == SECRET:
            print("    already secret")
        elif dry_run:
            print(f"    would change privacy {board.get('privacy')} -> SECRET")
        else:
            remote.client.set_board_privacy(board["id"], SECRET)
            print(f"    privacy {board.get('privacy')} -> SECRET")
    return 1 if errors else 0


def _previous_still_public(year: int, groups: list[Group], remote: Remote) -> list[str]:
    return [
        b["name"]
        for g in groups
        for b in remote.find(g.board_name(year - 1))
        if b.get("privacy") != SECRET
    ]


def _resolve_board(group: Group, year: int, state: State, remote: Remote) -> tuple[str | None, str]:
    """Board ID for this group's board, and what happened: 'existing', 'found', or 'create'."""
    name = group.board_name(year)
    saved = state.data["boards"].get(group.key)
    if saved and saved.get("name") == name and not remote.offline and remote.by_id(saved["id"]):
        return saved["id"], "existing"
    matches = [] if remote.offline else remote.find(name)
    if len(matches) > 1:
        raise PinterestError(f"{len(matches)} boards are named \"{name}\"; rename one so pins go to the right board")
    if matches:
        return matches[0]["id"], "found"
    return None, "create"


def sync(year: int, groups: dict[str, Group], items: list[Item], state: State, dry_run: bool, skip_rollover_check: bool) -> int:
    remote = Remote(dry_run)
    prefix = "[dry run] " if dry_run else ""
    if remote.offline:
        print(f"{prefix}Not logged in, so existing boards and pins can't be checked. Showing the plan only.")

    by_group = {key: [i for i in items if i.group == key] for key in groups}
    active = [groups[k] for k, group_items in by_group.items() if group_items]

    missing = [i for i in items if not state.image_path(i.key)]
    if missing:
        print("These items have no cached image; run `fetch` (and `pick`) first:")
        for i in missing:
            print(f"  [{i.group}] {i.name}")
        return 1

    if not skip_rollover_check and not remote.offline:
        public = _previous_still_public(year, active, remote)
        if public:
            print("Last year's boards are still visible; run `rollover` first (or pass --skip-rollover-check):")
            for name in public:
                print(f"  \"{name}\"")
            return 1

    errors = 0
    for group in active:
        name = group.board_name(year)
        try:
            board_id, how = _resolve_board(group, year, state, remote)
        except PinterestError as e:
            errors += 1
            print(f"  [{group.key}] ERROR: {e}")
            continue

        todo = [i for i in by_group[group.key] if not state.item(i.key).get("pin_id")]
        print(f"  [{group.key}] \"{name}\": {'create board, ' if how == 'create' else ''}"
              f"{len(todo)} new pin(s), {len(by_group[group.key]) - len(todo)} already pinned")

        if how == "create":
            if dry_run:
                board_id = None
                _collaborator_note("invite", group, name)
            else:
                board_id = remote.client.create_board(name)["id"]
                print("    board created")
                _collaborator_note("invite", group, name)
        if board_id:
            state.data["boards"][group.key] = {"id": board_id, "name": name}
            state.save()

        for item in by_group[group.key]:
            entry = state.item(item.key)
            if entry.get("pin_id"):
                if entry.get("pinned_image") and entry["pinned_image"] != entry.get("image"):
                    print(f"    note: {item.name}: image changed after pinning; the pin keeps the old image")
                continue
            if dry_run:
                print(f"    would pin {item.name}")
                continue
            try:
                pin = remote.client.create_pin(board_id, item.name, item.url, state.image_path(item.key), item.description)
            except PinterestError as e:
                errors += 1
                print(f"    FAILED {item.name}: {e}")
                continue
            entry.update(pin_id=pin["id"], pinned_image=entry.get("image"))
            state.save()
            print(f"    pinned {item.name}")

    listed = {i.key for i in items}
    orphans = [k for k, e in state.data["items"].items() if e.get("pin_id") and k not in listed]
    if orphans:
        print(f"{len(orphans)} pin(s) belong to items no longer in the list; delete them on Pinterest if unwanted.")
    return 1 if errors else 0
