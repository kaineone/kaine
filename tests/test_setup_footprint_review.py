# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from kaine.residency.budget import Domain
from kaine.residency.catalogue import Entry, load_catalogue, write_catalogue
from kaine.setup.footprint import (
    ComponentInfo,
    _child_wrapper,
    _measure_callable_in_child,
    _needs_for,
    _nvidia_smi_usage,
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


def _cpu_torch():
    """A torch stand-in on a host without CUDA."""

    class _Cuda:
        is_available = staticmethod(lambda: False)

    class _Torch:
        cuda = _Cuda()

    return _Torch()


def _fake_measure(mapping):
    calls = []

    def measure(info, config, timeout=600.0):
        calls.append({"info": info, "config": config, "timeout": timeout})
        if info.name in mapping:
            return mapping[info.name]
        return (True, 123 << 20, None, None, False, "")

    return measure, calls


def _fake_service(mapping):
    calls = []

    def measure(url):
        calls.append(url)
        return mapping.get(url)

    return measure, calls


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
    torch_module=None,
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
    # Hermetic by default: a CPU-only, system-only host, whatever this
    # machine has.
    kwargs["budgets_fn"] = budgets_fn if budgets_fn is not None else _fake_budgets
    if input_fn is not None:
        kwargs["input_fn"] = input_fn
    if stdin_isatty is not None:
        kwargs["stdin_isatty"] = stdin_isatty
    kwargs["torch_module"] = torch_module if torch_module is not None else _cpu_torch()

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


def test_valid_existing_catalogue_not_moved(capsys, tmp_path, monkeypatch):
    """A valid catalogue is parsed successfully and never renamed as corrupt."""
    _hermetic_selection(monkeypatch)
    catalogue_path = tmp_path / "footprints.json"
    write_catalogue(
        [
            Entry(
                component="topos.encoder",
                backend="internvideo_next",
                model_id="internvideo_next",
                bytes=100 << 20,
                host_class="cpu",
            )
        ],
        catalogue_path,
    )

    config = {
        "modules": {"topos": True},
        "topos": {"encoder_backend": "internvideo_next"},
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        budgets_fn=_fake_budgets,
    )

    assert code == 0
    assert not list(tmp_path.glob("footprints.json.bak-*"))
    entries = load_catalogue(cat)
    assert any(e.component == "topos.encoder" for e in entries)


def test_failed_backup_rename_returns_one_and_measures_nothing(
    capsys, tmp_path, monkeypatch
):
    """A corrupt catalogue that cannot be moved aside stops before measuring."""
    _hermetic_selection(monkeypatch)
    catalogue_path = tmp_path / "footprints.json"
    catalogue_path.write_text("not json {")
    (tmp_path / "model.safetensors").write_text("x")

    measure, calls = _fake_measure(
        {"topos.encoder": (True, 100 << 20, None, None, False, "")}
    )

    def _broken_rename(self, target):
        raise OSError("read-only")

    monkeypatch.setattr(Path, "rename", _broken_rename)

    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        measure=measure,
    )

    assert code == 1
    assert "could not be read and could not be moved aside" in err
    assert "nothing was recorded" in err
    assert not calls


def _fake_conn():
    class Conn:
        def __init__(self):
            self.sent = None

        def send(self, obj):
            self.sent = obj

        def close(self):
            pass

    return Conn()


