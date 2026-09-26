# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Plugin loader for KAINE module substitutions.

Plugins are discovered via the ``kaine.plugins`` importlib metadata entry-point
group, but only entry points whose names appear in ``[plugins].enabled`` are
loaded. The loader validates declared seams, detects conflicts, and supplies
constructor injections to module factories.
"""
from __future__ import annotations

import importlib.metadata
import logging
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

__all__ = [
    "PluginError",
    "INJECTABLE_SEAMS",
    "KainePlugin",
    "LoadedPlugins",
    "load_plugins",
]

logger = logging.getLogger("kaine.plugins")


class PluginError(ValueError):
    """Failure while loading, validating or invoking a named plugin."""


INJECTABLE_SEAMS: dict[str, frozenset[str]] = {
    "chronos": frozenset({"network"}),
    "soma": frozenset({"forward_model"}),
    "nous": frozenset({"engine"}),
}

# Log a warning on the 1st and every Nth cycle-tick failure or slow call.
_CYCLE_WARN_EVERY = 100
# Fraction of the tick period that counts as a slow cycle-tick hook.
_CYCLE_BUDGET_FRACTION = 0.1


class KainePlugin(Protocol):
    """Interface for objects returned by plugin factories.

    The entry point must resolve to a zero-argument callable that returns an
    object matching this protocol. ``make_oscillator`` is optional; the loader
    checks for it with ``hasattr`` rather than requiring it at runtime.

    Plugins MAY also implement ``on_cycle_tick(tick)``. It is called once per
    cycle tick with a read-only copy of the ``cycle.tick`` payload and must
    return quickly.
    """

    def seams(self, config: dict) -> frozenset[str]:
        """Return the dotted seams this plugin will fill."""

    def injections(self, module: str, config: dict) -> dict[str, Any]:
        """Return constructor objects for the requested module's seams."""

    def make_oscillator(
        self, module: str, config: dict, defaults: dict
    ) -> Any | None:
        """Optionally return a replacement oscillator for ``module``.

        This method is not required for the protocol's runtime check; the
        loader calls it only when the plugin declares ``oscillator.<module>``.
        """


