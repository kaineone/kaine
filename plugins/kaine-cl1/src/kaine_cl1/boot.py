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
- **Oscillator** and **Nous** land next, through ``oscillator.<module>`` and ``nous.engine``.

Nothing here edits core KAINE. Where a module lacks a seam, the policy is to add a
vendor-neutral one to core (silicon default unchanged); CL1 specifics stay in this
package.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kaine_cl1.backends.chronos import WetwareTimingModel
from kaine_cl1.backends.soma import WetwareInteroceptiveModel
from kaine_cl1.substrate.broker import ChannelTerritory, SubstrateBroker


@dataclass(frozen=True)
class WetwareBackendSpec:
    """How to realise one module on the substrate.

    ``make`` builds the injected object from a broker + leased territory;
    ``inject_kwarg`` is the KAINE constructor keyword that carries it.
    """

    make: Callable[[SubstrateBroker, ChannelTerritory], Any]
    inject_kwarg: str


#: The implemented backends. Oscillator and Nous land next.
WETWARE_BACKENDS: dict[str, WetwareBackendSpec] = {
    "chronos": WetwareBackendSpec(
        make=lambda broker, territory: WetwareTimingModel(broker, territory),
        inject_kwarg="network",
    ),
    "soma": WetwareBackendSpec(
        make=lambda broker, territory: WetwareInteroceptiveModel(broker, territory),
        inject_kwarg="forward_model",
    ),
}


def wetware_injection(
    module: str, broker: SubstrateBroker, territory: ChannelTerritory
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
    return spec.inject_kwarg, spec.make(broker, territory)
