# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Durable, append-only incident log for the Spot module supervisor.

Spot already executes a well-defined fault-recovery lifecycle (detect a crash or
hang -> freeze the cycle -> snapshot last-good state -> run the restart ladder ->
escalate). Every step has observable side effects, but none of them survive a
clean boot: the crash exception read in ``Spot.assess`` was historically
discarded, the ``spot.status`` / ``spot.log`` bus events are an ephemeral Redis
ring buffer trimmed on every publish, and the two durable files that do persist
(``state/cycle/escalation.json`` and ``state/cycle/control.json``) are wiped on
every clean boot by ``clear_escalation()`` / ``unfreeze()`` in the entrypoint.

This module adds a durable side-channel that writes one structured JSONL record
per lifecycle transition. All records for a single module fault window share a
generated ``incident_id`` so a resolved recovery (detect -> ... -> restart) or an
exhausted escalation (detect -> ... -> escalate) can be reconstructed after a
reboot for a research paper, an operator post-mortem, or a Guardian welfare
review.

Storage characteristics:

* Records live under ``state/cycle/incidents/`` in daily-rotated JSONL files
  (``incidents-<UTC-date>.jsonl``), via :class:`AsyncJsonlSink`.
* The sink is constructed with ``retention_days=0`` so the daily-rotation
  retention purge is unconditionally DISABLED -- research history is never
  auto-deleted (contrast: the evaluation sidecar observers default to a 30-day
  purge).
* Encryption at rest is automatic via the existing
  ``AsyncJsonlSink._encode_line`` -> ``get_state_encryptor().encrypt_text`` path
  when ``[security.state_encryption]`` is enabled. No new crypto code lives here.
* The directory is NEVER cleared at boot. ``clear_escalation()`` and ``unfreeze``
  do not touch it -- this is the load-bearing contrast with the single-state
  operational files they reset.

Privacy: ``exception_repr`` written in the ``detect`` record is scrubbed of
operator filesystem paths (``scrub_paths``) before write, per the project's
no-personal-details rule. Module names, fault metadata, snapshot ids, sizes,
timings, and attempt counts are non-sensitive operational data.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from kaine.experiment.run_context import _utc_iso
from kaine.persistence.jsonl_sink import AsyncJsonlSink

log = logging.getLogger(__name__)

# Absolute-path tokens that may leak an operator's filesystem layout into an
# exception repr. We replace the whole token with a single sentinel rather than
# trying to preserve a relative tail (which could itself contain a username).
#
#   POSIX home/root/user trees:  /home/<...>, /root/<...>, /Users/<...>
#   Windows drive paths:         C:\<...> (any drive letter, both slash styles)
#   Any POSIX absolute path:     /<...> with at least one trailing component
#                                (covers /tmp, /var, /opt, /proc, /srv, /mnt,
#                                /run, /etc, … — the full absolute-path space)
#
# The home/root/user alternatives intentionally also match the bare root (e.g.
# "/root") with no trailing component. The aggressive final pattern matches ANY
# absolute path token with a body of >=2 chars after the leading slash; this is
# deliberately broad because the function's purpose is aggressive scrubbing of
# free-text exception reprs, not surgical extraction. It runs LAST so the more
# specific patterns above have already collapsed their matches.
_PATH_PATTERNS = (
    re.compile(r"(?:/home|/root|/Users)(?:/[^\s'\"]*)?"),
    re.compile(r"[A-Za-z]:\\[^\s'\"]*"),
    re.compile(r"/[^\s'\"]{2,}"),
)

_PATH_SENTINEL = "<PATH>"


def scrub_paths(text: Optional[str]) -> Optional[str]:
    """Replace operator filesystem-path tokens in ``text`` with ``<PATH>``.

    Best-effort regex substitution over a string (typically an exception repr).
    Returns ``None`` unchanged (hung modules carry no exception repr). Emits a
    debug note when any substitution occurs so the redaction is observable
    without ever logging the raw path.
    """
    if text is None:
        return None
    scrubbed = text
    substitutions = 0
    for pattern in _PATH_PATTERNS:
        scrubbed, n = pattern.subn(_PATH_SENTINEL, scrubbed)
        substitutions += n
    if substitutions:
        log.debug(
            "incident log scrubbed %d filesystem-path token(s) from an "
            "exception repr before write",
            substitutions,
        )
    return scrubbed


class IncidentLog:
    """Durable JSONL writer for Spot lifecycle transitions.

    Wraps an :class:`AsyncJsonlSink` configured for the incident log's storage
    contract (no-purge, daily rotation, encrypted-at-rest when enabled). When
    constructed disabled, it is an inert no-op: no sink is built and no files are
    ever written.

    The class is deliberately thin -- it stamps ``ts`` if absent and forwards to
    the sink, guarding the write so a broken sink can never crash Spot (the
    watchdog must keep running precisely when things are failing).
    """

    def __init__(self, *, enabled: bool, path: str, name: str = "incidents") -> None:
        self._enabled = bool(enabled)
        self._path = str(path)
        self._name = str(name)
        self._sink: Optional[AsyncJsonlSink] = None
        if self._enabled:
            # retention_days=0 => the AsyncJsonlSink retention purge is a no-op;
            # incident history is never auto-deleted. ``name`` is the JSONL file
            # stem (``<name>-<UTC-date>.jsonl``): two IncidentLogs writing to the
            # SAME directory MUST use distinct names, or their independent per-sink
            # ``seq`` counters interleave in one file and break
            # ``admissibility.scan_run`` seq-contiguity.
            self._sink = AsyncJsonlSink(
                self._path, name=self._name, retention_days=0
            )

    @property
    def enabled(self) -> bool:
        return self._enabled and self._sink is not None

    async def start(self) -> None:
        if self._sink is not None:
            await self._sink.start()

    async def stop(self) -> None:
        if self._sink is not None:
            await self._sink.stop()

    async def write(self, record: dict[str, Any]) -> None:
        """Stamp ``ts`` (if absent) and durably append one transition record.

        No-op when disabled. Guarded so a sink failure degrades to a warning
        rather than crashing the supervisor poll loop.
        """
        if self._sink is None:
            return
        if "ts" not in record:
            record = {"ts": _utc_iso(), **record}
        try:
            await self._sink.write(record)
        except Exception:
            log.warning("incident log write failed", exc_info=True)
