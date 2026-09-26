# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator entrypoint: `python -m kaine.nexus` boots uvicorn against
the configured Nexus app. NOT invoked by first-boot scripts.
"""

from __future__ import annotations

import sys

from kaine.extras import check, format_missing

_missing = check({}, services={"nexus"})
if _missing:
    raise SystemExit(format_missing(_missing))
del _missing

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn

from kaine.bus.client import AsyncBus
from kaine.bus.config import load_bus_config
from kaine.bus.errors import BusConfigError
from kaine.bus.schema import Event
from kaine.evaluation.stream_registry import diagnostics_streams
from kaine.lifecycle.manager import ForkManager, merger_from_name
from kaine.nexus.app import create_app, make_default_privacy_filter
from kaine.nexus.bridge import BusBridge
from kaine.nexus.config import NexusConfigError, load_nexus_config
from kaine.nexus.conversation import LINGUA_EXTERNAL_STREAM
from kaine.nexus.health import load_health_prober

log = logging.getLogger(__name__)

# Derived from the canonical registry so the monitor, the research-event
# observer, and the raw archive never drift (see
# kaine/evaluation/stream_registry.py for the documented exclusions/extras).
DEFAULT_DIAGNOSTICS_STREAMS = diagnostics_streams()


def make_metrics_snapshot(
    runtime_path: Path = Path("state/cycle/runtime.json"),
):
    """Build the metrics_snapshot reader closure.

    The cycle process writes ``state/cycle/runtime.json`` on every tick (or every
    1s when idle). Nexus reads it on each request so it shows live values without
    an in-process cycle reference. The snapshot surfaces only non-content
    operational fields plus the run-identity / boot-mode metadata.
    """

    def metrics_snapshot() -> dict[str, Any]:
        if not runtime_path.exists():
            return {
                "cycle_status": "not running",
                "hint": "start the cycle with `python -m kaine.cycle`",
            }
        try:
            raw = json.loads(runtime_path.read_text())
        except Exception:
            return {"cycle_status": "runtime.json unreadable"}
        return {
            "cycle_status": "running",
            "pid": raw.get("pid"),
            "tick_index": raw.get("tick_index"),
            "processing_rate_hz": raw.get("processing_rate_hz"),
            "experiential_rate_hz": raw.get("experiential_rate_hz"),
            # Adaptive conscious access: the rate used on the latest tick and
            # the drive behind it; experiential_rate_hz above is the resting rate.
            "experiential_rate_effective_hz": raw.get("experiential_rate_effective_hz"),
            "access_drive": raw.get("access_drive"),
            # Operator-freeze state (experiential loop paused). Metadata-only —
            # the runtime.json writer records `cycle.is_paused`. Feeds the
            # left-rail four-state status chip (OFFLINE/FROZEN/SLEEPING/AWAKE);
            # frozen is only meaningful while the cycle is running.
            "frozen": bool(raw.get("frozen", False)),
            "modules": raw.get("modules") or [],
            # Run identity (RunContext) + boot-mode flags. Non-content run
            # metadata the diagnostics page renders in its run-identity /
            # supervision blocks. Absent keys read back as None.
            "run_id": raw.get("run_id"),
            "seed": raw.get("seed"),
            "git_sha": raw.get("git_sha"),
            "kaine_version": raw.get("kaine_version"),
            "deterministic": bool(raw.get("deterministic", False)),
            "supervision_mode": raw.get("supervision_mode"),
            "gate_checks": raw.get("gate_checks"),
        }

    return metrics_snapshot


def _load_lifecycle_config() -> dict[str, Any]:
    """Read the [lifecycle] table from config/kaine.toml (merged with the
    gitignored operator override). Returns an empty dict if the file is
    unreadable so the default `adapter_merger = "auto"` behavior still
    takes over (real TIES/DARE merger when the PEFT extra is importable,
    FakeAdapterMerger otherwise)."""
    from kaine.config import load_kaine_config

    if not Path("config/kaine.toml").exists():
        return {}
    try:
        data = load_kaine_config()
    except Exception:
        logging.exception("failed to read config/kaine.toml")
        return {}
    return data.get("lifecycle") or {}


def _build_fork_manager(
    lifecycle_cfg_loader: Any,
    encryption_section_loader: Any,
) -> tuple[ForkManager | None, str | None]:
    """Install the configured state-encryption posture and construct a ForkManager.

    Returns the manager and a reason string when fork/merge I/O is disabled.
    The reason is forwarded to the diagnostics router so /forks.json can
    report why fork operations are unavailable.
    """
    try:
        from kaine.security.crypto import install_from_section

        install_from_section(encryption_section_loader())
    except Exception as exc:
        log.error(
            "state-encryption setup failed; fork/merge state operations are disabled: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None, "the state-encryption posture could not be installed"

    try:
        lifecycle_cfg = lifecycle_cfg_loader()
        adapter_merger_name = str(lifecycle_cfg.get("adapter_merger", "auto"))
        adapter_merge_section = lifecycle_cfg.get("adapter_merge") or {}
        adapter_merger = merger_from_name(
            adapter_merger_name, config_section=adapter_merge_section
        )
        snapshots_path = str(lifecycle_cfg.get("snapshots_path", "state/forks"))
        max_retained = int(lifecycle_cfg.get("max_snapshots_retained", 64))
        return (
            ForkManager(
                snapshots_path,
                adapter_merger=adapter_merger,
                max_snapshots_retained=max_retained,
            ),
            None,
        )
    except Exception:
        log.warning("fork manager unavailable", exc_info=True)
        return None, "the fork manager could not be constructed"


def _load_security_state_encryption_config() -> dict[str, Any]:
    """Read [security.state_encryption] from config/kaine.toml (merged with
    the gitignored operator overlay).

    Raises on configuration errors so a malformed overlay can never be
    interpreted as a disabled encryption section. Only returns an empty
    section when the config file does not exist, which is the documented
    unconfigured case.
    """
    from kaine.config import load_kaine_config

    if not Path("config/kaine.toml").exists():
        return {}
    data = load_kaine_config()
    return (data.get("security") or {}).get("state_encryption") or {}


async def _build():
    bus_config = load_bus_config()
    bus = AsyncBus(bus_config)
    nexus_config = load_nexus_config()
    privacy = make_default_privacy_filter(nexus_config)
    bridge = BusBridge(bus, privacy, streams=DEFAULT_DIAGNOSTICS_STREAMS)

    async def history_loader(n: int) -> list[tuple[str, Event]]:
        try:
            return await bus.read(LINGUA_EXTERNAL_STREAM, last_id="0", count=n, block_ms=0)
        except Exception:
            logging.exception("conversation history backfill failed")
            return []

    metrics_snapshot = make_metrics_snapshot()

    # Install the same state-encryption posture the cycle uses so fork/merge
    # snapshots written/read from this process honour [security.state_encryption].
    # Fails closed: a configuration or key error disables fork/merge I/O.
    fork_manager, fm_reason = _build_fork_manager(
        _load_lifecycle_config, _load_security_state_encryption_config
    )

    health_prober = None
    try:
        health_prober = load_health_prober()
    except Exception:
        logging.warning("health prober unavailable", exc_info=True)

    async def rate_control_publisher(payload: dict[str, Any]) -> None:
        """Publish a `cycle.set_rates` event to the `cycle.control` stream.

        The bus's `publish()` routes by `event.source` to `<source>.out`, so
        we write the control stream directly via the redis client, using the
        same wire encoding the bus uses so the running cycle (which drains
        `cycle.control` once per tick) can decode it.
        """
        from kaine.bus.client import _encode_event

        event = Event(
            source="nexus",
            type="cycle.set_rates",
            payload=payload,
            salience=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        await bus.client.xadd(
            "cycle.control",
            _encode_event(event),
            maxlen=10000,
            approximate=True,
        )

    # Evaluation surface — read-only metrics, opt-in via [evaluation]. Set this
    # up BEFORE create_app so the unified console at `/` can render the
    # evaluation panels server-side via `evaluation_provider`. The router (for
    # `/diagnostics/evaluation/`) is added after the app is built.
    eval_cfg: Any = None
    eval_registry: Any = None
    eval_attribution: Any = None
    evaluation_provider = None
    try:
        from kaine.evaluation import load_evaluation_config
        from kaine.evaluation.nexus_tab import (
            aggregate_evaluation_metrics,
            empty_evaluation_metrics,
        )

        eval_cfg = load_evaluation_config()
        if eval_cfg.enabled:
            # Pass the live sidecar registry so observer counts (welfare,
            # prediction-error) surface without needing the JSONL rollups.
            # Attribution is threaded through the same call. Both are optional;
            # when None the surface degrades gracefully.
            try:
                from kaine.evaluation.registry import SidecarRegistry

                eval_registry = SidecarRegistry(bus=bus, config=eval_cfg)
            except Exception:
                logging.debug("sidecar registry unavailable at nexus boot", exc_info=True)

            def evaluation_provider() -> dict[str, Any]:
                return aggregate_evaluation_metrics(
                    eval_cfg, attribution=eval_attribution, registry=eval_registry
                )
        else:
            evaluation_provider = empty_evaluation_metrics
    except Exception:
        logging.warning("evaluation surface unavailable", exc_info=True)

    app = create_app(
        config=nexus_config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=metrics_snapshot,
        fork_manager=fork_manager,
        fork_manager_reason=fm_reason,
        health_prober=health_prober,
        rate_control_publisher=rate_control_publisher,
        evaluation_provider=evaluation_provider,
    )

    # Mount the evaluation tab router (/diagnostics/evaluation/) when enabled.
    if eval_cfg is not None and getattr(eval_cfg, "enabled", False):
        try:
            from kaine.evaluation.nexus_tab import build_evaluation_router

            app.include_router(
                build_evaluation_router(
                    eval_cfg,
                    attribution=eval_attribution,
                    registry=eval_registry,
                ),
                dependencies=list(getattr(app.state, "read_dependencies", [])),
            )
        except Exception:
            logging.warning("evaluation tab failed to mount", exc_info=True)

    return app, nexus_config


def _is_loopback_host(host: str) -> bool:
    import ipaddress

    if host.lower() in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
        return addr.is_loopback
    except ValueError:
        return False


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.new_event_loop()
    try:
        app, config = loop.run_until_complete(_build())
    except NexusConfigError as exc:
        log.error("nexus: %s", exc)
        return 1
    except BusConfigError as exc:
        # A fresh clone has no Redis password until the bootstrap has run; say
        # what to do instead of dumping a traceback.
        log.error(
            "nexus: the event bus is not set up yet (%s). "
            "Run: bash scripts/redis-bootstrap.sh",
            exc,
        )
        return 1
    finally:
        loop.close()

    if not (config.conversation_enabled or config.diagnostics_enabled):
        log.error(
            "nexus: no console is enabled; set [nexus].diagnostics_enabled "
            "(or conversation_enabled) to true, since signing in would lead nowhere"
        )
        return 1

    if not _is_loopback_host(config.host):
        if not config.non_loopback_allowed:
            log.error(
                "nexus: refusing to bind non-loopback host %s without "
                "[nexus].non_loopback_allowed = true",
                config.host,
            )
            return 1
        if not config.operator_token:
            log.error(
                "nexus: refusing to bind non-loopback host %s without a "
                "configured operator_token (KAINE_NEXUS_TOKEN or "
                "config/secrets.toml [nexus] operator_token)",
                config.host,
            )
            return 1

    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
