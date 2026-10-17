# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_COMPOSE = _REPO_ROOT / "compose" / "kaine.yml"
_QUADLET_DASHBOARD = _REPO_ROOT / "quadlet" / "kaine-dashboard.container"


def test_image_state_tree_is_empty() -> None:
    """The image must create /app/state but nothing beneath it."""
    dockerfile_text = _DOCKERFILE.read_text()
    non_comment_lines = [
        line for line in dockerfile_text.splitlines()
        if not line.lstrip().startswith("#")
    ]

    for line in non_comment_lines:
        assert "/app/state/" not in line, (
            f"Dockerfile line creates content under /app/state: {line!r}"
        )

    assert any(
        "mkdir -p /app/state " in line for line in non_comment_lines
    ), "Expected top-level /app/state directory creation"


def test_dockerfile_volume_paths_all_mounted_on_dashboard_compose() -> None:
    """Every path declared in Dockerfile VOLUME must be mounted by the dashboard service."""
    dockerfile_text = _DOCKERFILE.read_text()
    match = re.search(r"^VOLUME\s+(\[.*\])\s*$", dockerfile_text, re.MULTILINE)
    assert match is not None, "VOLUME JSON array not found in Dockerfile"

    volume_paths = json.loads(match.group(1))

    compose = yaml.safe_load(_COMPOSE.read_text())
    dashboard_volumes = compose["services"]["kaine-dashboard"]["volumes"]
    container_paths = {entry.split(":")[1] for entry in dashboard_volumes}

    for path in volume_paths:
        assert path in container_paths, (
            f"Dockerfile VOLUME path {path!r} is not mounted in dashboard service"
        )


def test_dashboard_models_mount_is_read_only_in_compose() -> None:
    """The models volume must be mounted read-only on the dashboard service."""
    compose = yaml.safe_load(_COMPOSE.read_text())
    dashboard_volumes = compose["services"]["kaine-dashboard"]["volumes"]
    assert "kaine-models:/models:ro" in dashboard_volumes


def test_quadlet_dashboard_mounts_models_and_state() -> None:
    """The quadlet unit must mount both models and state volumes."""
    text = _QUADLET_DASHBOARD.read_text()
    assert "Volume=kaine-models.volume:/models:ro" in text
    assert "Volume=kaine-state.volume:/app/state" in text
