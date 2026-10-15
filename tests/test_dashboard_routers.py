# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from kaine.bus.schema import Event
from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.conversation import ConversationState
from kaine.dashboard.privacy import PrivacyFilter
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.snapshot import artifacts_dir


def _event(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


async def _make_client(
    *,
    config: DashboardConfig | None = None,
    history: list[tuple[str, Event]] | None = None,
    metrics: dict | None = None,
    fork_manager: ForkManager | None = None,
    state: ConversationState | None = None,
    health_prober=None,
    rate_control_publisher=None,
    token: str | None = "test-token",
):
    # Conversation is deactivated by default in the first configuration; these router
    # tests exercise both surfaces, so enable conversation unless a test overrides.
    base = DashboardConfig(
        conversation_enabled=True,
        # TestClient sends Host: test; allow it so CSRF validation passes.
        host_allowlist=("127.0.0.1", "localhost", "test"),
    )
    if config is None:
        config = base
    else:
        # Merge explicit overrides onto the test default.
        from dataclasses import replace

        config = replace(base, **config.__dict__)
    # TestClient sends Host: test; make sure it remains allowed after merging.
    if "test" not in config.host_allowlist:
        from dataclasses import replace

        config = replace(config, host_allowlist=(*config.host_allowlist, "test"))
    if token is not None:
        from dataclasses import replace

        config = replace(config, operator_token=token)
    bus = StubBus()
    privacy = PrivacyFilter(dev_content_override=config.dev_content_override)
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return list(history or [])

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: dict(metrics or {}),
        fork_manager=fork_manager,
        conversation_state=state,
        health_prober=health_prober,
        rate_control_publisher=rate_control_publisher,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, app


def test_conversation_sleep_state_follows_sleep_lifecycle():
    """The sleep badge must react to the canonical sleep module's lifecycle event types
    (sleep.sleep.started/completed), not the old began_rest/ended_rest variants
    The sleep module never emits."""
    state = ConversationState()
    assert state.sleeping is False
    state.update_from_sleep("sleep.sleep.started")
    assert state.sleeping is True
    state.update_from_sleep("sleep.sleep.completed")
    assert state.sleeping is False
    # The old, wrong type must NOT toggle the badge (guards against regression).
    state.update_from_sleep("sleep.sleep.started")
    state.update_from_sleep("sleep.began_rest")
    assert state.sleeping is True


@pytest.mark.asyncio
async def test_conversation_route_renders_entity_name():
    state = ConversationState()
    state.entity_name = "Lyra"
    client, app = await _make_client(state=state)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        assert "Lyra" in r.text


@pytest.mark.asyncio
async def test_console_does_not_render_transcript_text():
    # The conversation transcript panel was removed from the console (the Presence
    # visualizer replaced it). The console renders NO live speech text — neither
    # external nor internal — which strictly preserves the privacy invariant that
    # the entity's internal monologue is never shown.
    history = [
        ("1-0", _event("language", "external_speech", {"text": "hi there"})),
        ("2-0", _event("language", "internal_speech", {"text": "should not appear"})),
    ]
    client, app = await _make_client(history=history)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        assert "should not appear" not in r.text  # internal monologue never leaks
        assert "hi there" not in r.text  # transcript panel removed


@pytest.mark.asyncio
async def test_diagnostics_route_has_no_message_text(tmp_path):
    fm = ForkManager(tmp_path)
    client, app = await _make_client(
        history=[("1-0", _event("language", "external_speech", {"text": "secret message"}))],
        metrics={"cycle.processing_hz": 3.333},
        fork_manager=fm,
    )
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        # No text from any history event leaks into diagnostics.
        assert "secret message" not in r.text
        # But metrics ARE present.
        assert "cycle.processing_hz" in r.text


@pytest.mark.asyncio
async def test_diagnostics_returns_404_when_disabled():
    config = DashboardConfig(diagnostics_enabled=False)
    client, app = await _make_client(config=config)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_root_redirects_to_diagnostics_when_conversation_disabled():
    config = DashboardConfig(conversation_enabled=False)
    client, app = await _make_client(config=config)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 307
        assert r.headers["location"].endswith("/diagnostics/")


@pytest.mark.asyncio
async def test_dev_override_shows_banner():
    config = DashboardConfig(dev_content_override=True)
    client, app = await _make_client(config=config)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        assert "dev mode" in r.text.lower()


@pytest.mark.asyncio
async def test_forks_endpoint_lists_snapshots(tmp_path):
    fm = ForkManager(tmp_path)

    class FakeMod:
        name = "interoception"

        def serialize(self):
            return {"wellness": 0.9}

        def deserialize(self, state):
            pass

    class FakeReg:
        def all_modules(self):
            return iter([FakeMod()])

    snap = fm.snapshot(FakeReg(), label="root")
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/forks.json", headers={"Authorization": "Bearer test-token"}
            )
        assert r.status_code == 200
        data = r.json()
        assert any(f["id"] == snap.id for f in data["forks"])


