# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import time
from pathlib import Path
from typing import Any

from kaine.residency.budget import Domain
from kaine.setup.footprint import (
    ComponentInfo,
    _measure_callable_in_child,
    _needs_for,
    _validate_child_record,
    main,
)


def _raise_file_not_found(*args: Any, **kwargs: Any) -> Path:
    raise FileNotFoundError()


def _hermetic_selection(monkeypatch: Any) -> None:
    """Make component selection independent of the machine's installed models."""
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached",
        lambda model_id, *, cache_dir=None: False,
    )
    monkeypatch.setattr(
        "kaine.setup.footprint._sherpa_present",
        lambda model_id, model_dir: False,
    )
    monkeypatch.setattr(
        "kaine.setup.footprint.resolve_model_dir",
        _raise_file_not_found,
    )


def _fake_budgets():
    total = 16 << 30
    reserve = 1 << 30
    return (
        Domain(
            name="system",
            kind="system",
            total_bytes=total,
            available_bytes=total - reserve,
            reserve_bytes=reserve,
            budget_bytes=total - reserve,
            derivation="test",
        ),
    )


def _run(
    argv,
    config,
    tmp_path,
    capsys,
    *,
    measure=None,
    service=None,
    config_loader=None,
    budgets_fn=None,
    input_fn=None,
    stdin_isatty=None,
):
    catalogue_path = tmp_path / "footprints.json"
    full_argv = ["--catalogue", str(catalogue_path)] + argv
    kwargs = {}
    if config_loader is None:
        kwargs["config_loader"] = lambda: config
    else:
        kwargs["config_loader"] = config_loader
    if measure is not None:
        kwargs["measure_fn"] = measure
    if service is not None:
        kwargs["service_fn"] = service
    if budgets_fn is not None:
        kwargs["budgets_fn"] = budgets_fn
    if input_fn is not None:
        kwargs["input_fn"] = input_fn
    if stdin_isatty is not None:
        kwargs["stdin_isatty"] = stdin_isatty

    code = main(full_argv, **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err, catalogue_path


def test_uncalibrated_enabled_components_exit_three_and_named(
    capsys, tmp_path, monkeypatch
):
    """An enabled, planned component without a catalogue figure makes the fit partial."""
    _hermetic_selection(monkeypatch)
    config = {
        "modules": {"topos": True},
        "topos": {"encoder_backend": "internvideo_next"},
    }

    code, out, err, catalogue_path = _run(
        ["--yes", "--only", "topos.encoder"], config, tmp_path, capsys
    )

    assert code == 3
    assert "Uncalibrated components: topos.encoder" in out
    assert "result is partial; uncalibrated components: topos.encoder" in err
    # The weights are absent, so nothing was measured and no file is written.
    assert not catalogue_path.exists()


def test_data_root_installed_before_selection(capsys, tmp_path, monkeypatch):
    """install_data_root runs before _select_components so paths match."""
    order = []

    def _tracking_install_data_root(config):
        order.append("install")
        # Simulate the real helper exposing a data-root path to selection.
        data_root = tmp_path / "data_root"
        data_root.mkdir(exist_ok=True)
        os.environ["KAINE_DATA_ROOT"] = str(data_root)

    def _tracking_select_components(config, *, only=None):
        order.append("select")
        assert os.environ.get("KAINE_DATA_ROOT") == str(tmp_path / "data_root")
        # Return empty so the command finishes cleanly.
        return []

    monkeypatch.setattr(
        "kaine.setup.footprint.install_data_root", _tracking_install_data_root
    )
    monkeypatch.setattr(
        "kaine.setup.footprint._select_components", _tracking_select_components
    )

    config = {"modules": {}}
    code, out, err, _ = _run([], config, tmp_path, capsys)
    assert code == 0
    assert order == ["install", "select"]


def test_remote_url_not_measured(capsys, tmp_path, monkeypatch):
    """A non-loopback endpoint is recorded as not_measured remote_endpoint."""
    _hermetic_selection(monkeypatch)
    config = {
        "modules": {"lingua": True},
        "lingua": {"backend": "openai", "chat_url": "http://example.com:5000"},
    }

    code, out, err, catalogue_path = _run(
        ["--yes", "--only", "lingua"], config, tmp_path, capsys
    )

    assert "not measured: remote_endpoint" in out
    assert code == 0
    # No local load was attempted and no entry was written.
    assert not catalogue_path.exists()


def test_parent_rejects_invalid_child_records():
    """Only well-formed, fully-valid records are accepted from children."""
    base = {
        "ok": True,
        "peak_bytes": 1,
        "device": None,
        "device_bytes": None,
        "mapped": False,
    }
    assert _validate_child_record(base)[0] is True

    zero = {**base, "peak_bytes": 0}
    assert _validate_child_record(zero)[0] is False

    bool_peak = {**base, "peak_bytes": True}
    assert _validate_child_record(bool_peak)[0] is False

    missing_ok = {k: v for k, v in base.items() if k != "ok"}
    assert _validate_child_record(missing_ok)[0] is False

    truthy_ok = {**base, "ok": "yes"}
    assert _validate_child_record(truthy_ok)[0] is False


def _exit_three_target():
    """Tiny CPU-only child target that exits without sending a record."""
    os._exit(3)


def test_real_child_crash_failed_quickly_and_writes_nothing(
    capsys, tmp_path, monkeypatch
):
    """A child that dies without communicating is FAILED quickly."""
    _hermetic_selection(monkeypatch)

    start = time.monotonic()
    ok, peak, device_bytes, device, mapped, error = _measure_callable_in_child(
        _exit_three_target, timeout=60
    )
    elapsed = time.monotonic() - start

    assert ok is False
    assert elapsed < 30
    assert "child" in error.lower() or "exit" in error.lower()

    # Ensure no catalogue side effects from the failure path by running main
    # with a component whose measurement target exits immediately.
    config = {
        "modules": {"audition": True},
        "audition": {"transcription_enabled": True, "backend": "sherpa_onnx"},
    }
    monkeypatch.setattr(
        "kaine.setup.footprint._sherpa_present",
        lambda model_id, model_dir: True,
    )

    code, out, err, catalogue_path = _run(
        ["--yes"],
        config,
        tmp_path,
        capsys,
        measure=lambda info, cfg, timeout: _measure_callable_in_child(
            _exit_three_target, timeout=timeout
        ),
    )
    assert code == 1
    assert "FAILED" in out
    assert not catalogue_path.exists()


def _env_assert_child():
    """Tiny CPU-only target that asserts the child env allowlist."""
    if "KAINE_STATE_KEY" in os.environ:
        raise AssertionError("KAINE_STATE_KEY is present in child env")
    if "HTTPS_PROXY" in os.environ:
        raise AssertionError("HTTPS_PROXY is present in child env")
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise AssertionError(
            f"HF_HUB_OFFLINE is {os.environ.get('HF_HUB_OFFLINE')!r}, expected '1'"
        )
    return {"mapped": False}


def test_child_env_allowlist_drops_secrets_and_sets_offline(monkeypatch):
    """The child receives only the allowlisted variables plus offline flags."""
    monkeypatch.setenv("KAINE_STATE_KEY", "secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    ok, peak, device_bytes, device, mapped, error = _measure_callable_in_child(
        _env_assert_child, timeout=10
    )

    assert ok is True, error


def test_corrupt_catalogue_untouched_when_nothing_is_measured(capsys, tmp_path, monkeypatch):
    """With nothing measured nothing is written, so a corrupt catalogue is left as is."""
    _hermetic_selection(monkeypatch)
    catalogue_path = tmp_path / "footprints.json"
    catalogue_path.write_text("not valid json")

    code, out, err, catalogue_path = _run(["--yes"], {"modules": {}}, tmp_path, capsys)

    assert code == 0  # nothing is enabled, so nothing is selected or planned
    assert catalogue_path.read_text() == "not valid json"
    assert not list(tmp_path.glob("footprints.json.bak-*"))


def test_non_positive_timeout_rejected(capsys, tmp_path):
    """argparse refuses zero, negative, and non-finite timeouts."""
    code, out, err, _ = _run(
        ["--timeout", "0"], {"modules": {}}, tmp_path, capsys
    )
    assert code == 2
    assert "timeout" in err.lower()

    code, out, err, _ = _run(
        ["--timeout", "-5"], {"modules": {}}, tmp_path, capsys
    )
    assert code == 2
    assert "timeout" in err.lower()


def test_needs_for_uncalibrated_and_device_folding():
    """_needs_for emits uncalibrated Needs and folds device bytes on unified hosts."""
    from kaine.residency.catalogue import Entry

    base_entry = dict(
        component="topos.encoder",
        backend="internvideo_next",
        model_id="internvideo_next",
        bytes=2 << 30,
        device="cuda:0",
        device_bytes=4 << 30,
        mapped=False,
    )

    discrete_entries = [Entry(host_class="discrete", **base_entry)]
    unified_entries = [Entry(host_class="unified", **base_entry)]

    info = ComponentInfo(
        name="topos.encoder",
        kind="in_process",
        backend="internvideo_next",
        model_id="internvideo_next",
    )

    discrete_budgets = (
        Domain(
            name="system",
            kind="system",
            total_bytes=16 << 30,
            available_bytes=15 << 30,
            reserve_bytes=1 << 30,
            budget_bytes=15 << 30,
            derivation="test",
        ),
        Domain(
            name="cuda:0",
            kind="accelerator",
            total_bytes=8 << 30,
            available_bytes=7 << 30,
            reserve_bytes=1 << 30,
            budget_bytes=7 << 30,
            derivation="test",
        ),
    )
    needs = _needs_for(discrete_entries, [info], "discrete", discrete_budgets)
    assert any(n.domain == "cuda:0" and n.footprint_bytes == 4 << 30 for n in needs)

    unified_budgets = (
        Domain(
            name="system",
            kind="system",
            total_bytes=32 << 30,
            available_bytes=31 << 30,
            reserve_bytes=1 << 30,
            budget_bytes=31 << 30,
            derivation="test",
        ),
    )
    needs = _needs_for(unified_entries, [info], "unified", unified_budgets)
    system_need = next(n for n in needs if n.domain == "system")
    assert system_need.footprint_bytes == (2 << 30) + (4 << 30)

    # Missing entry -> uncalibrated Need.
    needs = _needs_for([], [info], "discrete", discrete_budgets)
    assert len(needs) == 1
    assert needs[0].footprint_bytes is None
    assert needs[0].component == "topos.encoder"
