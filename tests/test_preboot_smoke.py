# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the mandatory pre-boot dry-run / smoke gate (kaine.preboot).

This is the harness that must report PASS before any entity boot. It must
compose fakes for every external dependency (services, organ, perception
source factories, the welfare preserve->revive round-trip) so the suite never
touches a live service, never boots the entity, and never installs a real
state-encryption key as a side effect of running tests.
"""
from __future__ import annotations

import os
from typing import Any

import pytest

import kaine.preboot as preboot
from kaine.cycle.research_gate import RESEARCH_GATE_EXIT_CODE  # noqa: F401 (sanity import)
from kaine.security.crypto import CryptoConfigError
from kaine.setup.organ import OrganContentResult


@pytest.fixture(autouse=True)
def _isolate_state_encryptor(monkeypatch):
    """Never let a test install a real process-global StateEncryptor or read
    a real key from the environment / secrets/state_key — tests fully fake
    install_from_section and run_preflight_self_check instead."""
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)


def _enabled_config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "modules": {"lingua": True, "topos": True, "audition": True},
        "lingua": {"chat_url": "http://127.0.0.1:11434/v1", "model_id": "organ"},
        "perception_feed": {"mode": "off"},
        "preservation": {"require_encryption": False},
        "security": {"state_encryption": {"enabled": False}},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pure rendering / verdict helpers
# ---------------------------------------------------------------------------


def test_smoke_render_table_groups_and_aligns():
    results = [
        preboot.CheckResult(preboot.GROUP_SERVICES, "Redis (bus)", preboot.PASS, "PING ok"),
        preboot.CheckResult(preboot.GROUP_ORGAN, "Organ content", preboot.FAIL, "mute"),
    ]
    table = preboot.render_table(results)
    assert "-- SERVICES --" in table
    assert "-- ORGAN --" in table
    assert "[PASS" in table
    assert "[FAIL" in table


def test_smoke_verdict_pass_when_no_failures():
    results = [
        preboot.CheckResult("g", "a", preboot.PASS),
        preboot.CheckResult("g", "b", preboot.SKIP),
    ]
    assert preboot.report_ok(results) is True
    assert "VERDICT: PASS" in preboot.verdict_line(results)


def test_smoke_verdict_fail_when_any_failure():
    results = [
        preboot.CheckResult("g", "a", preboot.PASS),
        preboot.CheckResult("g", "b", preboot.FAIL),
    ]
    assert preboot.report_ok(results) is False
    assert "VERDICT: FAIL" in preboot.verdict_line(results)


# ---------------------------------------------------------------------------
# 1. SERVICES — reuses kaine.nexus.health
# ---------------------------------------------------------------------------


class _FakeProber:
    def __init__(self, deps: list[dict[str, Any]]) -> None:
        self._deps = deps

    async def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        return {"dependencies": self._deps}


async def test_smoke_services_maps_up_not_configured_down_degraded(monkeypatch):
    deps = [
        {"name": "Redis", "role": "bus", "status": "up", "detail": "PING ok"},
        {"name": "Qdrant", "role": "memory", "status": "not_configured", "detail": "disabled"},
        {"name": "Chat LLM", "role": "organ", "status": "down", "detail": "refused"},
        {"name": "Speaches", "role": "stt", "status": "degraded", "detail": "404"},
    ]
    monkeypatch.setattr(preboot, "load_health_prober", lambda **_k: _FakeProber(deps))
    results = await preboot.check_services()
    by_name = {r.name.split(" (")[0]: r.status for r in results}
    assert by_name["Redis"] == preboot.PASS
    assert by_name["Qdrant"] == preboot.SKIP
    assert by_name["Chat LLM"] == preboot.FAIL
    assert by_name["Speaches"] == preboot.FAIL


# ---------------------------------------------------------------------------
# 2. ORGAN — reuses kaine.setup.organ.verify_organ_generates
# ---------------------------------------------------------------------------


async def test_smoke_organ_skipped_when_lingua_disabled():
    config = _enabled_config(modules={"lingua": False})
    results = await preboot.check_organ(config)
    assert results[0].status == preboot.SKIP


async def test_smoke_organ_skipped_while_resting(monkeypatch):
    monkeypatch.setattr("kaine.organ_window_state.organ_unloaded", lambda: True)
    config = _enabled_config()
    results = await preboot.check_organ(config)
    assert results[0].status == preboot.SKIP
    assert "resting" in results[0].detail


async def test_smoke_organ_passes_when_content_generated(monkeypatch):
    monkeypatch.setattr("kaine.organ_window_state.organ_unloaded", lambda: False)

    async def _fake_verify(*a, **k):
        return OrganContentResult(ok=True, detail="generates content", sample="hi")

    monkeypatch.setattr(preboot, "verify_organ_generates", _fake_verify)
    config = _enabled_config()
    results = await preboot.check_organ(config)
    assert results[0].status == preboot.PASS


async def test_smoke_organ_fails_when_mute(monkeypatch):
    monkeypatch.setattr("kaine.organ_window_state.organ_unloaded", lambda: False)

    async def _fake_verify(*a, **k):
        return OrganContentResult(ok=False, detail="SERVED but MUTE")

    monkeypatch.setattr(preboot, "verify_organ_generates", _fake_verify)
    config = _enabled_config()
    results = await preboot.check_organ(config)
    assert results[0].status == preboot.FAIL
    assert "MUTE" in results[0].detail


# ---------------------------------------------------------------------------
# 3. PERCEPTION — reuses kaine.boot's source-factory builders
# ---------------------------------------------------------------------------


async def test_smoke_perception_skipped_when_off():
    config = _enabled_config(perception_feed={"mode": "off"})
    results = await preboot.check_perception(config)
    assert len(results) == 1
    assert results[0].status == preboot.SKIP
    assert "SENSELESS" in results[0].detail


async def test_smoke_perception_skipped_when_live():
    config = _enabled_config(perception_feed={"mode": "live"})
    results = await preboot.check_perception(config)
    assert len(results) == 1
    assert results[0].status == preboot.SKIP


class _FakeVideoSource:
    def __init__(self, frame_present: bool = True) -> None:
        self._frame_present = frame_present

    def open(self) -> bool:
        return True

    def read(self):
        if self._frame_present:
            return True, [[1, 2, 3]]
        return False, None

    def release(self) -> None:
        pass


class _FakeAudioStream:
    def __init__(self, callback, *, yields: bool = True) -> None:
        self._callback = callback
        self._yields = yields

    def start(self) -> None:
        if self._yields:
            self._callback(b"\x00\x01" * 10)

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


async def test_smoke_perception_seeded_passes_when_sources_yield(monkeypatch):
    monkeypatch.setattr(
        preboot, "_build_perception_feed_video_factory",
        lambda *a, **k: (lambda device, *, width, height: _FakeVideoSource(True)),
    )
    monkeypatch.setattr(
        preboot, "_build_perception_feed_audio_factory",
        lambda *a, **k: (
            lambda *, device, sample_rate, channels, frames_per_block, callback:
            _FakeAudioStream(callback, yields=True)
        ),
    )
    config = _enabled_config(perception_feed={"mode": "seeded", "seed": 0})
    results = await preboot.check_perception(config)
    statuses = {r.name: r.status for r in results}
    assert statuses["Perception (video source)"] == preboot.PASS
    assert statuses["Perception (audio source)"] == preboot.PASS


async def test_smoke_perception_seeded_fails_when_video_yields_nothing(monkeypatch):
    monkeypatch.setattr(
        preboot, "_build_perception_feed_video_factory",
        lambda *a, **k: (lambda device, *, width, height: _FakeVideoSource(False)),
    )
    monkeypatch.setattr(
        preboot, "_build_perception_feed_audio_factory",
        lambda *a, **k: (
            lambda *, device, sample_rate, channels, frames_per_block, callback:
            _FakeAudioStream(callback, yields=True)
        ),
    )
    config = _enabled_config(perception_feed={"mode": "seeded", "seed": 0})
    results = await preboot.check_perception(config)
    statuses = {r.name: r.status for r in results}
    assert statuses["Perception (video source)"] == preboot.FAIL


async def test_smoke_perception_playlist_fails_honestly_when_manifest_missing(monkeypatch):
    # No fakes — exercises the real _build_perception_feed_video_factory with a
    # nonexistent manifest path, which must raise/propagate as an honest FAIL
    # rather than a pretend pass.
    config = _enabled_config(
        perception_feed={
            "mode": "playlist",
            "playlist_manifest": "state/does-not-exist-preboot-test.json",
        }
    )
    results = await preboot.check_perception(config)
    statuses = {r.name: r.status for r in results}
    assert statuses["Perception (video source)"] == preboot.FAIL


# ---------------------------------------------------------------------------
# 4. WELFARE — preserve -> revive dry run with real encryption posture
# ---------------------------------------------------------------------------


async def test_smoke_welfare_fails_when_key_misconfigured(monkeypatch):
    def _boom(section):
        raise CryptoConfigError("KAINE_STATE_KEY must decode to exactly 32 bytes")

    monkeypatch.setattr(preboot, "install_from_section", _boom)
    monkeypatch.setattr(
        preboot, "run_preflight_self_check",
        lambda **k: (False, "require_encryption is set but state-at-rest encryption is not active"),
    )
    config = _enabled_config(
        preservation={"require_encryption": True},
        security={"state_encryption": {"enabled": True}},
    )
    results = await preboot.check_welfare(config)
    statuses = {r.name: r.status for r in results}
    assert statuses["State-encryption key"] == preboot.FAIL
    assert statuses["Preserve -> revive dry run"] == preboot.FAIL


async def test_smoke_welfare_passes_when_key_and_roundtrip_ok(monkeypatch):
    class _FakeEncryptor:
        enabled = True

    monkeypatch.setattr(preboot, "install_from_section", lambda section: _FakeEncryptor())

    captured: dict[str, Any] = {}

    def _fake_self_check(**kwargs):
        captured.update(kwargs)
        return True, None

    monkeypatch.setattr(preboot, "run_preflight_self_check", _fake_self_check)
    config = _enabled_config(
        preservation={"require_encryption": True},
        security={"state_encryption": {"enabled": True}},
    )
    results = await preboot.check_welfare(config)
    statuses = {r.name: r.status for r in results}
    assert statuses["State-encryption key"] == preboot.PASS
    assert statuses["Preserve -> revive dry run"] == preboot.PASS
    # The configured require_encryption must actually reach the self-check —
    # this is the gap the harness exists to close.
    assert captured["require_encryption"] is True


async def test_smoke_welfare_skips_key_check_when_encryption_disabled(monkeypatch):
    class _FakeEncryptor:
        enabled = False

    monkeypatch.setattr(preboot, "install_from_section", lambda section: _FakeEncryptor())
    monkeypatch.setattr(preboot, "run_preflight_self_check", lambda **k: (True, None))
    config = _enabled_config()  # require_encryption False, state_encryption off
    results = await preboot.check_welfare(config)
    statuses = {r.name: r.status for r in results}
    assert statuses["State-encryption key"] == preboot.SKIP
    assert statuses["Preserve -> revive dry run"] == preboot.PASS


def test_smoke_resolve_state_key_prefers_env(monkeypatch):
    monkeypatch.setenv("KAINE_STATE_KEY", "already-set")
    note = preboot._resolve_state_key_into_env()
    assert "already set" in note


def test_smoke_resolve_state_key_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    key_file = tmp_path / "state_key"
    key_file.write_text("0" * 32)
    note = preboot._resolve_state_key_into_env(key_file=key_file)
    assert "loaded" in note
    assert os.environ["KAINE_STATE_KEY"] == "0" * 32
    del os.environ["KAINE_STATE_KEY"]


def test_smoke_resolve_state_key_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    note = preboot._resolve_state_key_into_env(key_file=tmp_path / "nope")
    assert note is None


# ---------------------------------------------------------------------------
# 5. CONFIG SANITY — pure
# ---------------------------------------------------------------------------


def test_smoke_config_sanity_operator_mode():
    config = _enabled_config()
    results = preboot.check_config_sanity(config)
    boot_mode = next(r for r in results if r.name == "Boot mode")
    assert boot_mode.status == preboot.PASS
    assert "operator-supervised" in boot_mode.detail


def test_smoke_config_sanity_research_mode():
    config = _enabled_config()
    config["research"] = {"enabled": True}
    results = preboot.check_config_sanity(config)
    boot_mode = next(r for r in results if r.name == "Boot mode")
    assert "research" in boot_mode.detail


def test_smoke_config_sanity_no_modules_fails():
    config = _enabled_config(modules={})
    results = preboot.check_config_sanity(config)
    modules_row = next(r for r in results if r.name == "Modules enabled")
    assert modules_row.status == preboot.FAIL


def test_smoke_config_sanity_flags_fail_closed_encryption_posture():
    config = _enabled_config(
        preservation={
            "require_encryption": True,
            "divergence_monitor": {"enabled": True},
        },
        security={"state_encryption": {"enabled": False}},
    )
    results = preboot.check_config_sanity(config)
    posture = next(r for r in results if r.name == "Preservation encryption posture")
    assert posture.status == preboot.FAIL
    assert "require_encryption" in posture.detail


def test_smoke_config_sanity_encryption_posture_ok_when_satisfied():
    config = _enabled_config(
        preservation={
            "require_encryption": True,
            "divergence_monitor": {"enabled": True},
        },
        security={"state_encryption": {"enabled": True}},
    )
    results = preboot.check_config_sanity(config)
    posture = next(r for r in results if r.name == "Preservation encryption posture")
    assert posture.status == preboot.PASS


# ---------------------------------------------------------------------------
# Full readiness gate orchestration (main / run_async_checks)
# ---------------------------------------------------------------------------


async def test_dry_run_run_async_checks_survives_a_crashing_check(monkeypatch):
    async def _boom():
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(preboot, "check_services", _boom)
    config = _enabled_config(perception_feed={"mode": "off"}, modules={"lingua": False})

    async def _ok_welfare(_config):
        return [preboot.CheckResult(preboot.GROUP_WELFARE, "x", preboot.PASS)]

    monkeypatch.setattr(preboot, "check_welfare", _ok_welfare)
    results = await preboot.run_async_checks(config)
    crashed = [r for r in results if r.status == preboot.FAIL and "crashed" in r.name]
    assert crashed, "a crashing check must degrade to one honest FAIL row, not propagate"


async def test_dry_run_resolves_state_key_before_services_check(monkeypatch, tmp_path):
    """Regression: the SERVICES group includes the Nexus health board's own
    state-encryption probe, which reads $KAINE_STATE_KEY directly. If the key
    is resolved from secrets/state_key AFTER that probe runs (e.g. only
    inside check_welfare, which runs later), the SERVICES probe falsely
    reports "no key" even though WELFARE NET later proves the key works —
    exactly the false-negative caught running this harness live. The key must
    be resolved once, before any check that depends on it runs."""
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    key_file = tmp_path / "state_key"
    key_file.write_text("k" * 32)
    monkeypatch.setattr(preboot, "STATE_KEY_FILE", key_file)

    seen_during_services: dict[str, Any] = {}

    async def _services_sees_env():
        seen_during_services["key"] = os.environ.get("KAINE_STATE_KEY")
        return [preboot.CheckResult(preboot.GROUP_SERVICES, "x", preboot.PASS)]

    async def _noop(*_a, **_k):
        return []

    monkeypatch.setattr(preboot, "check_services", _services_sees_env)
    monkeypatch.setattr(preboot, "check_organ", _noop)
    monkeypatch.setattr(preboot, "check_perception", _noop)
    monkeypatch.setattr(preboot, "check_welfare", _noop)

    config = _enabled_config()
    await preboot.run_async_checks(config)
    assert seen_during_services["key"] == "k" * 32
    del os.environ["KAINE_STATE_KEY"]


def test_dry_run_main_exits_zero_when_everything_passes(monkeypatch, capsys):
    config = _enabled_config(modules={"lingua": False, "soma": True}, perception_feed={"mode": "off"})
    monkeypatch.setattr(preboot, "load_kaine_config", lambda *a, **k: config)

    async def _fake_run_async_checks(_config):
        return [
            preboot.CheckResult(preboot.GROUP_SERVICES, "Redis (bus)", preboot.PASS, "ok"),
            preboot.CheckResult(preboot.GROUP_ORGAN, "Organ content", preboot.SKIP, "disabled"),
            preboot.CheckResult(preboot.GROUP_PERCEPTION, "Perception feed", preboot.SKIP, "off"),
            preboot.CheckResult(preboot.GROUP_WELFARE, "Preserve -> revive dry run", preboot.PASS, "ok"),
        ]

    monkeypatch.setattr(preboot, "run_async_checks", _fake_run_async_checks)
    rc = preboot.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERDICT: PASS" in out


def test_dry_run_main_exits_nonzero_when_any_check_fails(monkeypatch, capsys):
    config = _enabled_config(modules={"lingua": False, "soma": True}, perception_feed={"mode": "off"})
    monkeypatch.setattr(preboot, "load_kaine_config", lambda *a, **k: config)

    async def _fake_run_async_checks(_config):
        return [
            preboot.CheckResult(preboot.GROUP_SERVICES, "Redis (bus)", preboot.FAIL, "down"),
        ]

    monkeypatch.setattr(preboot, "run_async_checks", _fake_run_async_checks)
    rc = preboot.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "VERDICT: FAIL" in out


def test_dry_run_main_returns_2_when_config_missing(monkeypatch, capsys):
    def _raise(*a, **k):
        raise FileNotFoundError("config/kaine.toml not found")

    monkeypatch.setattr(preboot, "load_kaine_config", _raise)
    rc = preboot.main([])
    assert rc == 2