@pytest.mark.asyncio
async def test_post_fork_creates_new_snapshot(tmp_path):
    fm = ForkManager(tmp_path)

    class FakeMod:
        name = "interoception"

        def serialize(self):
            return {"v": 1}

        def deserialize(self, state):
            pass

    class FakeReg:
        def all_modules(self):
            return iter([FakeMod()])

    parent = fm.snapshot(FakeReg())
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/forks",
                json={"parent_id": parent.id, "label": "child", "shed": []},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["parent_id"] == parent.id
        assert body["label"] == "child"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_id",
    [
        "/etc/passwd",  # absolute path
        "../../../../etc/passwd",  # parent-dir traversal
        "..",  # bare parent ref
        "abc/def",  # embedded separator
        "aaaaaaaaaaaaaaaZ",  # non-hex char
        "aaaaaaaa",  # too short
        "aaaaaaaaaaaaaaaaaaaa",  # too long
        "",  # empty
    ],
)
async def test_post_fork_rejects_traversal_and_malformed_ids(tmp_path, bad_id):
    """An untrusted parent_id that is absolute, contains '..'/a separator, or is
    otherwise not a strict fork/merge id is rejected with 422 before it can reach
    load_snapshot — the P1 path-traversal defense at the request boundary."""
    fm = ForkManager(tmp_path)
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/forks",
                json={"parent_id": bad_id, "label": "x"},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_post_merge_rejects_traversal_ids(tmp_path):
    """Both merge parent ids are validated; a traversal id yields 422."""
    fm = ForkManager(tmp_path)
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/merges",
                json={"snapshot_a_id": "0123456789abcdef", "snapshot_b_id": "../../etc/passwd"},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_post_merge_accepts_valid_merge_form_ids(tmp_path):
    """A valid 16-hex id and a valid `<hex>+<hex>` merge-form id both pass
    validation (they reach the manager, which 404s only because they don't
    exist — proving the validator itself did not reject them)."""
    fm = ForkManager(tmp_path)
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/merges",
                json={
                    "snapshot_a_id": "0123456789abcdef",
                    "snapshot_b_id": "0123456789abcdef+fedcba9876543210",
                },
                headers={"Authorization": "Bearer test-token"},
            )
        # Not 422 (validation passed); 404 because the snapshots are absent.
        assert r.status_code == 404, r.text


class _InteroceptionOnlyModule:
    name = "interoception"

    def serialize(self):
        return {"v": 1}

    def deserialize(self, state):
        pass


class _InteroceptionOnlyRegistry:
    def all_modules(self):
        return iter([_InteroceptionOnlyModule()])


@pytest.mark.asyncio
async def test_post_merge_two_world_model_world_models_requires_choice(tmp_path):
    """When both parents carry a world model and no choice is given,
    the merge endpoint surfaces a 409 pointing at world_model_from."""
    fm = ForkManager(tmp_path)
    snap_a = fm.snapshot(_InteroceptionOnlyRegistry(), label="a")
    snap_b = fm.snapshot(_InteroceptionOnlyRegistry(), label="b")
    a_ph_dir = artifacts_dir(tmp_path, snap_a.id, "world_model")
    b_ph_dir = artifacts_dir(tmp_path, snap_b.id, "world_model")
    a_ph_dir.mkdir(parents=True, exist_ok=True)
    b_ph_dir.mkdir(parents=True, exist_ok=True)
    (a_ph_dir / "world_model.ckpt").write_bytes(b"a-model")
    (b_ph_dir / "world_model.ckpt").write_bytes(b"b-model")
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/merges",
                json={"snapshot_a_id": snap_a.id, "snapshot_b_id": snap_b.id},
                headers={"Authorization": "Bearer test-token"},
            )
    assert r.status_code == 409, r.text
    assert "world_model_from" in r.json()["detail"]


@pytest.mark.asyncio
async def test_post_merge_two_world_model_world_models_choice_b(tmp_path):
    """Passing world_model_from='b' succeeds and carries b's world model."""
    fm = ForkManager(tmp_path)
    snap_a = fm.snapshot(_InteroceptionOnlyRegistry(), label="a")
    snap_b = fm.snapshot(_InteroceptionOnlyRegistry(), label="b")
    a_ph_dir = artifacts_dir(tmp_path, snap_a.id, "world_model")
    b_ph_dir = artifacts_dir(tmp_path, snap_b.id, "world_model")
    a_ph_dir.mkdir(parents=True, exist_ok=True)
    b_ph_dir.mkdir(parents=True, exist_ok=True)
    (a_ph_dir / "world_model.ckpt").write_bytes(b"a-model")
    (b_ph_dir / "world_model.ckpt").write_bytes(b"b-model")
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/merges",
                json={
                    "snapshot_a_id": snap_a.id,
                    "snapshot_b_id": snap_b.id,
                    "world_model_from": "b",
                },
                headers={"Authorization": "Bearer test-token"},
            )
    assert r.status_code == 200, r.text
    merged_id = r.json()["id"]
    merged_ph = artifacts_dir(tmp_path, merged_id, "world_model") / "world_model.ckpt"
    assert merged_ph.read_bytes() == b"b-model"


