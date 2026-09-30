# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Real-shell tests for docker/organ-launcher.sh and compose/kaine.yml."""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parent.parent / "docker" / "organ-launcher.sh"
COMPOSE_FILE = Path(__file__).resolve().parent.parent / "compose" / "kaine.yml"

NEEDS_UNIX_TOOLS = pytest.mark.skipif(
    not os.path.exists("/bin/sh") or shutil.which("sha256sum") is None,
    reason="/bin/sh or sha256sum unavailable",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(adapter_dir: Path, filename: str, sha256_hex: str) -> None:
    adapter_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "activated_at": "2026-09-30T00:00:00Z",
        "adapter_id": "test-adapter",
        "file": filename,
        "sha256": sha256_hex,
    }
    (adapter_dir / "active.json").write_text(json.dumps(manifest, sort_keys=True))


def _wait_for_log(log: Path, timeout: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists() and log.stat().st_size:
            return log.read_text().splitlines()[-1]
        time.sleep(0.05)
    raise AssertionError(f"fake llama-server never wrote to {log}")


class LauncherSession:
    def __init__(self, tmp_path: Path, args=(), extra_env=None):
        self.tmp_path = tmp_path
        self.args = list(args)
        self.extra_env = extra_env or {}
        self.proc = None
        self.stderr_file = None

    def __enter__(self):
        adapter_dir = self.tmp_path / "adapters"
        adapter_dir.mkdir(parents=True, exist_ok=True)

        log = self.tmp_path / "llama.log"
        fake = self.tmp_path / "fake-llama-server"
        fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nsleep 3600\n')
        fake.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "KAINE_LLAMA_SERVER": str(fake),
                "KAINE_ORGAN_ADAPTERS_DIR": str(adapter_dir),
                "KAINE_ORGAN_POLL_S": "0.2",
                "PATH": os.environ.get("PATH", ""),
            }
        )
        env.update(self.extra_env)

        self.stderr_path = self.tmp_path / "launcher.stderr"
        self.stderr_file = open(
            self.stderr_path, "w", buffering=1, encoding="utf-8"
        )
        self.proc = subprocess.Popen(
            ["/bin/sh", str(LAUNCHER)] + self.args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=self.stderr_file,
            start_new_session=True,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.proc.kill()
                    self.proc.wait(timeout=2)
        finally:
            if self.stderr_file:
                self.stderr_file.close()

    def stderr(self) -> str:
        if self.stderr_file:
            self.stderr_file.flush()
        return self.stderr_path.read_text(encoding="utf-8", errors="replace")


@NEEDS_UNIX_TOOLS
def test_no_manifest_launches_without_lora(tmp_path: Path):
    with LauncherSession(tmp_path):
        last = _wait_for_log(tmp_path / "llama.log")
        assert "--lora" not in last


@NEEDS_UNIX_TOOLS
def test_valid_manifest_loads_adapter(tmp_path: Path):
    adapter = tmp_path / "adapters" / "active-1.gguf"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text("adapter-one")
    _write_manifest(tmp_path / "adapters", "active-1.gguf", _sha256(adapter))
    (tmp_path / "adapters" / "generation").write_text("1")

    with LauncherSession(tmp_path):
        last = _wait_for_log(tmp_path / "llama.log")
        assert "--lora-scaled" in last
        assert f"{adapter}:0" in last


@NEEDS_UNIX_TOOLS
def test_sha_mismatch_launches_without_lora(tmp_path: Path):
    adapter = tmp_path / "adapters" / "active-1.gguf"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text("adapter-one")
    _write_manifest(tmp_path / "adapters", "active-1.gguf", "0" * 64)
    (tmp_path / "adapters" / "generation").write_text("1")

    with LauncherSession(tmp_path) as session:
        last = _wait_for_log(tmp_path / "llama.log")
        assert "--lora" not in last
        assert "mismatch" in session.stderr().lower()


@NEEDS_UNIX_TOOLS
def test_bad_filename_launches_without_lora(tmp_path: Path):
    _write_manifest(tmp_path / "adapters", "../evil.gguf", "0" * 64)
    (tmp_path / "adapters" / "generation").write_text("1")

    with LauncherSession(tmp_path):
        last = _wait_for_log(tmp_path / "llama.log")
        assert "--lora" not in last


@NEEDS_UNIX_TOOLS
def test_generation_bump_restarts_with_new_adapter(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    a1 = adapter_dir / "active-1.gguf"
    a1.write_text("adapter-one")
    _write_manifest(adapter_dir, "active-1.gguf", _sha256(a1))
    (adapter_dir / "generation").write_text("1")

    with LauncherSession(tmp_path):
        _wait_for_log(tmp_path / "llama.log")

        a2 = adapter_dir / "active-2.gguf"
        a2.write_text("adapter-two")
        _write_manifest(adapter_dir, "active-2.gguf", _sha256(a2))
        (adapter_dir / "generation").write_text("2")

        deadline = time.monotonic() + 3.0
        last = ""
        while time.monotonic() < deadline:
            lines = (tmp_path / "llama.log").read_text().splitlines()
            if lines:
                last = lines[-1]
            if "active-2.gguf" in last:
                break
            time.sleep(0.05)

        assert "active-2.gguf" in last


@NEEDS_UNIX_TOOLS
def test_sigterm_terminates_fake_and_launcher(tmp_path: Path):
    session = LauncherSession(tmp_path)
    with session:
        _wait_for_log(tmp_path / "llama.log")
    assert session.proc is not None
    assert session.proc.returncode is not None


def test_compose_security_invariants():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(COMPOSE_FILE.read_text())

    trainer = data["services"]["kaine-trainer"]
    assert "training" in (trainer.get("profiles") or [])
    assert not trainer.get("ports")
    assert any(
        str(v).startswith("kaine-models:/models:ro")
        for v in trainer.get("volumes", [])
    )

    server = data["services"]["kaine-model-server"]
    assert any(
        "kaine-organ-adapters:/organ-adapters:ro" in str(v)
        for v in server.get("volumes", [])
    )

    for name, svc in data["services"].items():
        for vol in svc.get("volumes", []):
            assert "/var/run/docker.sock" not in str(vol), (
                f"{name} mounts Docker socket"
            )