class LoadedPlugins:
    """Container for enabled plugins after load-time validation."""

    def __init__(self, plugins: dict[str, dict[str, Any]]) -> None:
        self._plugins = plugins
        self._cycle_failures: dict[str, int] = {}
        self._cycle_slow: dict[str, int] = {}

    def __bool__(self) -> bool:
        return bool(self._plugins)

    def cycle_observer(self) -> Callable[[Mapping[str, Any], float], None] | None:
        if any(
            callable(getattr(info["plugin"], "on_cycle_tick", None))
            for info in self._plugins.values()
        ):
            return self.dispatch_cycle_tick
        return None

    def dispatch_cycle_tick(self, payload: Mapping[str, Any], target_ms: float) -> None:
        for name, info in self._plugins.items():
            tick_hook = getattr(info["plugin"], "on_cycle_tick", None)
            if not callable(tick_hook):
                continue
            tick_copy = dict(payload)
            start = time.perf_counter()
            try:
                tick_hook(tick_copy)
            except Exception as exc:
                count = self._cycle_failures[name] = self._cycle_failures.get(name, 0) + 1
                if count == 1 or count % _CYCLE_WARN_EVERY == 0:
                    logger.warning(
                        "plugin %s on_cycle_tick raised %s (%d failure(s) so far): %s",
                        name,
                        type(exc).__name__,
                        count,
                        exc,
                    )
                continue
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if target_ms > 0:
                budget = _CYCLE_BUDGET_FRACTION * target_ms
                if elapsed_ms > budget:
                    count = self._cycle_slow[name] = self._cycle_slow.get(name, 0) + 1
                    if count == 1 or count % _CYCLE_WARN_EVERY == 0:
                        logger.warning(
                            "plugin %s on_cycle_tick took %.1f ms, over %.1f ms "
                            "(10%% of the tick period); %d slow call(s) so far",
                            name,
                            elapsed_ms,
                            budget,
                            count,
                        )

    def declares_oscillator(self, module: str) -> bool:
        target = f"oscillator.{module}"
        return any(target in info["seams"] for info in self._plugins.values())

    def injections_for(self, module: str) -> dict[str, Any]:
        """Return merged constructor injections for ``module``."""
        result: dict[str, Any] = {}
        prefix = f"{module}."
        for name, info in self._plugins.items():
            plugin = info["plugin"]
            cfg = info["config"]
            seams = info["seams"]
            declared_keys = {
                seam[len(prefix) :]
                for seam in seams
                if seam.startswith(prefix) and "." not in seam[len(prefix) :]
            }
            if not declared_keys:
                continue
            try:
                provided = plugin.injections(module, cfg)
            except Exception as exc:
                raise PluginError(
                    f"plugin {name} raised {type(exc).__name__} while "
                    f"providing injections for {module}: {exc}"
                ) from exc
            if not isinstance(provided, dict):
                raise PluginError(
                    f"plugin {name} injections({module}) must return a dict, "
                    f"got {type(provided).__name__}"
                )
            for key in provided:
                if key not in declared_keys:
                    raise PluginError(
                        f"plugin {name} returned undeclared injection "
                        f"{module}.{key}"
                    )
            for key, value in provided.items():
                # A declared seam filled with None would make the module build
                # its default model while the log and manifest say otherwise.
                if value is None:
                    raise PluginError(
                        f"plugin {name} returned None for declared injection "
                        f"{module}.{key}"
                    )
            for key in declared_keys:
                if key not in provided:
                    raise PluginError(
                        f"plugin {name} missing declared injection "
                        f"{module}.{key}"
                    )
            for key, value in provided.items():
                result[key] = value
                logger.warning("plugin %s fills %s.%s", name, module, key)
        return result

    def oscillator_for(self, module: str, defaults: dict) -> Any | None:
        """Return a plugin oscillator for ``module`` if one was declared."""
        target = f"oscillator.{module}"
        for name, info in self._plugins.items():
            if target not in info["seams"]:
                continue
            plugin = info["plugin"]
            cfg = info["config"]
            maker = getattr(plugin, "make_oscillator", None)
            if maker is None:
                raise PluginError(
                    f"plugin {name} declares {target} but has no "
                    f"make_oscillator method"
                )
            try:
                osc = maker(module, cfg, defaults)
            except Exception as exc:
                raise PluginError(
                    f"plugin {name} raised {type(exc).__name__} while making "
                    f"oscillator for {module}: {exc}"
                ) from exc
            if osc is None:
                raise PluginError(
                    f"plugin {name} make_oscillator({module}) returned None"
                )
            logger.warning("plugin %s fills %s", name, target)
            return osc
        return None

    def manifest_entry(self) -> dict[str, dict]:
        """Manifest-ready summary: name -> distribution/version/seams."""
        return {
            name: {
                "distribution": info["distribution"],
                "version": info["version"],
                "seams": sorted(info["seams"]),
                "observes_cycle": callable(
                    getattr(info["plugin"], "on_cycle_tick", None)
                ),
            }
            for name, info in self._plugins.items()
        }