@pytest.mark.asyncio
async def test_post_fork_with_time_scale_stores_timing_profile(tmp_path):
    fm = ForkManager(tmp_path)

    class FakeMod:
        name = "interoception"

        def serialize(self):
            return {"v": 1}

        def deserialize(self, state):
            pass

    class FakeReg:
        def all_modules(self):
            return iter([FakeMod()])

    parent = fm.snapshot(FakeReg())
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/forks",
                json={
                    "parent_id": parent.id,
                    "label": "dilated",
                    "time_scale": 2.0,
                    "processing_rate_hz": 12.0,
                },
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        # The response surfaces the parsed profile.
        assert body["timing"]["time_scale"] == 2.0
        assert body["timing"]["processing_rate_hz"] == 12.0
        # And it is persisted in the snapshot metadata via the existing path.
        snap = fm.load(body["id"])
        assert snap.metadata["timing"]["time_scale"] == 2.0


@pytest.mark.asyncio
async def test_post_fork_rejects_nonpositive_time_scale(tmp_path):
    fm = ForkManager(tmp_path)

    class FakeMod:
        name = "interoception"

        def serialize(self):
            return {"v": 1}

        def deserialize(self, state):
            pass

    class FakeReg:
        def all_modules(self):
            return iter([FakeMod()])

    parent = fm.snapshot(FakeReg())
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/forks",
                json={"parent_id": parent.id, "time_scale": 0},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_post_fork_without_time_scale_has_no_timing(tmp_path):
    fm = ForkManager(tmp_path)

    class FakeMod:
        name = "interoception"

        def serialize(self):
            return {"v": 1}

        def deserialize(self, state):
            pass

    class FakeReg:
        def all_modules(self):
            return iter([FakeMod()])

    parent = fm.snapshot(FakeReg())
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/forks",
                json={"parent_id": parent.id, "label": "plain"},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "timing" not in body
        snap = fm.load(body["id"])
        assert "timing" not in snap.metadata


@pytest.mark.asyncio
async def test_forks_json_surfaces_timing_profile(tmp_path):
    from kaine.lifecycle.timing_profile import build_timing_metadata

    fm = ForkManager(tmp_path)

    class FakeMod:
        name = "interoception"

        def serialize(self):
            return {"v": 1}

        def deserialize(self, state):
            pass

    class FakeReg:
        def all_modules(self):
            return iter([FakeMod()])

    parent = fm.snapshot(FakeReg())
    child = fm.fork(
        parent.id,
        label="dilated",
        metadata=build_timing_metadata(time_scale=2.0),
    )
    client, app = await _make_client(fork_manager=fm)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/forks.json", headers={"Authorization": "Bearer test-token"}
            )
        assert r.status_code == 200
        forks = {f["id"]: f for f in r.json()["forks"]}
        assert forks[child.id]["timing"]["time_scale"] == 2.0
        # The plain parent has no timing key surfaced.
        assert "timing" not in forks[parent.id]


@pytest.mark.asyncio
async def test_metrics_json_returns_snapshot():
    client, app = await _make_client(metrics={"a": 1, "b": 2})
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/metrics.json", headers={"Authorization": "Bearer test-token"}
            )
        assert r.status_code == 200
        assert r.json() == {"a": 1, "b": 2}


# ---- Health board -------------------------------------------------------

from kaine.dashboard.health import (  # noqa: E402
    DOWN,
    NOT_CONFIGURED,
    UP,
    DependencySpec,
    HealthProber,
)


def _prober(modules_enabled, specs, **kw):
    return HealthProber(
        modules_enabled=modules_enabled,
        dependencies=specs,
        cache_ttl_s=kw.pop("cache_ttl_s", 0.0),
        probe_timeout_s=kw.pop("probe_timeout_s", 0.2),
        cycle_runtime_path=kw.pop("cycle_runtime_path", Path("/nonexistent/runtime.json")),
    )


