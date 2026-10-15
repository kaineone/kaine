# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""One-time cleanup of Redis streams left under their old names.

After the ``keys`` codemod scope renames every module bus stream (for example
the sleep module's stream is now ``sleep.out``), the old streams remain in
Redis as capped orphans. Because KAINE runs Redis with ``noeviction``, nothing ever evicts them
and they continue to consume memory. This module surveys the old names once,
reports what is safe to delete, and deletes it after an explicit confirmation.

Run from the command line::

    python -m kaine.bus.legacy_streams [--delete]

The command never deletes a stream the current release writes, a key that is not
a stream, or an old stream whose newest entry is less than ten minutes old (a
cycle or a study image from before the upgrade may still be writing it).
"""

from __future__ import annotations

import argparse
import sys
import time
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
    last_entry_ms: int = 0


def stream_map() -> list[tuple[str, str]]:
    table = legacy_aliases._table()
    pairs = [
        (entry["old"], entry["new"])
        for entry in legacy_aliases.active(table.STREAM_NAMES)
        if entry["old"] != entry["new"]
    ]
    return sorted(pairs)


def redis_now_ms(client) -> int:
    """Return the Redis server's current time in milliseconds.

    Falls back to the local clock if the Redis TIME command is unavailable.
    """
    try:
        seconds, microseconds = client.time()
        return int(seconds) * 1000 + int(microseconds) // 1000
    except Exception:
        return int(time.time() * 1000)


def survey(client, *, now_ms=None) -> list[OldStream]:
    if now_ms is None:
        now_ms = redis_now_ms(client)
    entries: list[OldStream] = []
    for old, new in stream_map():
        present = bool(client.exists(old))
        is_stream = present and client.type(old) in ("stream", b"stream")
        length = client.xlen(old) if is_stream else 0
        memory_bytes = 0
        last_entry_ms = 0
        if present:
            try:
                memory_bytes = client.memory_usage(old) or 0
            except Exception:
                memory_bytes = 0
            if is_stream:
                try:
                    newest = client.xrevrange(old, count=1)
                    if newest:
                        entry_id = newest[0][0]
                        if isinstance(entry_id, bytes):
                            entry_id = entry_id.decode("utf-8", "replace")
                        last_entry_ms = int(entry_id.split("-", 1)[0])
                except Exception:
                    # Age unknown: count it as just written so it is kept.
                    last_entry_ms = now_ms
        entries.append(
            OldStream(
                old=old,
                new=new,
                present=present,
                is_stream=is_stream,
                length=length,
                memory_bytes=memory_bytes,
                last_entry_ms=last_entry_ms,
            )
        )
    return entries


RECENT_WINDOW_MS = 10 * 60 * 1000


def is_recent(entry: OldStream, now_ms: int) -> bool:
    return bool(entry.last_entry_ms and now_ms - entry.last_entry_ms < RECENT_WINDOW_MS)


def deletable(entries: list[OldStream], *, now_ms=None) -> list[OldStream]:
    """The present old streams that may be deleted: orphaned, not live, not recently written."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    live = live_streams()
    orphaned = set(legacy_aliases.orphaned_stream_names(live))
    return [
        entry
        for entry in entries
        if entry.present
        and entry.is_stream
        and entry.old in orphaned
        and entry.old not in live
        and not is_recent(entry, now_ms)
    ]


def delete(client, entries: list[OldStream]) -> list[str]:
    removed: list[str] = []
    for entry in entries:
        if client.type(entry.old) not in ("stream", b"stream"):
            continue
        client.unlink(entry.old)
        removed.append(entry.old)
    return removed


def _render_status(entry: OldStream, now_ms: int) -> str:
    if not entry.present:
        return "absent"
    if not entry.is_stream:
        return "not a stream (kept)"
    if entry.old in live_streams():
        return "live (kept)"
    if is_recent(entry, now_ms):
        return "recently written (kept)"
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
        now_ms = redis_now_ms(client)
        entries = survey(client, now_ms=now_ms)
        for entry in entries:
            out.write(f"  {entry.old:<32} -> {entry.new:<32} {_render_status(entry, now_ms)}\n")

        to_delete = deletable(entries, now_ms=now_ms)
        n = len(to_delete)
        total_bytes = sum(entry.memory_bytes for entry in to_delete)
        out.write(f"{n} old-named streams to delete, {total_bytes} bytes\n")

        if not args.delete:
            out.write("Nothing deleted. Run again with --delete to remove them.\n")
            return 0

        if not to_delete:
            out.write("Nothing to delete.\n")
            return 0

        deletable_names = {entry.old for entry in to_delete}
        sleep_old = legacy_aliases.old_stream_name("sleep.out")
        external_old = legacy_aliases.old_stream_name("language.external")
        losses = []
        if external_old in deletable_names:
            losses.append(
                "from the dashboard's conversation history, what the entity said "
                "before the rename"
            )
        if sleep_old in deletable_names:
            losses.append(
                "the old sleep events the language module reads when it first looks "
                "for the last sleep index"
            )
        if losses:
            out.write(
                f"Deleting these also removes {', and '.join(losses)}. "
                "Research logs on disk are not affected.\n"
            )

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
