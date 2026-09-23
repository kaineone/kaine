# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Review-finding regression tests for kaine/wheel_index.py."""

from __future__ import annotations

import copy
import json

from kaine.wheel_index import (
    CPU_INDEX,
    ROCM_ARCH,
    Probes,
    _arch_list_to_entries,
    _device_coverage,
    _match_table_row,
    main,
    resolve_index,
    resolve_rocm,
)

CU130 = "https://download.pytorch.org/whl/cu130"
CU129 = "https://download.pytorch.org/whl/cu129"


def _probes(arch="x86_64", driver=(12, 8), caps=((9, 0),), memory="discrete"):
    return Probes(
        arch=arch,
        driver_cuda=driver,
        compute_caps=caps,
        memory_state=memory,
        notes={},
    )


def test_ptx_coverage_requires_device_gte_ptx_level():
    assert _device_coverage((7, 5), _arch_list_to_entries("8.0;9.0;10.0;12.0+PTX")) is None
    assert _device_coverage((12, 1), _arch_list_to_entries("8.0;12.0+PTX")) is not None
    assert _device_coverage((13, 0), ["compute_120"]) == ("ptx", (12, 0))
    # same-major SASS still shadows PTX; PTX never covers a device below the entry.
    assert _device_coverage((12, 0), ["sm_120", "compute_120"]) == ("exact", None)
    assert _device_coverage((11, 0), ["compute_120"]) is None


def test_aarch64_discrete_75_driver13_resolves_under_correct_ptx_rule():
    """A 7.5 device on an aarch64 discrete host with a 13.0 driver must be
    covered by an exact sm_75 entry (PTX 12.0 does NOT cover it), so the
    ladder must not fall through to cu129/torch 2.11.0.
    """
    result = resolve_index(
        _probes(arch="aarch64", driver=(13, 0), caps=((7, 5),), memory="discrete")
    )
    assert result["index_url"] != CU129
    assert result["index_url"] != CPU_INDEX
    assert result["torch_version"] == "2.9.1"
    assert result["index_url"] == CU130
    assert result["selftest_required"] is False


def test_resolve_rocm_prefers_older_index_when_only_it_covers_target(monkeypatch):
    """A GFX target covered only by an older recorded ROCm index must select
    that older index instead of a newer one with a higher torch version.
    """
    # Without the patch the synthetic target is not covered by any index.
    bare = resolve_rocm((7, 2), "gfx1234", "x86_64")
    assert bare["index_url"] is None

    patched = copy.deepcopy(ROCM_ARCH)
    # Add a synthetic target that is only present in the 2.9.1 ROCm entry.
    patched["2.9.1"]["gfx"] = [*patched["2.9.1"]["gfx"], "gfx1234"]
    monkeypatch.setattr("kaine.wheel_index.ROCM_ARCH", patched)

    result = resolve_rocm((7, 2), "gfx1234", "x86_64")
    assert result["index_url"] == "https://download.pytorch.org/whl/rocm6.4"
    assert result["torch_version"] == "2.9.1"


def test_resolve_rocm_refuses_uncovered_targets_with_warning():
    result = resolve_rocm((7, 2), "gfx9999", "x86_64")
    assert result["index_url"] is None
    assert result["torch_version"] is None
    joined = " ".join(result["warnings"])
    assert "gfx9999" in joined
    assert "no rocm index" in joined.lower()


def test_aarch64_unknown_memory_triggers_selftest_on_cuda13_index():
    result = resolve_index(
        _probes(arch="aarch64", driver=(13, 2), caps=((9, 0),), memory="unknown")
    )
    assert result["index_url"] != CPU_INDEX
    assert result["selftest_required"] is True
    joined = " ".join(result["warnings"]).lower()
    assert "memory classification is unknown" in joined
    assert "self-test" in joined


def test_aarch64_unified_memory_selftest_warning_unchanged():
    result = resolve_index(
        _probes(arch="aarch64", driver=(13, 2), caps=((8, 7),), memory="unified")
    )
    assert result["selftest_required"] is True
    joined = " ".join(result["warnings"]).lower()
    assert "nan" in joined


def test_unasserted_torchaudio_pairing_warning_in_cuda_ladder():
    # cu130 torch 2.14.0 ships with torchaudio 2.11.0 (different minor).
    probes = _probes(arch="x86_64", driver=(13, 0), caps=((8, 0),))
    result = resolve_index(probes, need_torchaudio=True)
    assert result["index_url"] == CU130
    assert result["torch_version"] == "2.14.0"
    assert result["torchaudio_version"] == "2.11.0"
    joined = " ".join(result["warnings"])
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" in joined
    assert "no published wheel metadata asserts this pairing" in joined

    silent = resolve_index(probes)
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" not in " ".join(silent["warnings"])


