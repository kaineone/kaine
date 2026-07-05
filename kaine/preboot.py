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
  5. CONFIG     — which boot mode this run would take (operator-supervised vs
                  research), which modules are enabled, and whether the
                  preservation config would fail closed (require_encryption
                  set but state encryption off while a monitor is enabled).

Every check is best-effort and NEVER raises out of this module — a check that
cannot run reports the honest gap as a FAIL/SKIP row with a reason, never a
silent pass and never an uncaught traceback (mirrors the "never raises"
contract of ``kaine.nexus.health`` and ``kaine.setup.organ``).

Exit code is non-zero iff any check reports FAIL, so this composes as a CI /
boot-script gate: ``python -m kaine.preboot && python -m kaine.cycle``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from kaine.boot import (
    _build_perception_feed_audio_factory,
    _build_perception_feed_video_factory,
)
from kaine.config import OPERATOR_CONFIG_PATH, SHIPPED_CONFIG_PATH, load_kaine_config
from kaine.cycle.preservation_monitor import PreservationConfig
from kaine.cycle.research_gate import research_mode_requested, run_preflight_self_check
from kaine.nexus import health
from kaine.nexus.health import load_health_prober
from kaine.security.crypto import CryptoConfigError, install_from_section
from kaine.setup.organ import verify_organ_generates

log = logging.getLogger(__name__)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

GROUP_SERVICES = "SERVICES"
GROUP_ORGAN = "ORGAN"
GROUP_PERCEPTION = "PERCEPTION"
GROUP_WELFARE = "WELFARE NET (preserve -> revive dry run)"
GROUP_CONFIG = "CONFIG SANITY"

# Default location of the gitignored 32-byte state-encryption key, as
# documented by the operator config (config/kaine.operator.toml) and
# SECURITY.md. Read into $KAINE_STATE_KEY for this process ONLY if the
# operator has not already exported it — the key itself is never logged.
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
    status: str  # PASS | FAIL | SKIP
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
    prober = load_health_prober(kaine_toml=kaine_toml, secrets_toml=secrets_toml)
    snapshot = await prober.snapshot(force=True)
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
        results.append(
            CheckResult(GROUP_SERVICES, "(no dependencies probed)", SKIP, "")
        )
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
                GROUP_ORGAN, "Organ content", SKIP,
                "[modules].lingua = false — no organ configured for this run",
            )
        ]

    try:
        from kaine.organ_window_state import organ_unloaded

        if organ_unloaded():
            return [
                CheckResult(
                    GROUP_ORGAN, "Organ content", SKIP,
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
                GROUP_PERCEPTION, "Perception feed", SKIP,
                "[perception_feed].mode = off — the entity WILL BE SENSELESS "
                "(no video/audio stimulus configured)",
            )
        ]
    if mode == "live":
        return [
            CheckResult(
                GROUP_PERCEPTION, "Perception feed", SKIP,
                "mode = live (real camera/microphone) — not exercised by this "
                "offline dry-run; bring Topos/Audition up to verify hardware "
                "capture (operator-present demos only, not a research run)",
            )
        ]

    results: list[CheckResult] = []
    results.append(_check_perception_video(config, feed, mode))
    results.append(await _check_perception_audio(config, feed, mode))
    return results


