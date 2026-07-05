# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verify `python -m kaine.cycle` refuses to boot without the operator
safety gate, and that the cycle config loader merges the Qdrant secret."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from kaine.cycle.__main__ import _load_kaine_config

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIPPED_CONFIG = _REPO_ROOT / "config" / "kaine.toml"


def _hermetic_cwd(tmp_path: Path) -> Path:
    """A throwaway cwd holding ONLY the shipped (all-off, net-off) config.

    The refusal tests boot `python -m kaine.cycle` as a subprocess, and the
    config loader reads ``config/kaine.toml`` + ``config/kaine.operator.toml``
    relative to CWD. Running in the repo root would deep-merge whatever LOCAL
    operator override a developer/operator has — which can enable the safety
    net and therefore make these tests BOOT A REAL ENTITY instead of refusing.
    A test must never be able to birth an entity, so we run in a temp dir with
    only the shipped config and no operator override.
    """
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SHIPPED_CONFIG, cfg_dir / "kaine.toml")
    return tmp_path


def test_main_refuses_without_operator_present(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "KAINE_CYCLE_OPERATOR_PRESENT"}
    # Also force this venv's Python so we get the right kaine module.
    py = sys.executable
    result = subprocess.run(
        [py, "-m", "kaine.cycle"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(_hermetic_cwd(tmp_path)),
        timeout=15,
    )
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr={result.stderr!r}"
    )
    assert "operator must be present" in result.stderr.lower()


