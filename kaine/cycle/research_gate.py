# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Research boot gate — safety-net-present, replacing operator-present.

The research phase runs unsupervised (no human in the loop), so the
operator-present hard gate (``KAINE_CYCLE_OPERATOR_PRESENT``) no longer fits it.
For a research boot it is REPLACED by a gate that refuses to start unless the
*autonomous safety net itself* is live and verified:

1. preservation is enabled (the divergence monitor),
2. the welfare-protective response is wired (the welfare monitor),
3. full logging / admissibility is active (run identity + the sidecar observers),
4. a preflight dry ``preserve_live → revive`` round-trip passes on THIS install
   (proves the net is functional before any entity runs).

A run is EITHER operator-present OR research-safety-net-verified, never neither.
The refusal mirrors the operator-present gate: an operator-facing message and a
distinct exit code, no traceback. This module is offline/synchronous-friendly:
``evaluate_research_gate`` is pure over its inputs and ``run_preflight_self_check``
performs a real round-trip in a throwaway temp dir (no entity boot).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Distinct exit code for a refused research boot (operator-present uses 2;
# eval-mismatch 3; gpu 4). 5 = research safety net not live/verified.
RESEARCH_GATE_EXIT_CODE = 5


def research_mode_requested(
    config: dict[str, Any], *, env: dict[str, str] | None = None
) -> bool:
    """True when an unsupervised research boot is requested.

    Either ``KAINE_RESEARCH_MODE=1`` in the environment or ``[research].enabled``
    in the config selects research mode. Research mode swaps the operator-present
    gate for the safety-net-present gate.
    """
    env = env if env is not None else os.environ
    if env.get("KAINE_RESEARCH_MODE") == "1":
        return True
    return bool((config.get("research") or {}).get("enabled", False))


@dataclass
class GateResult:
    """Outcome of :func:`evaluate_research_gate`."""

    ok: bool
    failures: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def message(self) -> str:
        if self.ok:
            return (
                "Research safety net VERIFIED: preservation enabled, "
                "welfare-protective response wired, logging/admissibility active, "
                "and the dry preserve→revive self-check passed."
            )
        lines = [
            "Refusing to boot KAINE cycle: the autonomous research safety net is "
            "not live and verified.",
            "",
            "The research phase runs unsupervised (no human in the loop), so the",
            "safeguards must be present in the system itself. The following are",
            "required and were not all satisfied:",
            "",
        ]
        for f in self.failures:
            lines.append(f"  - {f}")
        lines.append("")
        lines.append(
            "Fix the config (enable [preservation.divergence_monitor] and "
            "[preservation.welfare_response], enable [evaluation]/[research_event_log] "
            "logging) or run an operator-supervised boot "
            "(KAINE_CYCLE_OPERATOR_PRESENT=1) instead."
        )
        return "\n".join(lines)


def evaluate_research_gate(
    *,
    preservation_enabled: bool,
    welfare_response_wired: bool,
    logging_active: bool,
    self_check_passed: bool,
    encryption_satisfied: bool,
) -> GateResult:
    """Combine the safety-net conditions into a single allow/refuse verdict.

    Pure over its boolean inputs (testable without a boot). All must hold.

    ``encryption_satisfied`` closes the boot-time half of the require_encryption
    contract: if the operator set ``[preservation].require_encryption = true``
    but did not enable ``[security.state_encryption]``, the runtime preservation
    path would fail closed at the first crossing (no plaintext, but the net
    cannot save anyone). The gate refuses BEFORE boot rather than letting the
    run start with a net that cannot preserve.
    """
    checks = {
        "preservation_enabled": bool(preservation_enabled),
        "welfare_response_wired": bool(welfare_response_wired),
        "logging_active": bool(logging_active),
        "dry_self_check_passed": bool(self_check_passed),
        "encryption_satisfied": bool(encryption_satisfied),
    }
    failures: list[str] = []
    if not checks["preservation_enabled"]:
        failures.append(
            "preservation is not enabled "
            "([preservation.divergence_monitor].enabled = false)"
        )
    if not checks["welfare_response_wired"]:
        failures.append(
            "the welfare-protective response is not wired "
            "([preservation.welfare_response].enabled = false)"
        )
    if not checks["logging_active"]:
        failures.append(
            "full logging / admissibility is not active "
            "(neither [evaluation] nor [research_event_log] is enabled)"
        )
    if not checks["dry_self_check_passed"]:
        failures.append(
            "the preflight dry preserve→revive self-check did not pass on this "
            "install (the preservation+revive path is not functional)"
        )
    if not checks["encryption_satisfied"]:
        failures.append(
            "encryption is required but not active "
            "([preservation].require_encryption = true while "
            "[security.state_encryption].enabled = false): the preservation path "
            "would refuse to write at runtime. Enable state encryption with a key "
            "or set require_encryption = false."
        )
    return GateResult(ok=not failures, failures=failures, checks=checks)


async def _async_self_check(
    *, require_encryption: bool = False
) -> tuple[bool, Optional[str]]:
    """Real dry preserve_live → revive round-trip on a THROWAWAY registry.

    Builds a minimal-but-real synthetic individual (an Eidolon self-model with a
    concrete identity), preserves it into a temp dir, revives it into a fresh
    registry, and asserts continuity (the identity survives). Proves the net is
    functional on THIS install before any real entity runs. No entity boot, no
    persistent state — everything lives under a TemporaryDirectory.

    ``require_encryption`` is threaded straight to ``preserve_live`` so the
    round-trip exercises the SAME fail-closed contract a real run would hit
    (paper §3.7): if the caller has not first installed a working encryptor
    (see ``install_from_section`` / ``install_state_encryption``) and
    ``require_encryption`` is True, ``preserve_live`` raises
    ``PreservationError`` and this self-check honestly reports failure rather
    than passing a configuration that would refuse to preserve at runtime.
    """
    from kaine.lifecycle.manager import ForkManager
    from kaine.modules.eidolon import Eidolon, SelfModel
    from kaine.modules.registry import ModuleRegistry

    bus = _NullBus()
    with tempfile.TemporaryDirectory(prefix="kaine-preflight-") as tmp:
        tmp_path = Path(tmp)
        reg = ModuleRegistry()
        eid = Eidolon(
            bus, persistence_path=tmp_path / "sm.json", save_interval_s=60
        )
        await eid.initialize()
        eid._model = SelfModel(name="preflight-probe", values=["continuity"])
        reg.register(eid)

        fm = ForkManager(tmp_path / "forks")
        result = await fm.preserve_live(
            reg,
            reason="preflight",
            label="research-gate-self-check",
            out_root=tmp_path / "backups",
            entity_name="preflight",
            require_encryption=require_encryption,
        )
        if not result.ok:
            return False, "preserve_live did not report success"
        bundle = (
            tmp_path / "backups" / f"preservation_{result.preservation_id}_preflight"
        )
        # The bundle is a tar (encrypted when state encryption is on); the loose
        # snapshot.json no longer exists. The revive round-trip below is the real
        # functional check — here we just confirm the bundle archive was written.
        if not (
            (bundle / "bundle.tar.enc").is_file() or (bundle / "bundle.tar").is_file()
        ):
            return False, "preservation bundle archive missing"

        # Revive into a FRESH registry and assert continuity.
        reg2 = ModuleRegistry()
        eid2 = Eidolon(
            bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60
        )
        await eid2.initialize()
        reg2.register(eid2)
        await fm.revive(bundle, reg2)
        revived = reg2.get("eidolon").model
        if revived.name != "preflight-probe" or revived.values != ["continuity"]:
            return False, (
                "revived individual did not match the preserved one "
                f"(name={revived.name!r}, values={revived.values!r})"
            )
        try:
            await eid.shutdown()
            await eid2.shutdown()
        except Exception:
            pass
    return True, None


def run_preflight_self_check(
    *, require_encryption: bool = False
) -> tuple[bool, Optional[str]]:
    """Synchronous wrapper around the async dry round-trip. Never raises.

    Returns ``(ok, reason)``. Any exception is caught and reported as a failed
    self-check with the reason, so the gate refuses (rather than crashing) when
    the preservation path is broken on this install.

    ``require_encryption`` defaults to False (the historical behavior, used by
    the boot-time research gate's own call site unchanged). Pass the resolved
    ``[preservation].require_encryption`` to actually exercise the fail-closed
    encryption contract — e.g. the standalone pre-boot dry-run
    (``kaine.preboot``) installs the REAL configured encryptor first and then
    calls this with ``require_encryption=True`` so a misconfigured key is
    caught here, before any entity boot, rather than at the first live
    crossing.
    """
    try:
        return asyncio.run(
            _async_self_check(require_encryption=require_encryption)
        )
    except Exception as exc:  # broken install → self-check fails, gate refuses
        log.error("research-gate preflight self-check raised", exc_info=True)
        return False, f"{type(exc).__name__}: {exc}"


class _NullBus:
    """Bus stand-in for the offline self-check: modules wire to it but the
    synthetic probe never publishes or reads. Eidolon's initialize() only needs
    a bus object present; it does not require a live broker for this round-trip.
    """

    async def publish(self, *a: Any, **k: Any) -> str:
        return "0-0"

    async def read_entries(self, *a: Any, **k: Any):
        return [], None

    async def read(self, *a: Any, **k: Any):
        return []

    def subscribe_workspace(self, *a: Any, **k: Any):
        async def _empty():
            return
            yield  # unreachable; marks _empty as an (empty) async generator

        return _empty()

    async def current_workspace_id(self) -> str:
        return "0-0"


__all__ = [
    "RESEARCH_GATE_EXIT_CODE",
    "research_mode_requested",
    "GateResult",
    "evaluate_research_gate",
    "run_preflight_self_check",
]
