# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pre-boot dry-run / smoke gate for the whole KAINE supporting stack.

Run before EVERY entity boot:

    python -m kaine.preboot

This is the mandatory gate that closes the gap a prior boot fell through:
"services up + modules registered" was treated as readiness, and the entity
came up senseless (perception not actually delivering) and effectively
half-observable. "Up" is not "working" — every check here proves the
apparatus actually DOES something, not merely that a port answers.

It checks, WITHOUT booting the entity (no cognitive cycle, no bus consumer
loop — only read-only probes and throwaway round-trips):

  1. SERVICES   — Redis / Qdrant / the organ's OpenAI endpoint / Speaches /
                  Chatterbox are reachable. Reuses the exact probes the Nexus
                  health board uses (``kaine.nexus.health``).
  2. ORGAN      — the configured language organ actually GENERATES content
                  (not merely listed/served-but-mute). Reuses the boot-time
                  content gate (``kaine.organ_probe.verify_organ_generates``).
  3. PERCEPTION — when a deterministic feed is configured (seeded/playlist),
                  the configured source factory actually YIELDS a video frame
                  and an audio block. Reuses the exact factories the cycle
                  boot wires (``kaine.boot._build_perception_feed_*_factory``).
                  When the feed is off, this is reported SKIPPED with an
                  explicit warning that the entity will be senseless — never
                  silently passed.
  4. WELFARE    — a real preserve_live → revive round-trip on a throwaway
                  synthetic individual, run WITH the actually-configured
                  ``[preservation].require_encryption`` and the REAL state
                  encryptor (key resolved from $KAINE_STATE_KEY, falling back
                  to the gitignored ``secrets/state_key`` file). This is what
                  catches a misconfigured/missing encryption key BEFORE boot,
                  rather than the welfare net silently failing to preserve a
                  diverging or distressed individual at the first live
                  crossing (paper §3.7 / §6.2).
  5. RESOURCES  — whether the bus's configured stream caps fit in Redis
                  ``maxmemory`` (the "Bus budget" row), and whether the state
                  root, the data root and the native Redis data directory have
                  enough free disk. KAINE does not delete memories or research
                  records to stay under a limit, so these limits are checked
                  here, before boot, instead of being hit during a run.
  6. CONFIG     — which boot mode this run would take (operator-supervised vs
                  research), which modules are enabled, whether the tier being
                  recorded can actually run the enabled modules, and whether
                  the preservation config would fail closed
                  (require_encryption set but state encryption off while a
                  monitor is enabled).

Every check is best-effort and NEVER raises out of this module — a check that
cannot run reports the honest gap as a FAIL/WARN/SKIP row with a reason, never
a silent pass and never an uncaught traceback (mirrors the "never raises"
contract of ``kaine.nexus.health`` and ``kaine.setup.organ``).

Exit code is non-zero iff any check reports FAIL (a WARN row reports a risk
but does not fail the gate), so this composes as a CI / boot-script gate: ``python -m kaine.preboot && python -m kaine.cycle``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from kaine.boot import (
    _build_perception_feed_audio_factory,
    _build_perception_feed_video_factory,
)
from kaine.bus.config import (
    TYPICAL_EVENT_BYTES,
    BusConfig,
    maxlen_for,
    typical_event_bytes,
)
from kaine.bus.schema import module_stream
from kaine.config import (
    OPERATOR_CONFIG_PATH,
    SHIPPED_CONFIG_PATH,
    load_runtime_config,
    require_known_keys,
)
from kaine.cycle.ignition_log import IgnitionLogConfig
from kaine.cycle.preservation_monitor import PreservationConfig
from kaine.cycle.research_gate import research_mode_requested, run_preflight_self_check
from kaine.nexus import health
from kaine.nexus.health import load_health_prober
from kaine.organ_probe import verify_organ_generates
from kaine.security.crypto import CryptoConfigError, install_from_section
from kaine.storage import configured_data_root, resolve, storage_min_free_gb
from kaine.torch_stack import check_torch_stack, describe_torch_stack

log = logging.getLogger(__name__)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
# A risk worth the operator's attention that does not block boot.
WARN = "WARN"

GROUP_SERVICES = "SERVICES"
GROUP_ORGAN = "ORGAN"
GROUP_PERCEPTION = "PERCEPTION"
GROUP_WELFARE = "WELFARE NET (preserve -> revive dry run)"
GROUP_RESOURCES = "RESOURCES (bus memory + disk)"
GROUP_CONFIG = "CONFIG SANITY"

# Default location of the operator-provided 32-byte state-encryption key.
# Read into $KAINE_STATE_KEY for this process ONLY if the operator has not
# already exported it — the key itself is never logged.
STATE_KEY_FILE = Path("secrets/state_key")
STATE_KEY_ENV_VAR = "KAINE_STATE_KEY"

# Wall-clock ceiling for the seeded/playlist audio source to deliver its
# first block. The seeded producer paces at real time (frames_per_block /
# sample_rate, typically ~30ms), so this is generous headroom, not a tight
# race.
AUDIO_PROBE_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class CheckResult:
    """One row of the pre-boot report."""

    group: str
    name: str
    status: str  # PASS | WARN | FAIL | SKIP
    detail: str = ""


# ---------------------------------------------------------------------------
# 1. SERVICES
# ---------------------------------------------------------------------------


