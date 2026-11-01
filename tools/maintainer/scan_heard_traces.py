#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Report, without content, whether episodic traces hold heard text.

Read-only. It scans episodic memory traces written before the store kept heard
words and undeclared payloads out of the trace text, and reports for each
source how many traces it read, how many hold a member that may carry heard
text, the member types involved and the ids of the flagged traces. It never
prints, logs or writes any trace text, and it never changes a store, a fork
snapshot or a preservation bundle. Rewriting a preserved being is the
operator's decision.

Sources:

* ``--sqlite PATH``: a sqlite-vec episodic store, opened read-only.
* ``--snapshot PATH``: a fork snapshot file (``snapshot.json``).
* ``--fork-root DIR``: every fork snapshot under a fork root (``state/forks``).
* ``--bundle DIR``: a preservation bundle directory (``bundle.tar.enc``,
  ``bundle.tar`` or the loose layout).
* ``--qdrant-host HOST``: a running Qdrant store, read by scrolling payloads
  without vectors; the API key is read from the environment variable named by
  ``--qdrant-api-key-env`` (default ``QDRANT_API_KEY``).

Encrypted snapshots and bundles are decrypted in memory with the state key
(``KAINE_STATE_KEY`` or the kernel keyring), as revive does.

A member is flagged as:

* ``external_input``: an ``audition.transcription`` or ``embodiment.chat``
  member that kept its payload;
* ``heard_field``: a member whose payload holds a non-empty heard-text field
  under the shared heard rule (``kaine.faithful.external_input``);
* ``undeclared_text``: a member of a type outside ``INTERNAL_EVENT_TYPES``
  whose payload holds any non-empty string, which could be heard words under
  another field name;
* ``unparsed``: a member whose payload could not be read back and holds a
  quoted string, counted on the safe side.

Module names stored before the functional rename are mapped to their current
names first. The entity's own speech is not flagged; heard words it repeated
cannot be told apart from its own words. A sqlite store is opened with
``mode=ro``; SQLite may still need the store's ``-shm`` file to read a store
left in WAL mode.

Exit status: 0 when nothing is flagged, 1 when anything is flagged, 2 when a
source could not be read.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kaine.faithful.external_input import (  # noqa: E402
    EXTERNAL_INPUT_TYPES,
    INTERNAL_EVENT_TYPES,
    heard_texts,
    iter_text_leaves,
)

# Payload markers the store writes in place of a payload; a member holding one
# carries no content.
_CONTENT_FREE_PREFIXES = (
    "<heard omitted>",
    "<raw-perceptual omitted>",
    "<unclassified omitted>",
    "<replay of ",
)

# A member header in the trace text: `source:type=` at the start of the text or
# after the " | " separator.
_MEMBER_HEADER = re.compile(r"(?:^|(?<= \| ))([A-Za-z0-9_]+):([A-Za-z0-9_.]+)=")

CATEGORIES = ("external_input", "heard_field", "undeclared_text", "unparsed")


@dataclass
class SourceReport:
    """Counts and ids for one scanned source. Holds no trace text."""

    source: str
    traces: int = 0
    flagged: int = 0
    by_category: dict[str, int] = field(default_factory=lambda: {c: 0 for c in CATEGORIES})
    by_member_type: dict[str, int] = field(default_factory=dict)
    flagged_ids: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "traces": self.traces,
            "flagged": self.flagged,
            "by_category": dict(self.by_category),
            "by_member_type": dict(sorted(self.by_member_type.items())),
            "flagged_ids": list(self.flagged_ids),
            "error": self.error,
        }


def _members(text: str) -> Iterator[tuple[str, str, str]]:
    """Yield ``(source, type, payload text)`` for each member of a trace text."""
    headers = list(_MEMBER_HEADER.finditer(text))
    for i, match in enumerate(headers):
        end = headers[i + 1].start() - len(" | ") if i + 1 < len(headers) else len(text)
        yield match.group(1), match.group(2), text[match.end():max(end, match.end())]


def _current_names(source: str, type_: str) -> tuple[str, str]:
    """Map a module name stored before the functional rename to its current name."""
    from kaine import legacy_aliases

    new_source = legacy_aliases.map_module_key(source)
    if new_source != source and type_.startswith(source + "."):
        type_ = new_source + type_[len(source):]
    return new_source, type_