@pytest.mark.asyncio
async def test_health_endpoint_shape():
    async def up_probe():
        return UP, "ok"

    prober = _prober(
        {"episodic_memory": True},
        [DependencySpec(name="Qdrant", role="EpisodicMemory", module="episodic_memory", probe=up_probe)],
    )
    client, app = await _make_client(health_prober=prober)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/health.json", headers={"Authorization": "Bearer test-token"}
            )
        assert r.status_code == 200
        data = r.json()
        assert "dependencies" in data and "modules" in data and "checked_at" in data
        dep = data["dependencies"][0]
        assert set(dep) >= {"name", "role", "status", "detail", "checked_at"}
        assert dep["status"] == UP


# ---------------------------------------------------------------------------
# Snapshot pusher (task 2.2) — server-pushes a combined metrics+health
# snapshot over the single diagnostics SSE stream, retiring the client-side
# DashboardVitals/DashboardMetrics/DashboardSupervisor poll loops.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_snapshots_periodically_pushes_combined_snapshot():
    import asyncio

    from kaine.dashboard.diagnostics import push_snapshots_periodically

    class FakeBus:
        async def read(self, *a, **kw):
            return []

    async def up_probe():
        return UP, "ok"

    prober = _prober(
        {"episodic_memory": True},
        [DependencySpec(name="Qdrant", role="EpisodicMemory", module="episodic_memory", probe=up_probe)],
    )
    bridge = BusBridge(FakeBus(), PrivacyFilter(), streams=[])
    client = bridge.add_client("diagnostics")

    task = asyncio.create_task(
        push_snapshots_periodically(
            bridge,
            metrics_snapshot=lambda: {"a": 1},
            health_prober=prober,
            # Long enough that this test only ever observes the FIRST push
            # (which happens immediately, before the first sleep).
            interval_s=1000.0,
        )
    )
    try:
        _, event = await asyncio.wait_for(client.queue.get(), timeout=2.0)
        assert event.source == "dashboard"
        assert event.type == "dashboard.snapshot"
        assert event.payload["metrics"] == {"a": 1}
        assert event.payload["health"]["dependencies"][0]["status"] == UP
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected: the background task was cancelled and is awaited to
            # unwind during test teardown. Suppress intentionally.
            pass


@pytest.mark.asyncio
async def test_push_snapshots_periodically_never_faster_than_health_cache_ttl():
    # Never poll faster than the cache TTL (task 1.3): the pusher's default
    # cadence is max(DEFAULT_SNAPSHOT_PUSH_INTERVAL_S, health_prober.cache_ttl_s).
    import asyncio

    from kaine.dashboard.diagnostics import push_snapshots_periodically

    class FakeBus:
        async def read(self, *a, **kw):
            return []

    prober = _prober({}, [], cache_ttl_s=30.0)
    bridge = BusBridge(FakeBus(), PrivacyFilter(), streams=[])
    client = bridge.add_client("diagnostics")

    task = asyncio.create_task(
        push_snapshots_periodically(bridge, metrics_snapshot=lambda: {}, health_prober=prober)
    )
    try:
        # The first push happens immediately...
        await asyncio.wait_for(client.queue.get(), timeout=2.0)
        # ...and the second must NOT arrive within a window far shorter than
        # the 30s cache-TTL floor.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.queue.get(), timeout=0.3)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected: the background task was cancelled and is awaited to
            # unwind during test teardown. Suppress intentionally.
            pass


@pytest.mark.asyncio
async def test_push_snapshots_periodically_survives_health_prober_none():
    # No health_prober configured (e.g. diagnostics up without the board
    # wired) must still push a metrics-only snapshot, never crash the task.
    import asyncio

    from kaine.dashboard.diagnostics import push_snapshots_periodically

    class FakeBus:
        async def read(self, *a, **kw):
            return []

    bridge = BusBridge(FakeBus(), PrivacyFilter(), streams=[])
    client = bridge.add_client("diagnostics")
    task = asyncio.create_task(
        push_snapshots_periodically(
            bridge, metrics_snapshot=lambda: {"a": 1}, health_prober=None, interval_s=1000.0
        )
    )
    try:
        _, event = await asyncio.wait_for(client.queue.get(), timeout=2.0)
        assert event.payload == {"metrics": {"a": 1}, "health": None}
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected: the background task was cancelled and is awaited to
            # unwind during test teardown. Suppress intentionally.
            pass


@pytest.mark.asyncio
async def test_health_disabled_module_is_not_configured():
    async def should_not_run():
        raise AssertionError("probe ran for a disabled module")

    prober = _prober(
        {"vocal": False},
        [DependencySpec(name="Chatterbox", role="Vocal", module="vocal", probe=should_not_run)],
    )
    snap = await prober.snapshot(force=True)
    dep = snap["dependencies"][0]
    assert dep["status"] == NOT_CONFIGURED
    assert "disabled" in dep["detail"]