async def check_services(
    *,
    kaine_toml: str | os.PathLike[str] | None = None,
    secrets_toml: str | os.PathLike[str] | None = None,
) -> list[CheckResult]:
    """Probe every configured dependency via the shared Nexus health prober.

    Reuses :func:`kaine.nexus.health.load_health_prober` (which already
    deep-merges the operator config and resolves Redis/Qdrant secrets) and
    :meth:`HealthProber.snapshot` — no probe logic is duplicated here, only
    the up/not_configured/else -> PASS/SKIP/FAIL mapping appropriate to a
    boot gate (a dashboard tolerates "degraded"; a boot gate must not).
    """
    from kaine.nexus.health.probes import (
        SHERPA_PROBE_CHILD_TIMEOUT_S,
        get_sherpa_probe_wait,
        set_sherpa_probe_wait,
    )

    # Sherpa loads run in a child process with a bounded timeout. Pre-boot must
    # wait longer than that load before declaring it degraded, and the Nexus
    # prober's outer timeout must be longer still so the child result can be
    # returned. Network probes keep their own short timeouts, so raising the
    # outer timeout here does not make them hang.
    prev_wait = get_sherpa_probe_wait()
    set_sherpa_probe_wait(SHERPA_PROBE_CHILD_TIMEOUT_S + 5)
    try:
        prober = load_health_prober(
            kaine_toml=kaine_toml,
            secrets_toml=secrets_toml,
            probe_timeout_s=SHERPA_PROBE_CHILD_TIMEOUT_S + 10,
        )
        snapshot = await prober.snapshot(force=True)
    finally:
        set_sherpa_probe_wait(prev_wait)
    deps = snapshot.get("dependencies", [])
    results: list[CheckResult] = []
    for dep in deps:
        status = dep.get("status")
        if status == health.UP:
            mapped = PASS
        elif status == health.NOT_CONFIGURED:
            mapped = SKIP
        else:  # down or degraded — either is unfit to boot on
            mapped = FAIL
        name = f"{dep.get('name', '?')} ({dep.get('role', '?')})"
        results.append(CheckResult(GROUP_SERVICES, name, mapped, dep.get("detail", "")))
    if not results:
        results.append(CheckResult(GROUP_SERVICES, "(no dependencies probed)", SKIP, ""))
    return results


# ---------------------------------------------------------------------------
# 2. ORGAN
# ---------------------------------------------------------------------------


async def check_organ(config: dict[str, Any]) -> list[CheckResult]:
    """Confirm the configured organ actually GENERATES content.

    Mirrors the exact gate the cycle boot runs (kaine.cycle.__main__): skip
    when lingua is disabled, skip (not fail) while the organ is deliberately
    unloaded for a voice-alignment training window, else send one real
    completion through ``verify_organ_generates`` and require non-empty text.
    """
    modules = config.get("modules") or {}
    if not modules.get("lingua"):
        return [
            CheckResult(
                GROUP_ORGAN,
                "Organ content",
                SKIP,
                "[modules].lingua = false — no organ configured for this run",
            )
        ]

    try:
        from kaine.organ_window_state import organ_unloaded

        if organ_unloaded():
            return [
                CheckResult(
                    GROUP_ORGAN,
                    "Organ content",
                    SKIP,
                    "organ resting (voice-alignment training window) — "
                    "not probed while deliberately unloaded",
                )
            ]
    except Exception:
        log.debug("organ_unloaded() check failed; probing anyway", exc_info=True)

    lingua_cfg = config.get("lingua") or {}
    gate = await verify_organ_generates(
        str(lingua_cfg.get("chat_url", "http://127.0.0.1:11434/v1")),
        str(lingua_cfg.get("model_id") or ""),
        api_key=lingua_cfg.get("api_key") or os.environ.get("KAINE_MODEL_SERVER_API_KEY"),
    )
    return [CheckResult(GROUP_ORGAN, "Organ content", PASS if gate.ok else FAIL, gate.detail)]


# ---------------------------------------------------------------------------
# 3. PERCEPTION
# ---------------------------------------------------------------------------


async def check_perception(config: dict[str, Any]) -> list[CheckResult]:
    """Confirm the configured deterministic perception feed actually delivers.

    Checks at the SOURCE level (the exact factories ``kaine.boot`` wires into
    Topos/Audition), so this stays robust to internal fixes elsewhere in the
    perception pipeline: it proves the source itself yields a frame / a PCM
    block, independent of what the live module does with it afterward.

    mode == "off" is reported SKIPPED with an explicit warning rather than a
    silent pass — exactly the gap that let a senseless entity boot. mode ==
    "live" (real camera/microphone) is also SKIPPED: ``kaine.boot`` does not
    build a source_factory for it (the real cv2/sounddevice path is used
    directly), so there is no offline source to probe; hardware capture must
    be verified by bringing Topos/Audition up.
    """
    feed = dict(config.get("perception_feed") or {})
    mode = str(feed.get("mode", "off")).lower()

    if mode == "off":
        return [
            CheckResult(
                GROUP_PERCEPTION,
                "Perception feed",
                SKIP,
                "[perception_feed].mode = off — the entity WILL BE SENSELESS "
                "(no video/audio stimulus configured)",
            )
        ]
    if mode == "live":
        return [
            CheckResult(
                GROUP_PERCEPTION,
                "Perception feed",
                SKIP,
                "mode = live (real camera/microphone) — not exercised by this "
                "offline dry-run; bring Topos/Audition up to verify hardware "
                "capture (operator-present demos only, not a research run)",
            )
        ]

    results: list[CheckResult] = []
    results.append(_check_perception_video(config, feed, mode))
    results.append(await _check_perception_audio(config, feed, mode))
    return results


def _check_perception_video(config: dict[str, Any], feed: dict[str, Any], mode: str) -> CheckResult:
    topos_cfg = config.get("topos") or {}
    width = int(topos_cfg.get("capture_width", 640))
    height = int(topos_cfg.get("capture_height", 480))
    try:
        factory = _build_perception_feed_video_factory(mode, feed, width=width, height=height)
        source = factory(0, width=width, height=height)
        opened = source.open()
        ok, frame = source.read() if opened else (False, None)
        try:
            source.release()
        except Exception:
            log.debug("video source release failed", exc_info=True)
    except Exception as exc:
        return CheckResult(
            GROUP_PERCEPTION,
            "Perception (video source)",
            FAIL,
            f"mode={mode}: {type(exc).__name__}: {exc}",
        )
    if opened and ok and frame is not None:
        shape = getattr(frame, "shape", None)
        return CheckResult(
            GROUP_PERCEPTION,
            "Perception (video source)",
            PASS,
            f"mode={mode}: source yielded a frame" + (f" {shape}" if shape else ""),
        )
    return CheckResult(
        GROUP_PERCEPTION,
        "Perception (video source)",
        FAIL,
        f"mode={mode}: opened={opened} read_ok={ok} frame_is_none={frame is None}",
    )


