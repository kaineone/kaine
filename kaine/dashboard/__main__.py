# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator entrypoint: `python -m kaine.dashboard` boots uvicorn against
the configured dashboard app. NOT invoked by first-boot scripts.
"""

from __future__ import annotations

import sys

from kaine.extras import check, format_missing

_missing = check({}, services={"dashboard"})
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
from kaine.config import load_kaine_config
from kaine.dashboard.app import create_app, make_default_privacy_filter
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfigError, load_dashboard_config
from kaine.dashboard.conversation import (
    ConversationState,
    read_conversation_history,
    read_entity_name,
)
from kaine.dashboard.health import load_health_prober
from kaine.evaluation.stream_registry import diagnostics_streams
from kaine.lifecycle.identity import IDENTITY_PATH
from kaine.lifecycle.manager import ForkManager, merger_from_name
from kaine.storage import install_data_root, resolve

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
    1s when idle). The dashboard reads it on each request so it shows live values without
    an in-process cycle reference. The snapshot surfaces only non-content
    operational fields plus the run-identity / boot-mode metadata.
    """

    def metrics_snapshot() -> dict[str, Any]:
        path = resolve(runtime_path)
        if not path.exists():
            return {
                "cycle_status": "not running",
                "hint": "start the cycle with `python -m kaine.cycle`",
            }
        try:
            raw = json.loads(path.read_text())
        except Exception:
            return {"cycle_status": "runtime.json unreadable"}
        return {
            "cycle_status": "running",
            "pid": raw.get("pid"),
            "tick_index": raw.get("tick_index"),
            "processing_rate_hz": raw.get("processing_rate_hz"),
            "experiential_rate_hz": raw.get("experiential_rate_hz"),
            # Adaptive access: the rate used on the latest tick and
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


def _warn_ignored_snapshot_retention(lifecycle_cfg: dict[str, Any]) -> None:
    """Warn when a config still sets the removed snapshot count cap.

    ``[lifecycle].max_snapshots_retained`` used to delete the oldest snapshot
    directories. The fork root holds preserved entities, and infrastructure
    never deletes an entity, so the key is accepted and ignored.
    """
    raw = lifecycle_cfg.get("max_snapshots_retained")
    if raw is None:
        return
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 1
    if value > 0:
        log.warning(
            "[lifecycle].max_snapshots_retained is ignored: snapshots are never "
            "deleted by infrastructure (removing an entity's state is the "
            "CAL-gated decommission path only); remove the key from your config"
        )


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

        def _merge_checks_factory():
            from kaine.modules.sleep.capability_eval import (
                AbliterationProbeScorer,
                LocalProbeSetCapabilityEval,
            )

            p = str(adapter_merge_section.get("capability_probe_path", "")).strip()
            q = str(adapter_merge_section.get("abliteration_probe_path", "")).strip()
            return (
                LocalProbeSetCapabilityEval(probe_path=p or None, require_probes=True),
                AbliterationProbeScorer(probe_path=q or None),
            )

        adapter_merger = merger_from_name(
            adapter_merger_name,
            config_section=adapter_merge_section,
            merge_checks=_merge_checks_factory,
        )
        snapshots_path = str(resolve(lifecycle_cfg.get("snapshots_path", "state/forks")))
        _warn_ignored_snapshot_retention(lifecycle_cfg)
        return (
            ForkManager(snapshots_path, adapter_merger=adapter_merger),
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
    # Install the process-wide data root for this dashboard process.
    try:
        kaine_config = load_kaine_config()
    except Exception as exc:
        logging.warning("could not load KAINE config; data root not installed: %s", exc)
        kaine_config = None
    if kaine_config is not None:
        install_data_root(kaine_config)

    bus_config = load_bus_config()
    bus = AsyncBus(bus_config)
    dashboard_config = load_dashboard_config()
    privacy = make_default_privacy_filter(dashboard_config)
    bridge = BusBridge(bus, privacy, streams=DEFAULT_DIAGNOSTICS_STREAMS)

    async def history_loader(n: int) -> list[tuple[str, Event]]:
        return await read_conversation_history(bus, n)

    metrics_snapshot = make_metrics_snapshot()

    # Install the same state-encryption posture the cycle uses so fork/merge
    # snapshots written/read from this process honour [security.state_encryption].
    # Fails closed: a configuration or key error disables fork/merge I/O.
    fork_manager, fm_reason = _build_fork_manager(
        _load_lifecycle_config, _load_security_state_encryption_config
    )

    # Conversation state is built after the state-encryption posture is
    # installed because reading the self-model file may require decryption.
    self_model_section = (kaine_config or {}).get("self_model") or {}
    if not isinstance(self_model_section, dict):
        self_model_section = {}
    self_model_path_default = "state/self_model/self_model.json"
    self_model_path_value = self_model_section.get("persistence_path", self_model_path_default)
    if not isinstance(self_model_path_value, str):
        self_model_path_value = self_model_path_default
    self_model_path = resolve(Path(self_model_path_value))
    identity_path = resolve(IDENTITY_PATH)

    conversation_state = ConversationState()
    launch_name = read_entity_name(self_model_path, identity_path)
    if launch_name is not None:
        conversation_state.entity_name = launch_name

    bridge.add_observer(conversation_state.observe)

    async def startup() -> None:
        await conversation_state.backfill(bus)

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
            source="dashboard",
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
        from kaine.evaluation.dashboard_tab import (
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
                from kaine.text_embedding import make_text_embedder

                kaine_config = (
                    load_kaine_config()
                    if Path("config/kaine.toml").exists()
                    else {}
                )
                eval_registry = SidecarRegistry(
                    bus=bus,
                    config=eval_cfg,
                    embedder=make_text_embedder(kaine_config),
                )
            except Exception:
                logging.debug("sidecar registry unavailable at dashboard boot", exc_info=True)

            def evaluation_provider() -> dict[str, Any]:
                return aggregate_evaluation_metrics(
                    eval_cfg, attribution=eval_attribution, registry=eval_registry
                )
        else:
            evaluation_provider = empty_evaluation_metrics
    except Exception:
        logging.warning("evaluation surface unavailable", exc_info=True)

    app = create_app(
        config=dashboard_config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=metrics_snapshot,
        fork_manager=fork_manager,
        fork_manager_reason=fm_reason,
        conversation_state=conversation_state,
        health_prober=health_prober,
        rate_control_publisher=rate_control_publisher,
        evaluation_provider=evaluation_provider,
        startup=startup,
    )

    # Mount the evaluation tab router (/diagnostics/evaluation/) when enabled.
    if eval_cfg is not None and getattr(eval_cfg, "enabled", False):
        try:
            from kaine.evaluation.dashboard_tab import build_evaluation_router

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

    return app, dashboard_config


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
    except DashboardConfigError as exc:
        log.error("dashboard: %s", exc)
        return 1
    except BusConfigError as exc:
        # A fresh clone has no Redis password until the bootstrap has run; say
        # what to do instead of dumping a traceback.
        log.error(
            "dashboard: the event bus is not set up yet (%s). "
            "Run: bash scripts/redis-bootstrap.sh",
            exc,
        )
        return 1
    finally:
        loop.close()

    if not (config.conversation_enabled or config.diagnostics_enabled):
        log.error(
            "dashboard: no console is enabled; set [dashboard].diagnostics_enabled "
            "(or conversation_enabled) to true, since signing in would lead nowhere"
        )
        return 1

    if not _is_loopback_host(config.host):
        if not config.non_loopback_allowed:
            log.error(
                "dashboard: refusing to bind non-loopback host %s without "
                "[dashboard].non_loopback_allowed = true",
                config.host,
            )
            return 1

    if config.access == "token" and not config.operator_token:
        log.error(
            "dashboard: [dashboard].access is \"token\" but no operator token is "
            "configured; set KAINE_DASHBOARD_TOKEN (in compose/.env for the "
            "containers) or [dashboard] operator_token in config/secrets.toml, "
            "or set [dashboard].access = \"open\""
        )
        return 1

    if config.access == "open":
        log.info(
            "dashboard: open access — no sign-in; anyone who can reach this address "
            "can view and control the entity. Accepted hosts: %s",
            ", ".join(config.host_allowlist),
        )

    if config.read_only:
        log.info("dashboard: read-only mode — every control is refused")

    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
