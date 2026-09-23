# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

from kaine.preboot import check_config_sanity
from kaine.torch_stack import _load_metadata, check_torch_stack, describe_torch_stack


def test_coherent_cu130_stack():
    dists = {
        "torch": ("2.14.0+cu130", []),
        "torchvision": ("0.29.0+cu130", ["torch (==2.14.0)"]),
        "torchaudio": ("2.11.0+cu130", []),
    }
    assert check_torch_stack(dists) == []


def test_torchvision_pin_mismatch():
    dists = {
        "torch": ("2.14.0+cu130", []),
        "torchvision": ("0.26.0+cu130", ["torch==2.11.0"]),
    }
    probs = check_torch_stack(dists)
    assert len(probs) == 1
    assert "torchvision" in probs[0]
    assert "2.11.0" in probs[0]


def test_cuda_tag_mismatch():
    dists = {
        "torch": ("2.14.0+cu130", []),
        "torchaudio": ("2.11.0+cu128", []),
    }
    probs = check_torch_stack(dists)
    assert any("mixed builds" in p for p in probs)


def test_tagged_vs_untagged():
    dists = {
        "torch": ("2.14.0", []),
        "torchvision": ("0.29.0+cu130", []),
    }
    probs = check_torch_stack(dists)
    assert any("mixed builds" in p for p in probs)


def test_torch_absent():
    assert check_torch_stack({}) == []
    assert check_torch_stack({"torchvision": ("0.29.0", ["torch (==2.14.0)"])}) == []


def test_only_torch_present():
    assert check_torch_stack({"torch": ("2.14.0+cu130", [])}) == []


def test_extra_marker_ignored():
    dists = {
        "torch": ("2.14.0+cu130", []),
        "torchvision": ("0.29.0+cu130", ["torch==1.0; extra == 'dev'"]),
    }
    assert check_torch_stack(dists) == []


def test_describe_torch_stack():
    assert describe_torch_stack({"torch": ("2.14.0+cu130", [])}) == "torch 2.14.0+cu130"
    assert (
        describe_torch_stack(
            {
                "torch": ("2.14.0+cu130", []),
                "torchvision": ("0.29.0+cu130", []),
            }
        )
        == "torch 2.14.0+cu130, torchvision 0.29.0+cu130"
    )
    assert describe_torch_stack({}) == "torch not installed"
    assert describe_torch_stack({"torchvision": ("0.29.0", [])}) == "torch not installed"


def test_preboot_row(monkeypatch):
    def _problems():
        return [
            "torchaudio 2.11.0+cu128 requires torch==2.11.0 but torch 2.14.0+cu130 is installed"
        ]

    def _desc():
        return "torch 2.14.0+cu130, torchaudio 2.11.0+cu128"

    monkeypatch.setattr("kaine.preboot.check_torch_stack", _problems)
    monkeypatch.setattr("kaine.preboot.describe_torch_stack", _desc)

    results = check_config_sanity({"modules": {"soma": True}})
    row = next(r for r in results if r.name == "Torch stack")
    assert row.status == "FAIL"
    assert row.detail.endswith(" — reinstall with scripts/install.sh")
    assert "torchaudio" in row.detail

    def _no_problems():
        return []

    monkeypatch.setattr("kaine.preboot.check_torch_stack", _no_problems)
    results = check_config_sanity({"modules": {"soma": True}})
    row = next(r for r in results if r.name == "Torch stack")
    assert row.status == "PASS"
    assert row.detail == _desc()

    def _not_installed():
        return "torch not installed"

    monkeypatch.setattr("kaine.preboot.check_torch_stack", _no_problems)
    monkeypatch.setattr("kaine.preboot.describe_torch_stack", _not_installed)
    results = check_config_sanity({"modules": {"soma": True}})
    row = next(r for r in results if r.name == "Torch stack")
    assert row.status == "SKIP"
    assert row.detail == "torch not installed"


def test_no_args_against_real_environment_does_not_raise():
    result = check_torch_stack()
    assert isinstance(result, list)
    desc = describe_torch_stack()
    assert isinstance(desc, str)


def _fake_distribution(name: str) -> SimpleNamespace:
    if name == "torch":
        return SimpleNamespace(version="2.14.0+cu130", requires=[])
    if name == "torchvision":
        return SimpleNamespace(version="0.29.0+cu130", requires=["torch (==2.14.0)"])
    if name == "torchaudio":
        raise PackageNotFoundError(name)
    raise PackageNotFoundError(name)


def test_load_metadata_uses_distribution_and_skips_missing(monkeypatch):
    monkeypatch.setattr("kaine.torch_stack.distribution", _fake_distribution)
    got = _load_metadata()
    assert got == {
        "torch": ("2.14.0+cu130", []),
        "torchvision": ("0.29.0+cu130", ["torch (==2.14.0)"]),
    }


class _FakeDistribution:
    def __init__(
        self,
        version: str,
        requires: list[str] | None,
        root: Path,
        version_py: str | None = None,
    ) -> None:
        self.version = version
        self.requires = requires
        self._root = root
        self._version_py = version_py

    def locate_file(self, path: str) -> Path:
        target = self._root / path
        if self._version_py is not None and target.name == "version.py":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self._version_py, encoding="utf-8")
        return target


def test_load_metadata_prefers_version_py_build_tag_over_dist_version(tmp_path, monkeypatch):
    def _dist(name: str):
        if name == "torch":
            return _FakeDistribution(
                version="2.14.0",
                requires=[],
                root=tmp_path,
                version_py="__version__ = '2.14.0+cu130'\n",
            )
        if name == "torchvision":
            return _FakeDistribution(
                version="0.29.0",
                requires=["torch (==2.14.0)"],
                root=tmp_path,
                version_py="__version__ = '0.29.0+cu130'\n",
            )
        if name == "torchaudio":
            return _FakeDistribution(
                version="2.11.0",
                requires=[],
                root=tmp_path,
                version_py="__version__ = '2.11.0+cu130'\n",
            )
        raise PackageNotFoundError(name)

    monkeypatch.setattr("kaine.torch_stack.distribution", _dist)
    got = _load_metadata()
    assert got == {
        "torch": ("2.14.0+cu130", []),
        "torchvision": ("0.29.0+cu130", ["torch (==2.14.0)"]),
        "torchaudio": ("2.11.0+cu130", []),
    }
    assert check_torch_stack(got) == []


def test_load_metadata_reads_annotated_version_py(tmp_path, monkeypatch):
    def _dist(name: str):
        if name == "torch":
            return _FakeDistribution(
                version="2.14.0",
                requires=[],
                root=tmp_path,
                version_py='__version__: str = "2.14.0+cu130"\n',
            )
        raise PackageNotFoundError(name)

    monkeypatch.setattr("kaine.torch_stack.distribution", _dist)
    got = _load_metadata()
    assert got["torch"][0] == "2.14.0+cu130"


def test_load_metadata_falls_back_to_dist_version_when_version_py_missing(tmp_path, monkeypatch):
    def _dist(name: str):
        if name == "torch":
            return _FakeDistribution(
                version="2.14.0+cu130",
                requires=[],
                root=tmp_path,
                version_py=None,
            )
        raise PackageNotFoundError(name)

    monkeypatch.setattr("kaine.torch_stack.distribution", _dist)
    got = _load_metadata()
    assert got["torch"][0] == "2.14.0+cu130"


def test_unparseable_torch_version_returns_problem():
    dists = {"torch": ("not-a-version", [])}
    probs = check_torch_stack(dists)
    assert probs
    assert any("could not be parsed" in p for p in probs)
