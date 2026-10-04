# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the real-organ individuation smoke harness."""

import asyncio
import importlib.util
from pathlib import Path

import numpy as np


def _load_smoke():
    repo = Path(__file__).resolve().parents[1]
    path = (
        repo
        / "openspec"
        / "changes"
        / "individuation-rebuild"
        / "validation"
        / "smoke.py"
    )
    spec = importlib.util.spec_from_file_location("smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pairwise_stats_identical():
    mod = _load_smoke()
    v = np.ones((5, 8), dtype=float)
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    stats = mod.pairwise_stats(v)
    assert stats["near_identical_share"] == 1.0
    assert stats["mean_pairwise_distance"] == 0.0


def test_null_splits_on_same_distribution():
    mod = _load_smoke()
    rng = np.random.default_rng(42)
    dim = 16
    pools = []
    for _ in range(12):
        x = rng.normal(size=(40, dim))
        x = x / np.linalg.norm(x, axis=1, keepdims=True)
        pools.append(x)

    result = mod.null_splits(
        pools, n_ref=16, n_cur=8, splits=200, rng=rng
    )
    assert 0.0 <= result["rate"] <= 0.12
    assert isinstance(result["effect_min_suggested"], float)
    assert np.isfinite(result["effect_min_suggested"])


def test_control_power_detects_shift():
    mod = _load_smoke()
    rng = np.random.default_rng(7)
    dim = 16
    base = []
    ctrl = []
    shift = np.zeros(dim)
    shift[0] = 3.0
    for _ in range(12):
        b = rng.normal(size=(40, dim))
        b = b / np.linalg.norm(b, axis=1, keepdims=True)
        c = b + shift
        c = c / np.linalg.norm(c, axis=1, keepdims=True)
        base.append(b)
        ctrl.append(c)

    power = mod.control_power(
        base, ctrl, n_ref=16, n_cur=8, iterations=50, alpha=0.05, rng=rng
    )
    assert power >= 0.9


def test_acceptance_logic():
    mod = _load_smoke()

    report_missing = {
        "answers": {"degenerate": False},
        "real_data_null": {"pass": True},
        "positive_lora": {
            "power_lora": "not run: no test LoRA supplied"
        },
    }
    ok, reasons = mod.acceptance(report_missing)
    assert not ok
    assert any("not run" in r for r in reasons)

    report_pass = {
        "answers": {"degenerate": False},
        "real_data_null": {"pass": True},
        "positive_lora": {"power_lora": 0.85},
    }
    ok, reasons = mod.acceptance(report_pass)
    assert ok
    assert reasons == []


def test_collect_with_fake_sampler():
    mod = _load_smoke()

    class FakeSample:
        def __init__(self, text: str) -> None:
            self.text = text

    async def fake_sampler(prompt: str, seed: int) -> FakeSample:
        return FakeSample(f"answer for {prompt} with seed {seed}")

    class FakeEmbedder:
        async def embed(self, text: str) -> np.ndarray:
            v = np.random.randn(8)
            return v / np.linalg.norm(v)

    battery = [f"prompt {i}" for i in range(12)]
    samples = 8
    pools, stats = asyncio.run(
        mod.collect(fake_sampler, FakeEmbedder(), battery, samples)
    )

    assert len(pools) == 12
    for pool in pools:
        assert pool.shape == (samples, 8)

    latency = stats["latency_seconds"]
    assert "p50" in latency
    assert "p95" in latency
    assert "max" in latency

    # No answer text must leak into the returned statistics.
    assert "text" not in str(stats)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.raw = {}
        self.from_content = True
        self.lora_applied = False
        self.finish_reason = "stop"
        self.completion_tokens = 3


class _FakeClient:
    def __init__(self) -> None:
        self.resolver = None

    async def complete(self, req):
        return _FakeResponse(f"{req.prompt}|{req.seed}")

    def set_lora_resolver(self, resolver) -> None:
        self.resolver = resolver

    async def aclose(self) -> None:
        return None


class _FakeLingua:
    def __init__(self) -> None:
        self.chat_client = _FakeClient()
        self.facts: list[str] = []
        self.expects = True
        self._bus_self_model = None

    def set_expects_self_model(self, expected: bool) -> None:
        self.expects = expected

    async def add_situation_fact(self, text: str) -> bool:
        self.facts.append(text)
        return True

    def probe_self_model(self):
        base = dict(self._bus_self_model or {"values": [], "behavioral_norms": []})
        base["situation_facts"] = list(base.get("situation_facts") or []) + self.facts
        return base

    def probe_request(self, about, *, seed, max_tokens, self_model):
        from types import SimpleNamespace

        persona = "terse" if self_model.get("values") else "plain"
        return SimpleNamespace(prompt=f"{persona}:{about}", seed=seed)


class _FakeEmbedder:
    kind = "numpy_minilm"
    model_id = "fake"

    async def load(self) -> None:
        return None

    async def embed(self, text: str):
        import hashlib

        persona, rest = text.split(":", 1)
        prompt, seed = rest.rsplit("|", 1)
        centre = np.random.default_rng(
            int(hashlib.sha256((persona + prompt).encode()).hexdigest()[:8], 16)
        ).normal(0.0, 1.0, 16)
        noise = np.random.default_rng(int(seed)).normal(0.0, 0.05, 16)
        return (centre + noise).tolist()


def test_main_async_runs_end_to_end_with_a_fake_organ(tmp_path, monkeypatch):
    import argparse
    import json as _json

    smoke = _load_smoke()
    monkeypatch.setattr("kaine.boot.make_lingua", lambda bus, section: _FakeLingua())
    monkeypatch.setattr(
        "kaine.text_embedding.make_text_embedder", lambda cfg: _FakeEmbedder()
    )
    monkeypatch.setattr("kaine.config.load_kaine_config", lambda *a, **k: {})
    args = argparse.Namespace(
        config="unused.toml",
        operator_config=None,
        samples=24,
        splits=5,
        controls=3,
        control_lora=None,
        out=str(tmp_path / "runs"),
        seed=1,
        cost_permutations=50,
    )
    code = asyncio.run(smoke.main_async(args))
    reports = list((tmp_path / "runs").glob("smoke-*.json"))
    assert len(reports) == 1
    report = _json.loads(reports[0].read_text())
    # Not accepted without a test LoRA, so the exit code is 1.
    assert code == 1
    assert report["positive_lora"]["pass"] is False
    assert report["positive_identity"]["power_identity"] >= 0.0
    # No answer text anywhere in the report.
    assert "plain:" not in reports[0].read_text()
    assert "terse:" not in reports[0].read_text()
