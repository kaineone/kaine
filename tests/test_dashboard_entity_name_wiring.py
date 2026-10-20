# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The dashboard entrypoint wires the entity name and sleep state to the console.

Runs ``_build()`` with fakes for the bus and the config loaders, so no Redis,
network or real config file is needed.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import Event


class _FakeBusClient:
    async def exists(self, key):
        return False

    async def xadd(self, stream, fields, *, maxlen=None, approximate=None):
        return b"0-0"

    async def close(self):
        pass


class _FakeBus:
    def __init__(self, recent_entries):
        self.recent_entries = recent_entries
        self.client = _FakeBusClient()

    async def read_entries(self, stream, *, last_id, count, block_ms):
        return [], None

    async def read(self, stream, last_id="0", count=None, block_ms=0):
        return []

    async def last_entry_id(self, stream):
        return "0-0"

    async def current_workspace_id(self):
        return "0"

    async def recent(self, stream, count=100):
        return self.recent_entries(stream, count)


def _broken_health_prober():
    raise RuntimeError("health prober disabled")


def _patch_dashboard_main(monkeypatch, tmp_path, recent_entries):
    import kaine.dashboard.__main__ as dashboard_main
    from kaine.bus.config import BusConfig
    from kaine.dashboard.config import DashboardConfig

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        dashboard_main,
        "load_kaine_config",
        lambda: {"self_model": {"persistence_path": str(tmp_path / "self_model.json")}},
    )
    monkeypatch.setattr(dashboard_main, "install_data_root", lambda _cfg: None)
    monkeypatch.setattr(
        dashboard_main,
        "load_bus_config",
        lambda: BusConfig(password="x", audit_required=False),
    )
    monkeypatch.setattr(
        dashboard_main, "AsyncBus", lambda _cfg: _FakeBus(recent_entries)
    )
    monkeypatch.setattr(
        dashboard_main,
        "load_dashboard_config",
        lambda: DashboardConfig(
            conversation_enabled=True,
            diagnostics_enabled=False,
            host_allowlist=("127.0.0.1", "localhost", "test"),
            operator_token="test-token",
        ),
    )
    monkeypatch.setattr(
        dashboard_main, "_build_fork_manager", lambda _a, _b: (None, "test")
    )
    monkeypatch.setattr(dashboard_main, "load_health_prober", _broken_health_prober)
    monkeypatch.setattr(dashboard_main, "resolve", lambda p: Path(p))

    return dashboard_main


@pytest.mark.asyncio
async def test_dashboard_shows_entity_name_from_self_model_and_sleep_status(
    monkeypatch, tmp_path
):
    httpx = pytest.importorskip("httpx")

    def _recent(stream, count):
        if stream == "sleep.out":
            return [
                (
                    "2-0",
                    Event(
                        source="sleep",
                        type="sleep.sleep.started",
                        payload={},
                        salience=0.1,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            ]
        return []

    (tmp_path / "self_model.json").write_text('{"name": "Kaine Voxel"}')
    dashboard_main = _patch_dashboard_main(monkeypatch, tmp_path, _recent)

    app, _cfg = await dashboard_main._build()

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/", headers={"Authorization": "Bearer test-token"}
            )

    assert response.status_code == 200
    text = response.text
    assert "Kaine Voxel" in text
    assert 'data-sleeping="true"' in text


@pytest.mark.asyncio
async def test_dashboard_default_entity_name_and_not_sleeping_without_self_model(
    monkeypatch, tmp_path
):
    httpx = pytest.importorskip("httpx")

    def _recent(stream, count):
        return []

    dashboard_main = _patch_dashboard_main(monkeypatch, tmp_path, _recent)

    app, _cfg = await dashboard_main._build()

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/", headers={"Authorization": "Bearer test-token"}
            )

    assert response.status_code == 200
    text = response.text
    assert 'id="entity-name">KAINE<' in text
    assert 'data-sleeping="false"' in text


@pytest.mark.asyncio
async def test_dashboard_entity_name_updates_via_bridge_observer(
    monkeypatch, tmp_path
):
    httpx = pytest.importorskip("httpx")

    def _recent(stream, count):
        return []

    dashboard_main = _patch_dashboard_main(monkeypatch, tmp_path, _recent)

    from kaine.dashboard.bridge import BusBridge as _RealBusBridge

    _captured = []

    class _RecordingBusBridge(_RealBusBridge):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _captured.append(self)

    monkeypatch.setattr(dashboard_main, "BusBridge", _RecordingBusBridge)

    app, _cfg = await dashboard_main._build()
    bridge = _captured[0]

    async with app.router.lifespan_context(app):
        update_event = Event(
            source="self_model",
            type="self_model.document",
            payload={"name": "Lyra", "values": ["x"]},
            salience=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        for observer in bridge._observers:
            observer(update_event)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/", headers={"Authorization": "Bearer test-token"}
            )

    assert response.status_code == 200
    assert "Lyra" in response.text
