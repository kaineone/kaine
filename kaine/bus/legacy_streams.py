# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""One-time cleanup of Redis streams left under their old names.

After the ``keys`` codemod scope renames every module bus stream (for example
``hypnos.out`` to ``sleep.out``), the old streams remain in Redis as capped
orphans. Because KAINE runs Redis with ``noeviction``, nothing ever evicts them
and they continue to consume memory. This module surveys the old names once,
reports what is safe to delete, and deletes it after an explicit confirmation.

Run from the command line::

    python -m kaine.bus.legacy_streams [--delete]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import redis

from kaine import legacy_aliases
from kaine.bus.config import load_bus_config
from kaine.bus.schema import module_stream
from kaine.bus.streams import KNOWN_STREAMS

LIVE_EXTRA = frozenset({"cycle.control", module_stream("positive_control")})


def live_streams() -> frozenset[str]:
    return KNOWN_STREAMS | LIVE_EXTRA


@dataclass(frozen=True)
class OldStream:
    old: str
    new: str
    present: bool
    is_stream: bool
    length: int
    memory_bytes: int


def stream_map() -> list[tuple[str, str]]:
    table = legacy_aliases._table()
    pairs = [
        (entry["old"], entry["new"])
        for entry in legacy_aliases.active(table.STREAM_NAMES)
        if entry["old"] != entry["new"]
    ]
    return sorted(pairs)


def survey(client) -> list[OldStream]:
    entries: list[OldStream] = []
    for old, new in stream_map():
        present = bool(client.exists(old))
        is_stream = present and client.type(old) in ("stream", b"stream")
        length = client.xlen(old) if is_stream else 0
        memory_bytes = 0
        if present:
            try:
                memory_bytes = client.memory_usage(old) or 0
            except Exception:
                memory_bytes = 0
        entries.append(
            OldStream(
                old=old,
                new=new,
                present=present,
                is_stream=is_stream,
                length=length,
                memory_bytes=memory_bytes,
            )
        )
    return entries


def deletable(entries: list[OldStream]) -> list[OldStream]:
    live = live_streams()
    orphaned = set(legacy_aliases.orphaned_stream_names(live))
    return [
        entry
        for entry in entries
        if entry.present and entry.is_stream and entry.old in orphaned and entry.old not in live
    ]


def delete(client, entries: list[OldStream]) -> list[str]:
    removed: list[str] = []
    for entry in entries:
        if client.type(entry.old) not in ("stream", b"stream"):
            continue
        client.unlink(entry.old)
        removed.append(entry.old)
    return removed


def _render_status(entry: OldStream) -> str:
    if not entry.present:
        return "absent"
    if not entry.is_stream:
        return "not a stream (kept)"
    if entry.old in live_streams():
        return "live (kept)"
    return f"{entry.length} entries, {entry.memory_bytes} bytes"


def main(argv=None, *, client=None, input_fn=input, out=sys.stdout, err=sys.stderr) -> int:
    parser = argparse.ArgumentParser(
        prog="kaine.bus.legacy_streams",
        description="Survey and delete old-named KAINE bus streams after the keys rename.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete the old streams after asking for confirmation",
    )
    args = parser.parse_args(argv)

    if not legacy_aliases.scope_done("keys"):
        err.write("the keys rename has not run; there are no old-named streams to clean up\n")
        return 0

    close_when_done = client is None
    if client is None:
        try:
            cfg = load_bus_config()
            client = redis.Redis.from_url(
                cfg.url,
                socket_connect_timeout=2.0,
                socket_timeout=5.0,
            )
            client.ping()
        except Exception as exc:
            err.write(
                f"legacy_streams: cannot reach or authenticate to the bus ({type(exc).__name__})\n"
            )
            return 8

    try:
        entries = survey(client)
        for entry in entries:
            out.write(f"  {entry.old:<32} -> {entry.new:<32} {_render_status(entry)}\n")

        to_delete = deletable(entries)
        n = len(to_delete)
        total_bytes = sum(entry.memory_bytes for entry in to_delete)
        out.write(f"{n} old-named streams to delete, {total_bytes} bytes\n")

        if not args.delete:
            out.write("Nothing deleted. Run again with --delete to remove them.\n")
            return 0

        if not to_delete:
            out.write("Nothing to delete.\n")
            return 0

        confirmation = input_fn(
            f"Type DELETE {n} OLD STREAMS to delete them (anything else aborts):\n> "
        ).strip()
        if confirmation != f"DELETE {n} OLD STREAMS":
            out.write("Aborted; nothing deleted.\n")
            return 5

        for name in delete(client, to_delete):
            out.write(f"  deleted: {name}\n")
        return 0
    finally:
        if close_when_done and client is not None:
            try:
                client.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