@pytest.mark.asyncio
async def test_health_down_service_is_down():
    async def boom():
        raise ConnectionRefusedError("nope")

    prober = _prober(
        {"audition": True},
        [DependencySpec(name="Speaches", role="Audition", module="audition", probe=boom)],
    )
    snap = await prober.snapshot(force=True)
    assert snap["dependencies"][0]["status"] == DOWN


@pytest.mark.asyncio
async def test_health_timeout_does_not_block_other_probes():
    import asyncio

    async def hangs():
        await asyncio.sleep(10)
        return UP, "never"

    async def quick():
        return UP, "fast"

    prober = _prober(
        {"planning": True, "episodic_memory": True},
        [
            DependencySpec(name="ONA", role="Planning", module="planning", probe=hangs),
            DependencySpec(name="Qdrant", role="EpisodicMemory", module="episodic_memory", probe=quick),
        ],
        probe_timeout_s=0.05,
    )
    snap = await prober.snapshot(force=True)
    by_name = {d["name"]: d for d in snap["dependencies"]}
    assert by_name["ONA"]["status"] == DOWN
    assert "timed out" in by_name["ONA"]["detail"]
    assert by_name["Qdrant"]["status"] == UP


@pytest.mark.asyncio
async def test_health_results_cached_within_ttl():
    calls = {"n": 0}

    async def counting():
        calls["n"] += 1
        return UP, "ok"

    prober = _prober(
        {"episodic_memory": True},
        [DependencySpec(name="Qdrant", role="EpisodicMemory", module="episodic_memory", probe=counting)],
        cache_ttl_s=60.0,
    )
    await prober.snapshot()
    await prober.snapshot()
    await prober.snapshot()
    assert calls["n"] == 1  # cached after the first refresh


@pytest.mark.asyncio
async def test_health_board_rendered_on_diagnostics_page():
    async def up_probe():
        return UP, "PING ok"

    prober = _prober(
        {"episodic_memory": True},
        [DependencySpec(name="Redis", role="bus", module=None, probe=up_probe)],
    )
    client, app = await _make_client(health_prober=prober)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        assert "service" in r.text.lower() and "health" in r.text.lower()
        assert "Redis" in r.text


@pytest.mark.asyncio
async def test_console_renders_health_in_sidebar():
    # Health & services renders on the console in the glanceable right sidebar
    # (rail--right), compact and scroll-free. The service board and gpu pre-flight
    # render within it.
    async def up_probe():
        return UP, "PING ok"

    prober = _prober(
        {"episodic_memory": True},
        [DependencySpec(name="Redis", role="bus", module=None, probe=up_probe)],
    )
    client, app = await _make_client(health_prober=prober)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        # The right sidebar carries the health board + its content.
        assert "rail--right" in r.text
        assert 'id="board-health"' in r.text
        assert 'id="health"' in r.text and 'id="gpu-preflight"' in r.text
        assert "Redis" in r.text
        # The left-rail Health jump segment was removed.
        assert 'href="#board-health"' not in r.text


@pytest.mark.asyncio
async def test_health_json_when_no_prober_returns_empty():
    client, app = await _make_client(health_prober=None)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/health.json", headers={"Authorization": "Bearer test-token"}
            )
        assert r.status_code == 200
        assert r.json()["dependencies"] == []


# ---- Cycle rate control -------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_rate_control_publishes_event():
    published = []

    async def publisher(payload):
        published.append(payload)

    client, app = await _make_client(rate_control_publisher=publisher)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/cycle/rates",
                json={"processing_rate_hz": 5.0, "experiential_rate_hz": 2.0},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 200, r.text
        assert r.json()["published"] is True
    assert published == [{"processing_rate_hz": 5.0, "experiential_rate_hz": 2.0}]


@pytest.mark.asyncio
async def test_cycle_rate_control_rejects_nonpositive():
    async def publisher(payload):
        raise AssertionError("should not publish")

    client, app = await _make_client(rate_control_publisher=publisher)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/cycle/rates",
                json={"processing_rate_hz": 0},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_cycle_rate_control_503_when_not_configured():
    client, app = await _make_client(rate_control_publisher=None)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/diagnostics/cycle/rates",
                json={"processing_rate_hz": 3.0},
                headers={"Authorization": "Bearer test-token"},
            )
        assert r.status_code == 503


# ---- Layout smoke -------------------------------------------------------


@pytest.mark.asyncio
async def test_pages_share_dashboard_layout_marker():
    client, app = await _make_client(metrics={"cycle_status": "running"})
    async with client:
        async with app.router.lifespan_context(app):
            conv = await client.get("/", headers={"Authorization": "Bearer test-token"})
            diag = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        for resp in (conv, diag):
            assert resp.status_code == 200
            assert 'data-dashboard-layout="dashboard"' in resp.text


