# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from kaine.bus.client import AsyncBus, _decode_workspace_event
from kaine.bus.config import BusConfig
from kaine.bus.schema import WORKSPACE_STREAM, Event, module_stream
from kaine.evaluation.stream_registry import CANONICAL_MODULE_NAMES, diagnostics_streams
from kaine.nexus.bridge import BusBridge
from kaine.nexus.config import NexusConfig
from kaine.privacy_filter import PrivacyFilter
from tests.test_nexus_routers import _make_client

fakeredis = pytest.importorskip("fakeredis.aioredis")


def _make_bus() -> AsyncBus:
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


SNAPSHOT: dict[str, Any] = {
    "tick_index": 3,
    "inhibited": False,
    "salience_scores": {"1-0": 0.7},
    "selected": [
        {
            "entry_id": "1-0",
            "source": "topos",
            "type": "topos.report",
            "salience": 0.7,
            "payload": {"change_score": 0.2},
            "timestamp": "2026-10-03T00:00:00+00:00",
            "causal_parent": None,
        }
    ],
    "metadata": {"coherence": 0.42},
}


def test_diagnostics_streams_are_real_streams():
    streams = diagnostics_streams()
    canonical_streams = {module_stream(name) for name in CANONICAL_MODULE_NAMES}
    for stream in streams:
        assert stream == "workspace.broadcast" or stream in canonical_streams
    assert "cycle.out" in streams
    assert "cycle.tick" not in streams


@pytest.mark.asyncio
async def test_published_broadcast_reads_back_as_event():
    bus = _make_bus()
    snapshot = dict(SNAPSHOT)
    entry_id = await bus.publish_workspace(snapshot)
    assert entry_id is not None

    entries = await bus.read("workspace.broadcast", last_id="0")
    assert len(entries) == 1

    _, event = entries[0]
    assert event.source == "syneidesis"
    assert event.type == WORKSPACE_STREAM
    assert event.payload == snapshot
    assert event.salience == pytest.approx(0.7)
    assert event.timestamp.tzinfo is not None


def test_broadcast_salience_is_clamped_and_defaults():
    high = {
        "snapshot": '{"selected": [{"salience": 1.7}]}',
        "timestamp": "2026-10-03T00:00:00+00:00",
    }
    ev = _decode_workspace_event(high)
    assert ev.salience == pytest.approx(1.0)

    empty = {
        "snapshot": '{"selected": []}',
        "timestamp": "2026-10-03T00:00:00+00:00",
    }
    ev = _decode_workspace_event(empty)
    assert ev.salience == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_corrupt_snapshot_is_skipped():
    bus = _make_bus()
    await bus.client.xadd(
        "workspace.broadcast",
        {
            "snapshot": "not json {",
            "timestamp": "2026-10-03T00:00:00+00:00",
            "source": "syneidesis",
        },
    )
    entries = await bus.read("workspace.broadcast", last_id="0")
    assert entries == []


@pytest.mark.asyncio
async def test_subscribe_workspace_still_yields_snapshot_dicts():
    bus = _make_bus()
    snapshot = dict(SNAPSHOT)
    await bus.publish_workspace(snapshot)

    decoded = None
    async for entry_id, value in bus.subscribe_workspace(last_id="0"):
        decoded = value
        break

    assert decoded == snapshot


@pytest.mark.asyncio
async def test_cycle_events_are_on_cycle_out():
    bus = _make_bus()
    event = Event(
        source="cycle",
        type="cycle.tick",
        payload={"processing_rate_hz": 10.0, "experiential_rate_hz": 3.3},
        salience=0.05,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)

    entries = await bus.read("cycle.out", last_id="0")
    assert len(entries) == 1
    _, decoded = entries[0]
    assert decoded.source == "cycle"
    assert decoded.type == "cycle.tick"
    assert "cycle.out" in diagnostics_streams()



