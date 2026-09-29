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
                  content gate (``kaine.setup.organ.verify_organ_generates``).
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
from kaine.bus.config import BusConfig, maxlen_for, typical_event_bytes
from kaine.bus.schema import module_stream
from kaine.config import (
    OPERATOR_CONFIG_PATH,
    SHIPPED_CONFIG_PATH,
    load_runtime_config,
    require_known_keys,
)
from kaine.cycle.preservation_monitor import PreservationConfig
from kaine.cycle.research_gate import research_mode_requested, run_preflight_self_check
from kaine.nexus import health
from kaine.nexus.health import load_health_prober
from kaine.security.crypto import CryptoConfigError, install_from_section
from kaine.setup.organ import verify_organ_generates
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
# Wall-clock ceiling for reading maxmemory from the server.
BUS_PROBE_TIMEOUT_S = 5.0

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
}
_GIB = 2**30


def _fmt_gib(n_bytes: float) -> str:
    return f"{n_bytes / _GIB:.2f} GiB"


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


def bus_budget(config: dict[str, Any]) -> tuple[int, list[tuple[str, int]]]:
    """Estimated Redis memory, in bytes, that the configured caps imply.

    Returns the budget (sum of maxlen x typical event size over
    :func:`budget_streams`, times :data:`BUS_BUDGET_HEADROOM_FACTOR`) and the
    per-stream estimates before headroom, largest first. Raises on a malformed
    ``[bus]`` table.
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
    per: list[tuple[str, int]] = [
        (stream, maxlen_for(caps, stream) * typical_event_bytes(stream))
        for stream in budget_streams(modules if isinstance(modules, dict) else {})
    ]
    per.sort(key=lambda item: item[1], reverse=True)
    total = sum(n for _, n in per) * BUS_BUDGET_HEADROOM_FACTOR
    return total, per


async def _read_server_maxmemory() -> int:
    """Read ``maxmemory`` from the configured KAINE Redis through the bus client."""
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
        return await bus.server_maxmemory()
    finally:
        try:
            await bus.close()
        except Exception:
            log.debug("bus close after maxmemory probe failed", exc_info=True)


async def check_bus_budget(
    config: dict[str, Any],
    *,
    read_maxmemory: Optional[Callable[[], Awaitable[int]]] = None,
) -> list[CheckResult]:
    """Compare the bus memory the stream caps imply with Redis ``maxmemory``.

    FAIL when the budget exceeds ``maxmemory``, WARN above
    :data:`BUS_BUDGET_WARN_FRACTION` of it, WARN when ``maxmemory`` cannot be
    read or is 0 (no limit), PASS otherwise. ``read_maxmemory`` is an async
    callable returning bytes; it defaults to a real ``CONFIG GET maxmemory``.
    """
    name = "Bus budget"
    try:
        budget, per = bus_budget(config)
    except Exception as exc:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                FAIL,
                f"could not compute the bus budget from [bus]: {type(exc).__name__}: {exc}",
            )
        ]
    largest = ", ".join(f"{stream} {_fmt_gib(n)}" for stream, n in per[:3])
    basis = (
        f"budget {_fmt_gib(budget)} (maxlen x typical event size over "
        f"{len(per)} streams, x{BUS_BUDGET_HEADROOM_FACTOR} for AOF rewrite; "
        f"largest: {largest})"
    )
    reader = read_maxmemory or _read_server_maxmemory
    try:
        maxmemory = int(await asyncio.wait_for(reader(), BUS_PROBE_TIMEOUT_S))
    except Exception as exc:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                WARN,
                f"could not read Redis maxmemory ({type(exc).__name__}: {exc}); "
                f"{basis}; make sure KAINE_REDIS_MAXMEMORY is at least the budget",
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
    if budget > maxmemory:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                FAIL,
                f"{vs}: the bus would fill Redis and halt the entity; raise "
                "KAINE_REDIS_MAXMEMORY (compose/.env) and restart Redis",
            )
        ]
    if budget > BUS_BUDGET_WARN_FRACTION * maxmemory:
        return [
            CheckResult(
                GROUP_RESOURCES,
                name,
                WARN,
                f"{vs}: above {BUS_BUDGET_WARN_FRACTION:.0%} of the cap; consider "
                "raising KAINE_REDIS_MAXMEMORY",
            )
        ]
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


def check_disk(
    config: dict[str, Any],
    *,
    disk_usage: Optional[Callable[[Path], Any]] = None,
) -> list[CheckResult]:
    """Free-disk rows for the state root, the data root and the Redis data dir.

    FAIL below max(``disk_fail_min_free_gb``, ``disk_fail_min_free_percent`` of
    the filesystem), WARN below ``disk_warn_min_free_gb``, PASS otherwise. The
    Redis row measures the native data directory
    (``<state_root>/services/redis/data``); a container volume is not
    resolvable from the host and is reported SKIP.
    """
    usage_fn = disk_usage or shutil.disk_usage
    try:
        settings = _preboot_settings(config)
    except ValueError as exc:
        return [CheckResult(GROUP_RESOURCES, "Disk free", FAIL, str(exc))]

    fail_gb = float(settings["disk_fail_min_free_gb"])
    fail_pct = float(settings["disk_fail_min_free_percent"])
    warn_gb = float(settings["disk_warn_min_free_gb"])
    state_root = Path(settings["state_root"])
    data_root = Path(settings["data_root"])
    redis_dir = state_root / "services" / "redis" / "data"

    targets: list[tuple[str, Path, bool]] = [
        ("Disk free (state root)", state_root, True),
        ("Disk free (data root)", data_root, True),
        ("Disk free (Redis data)", redis_dir, False),
    ]
    results: list[CheckResult] = []
    for name, path, walk_up in targets:
        if walk_up:
            measured = _nearest_existing(path)
        elif path.is_dir():
            measured = path
        else:
            results.append(
                CheckResult(
                    GROUP_RESOURCES,
                    name,
                    SKIP,
                    f"no native Redis data directory at {path}; a container "
                    "volume is not measured from the host",
                )
            )
            continue
        try:
            usage = usage_fn(measured)
        except OSError as exc:
            results.append(
                CheckResult(
                    GROUP_RESOURCES,
                    name,
                    FAIL,
                    f"{path}: could not read disk usage: {type(exc).__name__}: {exc}",
                )
            )
            continue
        total = float(usage.total)
        free = float(usage.free)
        fail_floor = max(fail_gb * _GIB, total * fail_pct / 100.0)
        where = str(path) if measured == path else f"{path} (measured at {measured})"
        detail = f"{where}: {_fmt_gib(free)} free of {_fmt_gib(total)}"
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
    return results


async def check_resources(config: dict[str, Any]) -> list[CheckResult]:
    """The RESOURCES group: the bus budget row, then the disk-free rows."""
    results = await check_bus_budget(config)
    results.extend(check_disk(config))
    return results


# ---------------------------------------------------------------------------
# 6. CONFIG SANITY
# ---------------------------------------------------------------------------


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

    try:
        config = load_runtime_config(SHIPPED_CONFIG_PATH, OPERATOR_CONFIG_PATH)
    except FileNotFoundError as exc:
        sys.stderr.write(f"preboot: could not load config: {exc}\n")
        return 2
    except ProfileError as exc:
        sys.stderr.write(f"pre-boot: configuration error: {exc}\n")
        return 2

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
