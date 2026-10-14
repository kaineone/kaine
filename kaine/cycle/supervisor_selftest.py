# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The supervisor self-test for the unattended boot gate.

Constructs a scratch supervisor from a real ``[supervisor]`` section, redirects every
stateful path to a temporary directory, registers a synthetic probe module,
and drives one controlled failure through the full freeze/snapshot/restart/
release/incident lifecycle.  The gate uses this to prove the supervisor's recovery
path works before any entity module is loaded.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from kaine.cycle import control_state, escalation_state
from kaine.cycle.supervisor import Supervisor, SupervisorConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.storage import resolve

if TYPE_CHECKING:
    from kaine.cycle.unattended_gate import Condition

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SelftestResult:
    ok: bool
    reason: str = ""
    steps: tuple[tuple[str, float], ...] = ()


class _Probe(BaseModule):
    """Synthetic module that fails once on demand and is light-restartable."""

    name = "supervisor_selftest_probe"

    def __init__(self, bus: Any) -> None:
        super().__init__(bus)
        self._fail = asyncio.Event()
        self.initialize_count = 0
        self.frozen_at_restart: Optional[bool] = None
        self._control_path: Optional[Path] = None

    async def initialize(self) -> None:
        self.initialize_count += 1
        # Provide a fresh failure event for each initialize so the second
        # initialize (after restart) starts healthy.
        self._fail = asyncio.Event()
        if self.initialize_count > 1 and self._control_path is not None:
            self.frozen_at_restart = control_state.read_control(
                self._control_path
            ).frozen
        task = asyncio.create_task(
            self._failure_task(), name=f"{self.name}-failure"
        )
        self._tasks.append(task)

    async def _failure_task(self) -> None:
        await self._fail.wait()
        raise RuntimeError("selftest induced fault")

    def holds_external_resources(self) -> bool:
        return False

    def serialize(self) -> dict[str, Any]:
        return {"probe": True}

    def induce_fault(self) -> None:
        self._fail.set()


class _NullBus:
    """Bus double that satisfies the supervisor's publish calls without sending."""

    async def publish(self, event: Any = None) -> str:
        return "0-0"

    async def current_workspace_id(self) -> str:
        return "0-0"


def _raise_rebuild(name: str) -> BaseModule:
    raise RuntimeError("selftest: heavy rebuild path must not be used")