def test_child_wrapper_peak_reserved_selects_device(monkeypatch):
    """Peak torch reserved memory picks the device even after allocator frees."""
    monkeypatch.setattr(
        "kaine.setup.footprint._apply_child_env_allowlist", lambda: None
    )
    monkeypatch.setattr("kaine.setup.footprint._set_offline_env", lambda: None)
    monkeypatch.setattr("kaine.setup.footprint._read_baseline_bytes", lambda: 0)
    monkeypatch.setattr("kaine.setup.footprint._read_peak_bytes", lambda: 100)

    class _Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 2

        @staticmethod
        def max_memory_reserved(device=None):
            if device == 0:
                return 0
            if device == 1:
                return 3 << 30
            return 0

        @staticmethod
        def get_device_properties(i):
            class Props:
                uuid = f"uuid-{i}"

            return Props()

    fake_torch = type("_Torch", (), {"cuda": _Cuda()})()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        "kaine.setup.footprint._nvidia_smi_usage", lambda pids, tm: None
    )

    conn = _fake_conn()
    _child_wrapper(conn, lambda: {"mapped": False})

    assert conn.sent["ok"] is True
    assert conn.sent["device"] == "cuda:1"
    assert conn.sent["device_bytes"] >= 3 << 30


def test_child_wrapper_uses_smi_when_available(monkeypatch):
    """Device bytes prefer the child's own nvidia-smi figure when available."""
    monkeypatch.setattr(
        "kaine.setup.footprint._apply_child_env_allowlist", lambda: None
    )
    monkeypatch.setattr("kaine.setup.footprint._set_offline_env", lambda: None)
    monkeypatch.setattr("kaine.setup.footprint._read_baseline_bytes", lambda: 0)
    monkeypatch.setattr("kaine.setup.footprint._read_peak_bytes", lambda: 100)

    class _Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 2

        @staticmethod
        def max_memory_reserved(device=None):
            if device == 1:
                return 3 << 30
            return 0

        @staticmethod
        def get_device_properties(i):
            class Props:
                uuid = f"uuid-{i}"

            return Props()

    fake_torch = type("_Torch", (), {"cuda": _Cuda()})()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    smi_bytes = int(3.5 * (1 << 30))
    monkeypatch.setattr(
        "kaine.setup.footprint._nvidia_smi_usage",
        lambda pids, tm: {"cuda:1": smi_bytes},
    )

    conn = _fake_conn()
    _child_wrapper(conn, lambda: {"mapped": False})

    assert conn.sent["ok"] is True
    assert conn.sent["device"] == "cuda:1"
    assert conn.sent["device_bytes"] == smi_bytes


def test_needs_for_not_measured_local_is_uncalibrated():
    """A not_measured local organ without a catalogue entry is uncalibrated."""
    info = ComponentInfo(
        name="lingua",
        kind="not_measured",
        backend="llama_cpp",
        model_id="qwen2.5-3b",
    )
    needs = _needs_for([], [info], "cpu", _fake_budgets())
    assert len(needs) == 1
    assert needs[0].component == "lingua"
    assert needs[0].footprint_bytes is None


def test_needs_for_remote_endpoint_skipped():
    """A remote_endpoint component is skipped and produces no Need."""
    info = ComponentInfo(
        name="lingua",
        kind="not_measured",
        backend="openai",
        model_id="gpt-4o-mini",
        reason="remote_endpoint",
    )
    needs = _needs_for([], [info], "cpu", _fake_budgets())
    assert needs == []


def test_needs_for_external_without_entry_is_uncalibrated():
    """A local external service that was not measured is uncalibrated."""
    info = ComponentInfo(
        name="lingua",
        kind="external",
        backend="openai",
        model_id="gpt-4o-mini",
        url="http://localhost:1234",
    )
    needs = _needs_for([], [info], "cpu", _fake_budgets())
    assert len(needs) == 1
    assert needs[0].component == "lingua"
    assert needs[0].footprint_bytes is None


def _make_fake_torch(uuids):
    class _Cuda:
        @staticmethod
        def device_count():
            return len(uuids)

        @staticmethod
        def get_device_properties(i):
            class Props:
                uuid = uuids[i]

            return Props()

    return type("_Torch", (), {"cuda": _Cuda()})()


