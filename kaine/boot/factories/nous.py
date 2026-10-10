# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Nous factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.common import _check_injections
from kaine.boot.errors import ConfigurationError, _pop
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule

# Worst-case EFE step product (factors * max_states * actions * horizon) above
# which Nous's active-inference planning risks overrunning the cycle budget on
# the target CPU. The default compact envelope (4*4*4*1 = 64) is far below this.
_NOUS_COMPLEXITY_THRESHOLD = 4096


def make_nous(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    injections: Optional[Mapping[str, Any]] = None,
) -> BaseModule:
    from kaine.modules.nous.module import Nous

    injected = _check_injections("nous", injections, {"engine", "engine_wrapper"})

    if "engine" in injected and "engine_wrapper" in injected:
        raise ConfigurationError(
            "nous cannot take both an injected engine and an engine wrapper"
        )

    allowed = {
        # Complexity envelope (validated below).
        "factors",
        "max_states_per_factor",
        "actions",
        "planning_horizon",
        "efe_timeout_ms",
        # Active-inference backend selection.
        "backend",
        # Generative-model transition prior.
        "transition_persistence",
        "transition_concentration",
        "transition_max_concentration",
        # Module knobs.
        "baseline_salience",
        "alert_salience",
        "timeout_salience",
        # Proposal/learning switch.
        "drive_actions",
    }
    cfg = _pop(section, allowed)

    factors = int(cfg.pop("factors", 4))
    max_states = int(cfg.pop("max_states_per_factor", 4))
    actions = int(cfg.pop("actions", 4))
    horizon = int(cfg.pop("planning_horizon", 1))
    efe_timeout_ms = float(cfg.pop("efe_timeout_ms", 250.0))
    transition_persistence = float(cfg.pop("transition_persistence", 0.8))
    transition_concentration = float(cfg.pop("transition_concentration", 1.0))
    transition_max_concentration = float(cfg.pop("transition_max_concentration", 1000.0))

    if factors < 1 or max_states < 1 or actions < 1 or horizon < 1:
        raise ConfigurationError(
            "nous envelope values (factors, max_states_per_factor, actions, "
            "planning_horizon) must all be >= 1"
        )
    product = factors * max_states * actions * horizon
    if product > _NOUS_COMPLEXITY_THRESHOLD:
        raise ConfigurationError(
            f"nous complexity envelope {factors}*{max_states}*{actions}*{horizon}"
            f"={product} exceeds threshold {_NOUS_COMPLEXITY_THRESHOLD}; "
            "EFE planning would risk overrunning the cycle budget"
        )

    # An injected engine replaces the default; the envelope above is still
    # validated, but no PymdpEngine (and no pymdp/JAX import) is built.
    if "engine" in injected:
        return Nous(bus, engine=injected["engine"], **cfg)

    from kaine.modules.nous.engine import ActiveInferenceEngine, PymdpEngine
    from kaine.modules.nous.generative_model import build_generative_model

    # Build the engine eagerly so a misconfigured envelope / missing reasoning
    # extra fails loudly at boot rather than mid-cycle.
    backend = str(cfg.pop("backend", "pymdp"))
    if backend not in {"pymdp", "numpy"}:
        raise ConfigurationError(
            f"nous backend must be 'pymdp' or 'numpy', got {backend!r}"
        )

    model = build_generative_model(
        max_states_per_factor=max_states,
        persistence=transition_persistence,
        concentration=transition_concentration,
        transition_max_concentration=transition_max_concentration,
    )

    if backend == "pymdp":
        from kaine.modules.nous.engine import PymdpEngine
        engine = PymdpEngine(model, efe_timeout_ms=efe_timeout_ms, policy_len=horizon)
    else:
        from kaine.modules.nous.numpy_engine import NumpyActiveInferenceEngine
        engine = NumpyActiveInferenceEngine(
            model, efe_timeout_ms=efe_timeout_ms, policy_len=horizon
        )

    # The wrapper receives the engine KAINE built from [nous], so a plugin can
    # add to it without seeing the settings.
    if "engine_wrapper" in injected:
        wrapped = injected["engine_wrapper"](engine)
        if not isinstance(wrapped, ActiveInferenceEngine):
            who = getattr(injected["engine_wrapper"], "plugin_name", "a plugin")
            raise ConfigurationError(
                f"nous engine_wrapper from plugin {who} returned {type(wrapped).__name__}, "
                "which is not an ActiveInferenceEngine "
                "(needs an actions property and a step method)"
            )
        engine = wrapped

    return Nous(bus, engine=engine, **cfg)
