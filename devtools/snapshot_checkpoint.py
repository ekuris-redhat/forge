#!/usr/bin/env python3
"""Snapshot and restore workflow checkpoint state for a ticket.

Usage:
    # Save current state to a file
    uv run python devtools/snapshot_checkpoint.py snapshot AISOS-376
    uv run python devtools/snapshot_checkpoint.py snapshot AISOS-376 --label before-ci-fix

    # List saved snapshots for a ticket
    uv run python devtools/snapshot_checkpoint.py list AISOS-376

    # Restore state from a snapshot (dry-run by default)
    uv run python devtools/snapshot_checkpoint.py restore AISOS-376 devtools/snapshots/AISOS-376_20260505_143201.json
    uv run python devtools/snapshot_checkpoint.py restore AISOS-376 devtools/snapshots/AISOS-376_20260505_143201.json --apply

Snapshots are saved to devtools/snapshots/ by default.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


async def _read_state(ticket_key: str):
    """Try FEATURE then BUG graph to find state for the ticket."""
    from forge.models.workflow import TicketType
    from forge.orchestrator.checkpointer import get_checkpointer
    from forge.workflow.registry import create_default_router

    checkpointer = await get_checkpointer()
    router = create_default_router()
    config = {"configurable": {"thread_id": ticket_key}}

    for ticket_type in (TicketType.FEATURE, TicketType.BUG):
        workflow_instance = router.resolve(ticket_type=ticket_type, labels=[], event={})
        if not workflow_instance:
            continue
        graph = workflow_instance.build_graph()
        compiled = graph.compile(checkpointer=checkpointer)
        state = await compiled.aget_state(config)
        if state and state.values:
            return compiled, state, ticket_type.value

    return None, None, None


def _serialize(value):
    """Recursively make a value JSON-serializable."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


async def cmd_snapshot(ticket_key: str, label: str | None, snapshots_dir: Path) -> None:
    _, state, ticket_type = await _read_state(ticket_key)

    if not state:
        print(f"No checkpoint found for {ticket_key}")
        sys.exit(1)

    snapshots_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ticket_key}_{timestamp}"
    if label:
        safe_label = label.replace(" ", "-").replace("/", "-")
        filename += f"_{safe_label}"
    filename += ".json"

    snapshot = {
        "ticket_key": ticket_key,
        "ticket_type": ticket_type,  # stored for reference; restore auto-detects
        "captured_at": datetime.now().isoformat(),
        "label": label,
        "state": _serialize(dict(state.values)),
    }

    out_path = snapshots_dir / filename
    out_path.write_text(json.dumps(snapshot, indent=2))

    print(f"Snapshot saved: {out_path}")
    print(f"  Ticket:  {ticket_key} ({ticket_type})")
    print(f"  Node:    {state.values.get('current_node', 'unknown')}")
    print(f"  Fields:  {len(state.values)}")
    if label:
        print(f"  Label:   {label}")


async def cmd_list(ticket_key: str, snapshots_dir: Path) -> None:
    if not snapshots_dir.exists():
        print(f"No snapshots directory found at {snapshots_dir}")
        return

    snapshots = sorted(snapshots_dir.glob(f"{ticket_key}_*.json"))
    if not snapshots:
        print(f"No snapshots found for {ticket_key}")
        return

    print(f"Snapshots for {ticket_key}:")
    for path in snapshots:
        try:
            data = json.loads(path.read_text())
            node = data["state"].get("current_node", "unknown")
            captured = data.get("captured_at", "unknown")
            label = f"  [{data['label']}]" if data.get("label") else ""
            print(f"  {path.name}{label}")
            print(f"    captured: {captured}  node: {node}")
        except Exception as e:
            print(f"  {path.name}  (unreadable: {e})")


async def cmd_restore(ticket_key: str, snapshot_path: Path, apply: bool) -> None:
    if not snapshot_path.exists():
        print(f"Snapshot file not found: {snapshot_path}")
        sys.exit(1)

    snapshot = json.loads(snapshot_path.read_text())

    if snapshot["ticket_key"] != ticket_key:
        print(
            f"Warning: snapshot was for {snapshot['ticket_key']}, "
            f"restoring to {ticket_key} — are you sure? (continuing anyway)"
        )

    saved_state: dict = snapshot["state"]

    # Read current state for comparison
    compiled, current_state, _ = await _read_state(ticket_key)
    if not current_state:
        print(f"No existing checkpoint found for {ticket_key} — cannot restore")
        sys.exit(1)

    current_values = dict(current_state.values)

    # Show diff
    all_keys = sorted(set(current_values) | set(saved_state))
    changed = {
        k for k in all_keys
        if current_values.get(k) != saved_state.get(k)
    }

    if not changed:
        print("Current state is identical to snapshot — nothing to restore")
        return

    print(f"Snapshot: {snapshot_path.name}")
    print(f"  Captured: {snapshot.get('captured_at', 'unknown')}")
    if snapshot.get("label"):
        print(f"  Label:    {snapshot['label']}")
    print(f"\n{'APPLYING' if apply else 'DRY RUN'} — {len(changed)} field(s) would change:\n")

    for k in sorted(changed):
        old = current_values.get(k)
        new = saved_state.get(k)
        old_str = json.dumps(old) if not isinstance(old, str) else repr(old)
        new_str = json.dumps(new) if not isinstance(new, str) else repr(new)
        # Truncate long values for display
        if len(old_str) > 80:
            old_str = old_str[:77] + "..."
        if len(new_str) > 80:
            new_str = new_str[:77] + "..."
        print(f"  {k}:")
        print(f"    current  → {old_str}")
        print(f"    snapshot → {new_str}")

    if not apply:
        print("\nRun with --apply to restore.")
        return

    config = {"configurable": {"thread_id": ticket_key}}
    await compiled.aupdate_state(config, saved_state)

    print(f"\nRestored {ticket_key} to snapshot state.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Snapshot and restore workflow checkpoint state for a ticket."
    )
    parser.add_argument(
        "--dir",
        default=str(SNAPSHOTS_DIR),
        help=f"Directory for snapshot files (default: {SNAPSHOTS_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # snapshot
    p_snap = sub.add_parser("snapshot", help="Save current state to a file")
    p_snap.add_argument("ticket_key", help="Jira ticket key (e.g. AISOS-376)")
    p_snap.add_argument("--label", help="Optional human-readable label for the snapshot")

    # list
    p_list = sub.add_parser("list", help="List saved snapshots for a ticket")
    p_list.add_argument("ticket_key", help="Jira ticket key")

    # restore
    p_restore = sub.add_parser("restore", help="Restore state from a snapshot file")
    p_restore.add_argument("ticket_key", help="Jira ticket key")
    p_restore.add_argument("snapshot_file", help="Path to snapshot JSON file")
    p_restore.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the restore (default is dry-run)",
    )

    args = parser.parse_args()
    snapshots_dir = Path(args.dir)

    if args.command == "snapshot":
        asyncio.run(cmd_snapshot(args.ticket_key, args.label, snapshots_dir))
    elif args.command == "list":
        asyncio.run(cmd_list(args.ticket_key, snapshots_dir))
    elif args.command == "restore":
        asyncio.run(cmd_restore(args.ticket_key, Path(args.snapshot_file), args.apply))


if __name__ == "__main__":
    main()
