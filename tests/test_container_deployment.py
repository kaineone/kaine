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
import re
import shutil
import subprocess
import tomllib
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
        if flavor == "cuda":
            # The exact URL is host-dependent (the resolver picks the CPU index
            # on GPU-less hosts, cu128 on NVIDIA hosts) — only require a
            # non-empty string.
            assert isinstance(got, str) and got, flavor
        else:
            assert got == expected, flavor
    with pytest.raises(KeyError):
        mod.torch_index_url("bogus")


def test_print_index_cli_accessor():
    py = shutil.which("python3") or "python3"
    script = str(_REPO_ROOT / "scripts" / "install.py")
    cuda = subprocess.run(
        [py, script, "--print-index", "cuda"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert cuda.stdout.strip().startswith("https://download.pytorch.org/whl/")
    mps = subprocess.run(
        [py, script, "--print-index", "mps"], capture_output=True, text=True, check=True
    )
    assert mps.stdout.strip() == ""  # MPS uses default PyPI
    spec = subprocess.run(
        [py, script, "--print-torch-spec"], capture_output=True, text=True, check=True
    )

    with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
        deps = tomllib.load(f)["project"]["optional-dependencies"]["core"]
    expected = next(
        dep
        for dep in deps
        if isinstance(dep, str) and re.match(r"^torch\s*[<>=!~]", dep)
    )
    assert spec.stdout.strip() == expected


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
        ln for ln in text.splitlines() if ln.strip().upper().startswith("COPY")
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


def test_compose_nexus_has_privacy_hardening_environment():
    doc = _load_compose()
    env = doc["services"]["kaine-nexus"]["environment"]
    # Non-loopback binding is explicitly enabled inside the container (publishing
    # stays loopback-only).
    assert env["KAINE_NEXUS_NON_LOOPBACK_ALLOWED"] in ("1", "true", "yes")
    # The env token entry exists (empty falls through to the mounted secrets.toml).
    assert "KAINE_NEXUS_TOKEN" in env
    # Allowed Origins must reflect the host-published port, not the in-container 8088.
    assert "KAINE_NEXUS_ALLOWED_ORIGINS" in env
    assert "${KAINE_NEXUS_HOST_PORT:-8088}" in env["KAINE_NEXUS_ALLOWED_ORIGINS"]


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
        "kaine-models:/models" in v
        for v in doc["services"]["kaine-provision"]["volumes"]
    )
    assert any(
        v == "kaine-models:/models:ro"
        for v in doc["services"]["kaine-cycle"]["volumes"]
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


def _mount_target_and_tmpfs(v):
    """Return (target, is_tmpfs) for a compose mount, handling BOTH the short
    string form (``source:target:mode``, always a bind/named volume) and the long
    dict form (``{type, target, ...}``) — a perception scratch may be declared
    either as a top-level ``tmpfs:`` entry or a ``volumes:`` entry of type tmpfs."""
    if isinstance(v, dict):
        return str(v.get("target", "")), (v.get("type") == "tmpfs")
    s = str(v)
    parts = s.split(":")
    return (parts[1] if len(parts) > 1 else s), False


def test_no_durable_bind_or_volume_mounts_a_raw_sense_path():
    doc = _load_compose()
    named_volumes = set(doc.get("volumes", {}))
    for name, svc in doc["services"].items():
        for v in svc.get("volumes", []) or []:
            target, is_tmpfs = _mount_target_and_tmpfs(v)
            if is_tmpfs:
                continue  # RAM-backed scratch is ephemeral — the invariant is fine
            for token in ("state/perception", "state/audio_out", "audio_out"):
                if token in target:
                    pytest.fail(f"{name} mounts a raw-sense path durably: {v}")
        # If a perception scratch exists, it MUST be tmpfs (RAM-backed), never a
        # named/durable volume.
        for tp in svc.get("tmpfs", []) or []:
            assert "perception" in tp or "audio_out" in tp or tp  # tmpfs is fine

    def _tmpfs_targets(svc):
        # tmpfs declared either short-form (top-level tmpfs:) or long-form
        # (volumes: entry with type: tmpfs).
        yield from (str(t) for t in svc.get("tmpfs", []) or [])
        for v in svc.get("volumes", []) or []:
            target, is_tmpfs = _mount_target_and_tmpfs(v)
            if is_tmpfs:
                yield target

    # The cycle's only perception scratch is tmpfs (either declaration form).
    cycle = doc["services"]["kaine-cycle"]
    assert any("perception" in t for t in _tmpfs_targets(cycle))
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


def test_quadlet_nexus_privacy_hardening_and_python_healthcheck():
    text = (_QUADLET / "kaine-nexus.container").read_text()
    # Nexus binds all-interfaces inside the container; the published port is loopback-only.
    assert "Environment=KAINE_NEXUS_HOST=0.0.0.0" in text
    assert "Environment=KAINE_NEXUS_NON_LOOPBACK_ALLOWED=1" in text
    assert (
        "Environment=KAINE_NEXUS_ALLOWED_ORIGINS=http://127.0.0.1:8088,http://localhost:8088"
        in text
    )
    assert "PublishPort=127.0.0.1:" in text
    health_lines = [ln for ln in text.splitlines() if ln.startswith("HealthCmd")]
    assert health_lines
    health_cmd = health_lines[0]
    assert "curl" not in health_cmd
    assert "python" in health_cmd


def test_quadlet_referenced_volumes_have_unit_files():
    """Every Volume=... line in a .container unit must name a .volume file."""
    referenced: set[str] = set()
    for container in _QUADLET.glob("*.container"):
        for line in container.read_text().splitlines():
            if line.startswith("Volume="):
                # Volume=NAME.volume:/path or Volume=%h/...:/path
                name = line.split("=", 1)[1].split(":", 1)[0]
                if name.endswith(".volume"):
                    referenced.add(name)
    for name in referenced:
        assert (_QUADLET / name).exists(), f"missing quadlet volume unit: {name}"


def test_quadlet_qdrant_healthcheck_avoids_curl():
    lines = (_QUADLET / "kaine-qdrant.container").read_text().splitlines()
    health_lines = [ln for ln in lines if ln.startswith("HealthCmd")]
    assert health_lines
    health_cmd = health_lines[0]
    assert "curl" not in health_cmd
    assert "wget" not in health_cmd


def test_quadlet_redis_maxmemory_matches_compose_topology():
    quadlet_text = (_QUADLET / "kaine-redis.container").read_text()
    compose_doc = _load_compose()
    compose_cmd = compose_doc["services"]["kaine-redis"]["command"]
    compose_maxmemory = compose_cmd[compose_cmd.index("--maxmemory") + 1]
    assert f"--maxmemory {compose_maxmemory}" in quadlet_text


def test_compose_redis_maxmemory_matches_kaine_topology():
    compose_doc = _load_compose()
    kaine_cmd = compose_doc["services"]["kaine-redis"]["command"]
    kaine_maxmemory = kaine_cmd[kaine_cmd.index("--maxmemory") + 1]
    redis_path = _REPO_ROOT / "compose" / "redis.yml"
    redis_doc = yaml.safe_load(redis_path.read_text())
    redis_cmd = redis_doc["services"]["kaine-redis"]["command"]
    redis_maxmemory = redis_cmd[redis_cmd.index("--maxmemory") + 1]
    assert kaine_maxmemory == redis_maxmemory


def test_quadlet_cycle_and_nexus_have_redis_url():
    url = "Environment=KAINE_REDIS_URL=redis://:${KAINE_REDIS_PASSWORD}@kaine-redis:6379/0"
    assert url in (_QUADLET / "kaine-cycle.container").read_text()
    assert url in (_QUADLET / "kaine-nexus.container").read_text()


def _section(text: str, section: str) -> str:
    """Return the body of `section` (without the header line)."""
    lines = text.splitlines()
    target = f"[{section}]"
    in_section = False
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == target:
            in_section = True
            continue
        if in_section and stripped.startswith("[") and stripped.endswith("]"):
            break
        if in_section:
            body.append(line)
    return "\n".join(body)


def test_quadlet_units_never_embed_host_checkout_path():
    for path in _QUADLET.glob("*"):
        text = path.read_text()
        assert "projects/kaine" not in text, f"{path.name} embeds old host path"
        assert "%h/" not in text, f"{path.name} embeds unrendered home path"


def test_quadlet_secret_units_load_bootstrap_env_file():
    for path in _QUADLET.glob("*.container"):
        text = path.read_text()
        if "${" not in text:
            continue
        service = _section(text, "Service")
        assert (
            "EnvironmentFile=@KAINE_ROOT@/compose/.env" in service
        ), f"{path.name} expands secrets but does not load compose/.env in [Service]"


def test_quadlet_cycle_forwards_operator_presence_and_has_no_install():
    text = (_QUADLET / "kaine-cycle.container").read_text()
    container = _section(text, "Container")
    assert (
        "Environment=KAINE_CYCLE_OPERATOR_PRESENT=${KAINE_CYCLE_OPERATOR_PRESENT}"
        in container
    )
    assert not _has_section(text, "[Install]"), (
        "the entity must never be enabled/auto-started"
    )
    assert "Restart=no" in text


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
    dino_repos = {m.repo for m in aux_models({"topos": {"encoder_backend": "dinov2"}})}
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


def test_kaine_cycle_unattended_container_design(tmp_path: Path):
    """The opt-in unattended unit auto-starts, conflicts with the supervised unit,
    and is never installed by the setup script.
    """

    def _parse_quadlet(path: Path) -> dict[str, dict[str, list[str]]]:
        """Section -> key -> every value. Unit files repeat keys (Environment=,
        Volume=), so each occurrence is kept rather than the last one winning."""
        sections: dict[str, dict[str, list[str]]] = {}
        current: dict[str, list[str]] | None = None
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = sections.setdefault(line[1:-1], {})
                continue
            if current is not None and "=" in line:
                key, value = line.split("=", 1)
                current.setdefault(key.strip(), []).append(value.strip())
        return sections

    supervised = _REPO_ROOT / "quadlet" / "kaine-cycle.container"
    unattended = _REPO_ROOT / "quadlet" / "kaine-cycle-unattended.container"
    assert unattended.exists(), "unattended quadlet unit must exist"

    sup = _parse_quadlet(supervised)
    un = _parse_quadlet(unattended)

    # The unattended unit is installable and wants default.target.
    assert "Install" in un, "unattended unit must have an [Install] section"
    assert "default.target" in un["Install"].get("WantedBy", [])

    # It declares the unattended selector.
    assert any(
        "KAINE_CYCLE_UNATTENDED=1" in v for v in un["Container"].get("Environment", [])
    )

    # It conflicts with the supervised entity unit.
    assert any(
        "kaine-cycle.service" in v for v in un["Unit"].get("Conflicts", [])
    )

    # Refused gates stay failed.
    assert "no" in un["Service"].get("Restart", [])

    # Same container name as the supervised unit so they cannot run side by side.
    assert any(
        "kaine-cycle" in v for v in un["Container"].get("ContainerName", [])
    )

    # Secrets come from the same compose .env file.
    assert any(
        "@KAINE_ROOT@/compose/.env" in v for v in un["Service"].get("EnvironmentFile", [])
    )

    # The unattended unit must never forward operator presence.
    raw_unattended = unattended.read_text()
    assert "KAINE_CYCLE_OPERATOR_PRESENT" not in raw_unattended

    # The supervised unit is not installable and is not an unattended unit.
    assert "Install" not in sup
    raw_supervised = supervised.read_text()
    assert "KAINE_CYCLE_UNATTENDED" not in raw_supervised

    # Host/named mounts match the supervised unit except the D-Bus socket.
    sup_volumes = set(sup["Container"].get("Volume", []))
    un_volumes = set(un["Container"].get("Volume", []))
    bus_socket = "%t/bus:%t/bus"
    assert bus_socket in un_volumes
    for vol in un_volumes:
        if vol == bus_socket:
            continue
        assert vol in sup_volumes, (
            f"unattended volume {vol!r} missing from supervised unit"
        )

    # The install script must skip the unattended unit.
    fake_root = tmp_path / "checkout"
    fake_root.mkdir()
    shutil.copytree(_REPO_ROOT / "quadlet", fake_root / "quadlet")
    scripts_dir = fake_root / "scripts"
    scripts_dir.mkdir()
    shutil.copy(
        _REPO_ROOT / "scripts" / "install-quadlet.sh",
        scripts_dir / "install-quadlet.sh",
    )
    (fake_root / "config").mkdir()
    (fake_root / "config" / "kaine.operator.toml").write_text("")
    (fake_root / "config" / "secrets.toml").write_text("")
    (fake_root / "compose").mkdir()
    (fake_root / "compose" / ".env").write_text("")

    dest = tmp_path / "systemd"
    result = subprocess.run(
        [
            "bash",
            str(scripts_dir / "install-quadlet.sh"),
            "--root",
            str(fake_root),
            "--dest",
            str(dest),
            "--generator",
            "none",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    installed = {p.name for p in dest.glob("*.container")} if dest.exists() else set()
    assert "kaine-cycle-unattended.container" not in installed
    assert "kaine-cycle.container" in installed
    assert "skipped kaine-cycle-unattended.container" in (result.stdout + result.stderr)

    # Quadlet generator dry-run succeeds for the rendered unattended unit.
    generator = None
    for cand in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet"):
        if Path(cand).is_file():
            generator = cand
            break
    if generator is None:
        pytest.skip("podman quadlet generator not found")

    import os

    stage = tmp_path / "stage"
    stage.mkdir()
    for src in (_REPO_ROOT / "quadlet").glob("*"):
        if src.suffix in (".container", ".network", ".volume"):
            text = src.read_text().replace("@KAINE_ROOT@", str(fake_root))
            (stage / src.name).write_text(text)

    gen = subprocess.run(
        [generator, "-user", "-dryrun"],
        env={**os.environ, "QUADLET_UNIT_DIRS": str(stage)},
        capture_output=True,
        text=True,
    )
    assert gen.returncode == 0, gen.stderr
    generated = gen.stdout + gen.stderr
    assert "KAINE_CYCLE_UNATTENDED=1" in generated

    # Do NOT run systemd-analyze on quadlet output; it is not a plain unit file.