def test_unasserted_torchaudio_pairing_warning_in_cpu_ladder():
    probes = _probes(arch="x86_64", driver=(12, 4), caps=((8, 0),))
    result = resolve_index(probes, need_torchaudio=True)
    assert result["index_url"] == CPU_INDEX
    assert result["torch_version"] == "2.14.0"
    assert result["torchaudio_version"] == "2.11.0"
    joined = " ".join(result["warnings"])
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" in joined

    silent = resolve_index(probes)
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" not in " ".join(silent["warnings"])


def test_unasserted_torchaudio_pairing_warning_in_operator_override():
    probes = _probes(arch="x86_64", driver=(13, 0), caps=((8, 0),))
    result = resolve_index(
        probes,
        override="https://download.pytorch.org/whl/cu130",
        need_torchaudio=True,
    )
    assert result["torch_version"] == "2.14.0"
    assert result["torchaudio_version"] == "2.11.0"
    joined = " ".join(result["warnings"])
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" in joined

    silent = resolve_index(probes, override="https://download.pytorch.org/whl/cu130")
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" not in " ".join(silent["warnings"])


def test_unasserted_torchaudio_pairing_warning_in_rocm():
    result = resolve_rocm((7, 2), "gfx1100", "x86_64", need_torchaudio=True)
    assert result["torch_version"] == "2.14.0"
    assert result["torchaudio_version"] == "2.11.0"
    joined = " ".join(result["warnings"])
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" in joined

    silent = resolve_rocm((7, 2), "gfx1100", "x86_64")
    assert "torchaudio 2.11.0 is paired with torch 2.14.0" not in " ".join(silent["warnings"])


def test_operator_override_torchaudio_unavailable_flag_and_warning():
    result = resolve_index(
        _probes(arch="x86_64", driver=(13, 2), caps=((8, 9),)),
        override="https://download.pytorch.org/whl/cu132",
        need_torchaudio=True,
    )
    assert result.get("torchaudio_unavailable") is True
    joined = " ".join(result["warnings"])
    assert "publishes no torchaudio" in joined
    assert "the --research install needs torchaudio" in joined


def test_operator_override_with_torchaudio_available_flag_is_false():
    result = resolve_index(
        _probes(arch="x86_64", driver=(13, 0), caps=((8, 0),)),
        override="https://download.pytorch.org/whl/cu130",
        need_torchaudio=True,
    )
    assert result.get("torchaudio_unavailable") is False
    joined = " ".join(result["warnings"])
    assert "publishes no torchaudio" not in joined


def test_coerce_rocm_version_accepts_strings_and_pairs():
    """_coerce_rocm_version returns a (major, minor) pair or None."""
    from kaine.wheel_index import _coerce_rocm_version

    assert _coerce_rocm_version("7.2") == (7, 2)
    assert _coerce_rocm_version((6, 4)) == (6, 4)
    assert _coerce_rocm_version(3) is None
    assert _coerce_rocm_version(("a", "b")) is None


def test_cli_need_torchaudio_override_emits_torchaudio_unavailable(capsys, monkeypatch):
    monkeypatch.setenv("KAINE_WHEEL_PROBE_NVML", "0")
    rc = main([
        "--index-url", "https://download.pytorch.org/whl/cu132",
        "--need-torchaudio",
    ])
    assert rc == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result.get("torchaudio_unavailable") is True
    warnings = " ".join(result.get("warnings", []))
    assert "publishes no torchaudio" in warnings
    assert result["index_url"] == "https://download.pytorch.org/whl/cu132"


def test_decision_table_12_5_driver_matches_cpu_row():
    x86_row = _match_table_row(
        _probes(arch="x86_64", driver=(12, 5), caps=((8, 0),), memory="discrete"),
        CPU_INDEX,
    )
    assert x86_row is not None
    assert x86_row["row"] == 6

    aarch64_row = _match_table_row(
        _probes(arch="aarch64", driver=(12, 5), caps=((9, 0),), memory="discrete"),
        CPU_INDEX,
    )
    assert aarch64_row is not None
    assert aarch64_row["row"] == 12


