# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the portability-tiers change (openspec: runtime-backends,
deployment-tiers, host-probe).

None of these boot a real entity, need a GPU/specific hardware, or download
weights: the edge backends are exercised through the lazy-import failure path
(the dependency is absent in the test env, which is exactly the degrade-not-crash
contract), and the tier probe is driven with injected host facts.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kaine import hardware
from kaine.backend_state import (
    backend_failures,
    clear_backend_failures,
)
from kaine.config import (
    PROFILES_DIR,
    ProfileError,
    load_kaine_config,
    resolve_profile_name,
)
from kaine.modules.backends import (
    BackendRegistry,
    UnknownBackendError,
    resolve_backend,
)

REPO_ROOT = Path(__file__).parent.parent
PROFILE_NAMES = ["tier0", "tier1", "tier2", "tier3"]


@pytest.fixture(autouse=True)
def _clean_backend_registry():
    clear_backend_failures()
    yield
    clear_backend_failures()


# --------------------------------------------------------------------------
# 1. Backend-selection framework
# --------------------------------------------------------------------------


def test_default_backend_is_used_when_none_selected():
    reg: BackendRegistry[str] = BackendRegistry("demo", default="alpha")
    reg.register("alpha", lambda: "ALPHA")
    reg.register("beta", lambda: "BETA")
    assert reg.resolve(None) == "ALPHA"
    assert reg.resolve("") == "ALPHA"
    assert reg.resolve("beta") == "BETA"


def test_unselected_backend_factory_is_not_called():
    calls: list[str] = []

    reg: BackendRegistry[str] = BackendRegistry("demo", default="alpha")
    reg.register("alpha", lambda: (calls.append("alpha") or "A"))
    reg.register("beta", lambda: (calls.append("beta") or "B"))
    reg.resolve("alpha")
    # The 'beta' factory (its lazy import) is never run when 'alpha' is selected.
    assert calls == ["alpha"]


def test_failed_backend_falls_back_and_records_reason():
    def _boom() -> str:
        raise ImportError("no llama_cpp wheel here")

    reg: BackendRegistry[str] = BackendRegistry("lingua", default="ollama")
    reg.register("ollama", lambda: "HTTP")
    reg.register("llama_cpp", _boom, fallback="ollama")

    result = reg.resolve("llama_cpp")
    assert result == "HTTP"  # degraded to the declared fallback, did not raise
    failures = backend_failures()
    assert len(failures) == 1
    assert failures[0].module == "lingua"
    assert failures[0].backend == "llama_cpp"
    assert failures[0].fallback == "ollama"
    assert "llama_cpp" in failures[0].reason


def test_failed_backend_without_fallback_disables_and_records():
    def _boom() -> str:
        raise RuntimeError("load failed")

    reg: BackendRegistry[str] = BackendRegistry("topos", default="onnx")
    reg.register("onnx", _boom)  # no fallback declared
    assert reg.resolve("onnx") is None  # module disables itself, no raise
    failures = backend_failures()
    assert len(failures) == 1
    assert failures[0].module == "topos"
    assert failures[0].fallback is None


def test_unknown_backend_name_raises():
    reg: BackendRegistry[str] = BackendRegistry("demo", default="alpha")
    reg.register("alpha", lambda: "A")
    with pytest.raises(UnknownBackendError):
        reg.resolve("does-not-exist")


def test_cyclic_fallback_is_broken_not_infinite():
    reg: BackendRegistry[str] = BackendRegistry("demo", default="a")
    reg.register("a", lambda: (_ for _ in ()).throw(ImportError("a")), fallback="b")
    reg.register("b", lambda: (_ for _ in ()).throw(ImportError("b")), fallback="a")
    assert resolve_backend(reg, "a") is None  # terminates, does not loop


# --------------------------------------------------------------------------
# 5. Host probe → recommended tier (recommends only; never applies)
# --------------------------------------------------------------------------


def test_probe_recommends_tier0_when_torch_absent():
    rec = hardware.recommend_tier(
        torch_ok=False, ram_gb=8.0, arch="aarch64", gpu_count=0
    )
    assert rec.tier == 0
    assert rec.profile == "tier0"
    assert "torch" in rec.reason.lower()