@pytest.mark.asyncio
async def test_module_states_from_runtime_and_perception(tmp_path):
    runtime = tmp_path / "cycle_runtime.json"
    runtime.write_text(json.dumps({"modules": ["episodic_memory", "planning"], "tick_index": 5}))

    async def up_probe():
        return UP, "ok"

    prober = HealthProber(
        modules_enabled={"episodic_memory": True, "planning": True, "effectors": False},
        dependencies=[
            DependencySpec(name="Qdrant", role="EpisodicMemory", module="episodic_memory", probe=up_probe)
        ],
        cache_ttl_s=0.0,
        cycle_runtime_path=runtime,
    )
    snap = await prober.snapshot(force=True)
    mods = {m["name"]: m for m in snap["modules"]}
    assert mods["episodic_memory"]["enabled"] and mods["episodic_memory"]["initialized"]
    assert mods["planning"]["enabled"] and mods["planning"]["initialized"]
    # Disabled module: enabled False, not initialized.
    assert mods["effectors"]["enabled"] is False
    assert mods["effectors"]["initialized"] is False


def test_charts_served_locally_no_cdn():
    """Charting assets are vendored and referenced via /static; the rendered
    pages must not reference any remote chart CDN at runtime."""
    base = Path(__file__).resolve().parents[1] / "kaine" / "dashboard"
    diag = (base / "templates" / "diagnostics.html").read_text()
    evald = (base / "templates" / "evaluation.html").read_text()
    for html in (diag, evald):
        assert "/static/vendor/uPlot" in html
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html
        assert "cdnjs" not in html
        assert "http://" not in html and "https://" not in html  # no remote includes
    assert (base / "static" / "vendor" / "uPlot.iife.min.js").exists()


def test_presence_viz_served_locally_no_cdn():
    """The Presence-board ferrofluid visualizer (LevelMeter) and its Three.js
    dependency are vendored and loaded from /static/vendor — no CDN / remote
    ES-module import at runtime (no-cloud-runtime). Mirrors the chart-CDN guard.
    """
    base = Path(__file__).resolve().parents[1] / "kaine" / "dashboard"
    console = (base / "templates" / "console.html").read_text()
    # The console imports the viz as a local ES module — never a CDN.
    assert "/static/vendor/viz.js" in console
    assert "import" in console and "LevelMeter" in console
    assert "http://" not in console and "https://" not in console
    for needle in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs", "esm.sh", "skypack"):
        assert needle not in console, needle

    # The vendored files exist on disk, laid out so viz.js's relative imports
    # (`./vendor/three.module.js`, `./vendor/MarchingCubes.js`) resolve locally.
    vendor = base / "static" / "vendor"
    viz = vendor / "viz.js"
    three = vendor / "vendor" / "three.module.js"
    marching = vendor / "vendor" / "MarchingCubes.js"
    for path in (viz, three, marching):
        assert path.exists(), path

    # viz.js loads Three.js by relative path, not from any remote origin.
    viz_src = viz.read_text()
    assert "./vendor/three.module.js" in viz_src
    assert "./vendor/MarchingCubes.js" in viz_src
    # No remote ES-module import anywhere in the vendored viz/three sources.
    for src in (viz_src, three.read_text(), marching.read_text()):
        # `import ... from 'http(s)://...'` would be a runtime CDN fetch.
        assert "from 'http" not in src and 'from "http' not in src

    # The vendored components are tracked with their own licenses.
    tpl = Path(__file__).resolve().parents[1] / "THIRD_PARTY_LICENSES.md"
    assert tpl.exists()
    manifest = tpl.read_text()
    assert "GPL-3.0-or-later" in manifest  # viz.js / LevelMeter
    assert "Three.js" in manifest and "MIT" in manifest
    assert "SIL OFL 1.1" in manifest  # vendored fonts


def test_console_opens_exactly_one_sse_connection():
    """V.2: the console must open exactly ONE `EventSource` to the diagnostics
    stream, not the eight independent connections the pre-refactor console
    opened (subscribeMetrics, chart diagnostics, chart fatigue, supervisor, preservation,
    vitals, DashboardReveal, and the presence-affect inline script). Every feature
    now subscribes through the single shared `DashboardStream` dispatcher instead."""
    base = Path(__file__).resolve().parents[1] / "kaine" / "dashboard"
    dashboard_js = (base / "static" / "dashboard.js").read_text()
    dashboard_console_js = (base / "static" / "dashboard_console.js").read_text()
    console_html = (base / "templates" / "console.html").read_text()
    diagnostics_html = (base / "templates" / "diagnostics.html").read_text()

    # Exactly one `new EventSource(` construction across the whole client
    # bundle — inside DashboardStream, the shared dispatcher every feature below
    # subscribes through.
    total = sum(
        src.count("new EventSource(")
        for src in (dashboard_js, dashboard_console_js, console_html, diagnostics_html)
    )
    assert total == 1, (
        f"expected exactly one `new EventSource(` construction (the shared "
        f"DashboardStream dispatcher), found {total}"
    )
    assert "window.DashboardStream" in dashboard_js
    assert "new EventSource(url)" in dashboard_js

    # Every feature that used to open its own EventSource now goes through the
    # shared dispatcher instead.
    assert "DashboardStream.subscribe(" in dashboard_js
    assert "DashboardStream.subscribe(" in dashboard_console_js
    start = dashboard_js.index("window.DashboardStream = {")
    end = dashboard_js.index("};", start)
    stream_export = dashboard_js[start:end]
    assert "init: init" in stream_export  # exposes init() for the page to call

    # Both pages that open the stream call DashboardStream.init exactly once.
    for html in (console_html, diagnostics_html):
        assert html.count('DashboardStream.init("/diagnostics/stream")') == 1


