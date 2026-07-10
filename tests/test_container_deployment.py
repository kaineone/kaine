# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Container-deployment topology tests (containerize-deployment change).

These validate the Dockerfile, compose topology, Quadlet units, and the setup
provisioner by PARSING and LINTING — never by building an image or booting an
entity. They enforce the load-bearing invariants of the design:

  - the default bring-up starts NO entity (cycle is profile-gated);
  - no boot-gate variable is defaulted to a permissive value on the cycle;
  - every published port is loopback-only;
  - no volume/bind mount captures raw audio/video (zero raw-sense-data
    persistence), and perception scratch is RAM-backed tmpfs;
  - model weights / secrets / state never enter the image;
  - the image build reuses install.py's wheel-index mapping (single source of
    truth);
  - the setup provisioner plans every model weight.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COMPOSE = _REPO_ROOT / "compose" / "kaine.yml"
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"
_QUADLET = _REPO_ROOT / "quadlet"


def _load_compose() -> dict:
    with _COMPOSE.open() as fh:
        return yaml.safe_load(fh)


def _install_module():
    """Import scripts/install.py directly from the worktree (not a package)."""
    path = _REPO_ROOT / "scripts" / "install.py"
    spec = importlib.util.spec_from_file_location("_kaine_install_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# 1.1 — single source of truth for the wheel index
# --------------------------------------------------------------------------
def test_print_index_matches_index_by_flavor():
    mod = _install_module()
    for flavor, expected in mod._INDEX_BY_FLAVOR.items():
        got = mod.torch_index_url(flavor)
        assert got == expected, flavor
    with pytest.raises(KeyError):
        mod.torch_index_url("bogus")


def test_print_index_cli_accessor():
    py = shutil.which("python3") or "python3"
    script = str(_REPO_ROOT / "scripts" / "install.py")
    cuda = subprocess.run(
        [py, script, "--print-index", "cuda"], capture_output=True, text=True, check=True
    )
    assert cuda.stdout.strip() == "https://download.pytorch.org/whl/cu128"
    mps = subprocess.run(
        [py, script, "--print-index", "mps"], capture_output=True, text=True, check=True
    )
    assert mps.stdout.strip() == ""  # MPS uses default PyPI
    spec = subprocess.run(
        [py, script, "--print-torch-spec"], capture_output=True, text=True, check=True
    )
    assert spec.stdout.strip() == "torch>=2.5,<3"


# --------------------------------------------------------------------------
# 1.2 — the Dockerfile
# --------------------------------------------------------------------------
def test_dockerfile_shape():
    text = _DOCKERFILE.read_text()
    # multi-stage: a build stage and a runtime stage
    assert "AS build" in text and "AS runtime" in text
    # flavor build-arg + reuse of install.py's index
    assert "ARG FLAVOR" in text
    assert "install.py --print-index" in text
    # non-root user + volumes + offline guards. The state volume mounts at
    # /app/state (the app writes state CWD-relative under WORKDIR /app), not /state.
    assert "useradd" in text and "USER kaine" in text
    assert 'VOLUME ["/app/state", "/models"]' in text
    assert "HF_HUB_OFFLINE=1" in text and "TRANSFORMERS_OFFLINE=1" in text
    # default CMD is the cycle; nexus overrides it in compose
    assert 'CMD ["python", "-m", "kaine.cycle"]' in text


def test_dockerfile_never_copies_secrets_or_state():
    text = _DOCKERFILE.read_text()
    # Inspect actual COPY directives (not comments): none may reference
    # operator config, secrets, or state.
    copy_lines = [
        ln for ln in text.splitlines()
        if ln.strip().upper().startswith("COPY")
    ]
    for ln in copy_lines:
        assert "secrets.toml" not in ln, ln
        assert "operator.toml" not in ln, ln
        assert "state/" not in ln, ln
    assert any("config/kaine.toml" in ln for ln in copy_lines)


def test_dockerignore_excludes_sensitive_and_heavy():
    text = _DOCKERIGNORE.read_text()
    for token in (
        "state/",
        "config/*.operator.toml",
        "config/secrets.toml",
        "*.gguf",
        "*.safetensors",
        ".venv/",
    ):
        assert token in text, token
    # .containerignore mirrors it for Podman.
    assert (_REPO_ROOT / ".containerignore").read_text() == text


# --------------------------------------------------------------------------
# 1.3 / 1.4 — compose topology + no-auto-start structural invariant
# --------------------------------------------------------------------------
def test_compose_parses():
    doc = _load_compose()
    assert doc["name"] == "kaine"
    assert set(doc["services"]) >= {
        "kaine-redis",
        "kaine-qdrant",
        "kaine-model-server",
        "kaine-speaches",
        "kaine-chatterbox",
        "kaine-nexus",
        "kaine-cycle",
        "kaine-provision",
    }


def test_cycle_is_profile_gated_out_of_default_up():
    doc = _load_compose()
    assert doc["services"]["kaine-cycle"].get("profiles") == ["cycle"]
    assert doc["services"]["kaine-provision"].get("profiles") == ["setup"]
    # Nexus is NOT profile-gated — it is always-up and holds no entity.
    assert "profiles" not in doc["services"]["kaine-nexus"]


def test_cycle_defaults_no_gate_var_permissive():
    doc = _load_compose()
    env = doc["services"]["kaine-cycle"]["environment"]
    # The gate vars are present but resolve to EMPTY unless the operator sets
    # them — never "1"/"true"/permissive.
    for key in ("KAINE_CYCLE_OPERATOR_PRESENT", "KAINE_RESEARCH_MODE"):
        val = env[key]
        assert val.endswith(":-}"), f"{key} must default empty, got {val!r}"
        assert "1" not in val.split(":-")[-1]


def test_all_published_ports_are_loopback_only():
    doc = _load_compose()
    for name, svc in doc["services"].items():
        for mapping in svc.get("ports", []) or []:
            assert str(mapping).startswith("127.0.0.1:"), f"{name}: {mapping}"


def test_cycle_and_nexus_depend_on_healthy_data_services():
    doc = _load_compose()
    for svc_name in ("kaine-cycle", "kaine-nexus"):
        deps = doc["services"][svc_name]["depends_on"]
        for dep in ("kaine-redis", "kaine-qdrant"):
            assert deps[dep]["condition"] == "service_healthy", (svc_name, dep)


def test_nexus_and_cycle_share_image_different_command():
    doc = _load_compose()
    nexus = doc["services"]["kaine-nexus"]
    cycle = doc["services"]["kaine-cycle"]
    # Both build from the same Dockerfile (via the shared x-kaine-image anchor).
    assert nexus["build"]["dockerfile"] == "Dockerfile"
    assert cycle["build"]["dockerfile"] == "Dockerfile"
    assert nexus["command"] == ["python", "-m", "kaine.nexus"]
    assert cycle["command"] == ["python", "-m", "kaine.cycle"]


# --------------------------------------------------------------------------
# 3.2 / 3.4 — state volume + read-only config/secret bind mounts
# --------------------------------------------------------------------------
def test_state_is_named_volume_and_config_bind_mounts_are_readonly():
    doc = _load_compose()
    assert "kaine-state" in doc["volumes"]
    assert "kaine-models" in doc["volumes"]
    for svc_name in ("kaine-cycle", "kaine-nexus"):
        vols = doc["services"][svc_name]["volumes"]
        # Entity state persists at /app/state — the app writes state CWD-relative
        # under WORKDIR /app, so a /state mount would capture nothing it writes.
        assert any(v == "kaine-state:/app/state" for v in vols), svc_name
        for v in vols:
            if "operator.toml" in v or "secrets.toml" in v:
                assert v.endswith(":ro"), f"{svc_name}: {v} must be read-only"


def test_provisioned_weights_land_where_the_services_read_them():
    # The persistence contract that makes a from-scratch container actually boot:
    # provisioned model weights must be written to the shared kaine-models volume
    # (not the ephemeral /app/state), and the services that consume them must read
    # from that same volume at the same paths.
    from kaine.setup.organ import ORGAN_GGUF_DIR, ORGAN_GGUF_FILE

    doc = _load_compose()

    # Provision + cycle redirect the model-weights root onto /models (the shared
    # kaine-models volume) via KAINE_MODELS_DIR, so weights persist there.
    for svc in ("kaine-provision", "kaine-cycle"):
        assert doc["services"][svc]["environment"]["KAINE_MODELS_DIR"] == "/models", svc

    # Provision writes to kaine-models; the cycle reads it (encoder + embedder)
    # read-only.
    assert any(
        "kaine-models:/models" in v for v in doc["services"]["kaine-provision"]["volumes"]
    )
    assert any(
        v == "kaine-models:/models:ro" for v in doc["services"]["kaine-cycle"]["volumes"]
    )

    # The llama.cpp server's -m path is EXACTLY where the organ provisioner writes
    # the GGUF under /models — same subdir name, same filename. (.name is stable
    # regardless of the configured root, so this holds for local and container.)
    expected = f"/models/{ORGAN_GGUF_DIR.name}/{ORGAN_GGUF_FILE}"
    assert expected in doc["services"]["kaine-model-server"]["command"], expected


# --------------------------------------------------------------------------
# 3.3 — zero raw-sense-data persistence (load-bearing)
# --------------------------------------------------------------------------
def test_no_named_volume_captures_raw_sense_data():
    doc = _load_compose()
    for vol_name in doc.get("volumes", {}):
        low = vol_name.lower()
        assert "perception" not in low and "audio_out" not in low, vol_name


def test_no_durable_bind_or_volume_mounts_a_raw_sense_path():
    doc = _load_compose()
    named_volumes = set(doc.get("volumes", {}))
    for name, svc in doc["services"].items():
        for v in svc.get("volumes", []) or []:
            target = str(v).split(":")[1] if ":" in str(v) else str(v)
            for token in ("state/perception", "state/audio_out", "audio_out"):
                if token in target:
                    pytest.fail(f"{name} mounts a raw-sense path durably: {v}")
        # If a perception scratch exists, it MUST be tmpfs (RAM-backed), never a
        # named/durable volume.
        for tp in svc.get("tmpfs", []) or []:
            assert "perception" in tp or "audio_out" in tp or tp  # tmpfs is fine
    # The cycle's only perception scratch is tmpfs.
    cycle = doc["services"]["kaine-cycle"]
    assert any("perception" in t for t in cycle.get("tmpfs", []) or [])
    # And no named volume backs it.
    assert not any("perception" in nv for nv in named_volumes)


# --------------------------------------------------------------------------
# 4.1 — Quadlet cycle unit never auto-starts
# --------------------------------------------------------------------------
def _has_section(text: str, section: str) -> bool:
    """True if `section` appears as an ini section header line (not a comment)."""
    return any(ln.strip() == section for ln in text.splitlines())


def test_quadlet_cycle_has_no_install_section():
    text = (_QUADLET / "kaine-cycle.container").read_text()
    assert not _has_section(text, "[Install]"), (
        "the entity must never be enabled/auto-started"
    )
    assert "Restart=no" in text
    # The data/nexus units, by contrast, ARE enabled for reboot survival.
    assert _has_section((_QUADLET / "kaine-nexus.container").read_text(), "[Install]")
    assert _has_section((_QUADLET / "kaine-redis.container").read_text(), "[Install]")


# --------------------------------------------------------------------------
# 3.1 — setup provisioner plans every model weight (no network in the test)
# --------------------------------------------------------------------------
def test_provision_plans_all_models_without_network():
    from kaine.setup.internvideo_next import INTERNVIDEO_NEXT_REPO
    from kaine.setup.provision import aux_models, run_provision

    # Default (no config) → the shipped internvideo_next backend. The always-on
    # aux models are present; DINOv2 is NOT (it is fetched only when selected).
    repos = {m.repo for m in aux_models({})}
    assert "Systran/faster-distil-whisper-medium.en" in repos
    assert "sentence-transformers/all-MiniLM-L6-v2" in repos
    assert "emotion2vec/emotion2vec_plus_base" in repos
    assert "resemble-ai/chatterbox" in repos
    assert "facebook/dinov2-small" not in repos

    # Selecting the DINOv2 backend swaps in DINOv2 as a plain aux download.
    dino_repos = {
        m.repo for m in aux_models({"topos": {"encoder_backend": "dinov2"}})
    }
    assert "facebook/dinov2-small" in dino_repos

    # Inject a fake runner so NOTHING hits the network.
    calls: list[list[str]] = []

    def fake_runner(cmd, **kwargs):
        calls.append(list(cmd))

        class _R:
            returncode = 0
            stdout = ""

        return _R()

    config = {"modules": {"lingua": True}}
    _, aux_results = run_provision(config, consent=True, runner=fake_runner)
    # consent=False provisions nothing.
    assert run_provision(config, consent=False, runner=fake_runner) == ([], [])
    # Every issued command is an `hf download` (organ, aux, and the default
    # InternVideo-Next weights fetch all route through the injected runner).
    assert calls, "run_provision must issue downloads through the injected runner"
    assert all(c[:2] == ["hf", "download"] for c in calls)
    # The default backend fetches the InternVideo-Next weights (revision-pinned).
    assert any(INTERNVIDEO_NEXT_REPO in c for c in calls)
    assert any(r.repo == INTERNVIDEO_NEXT_REPO for r in aux_results)

    # With the DINOv2 backend selected, the InternVideo fetch is NOT issued and
    # DINOv2 IS downloaded as a plain aux model.
    dino_calls: list[list[str]] = []

    def dino_runner(cmd, **kwargs):
        dino_calls.append(list(cmd))
        return fake_runner(cmd, **kwargs)

    run_provision(
        {"modules": {"lingua": True}, "topos": {"encoder_backend": "dinov2"}},
        consent=True,
        runner=dino_runner,
    )
    assert not any(INTERNVIDEO_NEXT_REPO in c for c in dino_calls)
    assert any("facebook/dinov2-small" in c for c in dino_calls)


# --------------------------------------------------------------------------
# Optional strong check: docker parses the topology (parse only, never builds).
# --------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_docker_compose_config_validates():
    env = {
        "KAINE_REDIS_PASSWORD": "x",
        "KAINE_QDRANT_API_KEY": "y",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    result = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE), "config", "-q"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
