# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Downstream boot: wire CL1 backends into KAINE **without editing KAINE**.

A converted module is stock KAINE constructed with a CL1-backed object injected
through the seam KAINE already exposes. Different modules inject through different
seams, so each backend declares *what* to inject and *which* constructor keyword
carries it:

- **Chronos** injects a forward model through ``network=`` (Chronos builds its
  silicon ``CfCNetwork`` only when ``network is None``).
- **Soma** injects its interoceptive forward model through ``forward_model=``
  (kaine's ``soma.forward_model`` seam).
- **Nous** injects an engine wrapper through ``engine_wrapper=`` (kaine's
  ``nous.engine_wrapper`` seam): kaine's own engine keeps beliefs and expected
  free energy, and the wrapper adds the substrate's policy proposal.
- **Oscillator** runs through the plugin's ``make_oscillator`` hook on
  ``oscillator.<module>`` seams, not through this table.

Nothing here edits core KAINE. Where a module lacks a seam, the policy is to add a
vendor-neutral one to core (silicon default unchanged); CL1 specifics stay in this
package.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kaine_cl1.backends.chronos import WetwareTimingModel
from kaine_cl1.backends.nous import WetwarePolicyEngine
from kaine_cl1.backends.soma import WetwareInteroceptiveModel
from kaine_cl1.substrate.broker import ChannelTerritory, SubstrateBroker


@dataclass(frozen=True)
class WetwareBackendSpec:
    """How to realise one module on the substrate.

    ``make`` builds the injected object from a broker + leased territory, plus
    any per-module keyword options from the overlay (see ``OverlayConfig.backend_options``).
    ``inject_kwarg`` is the KAINE constructor keyword that carries it.
    """

    make: Callable[..., Any]
    inject_kwarg: str


def _nous_wrapper(
    broker: SubstrateBroker, territory: ChannelTerritory, *, mode: str = "shadow", seed: int = 0
) -> Callable[[Any], WetwarePolicyEngine]:
    """Return kaine's ``engine_wrapper``: wrap the engine kaine built in a policy proposer on
    this territory."""

    def wrap(inner: Any) -> WetwarePolicyEngine:
        return WetwarePolicyEngine(inner, broker, territory, mode=mode, seed=seed)

    return wrap


#: The implemented module backends (oscillators use the plugin's make_oscillator hook).
WETWARE_BACKENDS: dict[str, WetwareBackendSpec] = {
    "chronos": WetwareBackendSpec(
        make=WetwareTimingModel,
        inject_kwarg="network",
    ),
    "soma": WetwareBackendSpec(
        make=WetwareInteroceptiveModel,
        inject_kwarg="forward_model",
    ),
    "nous": WetwareBackendSpec(
        make=_nous_wrapper,
        inject_kwarg="engine_wrapper",
    ),
}


def wetware_injection(
    module: str, broker: SubstrateBroker, territory: ChannelTerritory, **options: Any
) -> tuple[str, Any]:
    """Return ``(constructor_kwarg, injected_object)`` for a converted module.

    Example:
        kwarg, obj = wetware_injection("chronos", broker, territory)
        chronos = Chronos(bus, **{kwarg: obj}, featurizer=..., anomaly=..., ...)
    """
    try:
        spec = WETWARE_BACKENDS[module]
    except KeyError:
        raise KeyError(
            f"no wetware backend registered for {module!r} "
            f"(available: {sorted(WETWARE_BACKENDS)})"
        ) from None
    return spec.inject_kwarg, spec.make(broker, territory, **options)