async def _check_perception_audio(
    config: dict[str, Any], feed: dict[str, Any], mode: str
) -> CheckResult:
    audition_cfg = config.get("audition") or {}
    sample_rate = int(audition_cfg.get("capture_sample_rate", 16000))
    channels = int(audition_cfg.get("capture_channels", 1))
    vad_frame_ms = int(audition_cfg.get("vad_frame_ms", 30))
    frames_per_block = max(1, sample_rate * vad_frame_ms // 1000)

    received: list[bytes] = []
    arrived = threading.Event()

    def _on_block(pcm: bytes) -> None:
        received.append(pcm)
        arrived.set()

    try:
        factory = _build_perception_feed_audio_factory(
            mode,
            feed,
            sample_rate=sample_rate,
            channels=channels,
            frames_per_block=frames_per_block,
        )
        stream = factory(
            device=None,
            sample_rate=sample_rate,
            channels=channels,
            frames_per_block=frames_per_block,
            callback=_on_block,
        )
        stream.start()
        try:
            got = await asyncio.to_thread(arrived.wait, AUDIO_PROBE_TIMEOUT_S)
        finally:
            stream.stop()
            try:
                stream.close()
            except Exception:
                log.debug("audio source close failed", exc_info=True)
    except Exception as exc:
        return CheckResult(
            GROUP_PERCEPTION,
            "Perception (audio source)",
            FAIL,
            f"mode={mode}: {type(exc).__name__}: {exc}",
        )

    if got and received and len(received[0]) > 0:
        return CheckResult(
            GROUP_PERCEPTION,
            "Perception (audio source)",
            PASS,
            f"mode={mode}: source yielded {len(received[0])} bytes PCM "
            f"within {AUDIO_PROBE_TIMEOUT_S:.0f}s",
        )
    return CheckResult(
        GROUP_PERCEPTION,
        "Perception (audio source)",
        FAIL,
        f"mode={mode}: no audio block received within {AUDIO_PROBE_TIMEOUT_S:.0f}s",
    )


# ---------------------------------------------------------------------------
# 4. WELFARE — preserve -> revive dry run, WITH real encryption active
# ---------------------------------------------------------------------------


def _resolve_state_key_into_env(
    *, key_file: Path | None = None, env_var: str = STATE_KEY_ENV_VAR
) -> Optional[str]:
    """Best-effort: load the state-encryption key into the environment.

    If ``$KAINE_STATE_KEY`` is already set, this is a no-op (the operator's
    explicit export wins). Otherwise, falls back to the gitignored key file
    the operator config documents (``secrets/state_key`` — survives
    fresh-run clears so preserved bundles stay decryptable). The key bytes
    are never logged; only a short status note is returned for the report.

    ``key_file`` defaults to the module-level :data:`STATE_KEY_FILE`,
    resolved HERE (not as a parameter default) so tests can monkeypatch
    ``kaine.preboot.STATE_KEY_FILE`` and have it take effect.
    """
    if key_file is None:
        key_file = STATE_KEY_FILE
    if os.environ.get(env_var):
        return f"${env_var} already set in the environment"
    if not key_file.is_file():
        return None
    try:
        content = key_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return f"could not read {key_file}: {type(exc).__name__}: {exc}"
    if not content:
        return f"{key_file} is empty"
    os.environ[env_var] = content
    return f"loaded ${env_var} from {key_file}"


async def check_welfare(config: dict[str, Any]) -> list[CheckResult]:
    """Real preserve_live -> revive round-trip, with REAL encryption active.

    This is the check that catches the exact gap flagged for this harness: a
    recent change made ``preserve_live`` fail CLOSED (raise) when
    ``require_encryption`` is set but the state encryptor is not actively
    encrypting. The existing self-check
    (``kaine.cycle.research_gate.run_preflight_self_check``) only proves the
    PATH works; it does not, by itself, prove the CONFIGURED encryption
    posture works, because nothing installs the real encryptor before it
    runs. This check closes that gap, in order:

      1. Resolve the real $KAINE_STATE_KEY (env, else secrets/state_key).
      2. Install the REAL configured encryptor
         (``[security.state_encryption]``) — this is where a misconfigured
         or unreadable key surfaces as ``CryptoConfigError``, BEFORE boot.
      3. Run the dry preserve_live -> revive round-trip with the ACTUAL
         configured ``[preservation].require_encryption``, so a True value
         either round-trips for real (key works) or fails closed loudly here
         — never silently at the entity's first live crossing.
    """
    preservation_cfg = PreservationConfig.from_section(config.get("preservation") or {})
    state_enc_section = dict((config.get("security") or {}).get("state_encryption") or {})

    results: list[CheckResult] = []
    key_note = _resolve_state_key_into_env()

    try:
        encryptor = install_from_section(state_enc_section)
    except CryptoConfigError as exc:
        results.append(
            CheckResult(
                GROUP_WELFARE,
                "State-encryption key",
                FAIL,
                str(exc) + (f" ({key_note})" if key_note else ""),
            )
        )
    else:
        if encryptor.enabled:
            results.append(
                CheckResult(
                    GROUP_WELFARE,
                    "State-encryption key",
                    PASS,
                    "key resolved; encryption ACTIVE" + (f" ({key_note})" if key_note else ""),
                )
            )
        else:
            results.append(
                CheckResult(
                    GROUP_WELFARE,
                    "State-encryption key",
                    SKIP,
                    "[security.state_encryption].enabled = false — "
                    "preservation would write plaintext at rest",
                )
            )

    self_ok, self_reason = await asyncio.to_thread(
        run_preflight_self_check,
        require_encryption=preservation_cfg.require_encryption,
    )
    if self_ok:
        detail = (
            "synthetic preserve->revive round-trip OK "
            f"(require_encryption={preservation_cfg.require_encryption})"
        )
    else:
        detail = self_reason or "preserve->revive self-check failed"
    results.append(
        CheckResult(GROUP_WELFARE, "Preserve -> revive dry run", PASS if self_ok else FAIL, detail)
    )
    return results


# ---------------------------------------------------------------------------
# 5. RESOURCES — bus memory budget + free disk
# ---------------------------------------------------------------------------

# Redis rewrites the append-only file by forking; copy-on-write pages during
# the rewrite can approach the dataset size, so the budget doubles the
# estimated stream memory.
BUS_BUDGET_HEADROOM_FACTOR = 2
# Above this fraction of maxmemory the budget row WARNs.
BUS_BUDGET_WARN_FRACTION = 0.70
# Wall-clock ceiling for the bus probe (maxmemory + per-stream sampling).
BUS_PROBE_TIMEOUT_S = 5.0
# A live stream needs at least this many entries before MEMORY USAGE / XLEN
# counts as a measurement (below it the fixed per-key overhead dominates).
BUS_SAMPLE_MIN_ENTRIES = 100

# Where a per-entry size in the budget comes from.
SIZE_LIVE = "live"  # sampled from the running bus
SIZE_TABLE = "table"  # measured value in kaine.bus.config.TYPICAL_EVENT_BYTES
SIZE_ESTIMATE = "estimate"  # the 2 KB default for an unmeasured stream

# Streams every run produces, whatever modules are enabled.
_CORE_BUDGET_STREAMS: tuple[str, ...] = ("workspace.broadcast", "cycle.out")
# Streams an enabled module produces besides its own ``<module>.out``.
_EXTRA_MODULE_STREAMS: dict[str, tuple[str, ...]] = {
    "lingua": ("lingua.internal", "lingua.external"),
    "nous": ("volition.out", "volition_feedback.out"),
}

# ``[preboot]`` defaults. GB here is 2**30 bytes, as ``df -h`` reports.
PREBOOT_DEFAULTS: dict[str, Any] = {
    "state_root": "state",
    "data_root": "data",
    "disk_fail_min_free_gb": 10.0,
    "disk_fail_min_free_percent": 5.0,
    "disk_warn_min_free_gb": 20.0,
    "extra_disk_paths": [],
}
_GIB = 2**30


def _fmt_gib(n_bytes: float) -> str:
    return f"{n_bytes / _GIB:.2f} GiB"


@dataclass(frozen=True)
class StreamBudget:
    """One stream's share of the bus budget (before AOF headroom)."""

    stream: str
    maxlen: int
    entry_bytes: int
    source: str  # SIZE_LIVE | SIZE_TABLE | SIZE_ESTIMATE

    @property
    def bytes(self) -> int:
        return self.maxlen * self.entry_bytes

    @property
    def measured(self) -> bool:
        return self.source != SIZE_ESTIMATE


def budget_streams(modules: dict[str, Any]) -> list[str]:
    """The streams a run with ``modules`` enabled produces, in stable order.

    Low-rate operational streams (lifecycle, welfare, preservation,
    individuation) are not counted; their volume is negligible next to the
    module streams.
    """
    streams: list[str] = list(_CORE_BUDGET_STREAMS)
    for name in sorted(k for k, v in modules.items() if v):
        for stream in (module_stream(name), *_EXTRA_MODULE_STREAMS.get(name, ())):
            if stream not in streams:
                streams.append(stream)
    return streams


def bus_budget(
    config: dict[str, Any], live_sizes: Optional[dict[str, int]] = None
) -> tuple[int, list[StreamBudget]]:
    """Estimated Redis memory, in bytes, that the configured caps imply.

    Each stream's per-entry size comes from the live bus when ``live_sizes``
    has a measurement for it, else from the measured table in
    ``kaine.bus.config``, else from the 2 KB estimate. Returns the budget (the
    sum over :func:`budget_streams`, times :data:`BUS_BUDGET_HEADROOM_FACTOR`)
    and the per-stream shares, largest first. Raises on a malformed ``[bus]``
    table.
    """
    bus_cfg = config.get("bus") or {}
    if not isinstance(bus_cfg, dict):
        raise ValueError("[bus] is not a table")
    per_stream = bus_cfg.get("per_stream_maxlen") or {}
    if not isinstance(per_stream, dict):
        raise ValueError("[bus.per_stream_maxlen] is not a table")
    caps = BusConfig(
        default_maxlen=int(bus_cfg.get("default_maxlen", BusConfig.default_maxlen)),
        per_stream_maxlen={str(k): int(v) for k, v in per_stream.items()},
    )
    modules = config.get("modules") or {}
    live = live_sizes or {}
    shares: list[StreamBudget] = []
    for stream in budget_streams(modules if isinstance(modules, dict) else {}):
        if live.get(stream):
            size, source = int(live[stream]), SIZE_LIVE
        elif stream in TYPICAL_EVENT_BYTES:
            size, source = TYPICAL_EVENT_BYTES[stream], SIZE_TABLE
        else:
            size, source = typical_event_bytes(stream), SIZE_ESTIMATE
        shares.append(StreamBudget(stream, maxlen_for(caps, stream), size, source))
    shares.sort(key=lambda s: s.bytes, reverse=True)
    total = sum(s.bytes for s in shares) * BUS_BUDGET_HEADROOM_FACTOR
    return total, shares


async def _probe_bus(streams: list[str]) -> tuple[int, dict[str, int]]:
    """Read ``maxmemory`` and sample per-entry sizes from the KAINE Redis.

    Per-entry sizes are ``MEMORY USAGE`` / ``XLEN`` of each existing stream
    with at least :data:`BUS_SAMPLE_MIN_ENTRIES` entries. Raises when
    ``maxmemory`` cannot be read; a stream that cannot be sampled is left out.
    """
    import redis.asyncio as aioredis

    from kaine.bus.client import AsyncBus
    from kaine.bus.config import load_bus_config

    bus_cfg = load_bus_config()
    client = aioredis.from_url(
        bus_cfg.url,
        decode_responses=True,
        socket_connect_timeout=BUS_PROBE_TIMEOUT_S,
        socket_timeout=BUS_PROBE_TIMEOUT_S,
    )
    bus = AsyncBus(bus_cfg, client=client)
    try:
        maxmemory = await bus.server_maxmemory()
        sizes: dict[str, int] = {}
        for stream in streams:
            try:
                size = await bus.stream_entry_bytes(
                    stream, min_entries=BUS_SAMPLE_MIN_ENTRIES
                )
            except Exception:
                log.debug("could not sample %s", stream, exc_info=True)
                continue
            if size:
                sizes[stream] = size
        return maxmemory, sizes
    finally:
        try:
            await bus.close()
        except Exception:
            log.debug("bus close after the budget probe failed", exc_info=True)


async def check_bus_budget(
    config: dict[str, Any],
    *,
    probe: Optional[Callable[[list[str]], Awaitable[tuple[int, dict[str, int]]]]] = None,
) -> list[CheckResult]:
    """Compare the bus memory the stream caps imply with Redis ``maxmemory``.

    FAIL only when the MEASURED part of the budget (streams sized from the
    live bus or the measured table) exceeds ``maxmemory``. When the overage
    depends on the 2 KB estimate for unmeasured streams, WARN and name those
    streams. WARN above :data:`BUS_BUDGET_WARN_FRACTION` of ``maxmemory``,
    WARN when ``maxmemory`` cannot be read or is 0 (no limit), PASS otherwise.
    ``probe`` is an async callable taking the stream list and returning
    ``(maxmemory, live per-entry sizes)``; it defaults to the real bus.
    """
    name = "Bus budget"
    try:
        streams = budget_streams(
            config.get("modules") if isinstance(config.get("modules"), dict) else {}
        )
        bus_budget(config)  # validate [bus] before touching the server
    except Exception as exc:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                FAIL,
                f"could not compute the bus budget from [bus]: {type(exc).__name__}: {exc}",
            )
        ]
    runner = probe or _probe_bus
    probe_error: Optional[BaseException] = None
    try:
        maxmemory, live = await asyncio.wait_for(runner(streams), BUS_PROBE_TIMEOUT_S)
        maxmemory = int(maxmemory)
    except Exception as exc:
        probe_error, maxmemory, live = exc, None, {}

    budget, shares = bus_budget(config, live)
    measured_budget = sum(s.bytes for s in shares if s.measured) * BUS_BUDGET_HEADROOM_FACTOR
    estimated = [s.stream for s in shares if not s.measured]
    largest = ", ".join(f"{s.stream} {_fmt_gib(s.bytes)} ({s.source})" for s in shares[:3])
    n_live = sum(1 for s in shares if s.source == SIZE_LIVE)
    basis = (
        f"budget {_fmt_gib(budget)} (maxlen x per-entry size over {len(shares)} "
        f"streams: {n_live} sampled live, {len(shares) - n_live - len(estimated)} from "
        f"the measured table, {len(estimated)} estimated at 2 KB; "
        f"x{BUS_BUDGET_HEADROOM_FACTOR} for AOF rewrite; largest: {largest})"
    )

    if probe_error is not None:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                WARN,
                f"could not read Redis maxmemory ({type(probe_error).__name__}: "
                f"{probe_error}); {basis}; make sure KAINE_REDIS_MAXMEMORY is at "
                "least the budget",
            )
        ]
    if maxmemory <= 0:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                WARN,
                "Redis maxmemory is 0 (no limit): the bus can grow into all host "
                f"memory; {basis}; set KAINE_REDIS_MAXMEMORY",
            )
        ]
    vs = f"{basis} vs maxmemory {_fmt_gib(maxmemory)}"
    if measured_budget > maxmemory:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                FAIL,
                f"{vs}: the measured streams alone ({_fmt_gib(measured_budget)}) "
                "would fill Redis and halt the entity; raise KAINE_REDIS_MAXMEMORY "
                "(compose/.env) and restart Redis",
            )
        ]
    if budget > maxmemory:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                WARN,
                f"{vs}: over the cap only through the 2 KB estimate for unmeasured "
                f"streams ({', '.join(estimated)}); a full study needs "
                "KAINE_REDIS_MAXMEMORY=12gb or more where the host has the RAM",
            )
        ]
    if budget > BUS_BUDGET_WARN_FRACTION * maxmemory:
        detail = (
            f"{vs}: above {BUS_BUDGET_WARN_FRACTION:.0%} of the cap; consider "
            "raising KAINE_REDIS_MAXMEMORY"
        )
        if estimated:
            detail += f" (estimated streams: {', '.join(estimated)})"
        return [CheckResult(GROUP_RESOURCES, name, WARN, detail)]
    return [CheckResult(GROUP_RESOURCES, name, PASS, vs)]


