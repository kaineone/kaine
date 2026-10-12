# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for episodic memory store-health block, prober, template, and recovery CLI."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from kaine.lifecycle.episodic_memory_recover import main
from kaine.modules.episodic_memory import FakeEmbedder, InMemoryStorage
from kaine.nexus import diagnostics
from kaine.nexus.health import blocks
from kaine.nexus.health.prober import HealthProber


def test_episodic_memory_store_block_states(tmp_path):
    """mnemos_store_block maps the health file to the right state and counts."""
    health_path = tmp_path / "health.json"

    disabled = blocks.episodic_memory_store_block(health_path, False)
    assert disabled["state"] == "disabled"

    missing = blocks.episodic_memory_store_block(health_path, True)
    assert missing["state"] == "unknown"

    health_path.write_text(json.dumps([]), encoding="utf-8")
    as_list = blocks.episodic_memory_store_block(health_path, True)
    assert as_list["state"] == "unknown"

    health_path.write_text(
        json.dumps(
            {
                "import_pending": True,
                "blocked_sleeps": 5,
                "persist_refusals": 0,
                "store_bytes": 100,
                "budget_bytes": 200,
                "updated_at": "2026-01-02T03:04:05Z",
                "message": "ignored",
            }
        ),
        encoding="utf-8",
    )
    critical = blocks.episodic_memory_store_block(health_path, True)
    assert critical["state"] == "critical"
    assert "python -m kaine.lifecycle.episodic_memory_recover" in critical["message"]
    assert critical["import_pending"] is True
    assert critical["blocked_sleeps"] == 5
    assert critical["store_bytes"] == 100
    assert critical["budget_bytes"] == 200
    assert critical["since"] == "2026-01-02T03:04:05Z"

    health_path.write_text(
        json.dumps(
            {
                "import_pending": False,
                "blocked_sleeps": 0,
                "persist_refusals": 3,
                "store_bytes": 100,
                "budget_bytes": 200,
                "updated_at": "2026-01-02T03:04:06Z",
                "message": "some traces were refused",
            }
        ),
        encoding="utf-8",
    )
    warning = blocks.episodic_memory_store_block(health_path, True)
    assert warning["state"] == "warning"
    assert warning["persist_refusals"] == 3
    assert warning["message"] == "some traces were refused"

    health_path.write_text(
        json.dumps(
            {
                "import_pending": False,
                "blocked_sleeps": 0,
                "persist_refusals": 0,
                "store_bytes": 100,
                "budget_bytes": 200,
                "updated_at": "2026-01-02T03:04:07Z",
            }
        ),
        encoding="utf-8",
    )
    ok = blocks.episodic_memory_store_block(health_path, True)
    assert ok["state"] == "ok"
    assert ok["import_pending"] is False
    assert ok["blocked_sleeps"] == 0
    assert ok["persist_refusals"] == 0
    assert ok["since"] == "2026-01-02T03:04:07Z"


async def test_health_prober_episodic_memory_store(tmp_path):
    """The health prober includes the episodic memory module's store block under its canonical key."""
    assert "mnemos_store" in diagnostics.HEALTH_BLOCK_KEYS

    health_path = tmp_path / "store_health.json"
    health_path.write_text(
        json.dumps(
            {
                "import_pending": True,
                "blocked_sleeps": 2,
                "persist_refusals": 0,
                "store_bytes": 50,
                "budget_bytes": 100,
                "updated_at": "2026-01-02T03:04:05Z",
            }
        ),
        encoding="utf-8",
    )

    prober = HealthProber(
        modules_enabled={"mnemos": True},
        dependencies=[],
        episodic_memory_store_health_path=health_path,
    )
    snapshot = await prober.snapshot(force=True)
    assert "mnemos_store" in snapshot
    assert snapshot["mnemos_store"]["state"] == "critical"
    assert snapshot["mnemos_store"]["import_pending"] is True
    assert snapshot["mnemos_store"]["blocked_sleeps"] == 2