def test_main_refuses_research_boot_without_safety_net(tmp_path):
    """Research mode (KAINE_RESEARCH_MODE=1) with the shipped (disabled) safety
    net refuses to start with the distinct research-gate exit code 5 — the boot
    is EITHER operator-present OR research-safety-net-verified, never neither.

    Runs in a hermetic cwd (shipped config only) so a local operator override
    can never flip the net on and turn this refusal test into an entity boot."""
    from kaine.cycle.research_gate import RESEARCH_GATE_EXIT_CODE

    env = {k: v for k, v in os.environ.items() if k != "KAINE_CYCLE_OPERATOR_PRESENT"}
    env["KAINE_RESEARCH_MODE"] = "1"
    py = sys.executable
    result = subprocess.run(
        [py, "-m", "kaine.cycle"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(_hermetic_cwd(tmp_path)),
        timeout=30,
    )
    assert result.returncode == RESEARCH_GATE_EXIT_CODE, (
        f"expected exit {RESEARCH_GATE_EXIT_CODE}, got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )
    assert "safety net is" in result.stderr.lower()
    # No traceback leaked to the operator.
    assert "Traceback" not in result.stderr


def test_research_gate_evaluated_once_and_threaded_to_boot(monkeypatch):
    """The research-mode gate is evaluated EXACTLY ONCE — in main(), before the
    event loop — and its result is threaded into _boot_and_run, never recomputed
    inside the running loop (where the self-check's asyncio.run() would nest).
    """
    import kaine.cycle.__main__ as m
    from kaine.cycle.research_gate import evaluate_research_gate

    calls = {"eval": 0}
    ok_result = evaluate_research_gate(
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=True,
        self_check_passed=True,
        encryption_satisfied=True,
    )

    def _counting_eval(config):
        calls["eval"] += 1
        return ok_result

    captured: dict[str, object] = {}

    async def _fake_boot(*, supervision_mode="operator", gate_checks=None):
        captured["supervision_mode"] = supervision_mode
        captured["gate_checks"] = gate_checks
        return 0

    # research mode ON via config; no real boot, no real gate compute.
    monkeypatch.setattr(m, "_load_kaine_config", lambda: {"research": {"enabled": True}})
    monkeypatch.setattr(m, "_evaluate_research_safety_net", _counting_eval)
    monkeypatch.setattr(m, "_boot_and_run", _fake_boot)

    rc = m.main([])

    assert rc == 0
    assert calls["eval"] == 1, "gate must be evaluated exactly once (in main)"
    assert captured["supervision_mode"] == "research"
    # The safety-net checks are threaded through for runtime.json (Nexus),
    # not recomputed inside the loop.
    assert captured["gate_checks"] == {
        "preservation_enabled": True,
        "welfare_response_wired": True,
        "logging_active": True,
        "dry_self_check_passed": True,
        "encryption_satisfied": True,
    }


_KAINE_TOML_QDRANT = """\
[mnemos]
backend = "qdrant"

[mnemos.qdrant]
host = "127.0.0.1"
port = 6533

[empatheia]
backend = "qdrant"

[empatheia.qdrant]
host = "127.0.0.1"
port = 6533
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_qdrant_key_from_secrets_file_is_merged(tmp_path: Path):
    kaine = _write(tmp_path / "kaine.toml", _KAINE_TOML_QDRANT)
    secrets = _write(tmp_path / "secrets.toml", '[qdrant]\napi_key = "from-secrets"\n')
    cfg = _load_kaine_config(path=kaine, secrets_path=secrets, env={})
    # Both qdrant-backed consumers receive the shared key.
    assert cfg["mnemos"]["qdrant"]["api_key"] == "from-secrets"
    assert cfg["empatheia"]["qdrant"]["api_key"] == "from-secrets"


def test_qdrant_env_overrides_secrets_file(tmp_path: Path):
    kaine = _write(tmp_path / "kaine.toml", _KAINE_TOML_QDRANT)
    secrets = _write(tmp_path / "secrets.toml", '[qdrant]\napi_key = "from-secrets"\n')
    cfg = _load_kaine_config(
        path=kaine, secrets_path=secrets, env={"KAINE_QDRANT_API_KEY": "from-env"}
    )
    assert cfg["mnemos"]["qdrant"]["api_key"] == "from-env"
    assert cfg["empatheia"]["qdrant"]["api_key"] == "from-env"


def test_qdrant_key_from_env_when_secrets_file_missing(tmp_path: Path):
    kaine = _write(tmp_path / "kaine.toml", _KAINE_TOML_QDRANT)
    missing = tmp_path / "absent.toml"
    cfg = _load_kaine_config(
        path=kaine, secrets_path=missing, env={"KAINE_QDRANT_API_KEY": "env-only"}
    )
    assert cfg["mnemos"]["qdrant"]["api_key"] == "env-only"
    assert cfg["empatheia"]["qdrant"]["api_key"] == "env-only"


def test_qdrant_key_absent_everywhere_injects_nothing(tmp_path: Path):
    kaine = _write(tmp_path / "kaine.toml", _KAINE_TOML_QDRANT)
    secrets = _write(tmp_path / "secrets.toml", "[redis]\npassword = \"x\"\n")
    cfg = _load_kaine_config(path=kaine, secrets_path=secrets, env={})
    # No empty key injected -> each module surfaces its own explicit error
    # (covered by tests/test_mnemos_module.py / test_empatheia_module.py).
    assert "api_key" not in cfg["mnemos"]["qdrant"]
    assert "api_key" not in cfg["empatheia"]["qdrant"]


def test_existing_kaine_toml_qdrant_key_left_intact(tmp_path: Path):
    # Mnemos has an explicit key; Empatheia does not. The explicit key wins for
    # Mnemos, while Empatheia still receives the resolved key.
    toml = _KAINE_TOML_QDRANT.replace(
        '[mnemos.qdrant]\nhost = "127.0.0.1"\nport = 6533\n',
        '[mnemos.qdrant]\nhost = "127.0.0.1"\nport = 6533\napi_key = "in-file"\n',
    )
    kaine = _write(tmp_path / "kaine.toml", toml)
    secrets = _write(tmp_path / "secrets.toml", '[qdrant]\napi_key = "from-secrets"\n')
    cfg = _load_kaine_config(
        path=kaine, secrets_path=secrets, env={"KAINE_QDRANT_API_KEY": "from-env"}
    )
    assert cfg["mnemos"]["qdrant"]["api_key"] == "in-file"
    assert cfg["empatheia"]["qdrant"]["api_key"] == "from-env"


def test_empatheia_only_qdrant_consumer_still_gets_key(tmp_path: Path):
    # Empatheia enabled without Mnemos: the merge must still reach it.
    kaine = _write(
        tmp_path / "kaine.toml",
        '[empatheia]\nbackend = "qdrant"\n\n[empatheia.qdrant]\nhost = "127.0.0.1"\nport = 6533\n',
    )
    secrets = _write(tmp_path / "secrets.toml", '[qdrant]\napi_key = "from-secrets"\n')
    cfg = _load_kaine_config(path=kaine, secrets_path=secrets, env={})
    assert cfg["empatheia"]["qdrant"]["api_key"] == "from-secrets"


class _FakeRegistry:
    def __init__(self, mods):
        self._m = dict(mods)

    def __contains__(self, k):
        return k in self._m

    def get(self, k):
        return self._m[k]


class _FakeMnemos:
    async def recall(self, *a, **k):
        return []


def test_eval_provider_factories_none_without_mnemos():
    from kaine.cycle.__main__ import (
        _cognitive_query_client_factory,
        _memory_source_factory,
    )
    from kaine.evaluation.config import EvaluationConfig

    reg = _FakeRegistry({})
    assert _memory_source_factory(reg) is None
    assert _cognitive_query_client_factory(reg, EvaluationConfig()) is None


def test_eval_provider_factories_present_with_mnemos():
    from kaine.cycle.__main__ import (
        _cognitive_query_client_factory,
        _memory_source_factory,
    )
    from kaine.evaluation.config import EvaluationConfig

    reg = _FakeRegistry({"mnemos": _FakeMnemos()})
    ms = _memory_source_factory(reg)
    cq = _cognitive_query_client_factory(reg, EvaluationConfig())
    assert hasattr(ms, "sample_old_memory")
    assert hasattr(cq, "query")
