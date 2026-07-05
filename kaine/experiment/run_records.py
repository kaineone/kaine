# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Post-run record loader for run admissibility / log validation.

Both the completeness gate (``admissibility.py``) and the range sweep
(``log_schema.py``) need the same thing: walk every JSONL sink file under the
evaluation root, decrypt each line, parse it, and yield the records that belong
to one run, grouped by their source sink/stream.

This module is boundary-neutral — it lives in ``kaine.experiment`` and imports
ONLY the standard library plus ``kaine.security.crypto`` (lazily). It never
imports ``kaine.evaluation``: the set of streams a run is *expected* to produce
is passed in as data by the caller, never derived by reaching into the
evaluation package.

Encryption is transparent: ``get_state_encryptor().decrypt_text`` decrypts a
line written with state encryption on and passes a plaintext line straight
through (``maybe_decrypt``), so a single read path handles both an encrypted and
a plaintext run.

A malformed line is NEVER raised on — it is counted as a parse error so the
admissibility gate can report it (a corrupt record is itself evidence the run is
not clean).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: Default evaluation root. Sink files live under this (directly or nested).
DEFAULT_ROOT = Path("data/evaluation")

#: The per-run manifest subdirectory name — never a record stream.
_RUNS_DIR = "runs"


@dataclass
class RunRecords:
    """Records of one run, grouped by stream, plus a parse-error count.

    ``by_stream`` maps a stream name (the sink file's ``<name>`` prefix, i.e.
    the part before ``-<UTC-date>.jsonl``) to the list of records carrying the
    target ``run_id`` from that stream, in file order. ``parse_errors`` counts
    lines that could not be decrypted/parsed into a JSON object across all
    scanned files (such a line cannot be attributed to a run, so it is a
    run-level signal).
    """

    run_id: str
    by_stream: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    parse_errors: int = 0

    def streams(self) -> set[str]:
        """Stream names that produced at least one record for this run."""
        return {s for s, recs in self.by_stream.items() if recs}

    def all_records(self) -> Iterable[tuple[str, dict[str, Any]]]:
        """Yield ``(stream, record)`` for every record across all streams."""
        for stream, recs in self.by_stream.items():
            for rec in recs:
                yield stream, rec


def _stream_name_for(path: Path) -> str:
    """Derive the stream name from a JSONL file name.

    Sink files are named ``<name>-<UTC-date>.jsonl`` (see
    ``kaine.persistence.jsonl_sink``). The stream identity is ``<name>`` — the
    portion before the trailing ``-YYYY-MM-DD`` date. If the name does not match
    that shape, the whole stem is used (robust to non-rotated test fixtures).
    """
    stem = path.stem  # drops ".jsonl"
    # Strip a trailing "-YYYY-MM-DD" if present.
    parts = stem.rsplit("-", 3)
    if len(parts) == 4:
        head, y, m, d = parts
        if y.isdigit() and m.isdigit() and d.isdigit() and head:
            return head
    return stem


def _iter_jsonl_files(root: Path) -> Iterable[Path]:
    """Yield every ``*.jsonl`` file under ``root`` except the manifest dir.

    The ``runs/`` directory holds per-run ``manifest.json`` files (not JSONL
    records) so it is skipped; any ``*.jsonl`` elsewhere is a candidate sink
    file.
    """
    if not root.exists():
        return
    runs_dir = root / _RUNS_DIR
    for path in sorted(root.rglob("*.jsonl")):
        try:
            path.relative_to(runs_dir)
            continue  # inside runs/ — manifests, not record streams
        except ValueError:
            pass
        if path.is_file():
            yield path


@dataclass
class RunDiscovery:
    """Result of enumerating the run(s) present in an eval-log tree.

    ``run_ids`` is the sorted set of DISTINCT, readable ``run_id`` values found.
    ``unreadable_lines`` counts lines (and whole files, on ``OSError``) that
    could NOT be decrypted/parsed into a JSON object. A non-zero count is
    security-relevant: it usually means the wrong/absent state key (the shipped
    operator config runs with ``[security.state_encryption].enabled = true``),
    so the logs cannot be vouched for. ``build_research_bundle`` fails CLOSED on
    it rather than mistaking unreadable logs for "no run data".
    """

    run_ids: list[str]
    unreadable_lines: int = 0


def discover_run_ids(root: Path | str = DEFAULT_ROOT) -> RunDiscovery:
    """Enumerate the DISTINCT ``run_id`` values present in the eval logs under ``root``.

    Walks the SAME ``*.jsonl`` sink files as :func:`load_run_records` (skipping
    the ``runs/`` manifest dir), decrypts + parses each line with the shared
    transparent-decrypt path, and collects every non-empty ``run_id`` seen.
    Records with no ``run_id`` (written outside any run) contribute nothing.

    Unlike a best-effort scan, a line that cannot be decrypted/parsed is NOT
    silently skipped: it is counted in ``RunDiscovery.unreadable_lines`` so the
    caller can fail closed (a wrong/missing key must never masquerade as an
    empty tree). This is the discovery half that lets ``build_research_bundle``
    gate admissibility WITHOUT the caller having to know the run id: the run(s)
    are found in the very tree the bundle is built from.
    """
    from kaine.security.crypto import get_state_encryptor

    encryptor = get_state_encryptor()
    seen: set[str] = set()
    unreadable = 0

    for path in _iter_jsonl_files(Path(root)):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        plain = encryptor.decrypt_text(line.rstrip("\n"))
                        record = json.loads(plain)
                    except Exception:
                        unreadable += 1
                        continue
                    if not isinstance(record, dict):
                        unreadable += 1
                        continue
                    rid = record.get("run_id")
                    if isinstance(rid, str) and rid:
                        seen.add(rid)
        except OSError:
            # An unreadable file is itself an unreadable-log signal.
            unreadable += 1
            continue

    return RunDiscovery(run_ids=sorted(seen), unreadable_lines=unreadable)


def load_run_records(
    run_id: str,
    *,
    root: Path | str = DEFAULT_ROOT,
) -> RunRecords:
    """Load every record carrying ``run_id`` from sink files under ``root``.

    Walks all ``*.jsonl`` files (skipping the ``runs/`` manifest dir), decrypts
    + parses each line (tolerating both encrypted and plaintext lines), keeps
    the records whose ``run_id`` matches, and groups them by stream. A line that
    cannot be decrypted/parsed into a JSON object is counted in ``parse_errors``
    and never raised on.

    Records with no ``run_id`` field at all are ignored (they were written
    outside any run); only records matching the target run are collected.
    """
    from kaine.security.crypto import get_state_encryptor

    encryptor = get_state_encryptor()
    out = RunRecords(run_id=run_id)
    target = str(run_id)

    for path in _iter_jsonl_files(Path(root)):
        stream = _stream_name_for(path)
        try:
            # Stream the file line-by-line rather than reading it whole into RAM
            # — a long-running sink file can be large, and only the matching
            # records are retained.
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        plain = encryptor.decrypt_text(line.rstrip("\n"))
                        record = json.loads(plain)
                    except Exception:
                        out.parse_errors += 1
                        continue
                    if not isinstance(record, dict):
                        out.parse_errors += 1
                        continue
                    if str(record.get("run_id", "")) != target:
                        continue
                    out.by_stream.setdefault(stream, []).append(record)
        except OSError:
            # An unreadable file is a parse failure for the whole file: count it
            # once rather than silently dropping it.
            out.parse_errors += 1
            continue

    return out


__all__ = [
    "RunRecords",
    "RunDiscovery",
    "load_run_records",
    "discover_run_ids",
    "DEFAULT_ROOT",
]
