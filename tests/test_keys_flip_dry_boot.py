# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Dry boot of the renamed tree: the shipped config, the base-thesis profile, an operator overlay written with the old module names and a study written with the old names all boot, each old-named file gives one deprecation line, and a layer that sets both names is refused."""

import asyncio
import base64
import copy
import logging
import os
import shutil
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.boot.registry import build_registry, known_module_names
from kaine.bus.client import AsyncBus
from kaine.config import ProfileError, load_kaine_config

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    legacy_names.SCOPE_STATUS.get("keys") != "done",
    reason="keys scope pending",
)

OLD_OVERLAY = """
[modules]
soma = true
chronos = true
lingua = true
thymos = true
hypnos = true
mnemos = true

[thymos]
soma_stream = "soma.out"

[mnemos.qdrant]
api_key = "test-key"

[empatheia.qdrant]
api_key = "test-key"

[perception_feed]
mode = "womb"

[perception_feed.womb]
birth_transition_seconds = 5

[nexus]
port = 9100
"""


@pytest.fixture(autouse=True)
def state_key_and_warnings(monkeypatch):
    """Provide a state key and collect legacy deprecation warnings."""
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    warnings = []
    logger = logging.getLogger("kaine.legacy")
    old_propagate = logger.propagate

    class Grab(logging.Handler):
        """Collect deprecation messages."""
        def emit(self, record):
            """Store the formatted record message."""
            warnings.append(record.getMessage())

    handler = Grab()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    yield warnings
    logger.removeHandler(handler)
    logger.propagate = old_propagate


@pytest.fixture
def files(tmp_path):
    """Write overlays and the copied study into tmp_path."""
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "old.operator.toml").write_text(OLD_OVERLAY)
    (overlays / "both.operator.toml").write_text("[thymos]\nx = 1\n[affect]\nx = 2\n")
    (overlays / "empty.operator.toml").write_text("")
    studies = tmp_path / "studies"
    studies.mkdir()
    src = REPO / "tests" / "fixtures" / "legacy_config" / "studies" / "workspace_mediation_pilot_matched.toml"
    shutil.copy(src, studies / "oldstudy.toml")
    return {"overlays": overlays, "studies": studies}


def load(op, **kw):
    """Load the shipped config with the given overlay and options."""
    cfg = copy.deepcopy(
        load_kaine_config(
            REPO / "config" / "kaine.toml",
            op,
            profiles_dir=REPO / "config" / "profiles",
            **kw,
        )
    )
    for name in ("episodic_memory", "social_cognition"):
        cfg.setdefault(name, {}).setdefault("qdrant", {}).setdefault("api_key", "test-key")
    return cfg


def boot(cfg, all_on=False):
    """Build the registry and run the dry boot phases."""
    from kaine.boot import _stimulus_source_params
    from kaine.cycle import __main__ as cm
    from kaine.cycle.boot_context import BootContext

    if all_on:
        for n in known_module_names():
            cfg["modules"][n] = True
    enabled = sorted(n for n, v in (cfg.get("modules") or {}).items() if v)
    reg = build_registry(MagicMock(spec=AsyncBus), cfg)
    names = sorted(m.name for m in reg.all_modules())
    ctx = BootContext()
    ctx.kaine_config = cfg
    ctx.registry = reg
    ctx.run_ctx = types.SimpleNamespace(run_id="dry-boot", seed=7)
    ctx.intent_secret = cm.generate_intent_secret()
    for phase in (cm._phase_workspace, cm._phase_action_selection):
        rc = asyncio.run(phase(ctx))
        if rc is not None:
            raise RuntimeError(f"{phase.__name__} returned {rc}")
    _stimulus_source_params(cfg.get("perception_feed") or {})
    missing = sorted(set(enabled) & set(known_module_names()) - set(names))
    if missing:
        raise RuntimeError(f"enabled but not registered: {missing}")
    return names


@pytest.mark.parametrize(
    "label, op_name, profile, study, use_studies_dir, all_on, deprecated_file",
    [
        ("shipped", "empty.operator.toml", None, None, False, False, None),
        ("shipped with all modules", "empty.operator.toml", None, None, False, True, None),
        ("thesis_test", "empty.operator.toml", "thesis_test", None, False, False, None),
        ("thesis_test with all modules", "empty.operator.toml", "thesis_test", None, False, True, None),
        ("old-named-operator-overlay", "old.operator.toml", "thesis_test", None, False, False, "old.operator.toml"),
        ("old-named-study", "empty.operator.toml", None, "oldstudy", True, False, "oldstudy.toml"),
    ],
)
def test_dry_boot(
    label,
    op_name,
    profile,
    study,
    use_studies_dir,
    all_on,
    deprecated_file,
    files,
    state_key_and_warnings,
):
    """Each configured layer boots and deprecation warnings are tracked."""
    warnings = state_key_and_warnings
    before = len(warnings)
    studies_dir = files["studies"] if use_studies_dir else None
    cfg = load(files["overlays"] / op_name, profile=profile, study=study, studies_dir=studies_dir)
    boot(cfg, all_on=all_on)
    new = warnings[before:]
    if deprecated_file:
        assert len(new) == 1
        assert deprecated_file in new[0]
        assert "deprecated names" in new[0].lower()
    else:
        assert not any("deprecated name" in w.lower() for w in new)


def test_old_overlay_reads_as_new_names(files):
    """The old-named operator overlay maps to new table names."""
    cfg = load(files["overlays"] / "old.operator.toml", profile="thesis_test")
    assert (cfg.get("affect") or {}).get("interoception_stream") == "interoception.out"
    assert (cfg.get("perception_feed") or {}).get("mode") == "stimulus_source"
    assert (
        (cfg.get("perception_feed") or {}).get("stimulus_source") or {}
    ).get("maturation_transition_seconds") == 5
    assert (cfg.get("dashboard") or {}).get("port") == 9100
    assert not any(k in cfg for k in ("thymos", "mnemos", "nexus", "soma"))


def test_both_names_overlay_refused(files):
    """A layer that sets both old and new names is rejected."""
    with pytest.raises((legacy_aliases.LegacyNameConflict, ProfileError)) as exc_info:
        load(files["overlays"] / "both.operator.toml")
    assert "both" in str(exc_info.value).lower()