def test_probe_recommends_tier0_when_ram_below_floor():
    rec = hardware.recommend_tier(
        torch_ok=True, ram_gb=0.5, arch="aarch64", gpu_count=0
    )
    assert rec.tier == 0


def test_probe_recommends_tier0_on_arm32():
    rec = hardware.recommend_tier(
        torch_ok=True, ram_gb=8.0, arch="armv7l", gpu_count=0
    )
    assert rec.tier == 0


def test_probe_recommends_tier1_cpu_agent():
    rec = hardware.recommend_tier(
        torch_ok=True, ram_gb=8.0, arch="aarch64", gpu_count=0, accelerator="cpu"
    )
    assert rec.tier == 1


def test_probe_recommends_tier2_single_gpu():
    rec = hardware.recommend_tier(
        torch_ok=True, ram_gb=32.0, arch="x86_64", gpu_count=1, accelerator="cuda"
    )
    assert rec.tier == 2


def test_probe_recommends_tier3_multi_gpu():
    rec = hardware.recommend_tier(
        torch_ok=True, ram_gb=128.0, arch="x86_64", gpu_count=2, accelerator="cuda"
    )
    assert rec.tier == 3


def test_recommendation_carries_capability_matrix_row():
    rec = hardware.recommend_tier(
        torch_ok=False, ram_gb=0.5, arch="armv6l", gpu_count=0
    )
    caps = rec.capabilities
    # Tier 0 names both what it provides and what it lacks.
    assert caps["present"]
    assert "≥2B LLM" in caps["absent"]
    d = rec.as_dict()
    assert d["tier"] == 0 and d["profile"] == "tier0" and "capabilities" in d


def test_probe_script_recommends_only_does_not_apply():
    """The CLI prints a recommendation; it never mutates config or boots."""
    import runpy
    import sys

    argv = sys.argv
    sys.argv = ["probe-host", "--json"]
    try:
        ns = runpy.run_path(str(REPO_ROOT / "scripts" / "probe-host"), run_name="_probe")
    finally:
        sys.argv = argv
    # Running it exposes recommend_tier and does not raise / boot anything.
    assert callable(ns["main"])


# --------------------------------------------------------------------------
# 4. Tier profiles: layered load + safety invariants
# --------------------------------------------------------------------------


def test_all_profiles_exist_and_parse():
    for name in PROFILE_NAMES:
        path = REPO_ROOT / PROFILES_DIR / f"{name}.toml"
        assert path.exists(), f"missing profile {path}"
        tomllib.loads(path.read_text())  # parses


def test_resolve_profile_name_prefers_explicit_then_env():
    assert resolve_profile_name("tier1", env={}) == "tier1"
    assert resolve_profile_name(None, env={"KAINE_PROFILE": "tier2"}) == "tier2"
    assert resolve_profile_name(None, env={}) is None


def test_resolve_profile_name_rejects_traversal():
    with pytest.raises(ProfileError):
        resolve_profile_name("../secrets", env={})
    with pytest.raises(ProfileError):
        resolve_profile_name("tier0/../../etc", env={})


def test_profile_layers_between_shipped_and_operator(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text('[lingua]\nbackend = "ollama"\nmodel_id = "x"\n')
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "tier1.toml").write_text('[lingua]\nbackend = "llama_cpp"\n')
    op = tmp_path / "kaine.operator.toml"
    op.write_text('[lingua]\nmodel_id = "operator-choice"\n')

    cfg = load_kaine_config(
        shipped, op, profile="tier1", profiles_dir=profiles
    )
    # Profile overrides the shipped default...
    assert cfg["lingua"]["backend"] == "llama_cpp"
    # ...but the operator's local value still wins, and shipped siblings survive.
    assert cfg["lingua"]["model_id"] == "operator-choice"


