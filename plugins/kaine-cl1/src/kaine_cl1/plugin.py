# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""kaine plugin entry point for the CL1 substrate.

Routes the forward models of modules configured to ``"cl1"`` onto one process-wide
CL1 substrate through the seams declared by kaine. The plugin never edits kaine.
"""

from __future__ import annotations

import atexit
import importlib.metadata
import logging
import math
from collections.abc import Callable, Mapping
from typing import Any

from kaine_cl1.backends.oscillator import WetwareOscillator
from kaine_cl1.boot import WETWARE_BACKENDS
from kaine_cl1.config import OverlayConfig, overlay_from_mapping
from kaine_cl1.substrate.broker import SubstrateBroker, nesting_factor_for
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession

log = logging.getLogger(__name__)


#: Modules awaiting a wetware seam conversion.
PENDING_CONVERSIONS: dict[str, str] = {
    "oscillator": "oscillator-on-wetware",
    "nous": "nous-on-wetware",
    "audition_frontend": "hybrid-wetware-conversions",
    "phantasia_surprise": "hybrid-wetware-conversions",
    "volition": "hybrid-wetware-conversions",
    "thymos": "hybrid-wetware-conversions",
}

#: 64 electrodes, channel 0 reserved.
_USABLE_CHANNELS = 63

REQUIREMENTS_MESSAGE = (
    "The cl1 plugin needs Cortical Labs' cl-sdk, which KAINE does not ship. "
    "Install it yourself with `pip install cl-sdk`. cl-sdk is licensed CC BY-NC 4.0 "
    "(non-commercial use only). Its simulator is non-learning: Cortical Labs describes "
    "its data as control data that does not respond to stimulation and must not be "
    "relied upon for experiments. Real neurons need a paid Cortical Cloud account or a "
    "CL1 device, which this plugin does not support yet. See docs/cl1.md."
)

CLOUD_MESSAGE = (
    "[substrate].target = \"cloud\" is not supported yet: Cortical Cloud runs code on the "
    "CL1 itself and publishes no API for an outside program such as KAINE to drive a "
    "remote CL1. See docs/cl1.md."
)

REQUIRED_ACKNOWLEDGEMENT = (
    "I have read plugins/kaine-cl1/docs/biological-welfare.md and hold institutional "
    "approval for work with this culture"
)


def _hardware_gate_problems(overlay: OverlayConfig) -> list[str]:
    problems: list[str] = []
    if overlay.hardware_acknowledgement != REQUIRED_ACKNOWLEDGEMENT:
        problems.append(
            "[hardware].welfare_acknowledgement must be exactly: " + REQUIRED_ACKNOWLEDGEMENT
        )
    if not overlay.ethics_reference:
        problems.append(
            "[hardware].ethics_reference must name your institutional approval or protocol"
        )
    if overlay.substrate.accelerated_time:
        problems.append(
            "[substrate].accelerated_time must be false on hardware "
            "(accelerated time is simulator-only)"
        )
    if overlay.substrate.data_source is not None:
        problems.append(
            "[substrate].data_source must not be set on hardware (simulated data sources do not "
            "apply)"
        )
    return problems


def _cl_sdk_installed() -> bool:
    """Whether Cortical Labs' cl-sdk distribution is installed (checked by
    package metadata, without importing the SDK)."""
    try:
        importlib.metadata.version("cl-sdk")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


class Cl1Plugin:
    """kaine's plugin object; it owns the one process-wide substrate session and broker
    and hands each converted module a model on its own channel territory, reusing that
    territory when the module is rebuilt.
    """

    name = "cl1"

    def __init__(
        self,
        *,
        session_factory: Callable[[SubstrateConfig], Any] = SubstrateSession,
    ) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None
        self._broker: SubstrateBroker | None = None
        self._close_registered = False
        self._accelerated = True
        self._warned_realtime = False

    def _validated(self, config: Mapping[str, Any]) -> OverlayConfig:
        overlay = overlay_from_mapping(config)

        if not _cl_sdk_installed():
            raise ValueError(REQUIREMENTS_MESSAGE)
        if overlay.substrate.target == "cloud":
            raise ValueError(CLOUD_MESSAGE)
        if overlay.substrate.target == "hardware":
            problems = _hardware_gate_problems(overlay)
            if problems:
                raise ValueError(
                    "the CL1 plugin refuses the hardware target until these are met "
                    "(see docs/cl1.md, Running on a CL1): " + "; ".join(problems)
                )

        converted = overlay.cl1_modules()

        for module in converted:
            if module not in WETWARE_BACKENDS:
                change = PENDING_CONVERSIONS.get(module, "no conversion is planned")
                raise ValueError(
                    f"module {module!r} has no wetware backend yet; pending change: {change}"
                )

            try:
                overlay.territory_for(module)
            except KeyError as exc:
                raise ValueError(exc.args[0] if exc.args else str(exc)) from None

        total = (
            sum(overlay.territory_for(m) for m in converted)
            + overlay.oscillator_channels * len(overlay.oscillator_modules)
        )
        if total > _USABLE_CHANNELS:
            raise ValueError(
                f"the CL1 plugin needs {total} channels but only {_USABLE_CHANNELS} are usable "
                f"(64 electrodes, channel 0 reserved); reduce territories or oscillator channels"
            )

        if (
            (converted or overlay.oscillator_modules)
            and overlay.substrate.accelerated_time is not True
        ):
            if not self._warned_realtime:
                log.warning(
                    "CL1 substrate runs in real time: it needs KAINE's cycle hook "
                    "(on_cycle_tick) for non-blocking one-window-per-tick timing; until the "
                    "first tick each step blocks for one window"
                )
                self._warned_realtime = True

        if converted or overlay.oscillator_modules:
            nesting_factor_for(overlay.substrate.ticks_per_second, overlay.cognitive_rate)

        return overlay

    def seams(self, config: Mapping[str, Any]) -> frozenset[str]:
        overlay = self._validated(config)
        converted = overlay.cl1_modules()
        oscillators = overlay.oscillator_modules
        if converted or oscillators:
            if overlay.substrate.target == "hardware":
                log.warning(
                    "A LIVING NEURAL CULTURE is in the loop (CL1 hardware target; ethics "
                    "reference: %s). Stimulation reaches real cells; KAINE freezes stop all "
                    "stimulation.",
                    overlay.ethics_reference,
                )
            elif overlay.substrate.target == "simulator":
                log.warning(
                    "CL1 substrate is SIMULATED (Cortical Labs cl-sdk simulator, "
                    "data_source=%s); results are not biological. Converted modules: %s; "
                    "oscillators: %s",
                    overlay.substrate.data_source,
                    ", ".join(converted) if converted else "none",
                    ", ".join(oscillators) if oscillators else "none",
                )
        module_seams = frozenset(
            f"{module}.{WETWARE_BACKENDS[module].inject_kwarg}"
            for module in converted
        )
        oscillator_seams = frozenset(f"oscillator.{m}" for m in oscillators)
        return module_seams | oscillator_seams

    def injections(self, module: str, config: Mapping[str, Any]) -> dict[str, Any]:
        overlay = self._validated(config)

        if module not in overlay.cl1_modules():
            return {}

        broker = self._ensure_broker(overlay)

        if broker.has_territory(module):
            territory = broker.territory(module)
            broker.discard_pending(module)
        else:
            territory = broker.allocate(module, overlay.territory_for(module))

        spec = WETWARE_BACKENDS[module]
        return {spec.inject_kwarg: spec.make(broker, territory)}

    def make_oscillator(
        self, module: str, config: Mapping[str, Any], defaults: Mapping[str, Any]
    ) -> Any:
        """KAINE's oscillator hook; returns a WetwareOscillator on this module's own
        territory ``oscillator.<module>``; called once per declared seam at boot."""
        overlay = self._validated(config)

        if module not in overlay.oscillator_modules:
            raise ValueError(f"module {module!r} is not listed in [oscillators].modules")

        broker = self._ensure_broker(overlay)

        name = f"oscillator.{module}"
        if broker.has_territory(name):
            territory = broker.territory(name)
            broker.discard_pending(name)
        else:
            territory = broker.allocate(name, overlay.oscillator_channels)

        return WetwareOscillator(
            broker, territory, plv_window=max(10, int(defaults.get("plv_window", 10)))
        )

    def _ensure_broker(self, overlay: OverlayConfig) -> SubstrateBroker:
        if self._broker is not None:
            return self._broker

        session = self._session_factory(overlay.substrate)
        neurons = session.open()

        broker = SubstrateBroker(
            channel_count=64,
            ticks_per_second=overlay.substrate.ticks_per_second,
            nesting_factor=nesting_factor_for(
                overlay.substrate.ticks_per_second, overlay.cognitive_rate
            ),
        )

        try:
            broker.open(neurons)
        except Exception:
            session.close()
            raise

        if overlay.substrate.target == "hardware":
            # On living tissue, stimulation happens only on KAINE's cycle ticks, so a
            # frozen cycle delivers none; never fall back to per-step windows.
            try:
                broker.start_beat(accelerated=False)
            except Exception:
                session.close()
                raise

        self._session = session
        self._broker = broker
        self._accelerated = bool(overlay.substrate.accelerated_time)

        if not self._close_registered:
            atexit.register(self.close)
            self._close_registered = True

        return self._broker

    def close(self) -> None:
        """Close the substrate session and release the broker."""
        if self._broker is not None:
            self._broker.stop_beat()
        if self._session is not None:
            self._session.close()
        self._session = None
        self._broker = None

    def on_cycle_tick(self, tick: Mapping[str, Any]) -> None:
        """KAINE's cycle hook: close one substrate window per processing tick.

        The first call switches the broker to beat mode; every call only signals the
        background substrate thread, so the cycle never waits on the substrate."""
        if self._broker is None:
            return
        if not self._broker.beat_mode:
            self._broker.start_beat(accelerated=self._accelerated)
        rate = float(tick.get("processing_rate_hz") or 0.0)
        if not math.isfinite(rate) or rate <= 0.0:
            rate = 10.0
        self._broker.beat(1.0 / rate)

    def territory_map(self) -> dict[str, tuple[int, ...]]:
        if self._broker is None:
            return {}
        return self._broker.territory_map()


def make_plugin() -> Cl1Plugin:
    """The ``kaine.plugins`` entry point."""
    return Cl1Plugin()
