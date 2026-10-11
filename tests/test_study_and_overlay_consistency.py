# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from kaine.research.ignition_study.__main__ import main
from kaine.research.ignition_study.plan import validate_plan
from kaine.storage import set_data_root


@pytest.fixture
def known_modules(monkeypatch):
    names = [
        "echo",
        "soma",
        "chronos",
        "topos",
        "nous",
        "mnemos",
        "eidolon",
        "thymos",
        "praxis",
        "lingua",
        "vox",
        "audition",
        "hypnos",
        "empatheia",
        "phantasia",
        "perception",
        "mundus",
    ]
    monkeypatch.setattr("kaine.boot.known_module_names", lambda: names)
    return names


@pytest.fixture
def base_plan(tmp_path, known_modules):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest = repo_root / "programme.toml"
    manifest.write_text("# programme manifest")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    cfg = repo_root / "config"
    cfg.mkdir()
    (cfg / "kaine.toml").write_text("[modules]\n")
    (cfg / "profiles").mkdir()
    return {
        "study_id": "ignite-test",
        "repo_root": str(repo_root),
        "base_modules": ["soma", "chronos", "topos", "audition", "lingua"],
        "order": ["thymos", "mnemos"],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "gestation": "t_g_",
            "branch": "t_b_",
            "repeat": "t_r_",
            "accumulate": "t_a_",
        },
    }


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    # main() installs the data root from the configuration on every call, so the
    # root is set the way an operator sets it: through KAINE_DATA_ROOT.
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("KAINE_DATA_ROOT", str(root))
    # The runner checks the plan against the operator's bus, which needs a password.
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", "test-only")
    yield root
    set_data_root(None)


def _init_args(plan: dict) -> list[str]:
    return [
        "init",
        "--study-id",
        plan["study_id"],
        "--study-dir",
        f"studies/{plan['study_id']}",
        "--repo-root",
        plan["repo_root"],
        "--base-modules",
        *plan["base_modules"],
        "--order",
        *plan["order"],
        "--programme-manifest",
        plan["programme"]["manifest"],
        "--redis-base-url",
        plan["redis"]["base_url"],
        "--db-gestation",
        str(plan["redis"]["db"]["gestation"]),
        "--db-branch",
        str(plan["redis"]["db"]["branch"]),
        "--db-repeat",
        str(plan["redis"]["db"]["repeat"]),
        "--db-accumulate",
        str(plan["redis"]["db"]["accumulate"]),
    ]


def test_status_finds_study_created_under_the_data_root(base_plan, data_root):
    # The working directory is the repository (where the configuration loads),
    # not the data root: init writes under the data root, and status must look
    # there too rather than relative to the working directory.
    plan = validate_plan(base_plan)
    assert main(_init_args(plan)) == 0
    assert (data_root / "studies" / plan["study_id"] / "study.json").exists()
    assert main(["status", "--study-dir", f"studies/{plan['study_id']}"]) == 0


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _merge_services(base: dict, overlay: dict) -> dict:
    merged = {svc: dict(cfg) for svc, cfg in base.get("services", {}).items()}
    for svc, cfg in overlay.get("services", {}).items():
        base_svc = merged.get(svc, {})
        merged_svc = dict(base_svc)
        for key, value in cfg.items():
            if key == "deploy":
                merged_svc[key] = value
            else:
                merged_svc[key] = value
        merged[svc] = merged_svc
    return merged


def test_cpu_overlay_has_no_gpu_reservations():
    base = yaml.safe_load((_repo_root() / "compose" / "kaine.yml").read_text())
    cpu = yaml.safe_load((_repo_root() / "compose" / "kaine.cpu.yml").read_text())
    merged = _merge_services(base, cpu)
    for svc, cfg in merged.items():
        devices = (
            cfg.get("deploy", {})
            .get("resources", {})
            .get("reservations", {})
            .get("devices")
        )
        assert devices is None or devices == [], (
            f"{svc} still has a GPU reservation: {devices}"
        )


def test_single_gpu_overlay_pins_study_to_card_zero():
    base = yaml.safe_load((_repo_root() / "compose" / "kaine.yml").read_text())
    gpu = yaml.safe_load(
        (_repo_root() / "compose" / "kaine.single-gpu.yml").read_text()
    )
    merged = _merge_services(base, gpu)
    pinned = {"kaine-study", "kaine-cycle", "kaine-chatterbox"}
    for svc, cfg in merged.items():
        devices = (
            cfg.get("deploy", {})
            .get("resources", {})
            .get("reservations", {})
            .get("devices")
        )
        if not devices:
            continue
        device_ids = devices[0].get("device_ids", [])
        if svc in pinned:
            assert device_ids == ["0"], (
                f"{svc} should be pinned to card 0, got {device_ids}"
            )
        else:
            assert device_ids, f"{svc} has no GPU reservation"
            for did in device_ids:
                assert did.startswith("${KAINE_ORGAN_GPU:-0}") or did.startswith(
                    "${KAINE_TRAINER_GPU:-${KAINE_ORGAN_GPU:-0}}"
                ), f"{svc} device id does not default to card 0: {did}"
