# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Ensure every durable output root declared in config/kaine.toml is backed by a
named volume in both the compose and quadlet cycle deployments.

The app writes CWD-relative under WORKDIR /app.  We parse the config, collect
the relative durable output roots, and verify that each is covered by a named
volume mount at /app/<root> or a parent directory (never /app itself).  The
test also verifies that every ``*.volume`` unit referenced by the cycle
quadlet units exists under quadlet/.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COMPOSE = _REPO_ROOT / "compose" / "kaine.yml"
_QUADLET = _REPO_ROOT / "quadlet"
_CONFIG = _REPO_ROOT / "config" / "kaine.toml"


def _load_compose() -> dict:
    with _COMPOSE.open() as fh:
        return yaml.safe_load(fh)


def _compose_named_volume_targets(service: str) -> list[tuple[str, str]]:
    """Return (volume_name, container_target) for named volumes on a service."""
    doc = _load_compose()
    raw_volumes = doc["services"][service]["volumes"]
    results: list[tuple[str, str]] = []
    for entry in raw_volumes:
        if not isinstance(entry, str):
            continue
        if "/" in entry.split(":", 1)[0]:
            # bind mounts have a path as the source; skip them
            continue
        name, rest = entry.split(":", 1)
        target = rest.split(":", 1)[0]
        results.append((name, target))
    return results


def _quadlet_named_volume_targets(container_path: Path) -> list[tuple[str, str]]:
    """Return (volume_unit_name, container_target) for Volume=*.volume lines."""
    results: list[tuple[str, str]] = []
    for line in container_path.read_text().splitlines():
        if not line.startswith("Volume="):
            continue
        payload = line.split("=", 1)[1]
        if ".volume:" not in payload:
            continue
        unit, rest = payload.split(":", 1)
        target = rest.split(":", 1)[0]
        results.append((unit, target))
    return results


def _covers(root: str, target: str) -> bool:
    full = f"/app/{root}"
    return target != "/app" and (full == target or full.startswith(target + "/"))


def test_durable_output_roots_are_named_volumes():
    with _CONFIG.open("rb") as fh:
        cfg = tomllib.load(fh)

    roots = [
        cfg["preservation"]["divergence_monitor"]["out_root"],
        cfg["preservation"]["welfare_response"]["out_root"],
        cfg["ignition_log"]["directory"],
        cfg["evaluation"]["paths"]["trajectory_dir"],
        cfg["research_event_log"]["log_dir"],
    ]

    compose_targets = _compose_named_volume_targets("kaine-cycle")
    doc = _load_compose()
    declared_volumes = set(doc["volumes"].keys())

    quadlet_cycle = _quadlet_named_volume_targets(_QUADLET / "kaine-cycle.container")
    quadlet_unattended = _quadlet_named_volume_targets(
        _QUADLET / "kaine-cycle-unattended.container"
    )

    for root in roots:
        compose_matches = [
            (name, target)
            for name, target in compose_targets
            if _covers(root, target)
        ]
        assert compose_matches, (
            f"compose kaine-cycle has no named volume covering /app/{root}"
        )
        for name, _ in compose_matches:
            assert name in declared_volumes, (
                f"compose named volume {name} is not declared in top-level volumes"
            )

        for label, targets in (
            ("kaine-cycle.container", quadlet_cycle),
            ("kaine-cycle-unattended.container", quadlet_unattended),
        ):
            quadlet_matches = [
                (name, target)
                for name, target in targets
                if _covers(root, target)
            ]
            assert quadlet_matches, (
                f"{label} has no Volume=*.volume mount covering /app/{root}"
            )


def test_quadlet_cycle_referenced_volume_units_exist():
    """Every Volume=... line referencing a .volume unit in the cycle units has
    a matching quadlet volume file."""
    referenced: set[str] = set()
    for container in (
        _QUADLET / "kaine-cycle.container",
        _QUADLET / "kaine-cycle-unattended.container",
    ):
        for line in container.read_text().splitlines():
            if not line.startswith("Volume="):
                continue
            name = line.split("=", 1)[1].split(":", 1)[0]
            if name.endswith(".volume"):
                referenced.add(name)
    for name in referenced:
        assert (_QUADLET / name).exists(), f"missing quadlet volume unit: {name}"