def _preboot_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Merge ``[preboot]`` over :data:`PREBOOT_DEFAULTS`, validating it.

    Raises ``ValueError`` naming an unknown key or a wrongly-typed value.
    """
    section = config.get("preboot")
    if section is None:
        section = {}
    if not isinstance(section, dict):
        raise ValueError("[preboot] is not a table")
    require_known_keys(section, set(PREBOOT_DEFAULTS), "[preboot]")
    settings = dict(PREBOOT_DEFAULTS)
    for key, value in section.items():
        default = PREBOOT_DEFAULTS[key]
        if isinstance(default, str):
            if not isinstance(value, str) or not value:
                raise ValueError(f"[preboot].{key} must be a non-empty string")
        elif isinstance(default, list):
            if not isinstance(value, list) or not all(
                isinstance(v, str) and v for v in value
            ):
                raise ValueError(
                    f"[preboot].{key} must be a list of non-empty strings"
                )
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"[preboot].{key} must be a number >= 0")
        settings[key] = value
    return settings


def _nearest_existing(path: Path) -> Path:
    """``path`` or its closest existing ancestor (a root may not exist yet)."""
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _table(config: dict[str, Any], *keys: str) -> dict[str, Any]:
    node: Any = config
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _dir_of(value: Any, default: str, *, is_file: bool = False) -> Path:
    path = Path(str(value) if isinstance(value, str) and value else default)
    return path.parent if is_file else path


def durable_paths(config: dict[str, Any]) -> list[tuple[str, Path]]:
    """Every configured directory that holds durable entity or research data.

    Resolved the way the modules resolve them: the same config keys and
    defaults, relative to the working directory the stack runs from.
    ``kaine.evaluation`` is outside this module's import boundary, so its
    keys are read here with the defaults of ``kaine.evaluation.config``.
    """
    settings = _preboot_settings(config)
    preservation = PreservationConfig.from_section(config.get("preservation") or {})
    ignition = IgnitionLogConfig.from_section(config.get("ignition_log"))
    evaluation_paths = _table(config, "evaluation", "paths")
    research = _table(config, "research_event_log")
    raw_archive = _table(config, "research_event_log", "raw_archive")
    voice = _table(config, "hypnos", "voice_alignment")
    lifecycle = _table(config, "lifecycle")
    incident_log = _table(config, "spot", "incident_log")
    eidolon = _table(config, "eidolon")

    paths: list[tuple[str, Path]] = [
        ("[preboot].state_root", resolve(Path(settings["state_root"]))),
        ("[preboot].data_root", resolve(Path(settings["data_root"]))),
        ("[lifecycle].snapshots_path", resolve(_dir_of(lifecycle.get("snapshots_path"), "state/forks"))),
        (
            "[preservation.divergence_monitor].out_root",
            resolve(Path(preservation.divergence_monitor.out_root)),
        ),
        (
            "[preservation.welfare_response].out_root",
            resolve(Path(preservation.welfare_response.out_root)),
        ),
        (
            "[evaluation.paths].trajectory_dir",
            resolve(_dir_of(evaluation_paths.get("trajectory_dir"), "data/workspace_trajectory")),
        ),
        (
            "[evaluation.paths].evaluation_logs",
            resolve(_dir_of(evaluation_paths.get("evaluation_logs"), "data/evaluation")),
        ),
        (
            "[research_event_log].log_dir",
            resolve(_dir_of(research.get("log_dir"), "data/evaluation/research_events")),
        ),
        (
            "[research_event_log.raw_archive].archive_dir",
            resolve(_dir_of(raw_archive.get("archive_dir"), "state/research/raw_bus_archive")),
        ),
        (
            "[hypnos.voice_alignment].adapter_output_dir",
            resolve(_dir_of(voice.get("adapter_output_dir"), "state/hypnos/adapters")),
        ),
        (
            "[hypnos.voice_alignment].trainer_workdir",
            resolve(_dir_of(
                str(voice.get("trainer_workdir") or "").strip() or None,
                "state/hypnos/voice_align_jobs",
            )),
        ),
        ("[ignition_log].directory", resolve(Path(ignition.directory))),
        ("[spot.incident_log].path", resolve(_dir_of(incident_log.get("path"), "state/cycle/incidents"))),
        (
            "[eidolon].persistence_path",
            resolve(_dir_of(
                eidolon.get("persistence_path"), "state/eidolon/self_model.json", is_file=True
            )),
        ),
    ]
    root = configured_data_root(config)
    if root is not None:
        paths.insert(0, ("[storage].data_root", resolve(root)))
    for extra in settings.get("extra_disk_paths", []):
        paths.append(("[preboot].extra_disk_paths", resolve(Path(extra))))
    return paths


def _device_of(path: Path) -> int:
    return os.stat(path).st_dev


def check_disk(
    config: dict[str, Any],
    *,
    disk_usage: Optional[Callable[[Path], Any]] = None,
    device_of: Optional[Callable[[Path], Any]] = None,
) -> list[CheckResult]:
    """Free-disk rows, one per filesystem holding a durable path.

    Every path from :func:`durable_paths` is measured at itself or its nearest
    existing ancestor, and paths on the same filesystem share one row that
    lists them. A row FAILS below max(``disk_fail_min_free_gb``,
    ``disk_fail_min_free_percent`` of the filesystem), WARNS below
    ``disk_warn_min_free_gb``, and PASSES otherwise. The native Redis data
    directory (``<state_root>/services/redis/data``) is included when it
    exists; a container volume is not resolvable from the host and is
    reported SKIP.
    """
    usage_fn = disk_usage or shutil.disk_usage
    dev_fn = device_of or _device_of
    try:
        settings = _preboot_settings(config)
        paths = durable_paths(config)
    except Exception as exc:
        return [CheckResult(GROUP_RESOURCES, "Disk free", FAIL, str(exc))]

    fail_gb = float(settings["disk_fail_min_free_gb"])
    fail_pct = float(settings["disk_fail_min_free_percent"])
    warn_gb = float(settings["disk_warn_min_free_gb"])
    results: list[CheckResult] = []

    redis_dir = resolve(settings["state_root"]) / "services" / "redis" / "data"
    native_redis = redis_dir.is_dir()
    if native_redis:
        paths.append(("native Redis data", redis_dir))

    groups: dict[Any, list[tuple[str, Path, Path]]] = {}
    seen: set[Path] = set()
    for label, path in paths:
        if path in seen:
            continue
        seen.add(path)
        measured = _nearest_existing(path)
        try:
            key = dev_fn(measured)
        except OSError as exc:
            results.append(
                CheckResult(
                    GROUP_RESOURCES,
                    f"Disk free ({label})",
                    FAIL,
                    f"{path}: could not stat: {type(exc).__name__}: {exc}",
                )
            )
            continue
        groups.setdefault(key, []).append((label, path, measured))

    for members in groups.values():
        label0, _, measured0 = members[0]
        name = "Disk free" + (
            f" ({label0})" if len(members) == 1 else f" ({label0} +{len(members) - 1})"
        )
        listed = ", ".join(str(path) for _, path, _ in members)
        try:
            usage = usage_fn(measured0)
        except OSError as exc:
            results.append(
                CheckResult(
                    GROUP_RESOURCES,
                    name,
                    FAIL,
                    f"{listed}: could not read disk usage: {type(exc).__name__}: {exc}",
                )
            )
            continue
        total = float(usage.total)
        free = float(usage.free)
        fail_floor = max(fail_gb * _GIB, total * fail_pct / 100.0)
        detail = f"{_fmt_gib(free)} free of {_fmt_gib(total)} for {listed}"
        if free < fail_floor:
            status = FAIL
            detail += (
                f"; below the floor {_fmt_gib(fail_floor)} "
                f"(max of {fail_gb:g} GiB and {fail_pct:g}%) — free space before boot"
            )
        elif free < warn_gb * _GIB:
            status = WARN
            detail += f"; below {warn_gb:g} GiB"
        else:
            status = PASS
        results.append(CheckResult(GROUP_RESOURCES, name, status, detail))

    if not native_redis:
        results.append(
            CheckResult(
                GROUP_RESOURCES,
                "Disk free (Redis data)",
                SKIP,
                f"no native Redis data directory at {redis_dir}; a container "
                "volume is not measured from the host",
            )
        )
    return results


def check_storage(config: dict[str, Any], *, disk_usage=None) -> list[CheckResult]:
    """Check the data root's filesystem has enough free space."""
    root = configured_data_root(config)
    if root is None:
        return [
            CheckResult(
                GROUP_RESOURCES,
                "Storage",
                SKIP,
                "no [storage].data_root; growing data is written under the working directory",
            )
        ]

    usage_fn = disk_usage or shutil.disk_usage
    try:
        total, used, free = usage_fn(_nearest_existing(root))
    except OSError as exc:
        return [
            CheckResult(
                GROUP_RESOURCES,
                "Storage",
                FAIL,
                f"{root}: could not read disk usage: {type(exc).__name__}: {exc}",
            )
        ]

    need = storage_min_free_gb(config)
    if free >= need * _GIB:
        return [
            CheckResult(
                GROUP_RESOURCES,
                "Storage",
                PASS,
                f"{_fmt_gib(free)} free at {root}; minimum {need:g} GiB",
            )
        ]
    return [
        CheckResult(
            GROUP_RESOURCES,
            "Storage",
            FAIL,
            f"{_fmt_gib(free)} free at {root}; minimum {need:g} GiB; free space or choose another data root",
        )
    ]