@pytest.mark.asyncio
async def test_bridge_relays_events_published_after_start():
    bus = _make_bus()

    # History published before the bridge starts must not be relayed.
    history = Event(
        source="topos",
        type="topos.report",
        payload={"change_score": 0.1},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(history)

    bridge = BusBridge(
        bus,
        PrivacyFilter(),
        streams=["topos.out", "cycle.out", "workspace.broadcast"],
        poll_interval_s=0.01,
    )
    client = bridge.add_client("diagnostics")
    await bridge.start()

    # Resolve cursors to the newest pre-start entry on each stream.
    await bridge._tick_once()

    topos_event = Event(
        source="topos",
        type="topos.report",
        payload={"change_score": 0.2, "latent": [0.1] * 768},
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(topos_event)

    cycle_event = Event(
        source="cycle",
        type="cycle.tick",
        payload={"processing_rate_hz": 10.0, "experiential_rate_hz": 3.3},
        salience=0.05,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(cycle_event)

    snapshot = {
        "tick_index": 4,
        "inhibited": False,
        "salience_scores": {"1-0": 0.8},
        "selected": [
            {
                "entry_id": "1-0",
                "source": "topos",
                "type": "topos.report",
                "salience": 0.8,
                "payload": {"latent": [0.2] * 768, "change_score": 0.3},
                "timestamp": "2026-10-03T00:00:00+00:00",
                "causal_parent": None,
            }
        ],
        "metadata": {"coherence": 0.42},
    }
    await bus.publish_workspace(snapshot)

    # Pick up the newly published events.
    await bridge._tick_once()
    await bridge.stop()

    drained: list[tuple[str, Event]] = []
    while True:
        try:
            drained.append(client.queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    assert len(drained) == 3

    topos_payloads = [
        event.payload for _, event in drained if event.type == "topos.report"
    ]
    assert all(payload.get("change_score") != 0.1 for payload in topos_payloads)
    assert {"change_score": 0.2} in topos_payloads

    event_types = {event.type for _, event in drained}
    assert "cycle.tick" in event_types
    assert "workspace.broadcast" in event_types

    broadcast_events = [
        event for _, event in drained if event.type == "workspace.broadcast"
    ]
    assert len(broadcast_events) == 1
    assert broadcast_events[0].payload["metadata"]["coherence"] == pytest.approx(0.42)
    assert "latent" not in json.dumps(broadcast_events[0].payload)


class _TallHealth:
    cache_ttl_s = 30.0

    async def snapshot(self):
        return {"dependencies": [], "modules": []}


@pytest.mark.asyncio
async def test_chart_routing_in_real_browser():
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright

    browser = None
    async with async_playwright() as pw:
        try:
            try:
                browser = await pw.chromium.launch(channel="chrome")
            except Exception as chrome_err:
                try:
                    browser = await pw.chromium.launch()
                except Exception:
                    pytest.skip(
                        f"System Chrome unavailable and fallback Chromium failed: {chrome_err}"
                    )

            page = await browser.new_page(viewport={"width": 1600, "height": 1000})

            config = NexusConfig(
                host_allowlist=("127.0.0.1", "localhost", "test", "nexus.test"),
            )
            client, app = await _make_client(
                config=config,
                health_prober=_TallHealth(),
            )
            client.base_url = httpx.URL("http://nexus.test")

            async with app.router.lifespan_context(app):
                async with client:

                    async def handler(route):
                        parsed = urlparse(route.request.url)
                        path_and_query = parsed.path + (
                            "?" + parsed.query if parsed.query else ""
                        )
                        if parsed.path.endswith("/stream") or "/stream?" in path_and_query:
                            await route.abort()
                            return
                        resp = await client.request(
                            route.request.method,
                            path_and_query,
                            headers={"Authorization": "Bearer test-token"},
                            content=route.request.post_data_buffer,
                        )
                        await route.fulfill(
                            status=resp.status_code,
                            headers={
                                k: v
                                for k, v in resp.headers.items()
                                if k.lower()
                                not in ("content-length", "content-encoding", "transfer-encoding")
                            },
                            body=resp.content,
                        )

                    await page.route("http://nexus.test/**", handler)

                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))

                    await page.goto("http://nexus.test/diagnostics/")
                    await page.wait_for_load_state("load")

                    results = await page.evaluate(
                        """(msgs) => {
                            const routing = window.NexusChartRouting;
                            return msgs.map(m => routing.chartSamples(m));
                        }""",
                        [
                            {"source": "syneidesis", "type": "workspace.broadcast", "salience": 0.7, "payload": {"metadata": {"coherence": 0.42}}},
                            {"source": "cycle", "type": "cycle.tick", "salience": 0.05, "payload": {"processing_rate_hz": 10, "experiential_rate_hz": 3.3}},
                            {"source": "topos", "type": "topos.report", "salience": 0.6, "payload": {}},
                            {"source": "syneidesis", "type": "workspace.broadcast", "salience": 0.7, "payload": {"metadata": {}}},
                        ],
                    )

                    assert len(results) == 4
                    assert results[0].get("coherence") == pytest.approx(0.42)
                    assert "salience" not in results[0]
                    assert results[1].get("rate") == [pytest.approx(10), pytest.approx(3.3)]
                    assert "salience" not in results[1]
                    assert results[2].get("salience") == pytest.approx(0.6)
                    assert "coherence" not in results[2]
                    assert "coherence" not in results[3]

                    assert errors == []
        finally:
            if browser is not None:
                await browser.close()
