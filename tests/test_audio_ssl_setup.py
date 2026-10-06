# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import subprocess

from kaine.setup.audio_ssl import (
    PINS,
    audio_ssl_download_cmd,
    run_audio_ssl_download,
)


def test_download_command_pinned_and_resolved_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_MODELS_DIR", str(tmp_path))
    cmd = audio_ssl_download_cmd("dasheng")
    repo, revision, dir_name = PINS["dasheng"]
    assert cmd == [
        "hf",
        "download",
        repo,
        "model.safetensors",
        "--revision",
        revision,
        "--local-dir",
        str(tmp_path / dir_name),
    ]

    cmd2 = audio_ssl_download_cmd("wavjepa", local_dir=tmp_path / "custom")
    assert "--local-dir" in cmd2
    assert str(tmp_path / "custom") in cmd2
    assert revision not in cmd2  # different revision for wavjepa
    assert PINS["wavjepa"][1] in cmd2


def test_no_consent_runs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("kaine.setup.audio_ssl.shutil.which", lambda _bin: "/bin/hf")
    ok, msg = run_audio_ssl_download("dasheng", consent=False, local_dir=tmp_path)
    assert ok is False
    assert "not consented" in msg
    assert not (tmp_path / "REVISION").exists()


def test_successful_download_writes_revision(tmp_path, monkeypatch):
    monkeypatch.setattr("kaine.setup.audio_ssl.shutil.which", lambda _bin: "/bin/hf")

    def fake_runner(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    ok, msg = run_audio_ssl_download(
        "dasheng", consent=True, runner=fake_runner, local_dir=tmp_path
    )
    assert ok is True
    assert (tmp_path / "REVISION").read_text() == PINS["dasheng"][1]


def test_failed_download_writes_no_revision(tmp_path, monkeypatch):
    monkeypatch.setattr("kaine.setup.audio_ssl.shutil.which", lambda _bin: "/bin/hf")

    def fake_runner(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="network error")

    ok, msg = run_audio_ssl_download(
        "wavjepa", consent=True, runner=fake_runner, local_dir=tmp_path
    )
    assert ok is False
    assert not (tmp_path / "REVISION").exists()
    assert "download failed" in msg


def test_pins_match_the_vendored_upstream_files():
    """The weights are fetched at exactly the commit the vendored code came
    from: each pin equals the 'Pinned commit:' line of external/<name>/UPSTREAM."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "external"
    for name, (repo, revision, _dir) in PINS.items():
        upstream = (root / name / "UPSTREAM").read_text()
        assert f"Pinned commit:    {revision}" in upstream, name
        assert f"huggingface.co/{repo}" in upstream, name