async def check_resources(config: dict[str, Any]) -> list[CheckResult]:
    """The RESOURCES group: the bus budget row, then the disk-free rows."""
    results = await check_bus_budget(config)
    results.extend(check_storage(config))
    results.extend(check_disk(config))
    return results


# ---------------------------------------------------------------------------
# 6. CONFIG SANITY
# ---------------------------------------------------------------------------


def check_device_map(config: dict[str, Any]) -> list[CheckResult]:
    """Verify the device map agrees with compose variables and cycle keys."""
    from kaine.setup.device_map import check_agreement

    status, detail = check_agreement(config, env_path=Path("compose/.env"))
    code = {"pass": PASS, "fail": FAIL, "skip": SKIP}[status]
    return [CheckResult(GROUP_CONFIG, "Device map", code, detail)]


def check_config_sanity(config: dict[str, Any]) -> list[CheckResult]:
    """Report the boot mode, the enabled modules, the tier fit, the encryption
    posture, and the torch stack.

    Performs no I/O beyond reading installed package metadata for the
    torch-stack row, in addition to what is already in ``config`` — reuses
    ``research_mode_requested`` and ``PreservationConfig`` rather than
    re-deriving boot-mode logic.

    Tier-fit validation is defensive: the operator overlay can write any shape
    into ``[tier]`` or ``[oscillator]``, so every access is type-checked and
    surfaced as an honest FAIL row instead of an uncaught exception.
    """
    results: list[CheckResult] = []

    research = research_mode_requested(config)
    if research:
        mode_detail = (
            "research (unsupervised) — requires the autonomous safety net "
            "verified (see WELFARE NET above)"
        )
    else:
        mode_detail = "operator-supervised — requires KAINE_CYCLE_OPERATOR_PRESENT=1 at boot"
    results.append(CheckResult(GROUP_CONFIG, "Boot mode", PASS, mode_detail))
    results.extend(check_device_map(config))

    modules = config.get("modules") or {}
    enabled = sorted(k for k, v in modules.items() if v)
    if enabled:
        results.append(CheckResult(GROUP_CONFIG, "Modules enabled", PASS, ", ".join(enabled)))
    else:
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Modules enabled",
                FAIL,
                "NONE — the entity would boot collecting no events at all",
            )
        )

    tier_cfg = config.get("tier")
    if tier_cfg is None:
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Tier fit",
                SKIP,
                "no deployment tier recorded",
            )
        )
    elif not isinstance(tier_cfg, dict):
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Tier fit",
                FAIL,
                "malformed [tier] table: expected a table with name / unsupported_modules / oscillator_supported",
            )
        )
    else:
        tier_name = str(tier_cfg.get("name", "unknown"))
        unsupported_modules = tier_cfg.get("unsupported_modules")
        oscillator_supported_raw = tier_cfg.get("oscillator_supported", True)

        if unsupported_modules is None:
            unsupported_modules = []

        malformed: str | None = None
        if not isinstance(unsupported_modules, list):
            malformed = "unsupported_modules must be a list of strings"
        elif not all(isinstance(m, str) for m in unsupported_modules):
            malformed = "unsupported_modules must be a list of strings"
        elif not isinstance(oscillator_supported_raw, bool):
            malformed = "oscillator_supported must be a bool"

        if malformed:
            results.append(
                CheckResult(
                    GROUP_CONFIG,
                    "Tier fit",
                    FAIL,
                    f"malformed [tier] table: {malformed}",
                )
            )
        else:
            unsupported = set(unsupported_modules)
            offending = [m for m in enabled if m in unsupported]
            oscillator_section = config.get("oscillator")
            if oscillator_section is not None and not isinstance(oscillator_section, dict):
                results.append(
                    CheckResult(
                        GROUP_CONFIG,
                        "Tier fit",
                        FAIL,
                        "malformed [oscillator] section: expected a table",
                    )
                )
            else:
                oscillator_enabled = (
                    bool(oscillator_section.get("enabled", False))
                    if isinstance(oscillator_section, dict)
                    else False
                )
                oscillator_supported = bool(oscillator_supported_raw)
                if offending:
                    results.append(
                        CheckResult(
                            GROUP_CONFIG,
                            "Tier fit",
                            FAIL,
                            f"enabled modules unsupported by tier {tier_name}: "
                            f"{', '.join(offending)}; disable them in the operator config "
                            "or record a larger tier",
                        )
                    )
                elif oscillator_enabled and not oscillator_supported:
                    results.append(
                        CheckResult(
                            GROUP_CONFIG,
                            "Tier fit",
                            FAIL,
                            f"[oscillator].enabled is not supported by tier {tier_name}; "
                            "disable it in the operator config or record a larger tier",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            GROUP_CONFIG,
                            "Tier fit",
                            PASS,
                            f"tier {tier_name}: the enabled modules fit",
                        )
                    )

    preservation_cfg = PreservationConfig.from_section(config.get("preservation") or {})
    encryption_enabled = bool(
        ((config.get("security") or {}).get("state_encryption") or {}).get("enabled", False)
    )
    preservation_active = (
        preservation_cfg.divergence_monitor.enabled or preservation_cfg.welfare_response.enabled
    )
    if preservation_cfg.require_encryption and not encryption_enabled and preservation_active:
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Preservation encryption posture",
                FAIL,
                "[preservation].require_encryption=true but "
                "[security.state_encryption].enabled=false with a "
                "preservation monitor ON: preserve_live will raise (refuse to "
                "write) at the first crossing. See WELFARE NET above.",
            )
        )
    elif preservation_cfg.require_encryption and not encryption_enabled:
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Preservation encryption posture",
                SKIP,
                "require_encryption=true but no preservation monitor is "
                "enabled (the net is off; this posture is not exercised)",
            )
        )
    else:
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Preservation encryption posture",
                PASS,
                f"require_encryption={preservation_cfg.require_encryption}, "
                f"state_encryption.enabled={encryption_enabled}",
            )
        )

    problems = check_torch_stack()
    desc = describe_torch_stack()
    if problems:
        results.append(
            CheckResult(
                GROUP_CONFIG,
                "Torch stack",
                FAIL,
                "; ".join(problems) + " — reinstall with scripts/install.sh",
            )
        )
    elif desc == "torch not installed":
        results.append(CheckResult(GROUP_CONFIG, "Torch stack", SKIP, desc))
    else:
        results.append(CheckResult(GROUP_CONFIG, "Torch stack", PASS, desc))
    return results


