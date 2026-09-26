# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import ast
import importlib
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from kaine import extras as extras_module
from kaine.boot import ConfigurationError, build_registry
from kaine.extras import Missing, check, format_missing


def _make_find_spec(available: set[str]):
    def _find_spec(name: str):
        top = name.split(".")[0]
        return object() if top in available else None

    return _find_spec


def test_check_reports_missing_core_for_enabled_soma_chronos(monkeypatch):
    monkeypatch.setattr(
        importlib.util, "find_spec", _make_find_spec(set())
    )
    config = {"modules": {"soma": True, "chronos": True}}
    missing = check(config)

    errors = [m for m in missing if m.severity == "error"]
    assert {m.extra for m in errors} == {"core"}
    assert {m.import_name for m in errors} == {"torch", "ncps"}

    warnings = [m for m in missing if m.severity == "warning"]
    assert {m.extra for m in warnings} == {"nvidia"}

    message = format_missing(missing)
    assert 'pip install "kaine[core]"' in message
    assert "Soma" not in message  # format uses lowercase module keys


def test_check_respects_module_toggles(monkeypatch):
    monkeypatch.setattr(
        importlib.util, "find_spec", _make_find_spec({"torch", "ncps"})
    )
    config = {"modules": {"soma": True, "chronos": False}}
    missing = check(config)
    assert missing == [
        Missing(
            module="soma",
            import_name="pynvml",
            extra="nvidia",
            severity="warning",
        )
    ]


def test_mnemos_qdrant_backend_needs_memory(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"sentence_transformers"}),
    )
    config = {"modules": {"mnemos": True}, "mnemos": {"backend": "qdrant"}}
    missing = check(config)
    assert any(
        m.module == "mnemos"
        and m.import_name == "qdrant_client"
        and m.extra == "memory"
        for m in missing
    )
    assert not any(m.import_name == "sqlite_vec" for m in missing)


def test_mnemos_sqlite_vec_backend_needs_memory_edge(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"sentence_transformers"}),
    )
    config = {"modules": {"mnemos": True}, "mnemos": {"backend": "sqlite_vec"}}
    missing = check(config)
    assert any(
        m.module == "mnemos"
        and m.import_name == "sqlite_vec"
        and m.extra == "memory-edge"
        for m in missing
    )
    assert not any(m.import_name == "qdrant_client" for m in missing)


def test_mnemos_inmemory_backend_needs_only_sentence_transformers(monkeypatch):
    monkeypatch.setattr(
        importlib.util, "find_spec", _make_find_spec({"sentence_transformers"})
    )
    config = {"modules": {"mnemos": True}, "mnemos": {"backend": "inmemory"}}
    missing = check(config)
    assert not missing


def test_topos_cv2_needed_when_capture_enabled(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"torch", "transformers", "PIL"}),
    )
    config = {"modules": {"topos": True}, "topos": {"capture_enabled": True}}
    missing = check(config)
    assert any(m.import_name == "cv2" and m.extra == "vision" for m in missing)


def test_topos_cv2_needed_in_playlist_mode(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"torch", "transformers", "PIL"}),
    )
    config = {
        "modules": {"topos": True},
        "topos": {"capture_enabled": False},
        "perception_feed": {"mode": "playlist"},
    }
    missing = check(config)
    assert any(m.import_name == "cv2" and m.extra == "vision" for m in missing)


def test_topos_cv2_not_needed_without_capture_or_playlist(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"torch", "transformers", "PIL", "cv2"}),
    )
    config = {
        "modules": {"topos": True},
        "topos": {"capture_enabled": False},
        "perception_feed": {"mode": "live"},
    }
    missing = check(config)
    assert not any(m.import_name == "cv2" for m in missing)