def test_episodic_memory_store_template_critical(tmp_path):
    """The episodic memory module's store template renders a critical block with a down chip."""
    env = Environment(loader=FileSystemLoader("kaine/nexus/templates"), autoescape=select_autoescape(["html"]))
    template = env.get_template("_episodic_memory_store.html")
    html = template.render(
        **{"mnemos_store": {
            "state": "critical",
            "import_pending": True,
            "blocked_sleeps": 1,
            "persist_refusals": 0,
            "store_bytes": 100,
            "budget_bytes": 200,
            "message": "an interrupted import is blocking sleep",
            "since": "2026-01-02T03:04:05Z",
        }}
    )
    assert "Memory store" in html
    assert "chip down" in html


def test_episodic_memory_store_template_unavailable(tmp_path):
    """The episodic memory module's store template shows unavailable when the block is missing."""
    env = Environment(loader=FileSystemLoader("kaine/nexus/templates"), autoescape=select_autoescape(["html"]))
    template = env.get_template("_episodic_memory_store.html")
    html = template.render(**{"mnemos_store": None})
    assert "unavailable" in html.lower()


def test_recover_cli_requires_confirmation():
    """Without confirmation the CLI refuses to run and explains why."""
    err = io.StringIO()
    out = io.StringIO()
    code = main([], out=out, err=err)
    assert code == 2
    text = err.getvalue()
    assert "no --confirm-keep-current-store" in text
    assert "confirm" in text.lower()


def test_recover_cli_refuses_while_cycle_running(monkeypatch):
    """With confirmation the CLI still refuses if a cycle appears to be running."""
    import kaine.config as config_mod
    import kaine.lifecycle.liveness as liveness_mod
    import kaine.storage as storage_util

    monkeypatch.setattr(
        config_mod,
        "load_runtime_config",
        lambda path, op_path: {},
    )
    monkeypatch.setattr(storage_util, "install_data_root", lambda cfg: None)
    monkeypatch.setattr(liveness_mod, "cycle_process_state", lambda: True)

    err = io.StringIO()
    out = io.StringIO()
    code = main(["--confirm-keep-current-store"], out=out, err=err)
    assert code == 3
    assert "cycle appears to be running" in err.getvalue()


def test_recover_cli_clears_pending_and_is_idempotent(monkeypatch, tmp_path):
    """A confirmed recovery clears the pending flag; a second run finds nothing to do."""
    import kaine.config as config_mod
    import kaine.lifecycle.liveness as liveness_mod
    import kaine.modules.episodic_memory.storage as storage_mod
    import kaine.storage as storage_util

    monkeypatch.setattr(
        config_mod,
        "load_runtime_config",
        lambda path, op_path: {
            "mnemos": {"backend": "sqlite_vec", "collection_prefix": "mnemos_"}
        },
    )
    monkeypatch.setattr(storage_util, "install_data_root", lambda cfg: None)
    monkeypatch.setattr(liveness_mod, "cycle_process_state", lambda: False)
    monkeypatch.setattr(
        storage_util,
        "resolve",
        lambda p: tmp_path / Path(p).name,
    )

    class PendingStorage(InMemoryStorage):
        async def initialize(self):
            await super().initialize()
            if not getattr(self, "_pending_seeded", False):
                await self.write_stamp(
                    "mnemos_embedding_space", FakeEmbedder(latent_dim=8).space
                )
                await self.write_meta(
                    "mnemos_strength",
                    {
                        "log_gain": 0.0,
                        "sleeps": 0,
                        "total": 0.0,
                        "entity_time": 0.0,
                        "bytes": 0,
                        "import_pending": True,
                    },
                )
                self._pending_seeded = True

    shared: Any = None

    def factory(**kwargs):
        nonlocal shared
        if shared is None:
            shared = PendingStorage(latent_dim=8)
        return shared

    monkeypatch.setattr(storage_mod, "SqliteVecStorage", factory)

    out1 = io.StringIO()
    err1 = io.StringIO()
    code1 = main(["--confirm-keep-current-store"], out=out1, err=err1)
    assert code1 == 0
    assert "recovered store" in out1.getvalue()

    meta = asyncio.run(shared.read_meta("mnemos_strength"))
    assert meta.get("import_pending") in (None, False)

    out2 = io.StringIO()
    err2 = io.StringIO()
    code2 = main(["--confirm-keep-current-store"], out=out2, err=err2)
    assert code2 == 1
    assert "no interrupted import is recorded" in out2.getvalue()