# ---------------------------------------------------------------------------
# Orchestration + report rendering
# ---------------------------------------------------------------------------


async def run_async_checks(config: dict[str, Any]) -> list[CheckResult]:
    """Run the async checks (1-5) in order, never letting one crash the rest.

    Each check function already catches its own internal failures and turns
    them into FAIL rows; this outer guard exists only for the unexpected
    (e.g. an import failing at call time), so a single broken check degrades
    to one honest FAIL row instead of losing the whole report.

    The state-encryption key is resolved into the environment FIRST, before
    SERVICES runs — the SERVICES group includes the Nexus health board's own
    ``State encryption`` probe (``kaine.nexus.health.probe_state_encryption``),
    which reads ``$KAINE_STATE_KEY`` directly. Resolving the key here (once)
    keeps that probe and the WELFARE NET check below consistent instead of
    the SERVICES probe falsely reporting no-key because it ran first.
    """
    _resolve_state_key_into_env()
    results: list[CheckResult] = []
    checks: list[tuple[str, Any]] = [
        (GROUP_SERVICES, check_services()),
        (GROUP_ORGAN, check_organ(config)),
        (GROUP_PERCEPTION, check_perception(config)),
        (GROUP_WELFARE, check_welfare(config)),
        (GROUP_RESOURCES, check_resources(config)),
    ]
    for group, coro in checks:
        try:
            results.extend(await coro)
        except Exception as exc:
            log.error("preboot: %s check raised", group, exc_info=True)
            results.append(
                CheckResult(group, "(check crashed)", FAIL, f"{type(exc).__name__}: {exc}")
            )
    return results