# Python reprs of non-finite floats, which ast.literal_eval does not read.
_NON_FINITE = re.compile(r"(?<![\w'\"])-?(?:nan|inf)(?![\w'\"])")
# A heard-text key followed by a non-empty string or a container, in a payload repr.
_HEARD_FIELD_REPR = re.compile(
    r"['\"](?:text|user_input|user_text|transcription|heard_text|faithful_rendering)['\"]"
    r"\s*:\s*(?:'\s*[^'\s]|\"\s*[^\"\s]|[\[{(])"
)


def classify_member(source: str, type_: str, value: str) -> str | None:
    """Return the flag category of one member, or None when it holds no heard text."""
    stripped = value.strip()
    if stripped.startswith(_CONTENT_FREE_PREFIXES):
        return None
    source, type_ = _current_names(source, type_)
    if type_ in EXTERNAL_INPUT_TYPES:
        return "external_input"
    declared = (source, type_) in INTERNAL_EVENT_TYPES
    try:
        payload = ast.literal_eval(_NON_FINITE.sub("None", stripped))
    except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
        payload = None
    if isinstance(payload, dict):
        event = SimpleNamespace(source=source, type=type_, payload=payload)
        if heard_texts(event):
            return "heard_field"
        if not declared and any(iter_text_leaves(payload)):
            return "undeclared_text"
        return None
    # The payload could not be read back: decide on the safe side.
    if declared:
        if source != "language" and _HEARD_FIELD_REPR.search(stripped):
            return "unparsed"
        return None
    if "'" in stripped or '"' in stripped:
        return "unparsed"
    return None


def classify_trace(text: str) -> list[tuple[str, str]]:
    """Return ``(category, "source:type")`` for each flagged member of a trace text."""
    found: list[tuple[str, str]] = []
    for source, type_, value in _members(text):
        category = classify_member(source, type_, value)
        if category is not None:
            found.append((category, f"{source}:{type_}"))
    return found


def scan_traces(source: str, traces: Iterable[tuple[str, str]]) -> SourceReport:
    """Scan ``(trace id, trace text)`` pairs into a content-free report."""
    report = SourceReport(source=source)
    for trace_id, text in traces:
        report.traces += 1
        if not isinstance(text, str) or not text:
            continue
        found = classify_trace(text)
        if not found:
            continue
        report.flagged += 1
        report.flagged_ids.append(str(trace_id))
        for category, member_type in found:
            report.by_category[category] += 1
            report.by_member_type[member_type] = report.by_member_type.get(member_type, 0) + 1
    return report


# --- readers (read-only) ------------------------------------------------------


def sqlite_traces(path: Path) -> Iterator[tuple[str, str]]:
    """Yield traces from a sqlite-vec store opened read-only."""
    if not path.is_file():
        raise FileNotFoundError(f"no such store file: {path}")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = db.execute("SELECT collection, point_id, text FROM memories")
        for collection, point_id, text in cur:
            yield f"{collection}:{point_id}", str(text or "")
    finally:
        db.close()