def test_nvidia_smi_usage_maps_identical_names_by_uuid(monkeypatch):
    """Two same-name GPUs are distinguished by UUID, not name."""
    fake_torch = _make_fake_torch(["aaaa", "bbbb"])

    def fake_run(cmd, **kwargs):
        class Proc:
            returncode = 0
            stdout = "42, 1000, GPU-aaaa\n42, 500, GPU-bbbb\n"

        return Proc()

    monkeypatch.setattr("kaine.setup.footprint.subprocess.run", fake_run)

    result = _nvidia_smi_usage({42}, fake_torch)
    assert result == {"cuda:0": 1000 * (1 << 20), "cuda:1": 500 * (1 << 20)}


def test_nvidia_smi_usage_unreported_usage_for_our_pid_is_unknown(monkeypatch):
    """Our process on a GPU with usage "[N/A]" is unknown, not zero."""
    fake_torch = _make_fake_torch(["aaaa"])

    def fake_run(cmd, **kwargs):
        class Proc:
            returncode = 0
            stdout = "42, [N/A], GPU-aaaa\n7, 300, GPU-aaaa\n"

        return Proc()

    monkeypatch.setattr("kaine.setup.footprint.subprocess.run", fake_run)
    assert _nvidia_smi_usage({42}, fake_torch) is None


def test_nvidia_smi_usage_unmappable_uuid_returns_none(monkeypatch):
    """An unknown GPU UUID makes the whole measurement unknown."""
    fake_torch = _make_fake_torch(["aaaa"])

    def fake_run(cmd, **kwargs):
        class Proc:
            returncode = 0
            stdout = "42, 1000, GPU-unknown\n"

        return Proc()

    monkeypatch.setattr("kaine.setup.footprint.subprocess.run", fake_run)

    assert _nvidia_smi_usage({42}, fake_torch) is None


def test_nvidia_smi_usage_missing_binary_returns_none(monkeypatch):
    """A missing nvidia-smi binary is reported as unknown."""
    fake_torch = _make_fake_torch(["aaaa"])

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr("kaine.setup.footprint.subprocess.run", fake_run)

    assert _nvidia_smi_usage({42}, fake_torch) is None


def test_nvidia_smi_usage_other_pids_empty(monkeypatch):
    """Rows for other processes contribute nothing."""
    fake_torch = _make_fake_torch(["aaaa"])

    def fake_run(cmd, **kwargs):
        class Proc:
            returncode = 0
            stdout = "99, 1000, GPU-aaaa\n"

        return Proc()

    monkeypatch.setattr("kaine.setup.footprint.subprocess.run", fake_run)

    assert _nvidia_smi_usage({42}, fake_torch) == {}


def test_local_service_gpu_unknown_not_recorded(capsys, tmp_path, monkeypatch):
    """A local service whose GPU memory cannot be read is left uncalibrated."""
    _hermetic_selection(monkeypatch)
    svc, svc_calls = _fake_service({"http://localhost:1234": 100 << 20})

    class FakeProc:
        pid = 42

        def name(self):
            return "python"

        def children(self, recursive=False):
            return []

    monkeypatch.setattr(
        "kaine.setup.footprint._listener_root_pid", lambda url: 42
    )
    monkeypatch.setattr("kaine.setup.footprint.psutil.Process", lambda pid: FakeProc())
    monkeypatch.setattr(
        "kaine.setup.footprint._nvidia_smi_usage", lambda pids, tm: None
    )

    budgets = (
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

    config = {
        "modules": {"lingua": True},
        "lingua": {
            "backend": "openai",
            "model_id": "m",
            "chat_url": "http://localhost:1234",
        },
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "lingua"],
        config,
        tmp_path,
        capsys,
        service=svc,
        budgets_fn=lambda: budgets,
    )

    assert code == 3
    assert "http://localhost:1234" in svc_calls
    assert (
        "not measured: its GPU memory could not be read" in out
    )
    assert "Uncalibrated components: lingua" in out
    assert not cat.exists()