def render_table(results: list[CheckResult]) -> str:
    """Render an aligned, grouped PASS/WARN/FAIL/SKIP table."""
    if not results:
        return "(no checks ran)"
    name_w = max(len(r.name) for r in results)
    lines: list[str] = []
    current_group: str | None = None
    for r in results:
        if r.group != current_group:
            if current_group is not None:
                lines.append("")
            lines.append(f"-- {r.group} --")
            current_group = r.group
        detail = (r.detail or "").splitlines()[0] if r.detail else ""
        lines.append(f"  [{r.status:<4}] {r.name:<{name_w}}  {detail}")
    return "\n".join(lines)


def verdict_line(results: list[CheckResult]) -> str:
    n_pass = sum(1 for r in results if r.status == PASS)
    n_fail = sum(1 for r in results if r.status == FAIL)
    n_warn = sum(1 for r in results if r.status == WARN)
    n_skip = sum(1 for r in results if r.status == SKIP)
    overall = PASS if n_fail == 0 else FAIL
    return (
        f"VERDICT: {overall}  ({len(results)} checks: {n_pass} pass, {n_fail} fail, "
        f"{n_warn} warn, {n_skip} skip)"
    )


def report_ok(results: list[CheckResult]) -> bool:
    return all(r.status != FAIL for r in results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from kaine.config import ProfileError
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        prog="python -m kaine.preboot",
        description=(
            "Pre-boot dry-run: verify the whole supporting stack — services, "
            "the organ, perception delivery, the welfare preserve/revive "
            "net, and bus memory and disk headroom — actually WORK before "
            "booting the KAINE entity. Never "
            "boots the entity itself."
        ),
    )
    parser.parse_args(argv)

    from kaine.storage import install_data_root

    try:
        config = load_runtime_config(SHIPPED_CONFIG_PATH, OPERATOR_CONFIG_PATH)
    except FileNotFoundError as exc:
        sys.stderr.write(f"preboot: could not load config: {exc}\n")
        return 2
    except ProfileError as exc:
        sys.stderr.write(f"pre-boot: configuration error: {exc}\n")
        return 2

    install_data_root(config)

    try:
        results = asyncio.run(run_async_checks(config))
    except Exception as exc:  # pragma: no cover - run_async_checks never raises
        sys.stderr.write(f"preboot: unexpected error running checks: {exc}\n")
        return 2
    results += check_config_sanity(config)

    print(render_table(results))
    print()
    print(verdict_line(results))

    return 0 if report_ok(results) else 1


if __name__ == "__main__":
    sys.exit(main())