def memory_state_traces(memory_state: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield traces from an episodic memory capture (``export_state`` output)."""
    for i, entry in enumerate(memory_state.get("short_term") or []):
        if isinstance(entry, dict):
            yield f"short_term[{i}]", str(entry.get("text") or "")
    for collection, points in (memory_state.get("persisted") or {}).items():
        for point in points or []:
            if isinstance(point, dict):
                yield f"{collection}:{point.get('id')}", str(point.get("text") or "")


def _snapshot_memory_states(snapshot_text: str) -> Iterator[tuple[str, dict[str, Any]]]:
    from kaine.lifecycle.snapshot import ForkSnapshot

    snap = ForkSnapshot.from_dict(json.loads(snapshot_text))
    for module_name, state in sorted(snap.modules.items()):
        if isinstance(state, dict) and isinstance(state.get("memory_state"), dict):
            yield module_name, state["memory_state"]


def snapshot_text_traces(snapshot_text: str) -> Iterator[tuple[str, str]]:
    for module_name, memory_state in _snapshot_memory_states(snapshot_text):
        for trace_id, text in memory_state_traces(memory_state):
            yield f"{module_name}/{trace_id}", text


def install_state_key() -> None:
    """Install the state encryptor from the environment or the kernel keyring,
    as boot does, so encrypted snapshots and bundles can be read in memory."""
    from kaine.security.crypto import install_from_section

    install_from_section({})


def snapshot_file_traces(path: Path) -> Iterator[tuple[str, str]]:
    from kaine.security.crypto import get_state_encryptor

    text = get_state_encryptor().maybe_decrypt(path.read_bytes()).decode("utf-8")
    yield from snapshot_text_traces(text)


def bundle_traces(bundle: Path) -> Iterator[tuple[str, str]]:
    from kaine.lifecycle.preservation import _read_bundle_members

    members = _read_bundle_members(bundle)
    text = members.get("snapshot.json")
    if text is None:
        raise FileNotFoundError(f"no snapshot.json in bundle {bundle}")
    yield from snapshot_text_traces(text)


def qdrant_traces(host: str, port: int, api_key: str | None, prefixes: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    from qdrant_client import QdrantClient  # type: ignore[import-untyped]

    client = QdrantClient(host=host, port=port, api_key=api_key, https=False)
    try:
        names = sorted(c.name for c in client.get_collections().collections)
        for name in names:
            if not name.startswith(prefixes):
                continue
            offset = None
            while True:
                batch, offset = client.scroll(
                    collection_name=name,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in batch:
                    payload = dict(getattr(point, "payload", None) or {})
                    yield f"{name}:{point.id}", str(payload.get("text") or "")
                if offset is None:
                    break
    finally:
        client.close()


def _scan(source: str, traces: Iterable[tuple[str, str]]) -> SourceReport:
    try:
        return scan_traces(source, traces)
    except Exception as exc:  # report the failure (type and message), never trace text
        report = SourceReport(source=source)
        report.error = f"{type(exc).__name__}: {exc}"[:300]
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sqlite", type=Path, action="append", default=[])
    parser.add_argument("--snapshot", type=Path, action="append", default=[])
    parser.add_argument("--fork-root", type=Path, action="append", default=[])
    parser.add_argument("--bundle", type=Path, action="append", default=[])
    parser.add_argument("--qdrant-host")
    parser.add_argument("--qdrant-port", type=int, default=6533)
    parser.add_argument("--qdrant-api-key-env", default="QDRANT_API_KEY")
    parser.add_argument(
        "--collection-prefix",
        action="append",
        default=None,
        help="Qdrant collection prefixes to scan (default: episodic_memory_ and mnemos_)",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)
    if args.snapshot or args.fork_root or args.bundle:
        install_state_key()

    reports: list[SourceReport] = []
    for path in args.sqlite:
        reports.append(_scan(f"sqlite:{path}", sqlite_traces(path)))
    snapshot_paths = list(args.snapshot)
    for root in args.fork_root:
        snapshot_paths.extend(sorted(root.glob("*/snapshot.json")))
    for path in snapshot_paths:
        reports.append(_scan(f"snapshot:{path}", snapshot_file_traces(path)))
    for bundle in args.bundle:
        reports.append(_scan(f"bundle:{bundle}", bundle_traces(bundle)))
    if args.qdrant_host:
        prefixes = tuple(args.collection_prefix or ("episodic_memory_", "mnemos_"))
        api_key = os.environ.get(args.qdrant_api_key_env) or None
        reports.append(
            _scan(
                f"qdrant:{args.qdrant_host}:{args.qdrant_port}",
                qdrant_traces(args.qdrant_host, args.qdrant_port, api_key, prefixes),
            )
        )
    if not reports:
        parser.error("name at least one source")

    if args.json:
        print(json.dumps({"reports": [r.to_dict() for r in reports]}, indent=2, sort_keys=True))
    else:
        for r in reports:
            if r.error:
                print(f"{r.source}: ERROR {r.error}")
                continue
            print(f"{r.source}: {r.traces} traces, {r.flagged} flagged")
            for category in CATEGORIES:
                if r.by_category[category]:
                    print(f"  {category}: {r.by_category[category]} members")
            for member_type, count in sorted(r.by_member_type.items()):
                print(f"  {member_type}: {count} members")
            for trace_id in r.flagged_ids:
                print(f"  flagged trace: {trace_id}")
    if any(r.error for r in reports):
        return 2
    return 1 if any(r.flagged for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