def test_resolve_fixed_flavor_cpu_matches_recorded_companions():
    """The CPU resolver picks the newest in-range torch and its companions per arch."""

    from kaine.wheel_index import (
        COMPANIONS,
        PUBLISHED,
        _in_range,
        _parse_spec,
        _vtuple,
        project_torch_spec,
        resolve_fixed_flavor,
    )

    spec = project_torch_spec()
    spec_list = _parse_spec(spec)
    for test_arch in ("x86_64", "aarch64"):
        candidates = PUBLISHED["cpu"].get(test_arch, ())
        expected = next(
            (v for v in sorted(candidates, key=_vtuple, reverse=True) if _in_range(v, spec_list)),
            None,
        )
        result = resolve_fixed_flavor("cpu", test_arch)
        assert result["variant"] == "cpu"
        assert result["index_url"] == "https://download.pytorch.org/whl/cpu"
        assert result["torch_version"] == expected
        assert result["torchvision_version"] == COMPANIONS["cpu"].get(test_arch, {}).get(expected, {}).get("torchvision")
        assert result["torchaudio_version"] == COMPANIONS["cpu"].get(test_arch, {}).get(expected, {}).get("torchaudio")
        assert result["selftest_required"] is False
        assert result["torch_spec"] == spec


def test_resolve_fixed_flavor_xpu_x86_64_matches_recorded_companions():
    """The XPU resolver picks the newest in-range x86_64 torch and its companions."""
    from kaine.wheel_index import (
        COMPANIONS,
        PUBLISHED,
        _in_range,
        _parse_spec,
        _vtuple,
        project_torch_spec,
        resolve_fixed_flavor,
    )

    spec_list = _parse_spec(project_torch_spec())
    candidates = PUBLISHED["xpu"]["x86_64"]
    expected = next(
        v for v in sorted(candidates, key=_vtuple, reverse=True) if _in_range(v, spec_list)
    )
    result = resolve_fixed_flavor("xpu", "x86_64")
    assert result["variant"] == "xpu"
    assert result["index_url"] == "https://download.pytorch.org/whl/xpu"
    assert result["torch_version"] == expected
    companions = COMPANIONS["xpu"]["x86_64"][expected]
    assert result["torchvision_version"] == companions["torchvision"]
    assert result["torchaudio_version"] == companions.get("torchaudio")


def test_resolve_fixed_flavor_xpu_aarch64_refuses_with_warning():
    """XPU wheels are recorded for x86_64 only; aarch64 gets a clear refusal."""
    from kaine.wheel_index import project_torch_spec, resolve_fixed_flavor

    spec = project_torch_spec()
    result = resolve_fixed_flavor("xpu", "aarch64")
    assert result["variant"] == "xpu"
    assert result["index_url"] is None
    assert result["torch_version"] is None
    expected = f"no in-range torch published on the xpu index for aarch64 (range {spec})"
    assert any(w == expected for w in result["warnings"])


def test_resolve_fixed_flavor_need_torchaudio_prefers_and_warns(monkeypatch):
    """With need_torchaudio, the highest torch that has a companion wins; a mm mismatch warns."""
    from kaine.wheel_index import resolve_fixed_flavor

    monkeypatch.setattr(
        "kaine.wheel_index.PUBLISHED",
        {
            "cpu": {"x86_64": ("2.14.0", "2.13.0", "2.11.0")},
        },
    )
    monkeypatch.setattr(
        "kaine.wheel_index.COMPANIONS",
        {
            "cpu": {
                "x86_64": {
                    "2.14.0": {"torchvision": "0.19.0"},  # no torchaudio
                    "2.13.0": {"torchvision": "0.18.0", "torchaudio": "2.11.0"},  # mismatched mm
                    "2.11.0": {"torchvision": "0.16.0", "torchaudio": "2.11.0"},
                }
            }
        },
    )
    result = resolve_fixed_flavor("cpu", "x86_64", spec=">=2.11.0,<2.15", need_torchaudio=True)
    assert result["torch_version"] == "2.13.0"
    assert result["torchaudio_version"] == "2.11.0"
    assert any("paired with torch 2.13.0 by release timing only" in w for w in result["warnings"])


def test_cli_flavor_cpu_outputs_resolution_json(capsys, monkeypatch):
    """--flavor cpu prints the same JSON the installers consume."""
    import json
    import platform
    import sys

    from kaine import wheel_index as wi

    monkeypatch.setattr(sys, "argv", ["kaine.wheel_index", "--flavor", "cpu"])
    rc = wi.main()
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    expected = wi.resolve_fixed_flavor("cpu", wi._normalize_arch(platform.machine()))
    assert data["variant"] == "cpu"
    assert data["index_url"] == expected["index_url"]
    assert data["torch_version"] == expected["torch_version"]


def test_cli_flavor_bogus_outputs_refusal_json(capsys, monkeypatch):
    """--flavor with an unsupported value refuses in JSON without crashing."""
    import json
    import sys

    from kaine import wheel_index as wi

    monkeypatch.setattr(sys, "argv", ["kaine.wheel_index", "--flavor", "bogus"])
    rc = wi.main()
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["index_url"] is None
    assert any("unsupported --flavor bogus" in w for w in data["warnings"])
