# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The state the cycle's boot phases share.

``kaine.cycle.__main__._boot_and_run`` runs its phases in order over one
``BootContext``; each phase reads what earlier phases set and adds its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, repr=False)
class BootContext:
    """State the boot phases share, in the order the phases set it.

    Each field is set by the phase named in its comment and read by later
    phases, the run loop or shutdown. Fields start as ``None``. The repr leaves
    every field out, because the context holds the effectors module's intent secret.
    """

    supervision_mode: Any = None  # parameter
    gate_checks: Any = None  # parameter
    revive: Any = None  # parameter
    identity: Any = None  # set by _phase_stage
    kaine_config: Any = None  # parameter
    fresh_development: Any = None  # set by _phase_stage
    stage_state: Any = None  # set by _phase_stage
    staging_enabled: Any = None  # set by _phase_stage
    eval_cfg: Any = None  # set by _phase_preconditions
    individuation_cfg: Any = None  # set by _phase_preconditions
    research_event_log_cfg: Any = None  # set by _phase_preconditions
    experiment_cfg: Any = None  # set by _phase_run_identity
    plugins: Any = None  # set by _phase_run_identity
    run_ctx: Any = None  # set by _phase_run_identity
    bus: Any = None  # set by _phase_bus
    preservation_cfg: Any = None  # set by _phase_bus
    welfare_producer: Any = None  # set by _phase_bus
    _publish_lifecycle: Any = None  # set by _phase_stimulus_source_hold
    stimulus_source_ready: Any = None  # set by _phase_stimulus_source_hold
    intent_secret: Any = None  # set by _phase_registry
    registry: Any = None  # set by _phase_registry
    ds_config: Any = None  # set by _phase_maturation_gate
    gate_runner: Any = None  # set by _phase_maturation_gate
    cycle_cfg: Any = None  # set by _phase_workspace
    coherence_scorer: Any = None  # set by _phase_workspace
    affect_provider: Any = None  # set by _phase_workspace
    access_rate: Any = None  # set by _phase_workspace
    affect_observer: Any = None  # set by _phase_workspace
    workspace: Any = None  # set by _phase_workspace
    action_selection: Any = None  # set by _phase_action_selection
    cycle: Any = None  # set by _phase_cycle
    supervisor_cfg: Any = None  # set by _phase_supervision
    fork_manager: Any = None  # set by _phase_supervision
    rebuild_module: Any = None  # set by _phase_supervision
    sidecar: Any = None  # set by _phase_sidecar
    ignition_log: Any = None  # set by _phase_ignition_log
    preview_server: Any = None  # set by _phase_preview
    perception_preview: Any = None  # set by _phase_preview
    remote_bridge: Any = None  # set by _phase_remote_bridge
    stop_event: Any = None  # set by _phase_signals
    supervisor: Any = None  # set by _phase_supervisor
    divergence_monitor: Any = None  # set by _phase_safety_net
    unfrozen_clock: Any = None  # set by _phase_safety_net; one per process, shared by the welfare timers
    welfare_monitor: Any = None  # set by _phase_safety_net
    caretaker: Any = None  # set by _phase_safety_net
    _caretaker_tasks: Any = None  # set by _phase_safety_net
    cycle_task: Any = None  # set by _phase_launch
    freeze_task: Any = None  # set by _phase_launch
    supervisor_task: Any = None  # set by _phase_launch
    divergence_task: Any = None  # set by _phase_launch
    welfare_task: Any = None  # set by _phase_launch
    gate_task: Any = None  # set by _phase_maturation
    individuation_task: Any = None  # set by _phase_maturation
    stimulus_source_watch_task: Any = None  # set by _phase_stimulus_source_watch
    caretaker_task: Any = None  # set by _phase_caretaker
    input_watch_task: Any = None  # set by _phase_caretaker
    stimulus_source_presence_task: Any = None  # set by _phase_development
    hearing_stage_watch: Any = None  # set by _phase_development
    development_task: Any = None  # set by _phase_development
    housekeeping_floor_task: Any = None  # set by _phase_development
    preserve_task: Any = None  # set by _phase_watchers
    programme_end_task: Any = None  # set by _phase_watchers
    utterance_outcome: Any = None  # set by _phase_watchers
    checkpointer: Any = None  # set by _phase_checkpoint
    checkpoint_task: Any = None  # set by _phase_checkpoint
