# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Optional LOCAL-ONLY raw bus archive consumer.

NEVER EXPORT-ELIGIBLE
---------------------
This consumer tees VERBATIM bus events — including conversation content,
transcripts, intent params, and memory text — to ``state/research/raw_bus_archive/``.

- The raw archive NEVER leaves the host.
- The raw archive is NEVER export-eligible: it writes to ``state/research/...``,
  which is structurally OUTSIDE ``data/evaluation/``, so the metrics bundle
  builder (which only reads from ``data/evaluation/``) can never include it.
- It exists ONLY because the operator explicitly opted in with attestation:
  both ``entity_privacy_attested`` and ``bystander_consent_attested`` must be
  true in ``[research_event_log.raw_archive]``, on top of ``enabled = true``.

If enabled without both attestations, :meth:`RawBusArchiveConsumer.start`
raises :class:`RawArchiveAttestationError` and logs at ERROR; nothing starts.
This mirrors the ``BundleTierError`` attestation gate in
``kaine/research/submission.py``.

The archive is encrypted at rest via the same ``AsyncJsonlSink`` +
``StateEncryptor`` mechanism as every other sink. It captures records verbatim
(no privacy transform) — that is the entire point, and the reason it is locked
behind the double gate and structural path isolation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.config import (
    RawArchiveConfig,
    assert_raw_archive_outside_export_allowlist,
)
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


class RawArchiveAttestationError(ValueError):
    """Raised when the raw archive is enabled without both attestation flags.

    Mirrors ``BundleTierError`` in ``kaine/research/submission.py``.
    """


#: Every ``<module>.out`` stream the raw archive follows verbatim.
_MODULE_OUT_STREAMS: tuple[str, ...] = (
    "soma.out",
    "chronos.out",
    "topos.out",
    "nous.out",
    "mnemos.out",
    "eidolon.out",
    "thymos.out",
    "praxis.out",
    "lingua.out",
    "audition.out",
    "vox.out",
    "mundus.out",
    "perception.out",
    "empatheia.out",
    "phantasia.out",
    "hypnos.out",
    "volition.out",
    "spot.out",
    "cycle.out",
    "welfare.out",
    "preservation.out",
)


class _VerbatimStreamArchiver(StreamSubscriberObserver):
    """Follows one ``<module>.out`` stream and archives events verbatim."""

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        source_stream: str,
        name: str,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self.stream = source_stream
        self.name = name
        self._sink = sink

    async def handle(self, entry_id: str, event: Event) -> None:
        # Verbatim — NO privacy transform. This is the local-only raw archive.
        await self._sink.write(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "entry_id": entry_id,
                "stream": self.stream,
                "source": event.source,
                "type": event.type,
                "salience": event.salience,
                "timestamp": event.timestamp.isoformat(),
                "causal_parent": event.causal_parent,
                "payload": dict(event.payload or {}),
            }
        )


class RawBusArchiveConsumer:
    """Composite consumer that archives every ``<module>.out`` stream verbatim.

    Exposes the same ``start``/``stop`` lifecycle as ``BaseObserver`` so the
    ``SidecarRegistry`` can manage it uniformly alongside the curated observer.
    """

    name = "raw_bus_archive"

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        config: RawArchiveConfig,
    ) -> None:
        self._bus = bus
        self._sink = sink
        self._config = config
        self._archivers = [
            _VerbatimStreamArchiver(
                bus,
                sink,
                source_stream=stream,
                name=f"raw_bus_archive_{stream.split('.', 1)[0]}",
            )
            for stream in _MODULE_OUT_STREAMS
        ]

    def _assert_attested(self) -> None:
        if not (
            self._config.entity_privacy_attested
            and self._config.bystander_consent_attested
        ):
            msg = (
                "raw bus archive is enabled but requires BOTH "
                "entity_privacy_attested=true AND bystander_consent_attested=true "
                "in [research_event_log.raw_archive] (got "
                f"entity_privacy_attested={self._config.entity_privacy_attested}, "
                f"bystander_consent_attested={self._config.bystander_consent_attested}). "
                "The raw archive captures verbatim conversation content and is "
                "never export-eligible; it will not start without explicit attestation."
            )
            log.error("RawBusArchiveConsumer refusing to start: %s", msg)
            raise RawArchiveAttestationError(msg)

    async def start(self) -> None:
        self._assert_attested()
        # Defence-in-depth: re-validate confinement at start() in case the config
        # was built bypassing from_mapping. Fails closed (RawArchiveConfinementError).
        assert_raw_archive_outside_export_allowlist(self._config.archive_dir)
        for archiver in self._archivers:
            await archiver.start()
        log.info(
            "raw bus archive started (LOCAL-ONLY, never export-eligible) at %s",
            Path(self._config.archive_dir),
        )

    async def stop(self) -> None:
        for archiver in self._archivers:
            try:
                await archiver.stop()
            except Exception:
                log.warning(
                    "raw archive stream %s stop failed", archiver.name, exc_info=True
                )