def test_fonts_served_locally_no_external_font_url():
    """The vendored web fonts are referenced from /static/fonts via @font-face;
    no external font CDN (Google Fonts etc.) is reached at runtime
    (no-cloud-runtime). Every referenced woff2 exists on disk."""
    base = Path(__file__).resolve().parents[1] / "kaine" / "dashboard"
    css = (base / "static" / "style.css").read_text()
    assert "@font-face" in css
    assert "/static/fonts/" in css
    # No remote font sources of any kind.
    assert "fonts.googleapis.com" not in css
    assert "fonts.gstatic.com" not in css
    assert "http://" not in css and "https://" not in css
    fonts_dir = base / "static" / "fonts"
    # Every woff2 the CSS references must exist on disk (derived, not hard-coded).
    import re

    referenced = re.findall(r"/static/fonts/([^\"')]+\.woff2)", css)
    assert referenced, "no @font-face woff2 references found in style.css"
    for fname in referenced:
        assert (fonts_dir / fname).exists(), fname
    # The Kaine brand type system: Zen Dots (display), Inter (UI), JetBrains Mono.
    for family in ("zen-dots", "inter", "jetbrains-mono"):
        assert any(family in f for f in referenced), family
    # Zen Dots ships a single weight, declared as a 400 700 range so the
    # console's 600/700 display rules match the face instead of being
    # synthesized into fake bold. Losing the range silently degrades every
    # header, so pin it.
    assert "font-weight: 400 700" in css, "Zen Dots must declare a 400 700 weight range"


# ---- the supervisor health block ----------------------------------------


import json  # noqa: E402


def _supervisor_prober(tmp_path):
    """HealthProber wired to tmp state files so tests are hermetic."""
    return HealthProber(
        modules_enabled={},
        dependencies=[],
        cache_ttl_s=0.0,
        probe_timeout_s=0.2,
        cycle_runtime_path=Path("/nonexistent/runtime.json"),
        supervisor_control_path=tmp_path / "control.json",
        supervisor_escalation_path=tmp_path / "escalation.json",
    )


@pytest.mark.asyncio
async def test_health_json_supervisor_block_ok_when_no_files(tmp_path):
    """No state files → supervisor block state is 'ok'."""
    prober = _supervisor_prober(tmp_path)
    snap = await prober.snapshot(force=True)
    assert "supervisor" in snap
    s = snap["supervisor"]
    assert s["state"] == "ok"
    assert s["module"] is None
    assert s["attempts"] == 0
    assert s["message"] == ""
    assert s["snapshot_id"] is None
    assert s["since"] is None


@pytest.mark.asyncio
async def test_health_json_supervisor_block_recovery(tmp_path):
    """Control file with frozen=true and source='supervisor' → state 'recovery'."""
    ctrl = {
        "frozen": True,
        "frozen_at": "2026-06-07T12:00:00+00:00",
        "reason": "restarting interoception",
        "source": "supervisor",
    }
    (tmp_path / "control.json").write_text(json.dumps(ctrl))
    prober = _supervisor_prober(tmp_path)
    snap = await prober.snapshot(force=True)
    s = snap["supervisor"]
    assert s["state"] == "recovery"
    assert s["message"] == "restarting interoception"
    assert s["since"] == "2026-06-07T12:00:00+00:00"


@pytest.mark.asyncio
async def test_health_json_supervisor_block_critical(tmp_path):
    """Escalation file with escalated=true → state 'critical'."""
    esc = {
        "escalated": True,
        "module": "planning",
        "attempts": 5,
        "snapshot_id": "snap-abc",
        "escalated_at": "2026-06-07T11:59:00+00:00",
        "message": "planning failed 5 times; halting",
    }
    (tmp_path / "escalation.json").write_text(json.dumps(esc))
    prober = _supervisor_prober(tmp_path)
    snap = await prober.snapshot(force=True)
    s = snap["supervisor"]
    assert s["state"] == "critical"
    assert s["module"] == "planning"
    assert s["attempts"] == 5
    assert s["snapshot_id"] == "snap-abc"
    assert s["message"] == "planning failed 5 times; halting"
    assert s["since"] == "2026-06-07T11:59:00+00:00"