def _check_perception_video(
    config: dict[str, Any], feed: dict[str, Any], mode: str
) -> CheckResult:
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
            GROUP_PERCEPTION, "Perception (video source)", FAIL,
            f"mode={mode}: {type(exc).__name__}: {exc}",
        )
    if opened and ok and frame is not None:
        shape = getattr(frame, "shape", None)
        return CheckResult(
            GROUP_PERCEPTION, "Perception (video source)", PASS,
            f"mode={mode}: source yielded a frame" + (f" {shape}" if shape else ""),
        )
    return CheckResult(
        GROUP_PERCEPTION, "Perception (video source)", FAIL,
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
            mode, feed, sample_rate=sample_rate, channels=channels,
            frames_per_block=frames_per_block,
        )
        stream = factory(
            device=None, sample_rate=sample_rate, channels=channels,
            frames_per_block=frames_per_block, callback=_on_block,
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
            GROUP_PERCEPTION, "Perception (audio source)", FAIL,
            f"mode={mode}: {type(exc).__name__}: {exc}",
        )

    if got and received and len(received[0]) > 0:
        return CheckResult(
            GROUP_PERCEPTION, "Perception (audio source)", PASS,
            f"mode={mode}: source yielded {len(received[0])} bytes PCM "
            f"within {AUDIO_PROBE_TIMEOUT_S:.0f}s",
        )
    return CheckResult(
        GROUP_PERCEPTION, "Perception (audio source)", FAIL,
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
                GROUP_WELFARE, "State-encryption key", FAIL,
                str(exc) + (f" ({key_note})" if key_note else ""),
            )
        )
        encryptor = None
    else:
        if encryptor.enabled:
            results.append(
                CheckResult(
                    GROUP_WELFARE, "State-encryption key", PASS,
                    "key resolved; encryption ACTIVE"
                    + (f" ({key_note})" if key_note else ""),
                )
            )
        else:
            results.append(
                CheckResult(
                    GROUP_WELFARE, "State-encryption key", SKIP,
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
        CheckResult(
            GROUP_WELFARE, "Preserve -> revive dry run", PASS if self_ok else FAIL, detail
        )
    )
    return results


# ---------------------------------------------------------------------------
# 5. CONFIG SANITY
# ---------------------------------------------------------------------------


def check_config_sanity(config: dict[str, Any]) -> list[CheckResult]:
    """Report the boot mode, the enabled modules, and the encryption posture.

    Pure (no I/O beyond what's already in ``config``) — reuses
    ``research_mode_requested`` and ``PreservationConfig`` rather than
    re-deriving boot-mode logic.
    """
    results: list[CheckResult] = []

    research = research_mode_requested(config)
    if research:
        mode_detail = (
            "research (unsupervised) — requires the autonomous safety net "
            "verified (see WELFARE NET above)"
        )
    else:
        mode_detail = (
            "operator-supervised — requires KAINE_CYCLE_OPERATOR_PRESENT=1 "
            "at boot"
        )
    results.append(CheckResult(GROUP_CONFIG, "Boot mode", PASS, mode_detail))

    modules = config.get("modules") or {}
    enabled = sorted(k for k, v in modules.items() if v)
    if enabled:
        results.append(
            CheckResult(GROUP_CONFIG, "Modules enabled", PASS, ", ".join(enabled))
        )
    else:
        results.append(
            CheckResult(
                GROUP_CONFIG, "Modules enabled", FAIL,
                "NONE — the entity would boot collecting no events at all",
            )
        )

    preservation_cfg = PreservationConfig.from_section(config.get("preservation") or {})
    encryption_enabled = bool(
        ((config.get("security") or {}).get("state_encryption") or {}).get("enabled", False)
    )
    preservation_active = (
        preservation_cfg.divergence_monitor.enabled
        or preservation_cfg.welfare_response.enabled
    )
    if preservation_cfg.require_encryption and not encryption_enabled and preservation_active:
        results.append(
            CheckResult(
                GROUP_CONFIG, "Preservation encryption posture", FAIL,
                "[preservation].require_encryption=true but "
                "[security.state_encryption].enabled=false with a "
                "preservation monitor ON: preserve_live will raise (refuse to "
                "write) at the first crossing. See WELFARE NET above.",
            )
        )
    elif preservation_cfg.require_encryption and not encryption_enabled:
        results.append(
            CheckResult(
                GROUP_CONFIG, "Preservation encryption posture", SKIP,
                "require_encryption=true but no preservation monitor is "
                "enabled (the net is off; this posture is not exercised)",
            )
        )
    else:
        results.append(
            CheckResult(
                GROUP_CONFIG, "Preservation encryption posture", PASS,
                f"require_encryption={preservation_cfg.require_encryption}, "
                f"state_encryption.enabled={encryption_enabled}",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Orchestration + report rendering
# ---------------------------------------------------------------------------


async def run_async_checks(config: dict[str, Any]) -> list[CheckResult]:
    """Run the async checks (1-4) in order, never letting one crash the rest.

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
    """Render an aligned, grouped PASS/FAIL/SKIP table."""
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
    n_skip = sum(1 for r in results if r.status == SKIP)
    overall = PASS if n_fail == 0 else FAIL
    return (
        f"VERDICT: {overall}  "
        f"({len(results)} checks: {n_pass} pass, {n_fail} fail, {n_skip} skip)"
    )


def report_ok(results: list[CheckResult]) -> bool:
    return all(r.status != FAIL for r in results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(
        prog="python -m kaine.preboot",
        description=(
            "Pre-boot dry-run: verify the whole supporting stack — services, "
            "the organ, perception delivery, and the welfare preserve/revive "
            "net — actually WORK before booting the KAINE entity. Never "
            "boots the entity itself."
        ),
    )
    parser.parse_args(argv)

    try:
        config = load_kaine_config(SHIPPED_CONFIG_PATH, OPERATOR_CONFIG_PATH)
    except FileNotFoundError as exc:
        sys.stderr.write(f"preboot: could not load config: {exc}\n")
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
