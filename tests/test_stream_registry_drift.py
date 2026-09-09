# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Drift contract: the three module-stream consumer lists must EXACTLY match
the canonical registry-derived sets (with each list's documented
exclusions/extras encoded in the registry itself). Any future drift fails
loudly here."""


def test_canonical_names_match_module_packages():
    """The static name tuple must track the real module packages on disk.

    Documented non-package names (no kaine/modules/<name>/ package exists,
    by design):

    - ``cycle``, ``volition``, ``spot``: cycle-layer components, not
      module packages.
    - ``welfare``, ``preservation``, ``individuation``: lifecycle streams,
      not module packages.

    Documented package exclusion: ``echo`` is a test-only single-file module
    (kaine/modules/echo.py, not a package) and is deliberately excluded
    from the research streams. ``perception_prng`` is an implementation
    detail of ``perception``, not a research stream source.
    """
    import importlib
    from pathlib import Path

    from kaine.evaluation.stream_registry import CANONICAL_MODULE_NAMES

    non_package_names = {
        "cycle",  # cycle-layer component
        "volition",  # cycle-layer component
        "spot",  # cycle-layer component
        "welfare",  # lifecycle stream
        "preservation",  # lifecycle stream
        "individuation",  # lifecycle stream
    }
    test_only_excluded_packages = {"echo", "perception_prng"}

    modules_dir = Path(importlib.import_module("kaine.modules").__file__).parent
    on_disk = {
        p.name
        for p in modules_dir.iterdir()
        if p.is_dir()
        and not p.name.startswith("__")
        and not p.name.startswith(".")
    } - test_only_excluded_packages

    assert set(CANONICAL_MODULE_NAMES) - non_package_names == on_disk


def test_effective_memberships_are_golden():
    """Golden drift guard: any registry edit changes these derived sets and
    must consciously update the golden sets below."""
    from kaine.evaluation.stream_registry import (
        canonical_module_streams,
        curated_module_streams,
        diagnostics_streams,
        raw_archive_module_streams,
    )

    # Curated: full canonical set minus content streams (lingua, vox).
    golden_curated = frozenset(
        {
            "cycle.out",
            "volition.out",
            "soma.out",
            "chronos.out",
            "topos.out",
            "phantasia.out",
            "nous.out",
            "thymos.out",
            "audition.out",
            "mnemos.out",
            "hypnos.out",
            "eidolon.out",
            "empatheia.out",
            "praxis.out",
            "spot.out",
            "perception.out",
            "mundus.out",
            "welfare.out",
            "preservation.out",
            "individuation.out",
        }
    )

    # Raw archive: full canonical set with Lingua split.
    golden_raw_archive = frozenset(
        golden_curated
        | {"lingua.external", "lingua.internal", "vox.out"}
    )

    # Diagnostics: cycle.tick + high-signal module streams (Lingua split,
    # no cycle.out) + workspace.broadcast.
    golden_diagnostics = frozenset(
        {
            "cycle.tick",
            "soma.out",
            "chronos.out",
            "topos.out",
            "phantasia.out",
            "nous.out",
            "thymos.out",
            "audition.out",
            "lingua.external",
            "lingua.internal",
            "vox.out",
            "mnemos.out",
            "hypnos.out",
            "eidolon.out",
            "empatheia.out",
            "praxis.out",
            "spot.out",
            "workspace.broadcast",
        }
    )

    assert frozenset(curated_module_streams()) == golden_curated
    assert frozenset(raw_archive_module_streams()) == golden_raw_archive
    assert frozenset(diagnostics_streams()) == golden_diagnostics


def test_registry_invariants():
    from kaine.bus.schema import module_stream
    from kaine.evaluation.stream_registry import (
        CANONICAL_MODULE_NAMES,
        canonical_module_streams,
    )

    names = list(CANONICAL_MODULE_NAMES)
    assert len(names) == len(set(names)), "duplicate module names in registry"
    assert canonical_module_streams() == tuple(
        module_stream(n) for n in names
    )
    # lingua.out IS in the canonical (unsplit) set; consumers split it.
    assert "lingua.out" in canonical_module_streams()