def load_plugins(
    kaine_config: Mapping[str, Any],
    *,
    known_modules: Iterable[str],
    entry_points: Callable[..., Any] | None = None,
) -> LoadedPlugins:
    """Load and validate plugins named in ``[plugins].enabled``.

    ``entry_points`` defaults to ``importlib.metadata.entry_points`` and is
    exposed only so tests can supply fake entry points. It is called as
    ``entry_points(group="kaine.plugins")``.
    """
    plugins_cfg = kaine_config.get("plugins")
    enabled: list[Any] = []
    if isinstance(plugins_cfg, dict):
        enabled_raw = plugins_cfg.get("enabled")
        if enabled_raw is not None:
            enabled = list(enabled_raw)

    if not enabled:
        return LoadedPlugins({})

    known_modules_set = frozenset(known_modules)
    oscillator_cfg = kaine_config.get("oscillator") or {}
    oscillator_enabled = (
        bool(oscillator_cfg.get("enabled"))
        if isinstance(oscillator_cfg, dict)
        else False
    )

    if entry_points is None:
        all_eps = importlib.metadata.entry_points(group="kaine.plugins")
    else:
        all_eps = entry_points(group="kaine.plugins")

    by_name: dict[str, list[Any]] = {}
    for ep in all_eps:
        by_name.setdefault(ep.name, []).append(ep)

    loaded: dict[str, dict[str, Any]] = {}
    seam_owners: dict[str, str] = {}

    for name in dict.fromkeys(enabled):
        eps = by_name.get(name, [])
        if len(eps) == 0:
            raise PluginError(
                f"plugin {name} is not installed (no kaine.plugins entry "
                f"point named {name})"
            )
        if len(eps) > 1:
            dists = [
                ep.dist.name if ep.dist and ep.dist.name else "unknown"
                for ep in eps
            ]
            raise PluginError(
                f"plugin {name} is exported by multiple distributions: "
                f"{', '.join(dists)}"
            )

        # The plugin reads only its own [plugins.<name>] table. An absent table
        # is empty; any other non-table value is a configuration error.
        plugin_cfg = plugins_cfg.get(name, {}) if isinstance(plugins_cfg, dict) else {}
        if not isinstance(plugin_cfg, dict):
            raise PluginError(
                f"plugin {name} configuration table must be a dict, got "
                f"{type(plugin_cfg).__name__}"
            )

        ep = eps[0]
        try:
            factory = ep.load()
            plugin = factory()
        except Exception as exc:
            raise PluginError(
                f"plugin {name} failed to load: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            seams = plugin.seams(plugin_cfg)
        except Exception as exc:
            raise PluginError(
                f"plugin {name} raised {type(exc).__name__} in seams(): {exc}"
            ) from exc

        if not isinstance(seams, (set, frozenset)):
            raise PluginError(
                f"plugin {name} seams() must return a set/frozenset of "
                f"strings, got {type(seams).__name__}"
            )

        for seam in seams:
            if not isinstance(seam, str):
                raise PluginError(
                    f"plugin {name} seam must be a string, got "
                    f"{type(seam).__name__}"
                )
            if seam in seam_owners:
                other = seam_owners[seam]
                raise PluginError(
                    f"plugins {other} and {name} both declare seam {seam}"
                )

            if seam.startswith("oscillator."):
                module = seam[len("oscillator.") :]
                if module not in known_modules_set:
                    raise PluginError(
                        f"plugin {name} declares unknown seam {seam}"
                    )
                if not oscillator_enabled:
                    raise PluginError(
                        f"plugin {name} declares oscillator seam {seam} "
                        f"but [oscillator].enabled is not true"
                    )
            else:
                if "." not in seam:
                    raise PluginError(
                        f"plugin {name} declares unknown seam {seam}"
                    )
                parts = seam.split(".")
                if len(parts) != 2:
                    raise PluginError(
                        f"plugin {name} declares unknown seam {seam}"
                    )
                module, key = parts
                if (
                    module not in INJECTABLE_SEAMS
                    or key not in INJECTABLE_SEAMS[module]
                ):
                    raise PluginError(
                        f"plugin {name} declares unknown seam {seam}"
                    )

            seam_owners[seam] = name

        dist_name = None
        version = None
        if ep.dist:
            dist_name = ep.dist.name
            version = ep.dist.version

        loaded[name] = {
            "plugin": plugin,
            "config": plugin_cfg,
            "seams": frozenset(seams),
            "distribution": dist_name,
            "version": version,
        }

    return LoadedPlugins(loaded)