@pytest.mark.asyncio
async def test_health_json_supervisor_via_endpoint(tmp_path):
    """health.json HTTP endpoint includes a 'supervisor' key with valid state."""
    prober = _supervisor_prober(tmp_path)
    client, app = await _make_client(health_prober=prober)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/health.json", headers={"Authorization": "Bearer test-token"}
            )
        assert r.status_code == 200
        data = r.json()
        assert "supervisor" in data
        assert data["supervisor"]["state"] in ("ok", "recovery", "critical")


@pytest.mark.asyncio
async def test_diagnostics_page_has_supervisor_alert_overlay(tmp_path):
    """The diagnostics page renders the supervisor-alert overlay and supervisor-console."""
    prober = _supervisor_prober(tmp_path)
    client, app = await _make_client(health_prober=prober)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        assert 'id="supervisor-alert"' in r.text
        assert "data-state" in r.text
        assert 'id="supervisor-console"' in r.text


def test_supervisor_out_in_default_diagnostics_streams():
    """supervisor.out must be in DEFAULT_DIAGNOSTICS_STREAMS."""
    import kaine.dashboard.__main__ as dashboard_main

    assert "supervisor.out" in dashboard_main.DEFAULT_DIAGNOSTICS_STREAMS


# ---- Entity-care (read-only welfare/divergence block) --------------------


@pytest.mark.asyncio
async def test_health_json_has_entity_care_block(tmp_path):
    """health.json carries an entity_care block (CAL 4.2/4.3, read-only)."""
    prober = _supervisor_prober(tmp_path)
    snap = await prober.snapshot(force=True)
    assert "entity_care" in snap
    care = snap["entity_care"]
    assert "summary" in care
    assert "care_obligations" in care and isinstance(care["care_obligations"], list)
    assert care["care_obligations"]  # non-empty static checklist
    # diverged is a tri-state: True / False / None (could-not-assess).
    assert care["diverged"] in (True, False, None)


@pytest.mark.asyncio
async def test_diagnostics_page_renders_entity_care_panel_readonly(tmp_path):
    """The diagnostics page shows the read-only entity-care panel and contains
    NO decommission/delete control anywhere in the UI."""
    prober = _supervisor_prober(tmp_path)
    client, app = await _make_client(health_prober=prober)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/diagnostics/", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        text = r.text
        assert 'id="entity-care"' in text
        assert "care obligation" in text.lower()
        # No destructive control: no decommission/delete button or form/endpoint.
        low = text.lower()
        assert "decommission</button>" not in low
        assert "/diagnostics/decommission" not in low
        assert "delete entity" not in low
        assert "/decommission" not in low


@pytest.mark.asyncio
async def test_diagnostics_rail_hides_console_link_when_conversation_off():
    client, app = await _make_client(config=DashboardConfig(conversation_enabled=False))
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/",
                headers={"Authorization": "Bearer test-token"},
            )
            assert r.status_code == 200
            assert ">Console</a>" not in r.text
            assert 'class="rail__brand" href="/diagnostics/"' in r.text


@pytest.mark.asyncio
async def test_diagnostics_rail_shows_console_link_when_conversation_on():
    client, app = await _make_client()
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get(
                "/diagnostics/",
                headers={"Authorization": "Bearer test-token"},
            )
            assert r.status_code == 200
            assert ">Console</a>" in r.text
            assert 'class="rail__brand" href="/"' in r.text


@pytest.mark.asyncio
async def test_caretaker_ack_requires_auth_in_the_real_app(tmp_path, monkeypatch):
    """The acknowledge action is mounted on the real app behind the operator
    session: without a token it is refused and no acknowledgement is written."""
    from kaine.cycle import caretaker_state

    monkeypatch.setattr(caretaker_state, "START_PATH", tmp_path / "start.json")
    monkeypatch.setattr(caretaker_state, "ACK_PATH", tmp_path / "ack.json")
    caretaker_state.write_start(
        caretaker_state.CaretakerStart(start_id="a" * 32, started_at="2026-01-01T00:00:00+00:00")
    )
    client, app = await _make_client()
    async with client:
        denied = await client.post("/diagnostics/caretaker/ack", json={"start_id": "a" * 32})
        allowed = await client.post(
            "/diagnostics/caretaker/ack",
            json={"start_id": "a" * 32},
            headers={"Authorization": "Bearer test-token"},
        )
    assert denied.status_code in (401, 403)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["pending"] is False
