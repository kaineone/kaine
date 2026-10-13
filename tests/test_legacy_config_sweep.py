# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Every config key the keys rename moves has a reader alias: normalizing the pre-rename shipped config gives exactly what the codemod writes."""

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tomllib

import pytest

from kaine import legacy_aliases, legacy_names

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "legacy_config"
CODEMOD_PATH = REPO_ROOT / "tools" / "maintainer" / "rename_modules.py"
LEGACY_NAMES_PATH = REPO_ROOT / "kaine" / "legacy_names.py"


def _load_codemod():
    spec = importlib.util.spec_from_file_location("rename_modules", CODEMOD_PATH)
    rename_modules = importlib.util.module_from_spec(spec)
    sys.modules["rename_modules"] = rename_modules
    spec.loader.exec_module(rename_modules)
    return rename_modules


def _fixture_to_repo_path(rel_path: pathlib.Path) -> pathlib.Path:
    rel_str = rel_path.as_posix()
    if rel_str == "kaine.toml":
        return pathlib.Path("config/kaine.toml")
    if rel_str.startswith("profiles/"):
        return pathlib.Path("config") / rel_path
    if rel_str.startswith("studies/"):
        return pathlib.Path("config") / rel_path
    if rel_path.name == "kaine_cl1.example.toml":
        return pathlib.Path("plugins/kaine-cl1/config/kaine_cl1.example.toml")
    raise ValueError(f"unexpected fixture path: {rel_path}")


def _recursive_diff(old, new, path=()):
    diffs = []
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old) | set(new)
        for key in sorted(all_keys):
            subpath = path + (key,)
            if key in old and key not in new:
                diffs.append(f"only in old: {'.'.join(subpath)}")
            elif key in new and key not in old:
                diffs.append(f"only in new: {'.'.join(subpath)}")
            else:
                diffs.extend(_recursive_diff(old[key], new[key], subpath))
    elif old != new:
        diffs.append(f"differ at {'.'.join(path)}: {old!r} != {new!r}")
    return diffs


def _collect_toml_fixtures():
    toml_files = []
    for fixture_path in sorted(FIXTURE.rglob("*.toml")):
        rel = fixture_path.relative_to(FIXTURE)
        try:
            _fixture_to_repo_path(rel)
        except ValueError:
            continue
        toml_files.append(rel)
    return toml_files


TOML_FIXTURES = _collect_toml_fixtures()


@pytest.fixture
def rename_modules():
    return _load_codemod()


@pytest.fixture
def renamed_repo(tmp_path, monkeypatch, rename_modules):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "plugins" / "kaine-cl1" / "config").mkdir(parents=True)

    for rel in TOML_FIXTURES:
        src = FIXTURE / rel
        dst = repo / _fixture_to_repo_path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )

    try:
        ret = rename_modules.main(
            [
                "--apply",
                "--scope",
                "keys",
                "--root",
                str(repo),
                "--table",
                str(LEGACY_NAMES_PATH),
            ]
        )
    except SystemExit as exc:
        ret = exc.code

    if ret is None:
        ret = 0
    assert ret == 0, f"codemod exited {ret!r} for {repo}"

    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    return repo


def test_shipped_config_keys_match_codemod(renamed_repo):
    mismatches = []
    for rel in TOML_FIXTURES:
        old = tomllib.loads((FIXTURE / rel).read_text(encoding="utf-8"))
        new = tomllib.loads((renamed_repo / _fixture_to_repo_path(rel)).read_text(encoding="utf-8"))
        normalized = legacy_aliases.normalize_config_layer(old, str(rel))

        if normalized != new:
            diff = "\n".join(_recursive_diff(normalized, new))
            mismatches.append(f"{rel}:\n{diff}")

    assert not mismatches, "\n\n".join(mismatches)


def test_old_shipped_config_normalizes_without_conflict(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    old = tomllib.loads((FIXTURE / "kaine.toml").read_text(encoding="utf-8"))
    legacy_aliases.normalize_config_layer(old, "kaine.toml")
