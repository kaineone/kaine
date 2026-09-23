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