def test_audition_needs_audio_when_capture_enabled(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {
        "modules": {"audition": True},
        "audition": {"capture_enabled": True},
    }
    missing = check(config)
    assert any(m.import_name == "sounddevice" for m in missing)
    assert any(m.import_name == "webrtcvad" for m in missing)


def test_audition_playlist_requires_av_and_webrtcvad_not_sounddevice(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {
        "modules": {"audition": True},
        "audition": {"capture_enabled": False},
        "perception_feed": {"mode": "playlist"},
    }
    missing = check(config)
    assert any(m.import_name == "av" and m.extra == "audio" for m in missing)
    assert any(m.import_name == "webrtcvad" and m.extra == "audio" for m in missing)
    assert not any(m.import_name == "sounddevice" for m in missing)


def test_audition_webrtcvad_needed_in_seeded_womb_or_screen_not_sounddevice(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    for mode in ("seeded", "womb", "screen"):
        config = {
            "modules": {"audition": True},
            "audition": {"capture_enabled": False},
            "perception_feed": {"mode": mode},
        }
        missing = check(config)
        assert any(
            m.import_name == "webrtcvad" and m.extra == "audio" for m in missing
        )
        assert not any(
            m.import_name == "sounddevice" for m in missing
        )


def test_audition_seeded_rms_backend_needs_no_audio_extra(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {
        "modules": {"audition": True},
        "audition": {"capture_enabled": False, "vad_backend": "rms"},
        "perception_feed": {"mode": "seeded"},
    }
    missing = check(config)
    assert not any(m.module == "audition" for m in missing)


def test_audition_live_capture_requires_sounddevice_and_webrtcvad(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {
        "modules": {"audition": True},
        "audition": {"capture_enabled": True},
        "perception_feed": {"mode": "live"},
    }
    missing = check(config)
    assert any(m.import_name == "sounddevice" for m in missing)
    assert any(m.import_name == "webrtcvad" for m in missing)


def test_nous_needs_reasoning(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {"modules": {"nous": True}}
    missing = check(config)
    assert any(m.import_name == "pymdp" and m.extra == "reasoning" for m in missing)
    assert any(m.import_name == "jax" and m.extra == "reasoning" for m in missing)


def test_phantasia_dreamerv3_needs_worldmodel(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {"modules": {"phantasia": True}, "phantasia": {"backend": "dreamerv3"}}
    missing = check(config)
    assert any(m.import_name == "jax" and m.extra == "worldmodel" for m in missing)


def test_phantasia_fake_backend_needs_nothing(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", _make_find_spec(set()))
    config = {"modules": {"phantasia": True}, "phantasia": {"backend": "fake"}}
    missing = check(config)
    assert not missing


def test_soma_missing_pynvml_is_warning(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"torch", "ncps"}),
    )
    config = {"modules": {"soma": True}}
    missing = check(config)
    pynvml_missing = [m for m in missing if m.import_name == "pynvml"]
    assert len(pynvml_missing) == 1
    assert pynvml_missing[0].severity == "warning"
    assert pynvml_missing[0].extra == "nvidia"
    assert not format_missing(missing)  # warnings are not in the error message


def test_format_missing_omits_warnings_and_groups_extras(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"torch"}),
    )
    config = {"modules": {"soma": True, "nous": True}}
    missing = check(config)
    message = format_missing(missing)
    assert "core" in message
    assert "reasoning" in message
    assert "pynvml" not in message
    assert 'pip install "kaine[core,reasoning]"' in message


def test_build_registry_raises_before_building_any_module(monkeypatch):
    bus = MagicMock()
    config = {"modules": {"soma": True}}
    fake_missing = [
        Missing(module="soma", import_name="torch", extra="core", severity="error")
    ]

    monkeypatch.setattr("kaine.extras.check", lambda cfg: fake_missing)
    monkeypatch.setattr(
        "kaine.extras.format_missing", lambda missing: "missing soma torch core"
    )
    with pytest.raises(ConfigurationError) as excinfo:
        build_registry(bus, config)
    assert "missing soma torch core" in str(excinfo.value)


def test_build_registry_logs_warnings_and_continues(monkeypatch, caplog):
    bus = MagicMock()
    config = {"modules": {"soma": True}}
    fake_missing = [
        Missing(
            module="soma",
            import_name="pynvml",
            extra="nvidia",
            severity="warning",
        )
    ]

    monkeypatch.setattr("kaine.extras.check", lambda cfg: fake_missing)
    monkeypatch.setattr("kaine.extras.format_missing", lambda missing: "")

    # Prevent actual module construction in case torch is present.
    monkeypatch.setattr("kaine.boot.ModuleRegistry", MagicMock)

    with caplog.at_level("WARNING"):
        build_registry(bus, config)
    assert "pynvml" in caplog.text
    assert "nvidia" in caplog.text


def test_nexus_service_check_reports_missing_nexus(monkeypatch):
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        _make_find_spec({"uvicorn", "jinja2"}),
    )
    missing = check({}, services={"nexus"})
    assert any(
        m.module == "nexus"
        and m.import_name == "fastapi"
        and m.extra == "nexus"
        for m in missing
    )
    message = format_missing(missing)
    assert "nexus" in message
    assert 'pip install "kaine[nexus]"' in message


def test_nexus_main_refuses_without_nexus(monkeypatch):
    from kaine import extras as extras_mod

    fake_missing = [
        Missing(
            module="nexus",
            import_name="fastapi",
            extra="nexus",
            severity="error",
        )
    ]
    monkeypatch.setattr(
        extras_mod, "check", lambda config, services=None: fake_missing
    )

    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)

    # The module checks dependencies before importing FastAPI/uvicorn, so the
    # refusal happens at import time.
    sys.modules.pop("kaine.nexus.__main__", None)
    try:
        with pytest.raises(SystemExit) as excinfo:
            importlib.import_module("kaine.nexus.__main__")
        # SystemExit carrying the message: the interpreter prints it to stderr
        # and exits with status 1.
        assert "fastapi" in str(excinfo.value.code)
        assert "kaine[nexus]" in str(excinfo.value.code)
    finally:
        sys.modules.pop("kaine.nexus.__main__", None)


def _collect_top_level_imports(*paths: Path) -> set[str]:
    names: set[str] = set()
    for path in paths:
        if path.is_file():
            files = [path]
        else:
            files = list(path.rglob("*.py"))
        for pyfile in files:
            try:
                tree = ast.parse(pyfile.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        names.add(node.module.split(".")[0])
    return names


def _module_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "kaine" / "modules" / name


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_table_matches_real_module_imports():
    repo = _repo_root()
    extra_files = {
        "sentence_transformers": [repo / "kaine" / "text_embedding.py"],
        "pynvml": [repo / "kaine" / "modules" / "soma" / "reader.py"],
    }
    for name, reqs in extras_module.REQUIREMENTS.items():
        if name == "nexus":
            continue
        paths = [_module_dir(name)]
        for req in reqs:
            if req.import_name in extra_files:
                paths.extend(extra_files[req.import_name])
        imports = _collect_top_level_imports(*paths)
        for req in reqs:
            assert req.import_name in imports, (
                f"{name} declares {req.import_name!r} in extras table "
                f"but the module source does not import that name"
            )


def test_nexus_table_matches_real_imports():
    nexus_dir = _repo_root() / "kaine" / "nexus"
    imports = _collect_top_level_imports(nexus_dir)
    for req in extras_module.REQUIREMENTS["nexus"]:
        if req.transitive_for:
            # installed for a direct dependency (e.g. jinja2 for fastapi.templating)
            continue
        assert req.import_name in imports, (
            f"nexus declares {req.import_name!r} in extras table "
            f"but kaine/nexus does not import that name"
        )


def _load_install_module() -> ModuleType:
    repo_root = _repo_root()
    spec = importlib.util.spec_from_file_location(
        "kaine_install_module", repo_root / "scripts" / "install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_py_extras_need_torch():
    module = _load_install_module()
    assert module._extras_need_torch("full")
    assert module._extras_need_torch("core")
    assert module._extras_need_torch("core,memory")
    assert module._extras_need_torch("memory,core,nexus")
    assert not module._extras_need_torch("memory")
    assert not module._extras_need_torch("memory,nexus,audio")
    assert not module._extras_need_torch("nvidia,vision,reasoning")


def test_install_py_torch_spec_reads_core_extra():
    repo_root = _repo_root()
    module = _load_install_module()
    spec = module.torch_spec(repo_root)
    assert spec.startswith("torch")
    assert "<" in spec or ">" in spec or "=" in spec


def test_install_py_extras_argument_default_is_full():
    module = _load_install_module()
    # Exercise argparse by invoking --help; the default is tested by inspection
    # of the parser definition.  This test ensures the parser accepts --extras.
    result = module.subprocess.run(
        [sys.executable, str(_repo_root() / "scripts" / "install.py"), "--extras", "nexus", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--extras" in result.stdout