def test_no_profile_is_behaviour_identical(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text('[lingua]\nbackend = "ollama"\n')
    op = tmp_path / "kaine.operator.toml"  # absent
    with_none = load_kaine_config(shipped, op, profile=None)
    assert with_none == {"lingua": {"backend": "ollama"}}


def test_missing_selected_profile_raises_not_silent(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[modules]\nsoma = false\n")
    op = tmp_path / "kaine.operator.toml"
    with pytest.raises(ProfileError):
        load_kaine_config(shipped, op, profile="tier9", profiles_dir=tmp_path)


def test_shipped_profiles_are_inert_no_module_enabled():
    """Safety invariant: a shipped profile never turns a module on."""
    for name in PROFILE_NAMES:
        path = REPO_ROOT / PROFILES_DIR / f"{name}.toml"
        parsed = tomllib.loads(path.read_text())
        modules = parsed.get("modules", {})
        enabled = sorted(k for k, on in modules.items() if on)
        assert enabled == [], f"{name} enables modules {enabled} (must be inert)"


def test_shipped_profiles_are_voice_free():
    """Safety invariant: a shipped profile embeds no private predefined voice."""
    for name in PROFILE_NAMES:
        raw = (REPO_ROOT / PROFILES_DIR / f"{name}.toml").read_text()
        assert "predefined_voice_id" not in raw, f"{name} embeds a voice id"
        parsed = tomllib.loads(raw)
        vox = parsed.get("vox", {})
        assert "predefined_voice_id" not in vox


# --------------------------------------------------------------------------
# 3.5 Vocal emotion disables cleanly below Tier 2
# --------------------------------------------------------------------------


async def test_null_emotion_classifier_is_disabled_but_transcribes():
    from kaine.modules.audition.emotion import NullEmotionClassifier

    clf = NullEmotionClassifier()
    assert clf.model_id == ""
    result = await clf.classify(b"\x00\x00", sample_rate=16000)
    assert result.category == "neutral"
    assert result.confidence == 0.0
    assert result.model == "disabled"
    assert result.raw.get("disabled") is True
    await clf.shutdown()


# --------------------------------------------------------------------------
# 2.3 Mnemos sqlite-vec backend selection (behind the storage interface)
# --------------------------------------------------------------------------


def test_mnemos_sqlite_vec_backend_constructs_storage():
    from kaine.modules.mnemos.storage import SqliteVecStorage

    store = SqliteVecStorage(latent_dim=8)
    assert store.latent_dim == 8


def test_mnemos_backend_selects_sqlite_vec_without_qdrant_key():
    """backend='sqlite_vec' needs no Qdrant api_key (in-process, no server)."""
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.mnemos.module import Mnemos
    from kaine.modules.mnemos.storage import SqliteVecStorage

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    m = Mnemos(bus, backend="sqlite_vec")
    assert isinstance(m.core.storage, SqliteVecStorage)


# --------------------------------------------------------------------------
# 2.1 / 1.3 Lingua backend seam (behind the ChatClient interface)
# --------------------------------------------------------------------------


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def test_lingua_default_backend_builds_http_client_unchanged():
    """No backend key → Lingua constructs its own OpenAIChatClient, as today."""
    from kaine.boot import make_lingua
    from kaine.modules.lingua.client import OpenAIChatClient

    lingua = make_lingua(_bus(), {"chat_url": "http://127.0.0.1:11434/v1"})
    assert isinstance(lingua.chat_client, OpenAIChatClient)
    # No backend was selected, so nothing was recorded as failed.
    assert backend_failures() == []


def test_lingua_llama_cpp_backend_degrades_to_http_when_dep_absent():
    """backend='llama_cpp' with no llama-cpp-python wheel degrades to the HTTP
    client (its declared fallback) and surfaces the reason — never crashes boot."""
    from kaine.boot import make_lingua

    lingua = make_lingua(
        _bus(),
        {"chat_url": "http://127.0.0.1:11434/v1", "backend": "llama_cpp"},
    )
    # The organ still exists and can speak over HTTP.
    assert lingua.chat_client is not None
    failures = backend_failures()
    assert any(f.module == "lingua" and f.backend == "llama_cpp" for f in failures)


# --------------------------------------------------------------------------
# 1.4 Backend-load failures surface on the Nexus health surface
# --------------------------------------------------------------------------


def test_backend_failures_surface_on_health_snapshot():
    from kaine.backend_state import record_backend_failure
    from kaine.nexus.health.prober import HealthProber

    record_backend_failure("lingua", "llama_cpp", "no wheel", fallback="ollama")
    block = HealthProber._backends_block(object.__new__(HealthProber))
    assert block["ok"] is False
    assert block["failures"][0]["module"] == "lingua"
    assert block["failures"][0]["fallback"] == "ollama"