async def run_supervisor_selftest(
    supervisor_section: dict, *, timeout_s: float = 10.0
) -> SelftestResult:
    try:
        cfg = SupervisorConfig.from_section(supervisor_section)
    except Exception as exc:
        return SelftestResult(False, f"invalid spot config: {exc}")

    if not cfg.enabled:
        return SelftestResult(False, "not enabled")
    if cfg.max_restart_attempts < 1:
        return SelftestResult(False, "no restart ladder")

    start = time.monotonic()
    steps: list[tuple[str, float]] = []
    last_step = "armed"

    with tempfile.TemporaryDirectory(prefix="kaine-spot-selftest-") as tmp:
        tmp_path = Path(tmp)
        control_path = tmp_path / "control.json"
        escalation_path = tmp_path / "escalation.json"

        scratch_cfg = dataclasses.replace(
            cfg,
            poll_interval_s=0.05,
            restart_backoff_s=0.0,
            incident_log=dataclasses.replace(
                cfg.incident_log,
                enabled=True,
                path=str(tmp_path / "incidents"),
            ),
        )

        registry = ModuleRegistry()
        probe = _Probe(_NullBus())
        probe._control_path = control_path
        registry.register(probe)

        fork_manager = ForkManager(tmp_path / "forks")

        supervisor = Supervisor(
            registry=registry,
            fork_manager=fork_manager,
            kaine_config={},
            config=scratch_cfg,
            rebuild_module=_raise_rebuild,
            bus=_NullBus(),
            control_path=control_path,
            escalation_path=escalation_path,
        )

        captured: list[dict[str, Any]] = []
        original_write = supervisor._write_incident_record

        async def _capture(
            record: dict[str, Any], *, publish: bool = True
        ) -> None:
            captured.append(record)
            await original_write(record, publish=publish)

        supervisor._write_incident_record = _capture

        try:
            await supervisor._incident_log.start()
            await probe.initialize()
            steps.append(("armed", time.monotonic() - start))

            probe.induce_fault()
            await asyncio.sleep(0)
            last_step = "induced"
            steps.append((last_step, time.monotonic() - start))

            stop_event = asyncio.Event()
            await asyncio.wait_for(
                supervisor._poll_once(stop_event), timeout=timeout_s
            )
            last_step = "recovered"
            steps.append((last_step, time.monotonic() - start))

            transitions = {
                rec.get("transition")
                for rec in captured
                if rec.get("module") == probe.name
            }
            required = ["detect", "freeze", "snapshot", "restart"]
            for transition in required:
                if transition not in transitions:
                    return SelftestResult(
                        False,
                        f"missing {transition} record",
                        tuple(steps),
                    )

            restart_records = [
                rec
                for rec in captured
                if rec.get("module") == probe.name
                and rec.get("transition") == "restart"
            ]
            if not any(
                rec.get("outcome") == "recovered" for rec in restart_records
            ):
                return SelftestResult(
                    False,
                    "restart did not report recovered",
                    tuple(steps),
                )

            if probe.frozen_at_restart is not True:
                return SelftestResult(
                    False,
                    "freeze did not take effect before restart",
                    tuple(steps),
                )

            if probe.initialize_count != 2:
                return SelftestResult(
                    False,
                    f"probe initialized {probe.initialize_count} times, expected 2",
                    tuple(steps),
                )

            if control_state.read_control(control_path).frozen:
                return SelftestResult(
                    False,
                    "cycle freeze was not released",
                    tuple(steps),
                )

            snapshot_exists = any((tmp_path / "forks").rglob("*"))
            if not snapshot_exists:
                return SelftestResult(
                    False,
                    "snapshot was not written",
                    tuple(steps),
                )

            for rec in captured:
                transition = rec.get("transition")
                if transition in required:
                    steps.append((transition, time.monotonic() - start))

            return SelftestResult(True, "", tuple(steps))
        except asyncio.TimeoutError:
            return SelftestResult(
                False,
                f"timed out during {last_step}",
                tuple(steps),
            )
        except Exception as exc:
            return SelftestResult(
                False,
                f"{type(exc).__name__}: {exc}",
                tuple(steps),
            )
        finally:
            try:
                await probe.shutdown()
            except Exception:
                log.warning(
                    "spot selftest probe shutdown failed", exc_info=True
                )
            try:
                await supervisor._incident_log.stop()
            except Exception:
                log.warning(
                    "spot selftest incident log stop failed", exc_info=True
                )


def check_supervisor_condition(
    supervisor_section: dict, *, timeout_s: float | None = None
) -> "Condition":
    from kaine.cycle.unattended_gate import CONDITION_NAMES, Condition

    try:
        cfg = SupervisorConfig.from_section(supervisor_section)
    except Exception as exc:
        return Condition(
            6, CONDITION_NAMES[6], False, f"invalid spot config: {exc}"
        )

    if not cfg.enabled:
        return Condition(6, CONDITION_NAMES[6], False, "not enabled")
    if cfg.max_restart_attempts < 1:
        return Condition(6, CONDITION_NAMES[6], False, "no restart ladder")

    escalation_dir = resolve(escalation_state.ESCALATION_PATH).parent
    try:
        escalation_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=escalation_dir, delete=True
        ):
            pass
    except OSError:
        return Condition(
            6, CONDITION_NAMES[6], False, "escalation path not writable"
        )

    if cfg.incident_log.enabled:
        incident_dir = resolve(Path(cfg.incident_log.path))
        try:
            incident_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=incident_dir, delete=True
            ):
                pass
        except OSError:
            return Condition(
                6, CONDITION_NAMES[6], False, "incident log not writable"
            )

    if timeout_s is None:
        timeout_s = cfg.selftest_timeout_s

    result = asyncio.run(run_supervisor_selftest(supervisor_section, timeout_s=timeout_s))
    if not result.ok:
        return Condition(
            6,
            CONDITION_NAMES[6],
            False,
            f"selftest failed: {result.reason}",
        )
    return Condition(6, CONDITION_NAMES[6], True, "")