def test_child_failure_message_preserved(monkeypatch):
    """A child's own failure message is returned verbatim."""

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        @property
        def pid(self):
            return 1234

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

        def kill(self):
            raise AssertionError("should not kill an exited process")

    class FakeConn:
        def __init__(self):
            self.closed = False

        def poll(self, timeout):
            return True

        def recv(self):
            return {"ok": False, "error": "boom"}

        def close(self):
            self.closed = True

    def fake_get_context(name):
        class Ctx:
            def Pipe(self, duplex=False):
                return (FakeConn(), FakeConn())

            def Process(self, *args, **kwargs):
                return FakeProcess(*args, **kwargs)

        return Ctx()

    monkeypatch.setattr(
        "kaine.setup.footprint.multiprocessing.get_context", fake_get_context
    )

    ok, peak, device_bytes, device, mapped, error = _measure_callable_in_child(
        lambda: {}
    )
    assert ok is False
    assert error == "boom"


def test_stop_group_fallback_kills_process(monkeypatch):
    """If os.killpg fails, the process is killed directly."""
    from kaine.setup import footprint

    killed = []
    joined = []

    class FakeProcess:
        alive = True

        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        @property
        def pid(self):
            return 42

        def is_alive(self):
            return self.alive

        def kill(self):
            self.alive = False
            killed.append(True)

        def join(self, timeout=None):
            joined.append(timeout)

        @property
        def exitcode(self):
            return 0

    class FakeConn:
        def __init__(self):
            self.closed = False

        def poll(self, timeout):
            return False

        def recv(self):
            raise EOFError

        def close(self):
            self.closed = True

    def fake_get_context(name):
        class Ctx:
            def Pipe(self, duplex=False):
                return (FakeConn(), FakeConn())

            def Process(self, *args, **kwargs):
                return FakeProcess(*args, **kwargs)

        return Ctx()

    monkeypatch.setattr(
        "kaine.setup.footprint.multiprocessing.get_context", fake_get_context
    )
    monkeypatch.setattr(
        footprint.os,
        "killpg",
        lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError(pid)),
    )

    ok, peak, device_bytes, device, mapped, error = _measure_callable_in_child(
        lambda: {}, timeout=0.01
    )
    assert ok is False
    assert killed
    assert 5 in joined


def test_service_gpu_memory_unknown_paths_on_a_device_host(monkeypatch):
    """With a cuda:N budget, anything that hides the service's GPU use is unknown."""
    from kaine.setup.footprint import _service_gpu_memory

    def domain(name, kind):
        return Domain(
            name=name,
            kind=kind,
            total_bytes=8 << 30,
            available_bytes=7 << 30,
            reserve_bytes=1 << 30,
            budget_bytes=7 << 30,
            derivation="test",
        )

    device_host = (domain("system", "system"), domain("cuda:0", "accelerator"))
    cpu_host = (domain("system", "system"),)

    monkeypatch.setattr("kaine.setup.footprint._listener_root_pid", lambda url: None)
    assert _service_gpu_memory("http://127.0.0.1:1", device_host, None) is None
    assert _service_gpu_memory("http://127.0.0.1:1", cpu_host, None) == (None, None)

    def no_access(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr("kaine.setup.footprint._listener_root_pid", lambda url: 42)
    monkeypatch.setattr("kaine.setup.footprint.psutil.Process", no_access)
    assert _service_gpu_memory("http://127.0.0.1:1", device_host, None) is None


def test_nvidia_smi_usage_maps_prefixed_torch_uuids(monkeypatch):
    """torch versions that print the uuid with a GPU- prefix still map."""
    fake_torch = _make_fake_torch(["GPU-aaaa"])

    def fake_run(cmd, **kwargs):
        class Proc:
            returncode = 0
            stdout = "42, 1000, GPU-AAAA\n"

        return Proc()

    monkeypatch.setattr("kaine.setup.footprint.subprocess.run", fake_run)
    assert _nvidia_smi_usage({42}, fake_torch) == {"cuda:0": 1000 * (1 << 20)}
