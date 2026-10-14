# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Drift contract: the three module-stream consumer lists must EXACTLY match
the canonical registry-derived sets (with each list's documented
exclusions/extras encoded in the registry itself). Any future drift fails
loudly here."""


def test_canonical_names_match_module_packages():
    """The static name tuple must track the real module packages on disk.

    Keys whose packages have already moved under a new identifier are
    translated back to their key before comparing.

    Documented non-package names (no kaine/modules/<name>/ package exists,
    by design):

    - ``cycle``, ``action_selection``, ``supervisor``: cycle-layer components, not
      module packages.
    - ``welfare``, ``preservation``, ``individuation``: lifecycle streams,
      not module packages.

    Documented package exclusion: ``recorder`` is a test-only single-file module
    (kaine/modules/recorder.py, not a package) and is deliberately excluded
    from the research streams. ``perception_prng`` is an implementation
    detail of ``perception``, not a research stream source.
    """
    import importlib
    from pathlib import Path

    from kaine.evaluation.stream_registry import CANONICAL_MODULE_NAMES
    from tests._module_packages import key_for_identifier

    non_package_names = {
        "cycle",  # cycle-layer component
        "action_selection",  # cycle-layer component
        "supervisor",  # cycle-layer component
        "welfare",  # lifecycle stream
        "preservation",  # lifecycle stream
        "individuation",  # lifecycle stream
    }
    test_only_excluded_packages = {"recorder", "perception_prng"}

    modules_dir = Path(importlib.import_module("kaine.modules").__file__).parent
    on_disk = {
        key_for_identifier(p.name)
        for p in modules_dir.iterdir()
        if p.is_dir() and not p.name.startswith("__") and not p.name.startswith(".")
    } - test_only_excluded_packages

    assert set(CANONICAL_MODULE_NAMES) - non_package_names == on_disk


def test_effective_memberships_are_golden():
    """Golden drift guard: any registry edit changes these derived sets and
    must consciously update the golden sets below."""
    from kaine.bus.streams import PERCEPTION_FEED_STREAM
    from kaine.evaluation.stream_registry import (
        curated_module_streams,
        diagnostics_streams,
        raw_archive_module_streams,
    )

    # Curated: full canonical set minus content streams (language, vocal).
    golden_curated = frozenset(
        {
            "cycle.out",
            "action_selection.out",
            "action_selection_feedback.out",
            "positive_control.out",
            "interoception.out",
            "sequence.out",
            "vision.out",
            "world_model.out",
            "planning.out",
            "affect.out",
            "audition.out",
            "episodic_memory.out",
            "sleep.out",
            "self_model.out",
            "social_cognition.out",
            "effectors.out",
            "supervisor.out",
            "perceptual_locus.out",
            "embodiment.out",
            "welfare.out",
            "preservation.out",
            "individuation.out",
        } | {PERCEPTION_FEED_STREAM}
    )

    # Raw archive: full canonical set (the language module now publishes aggregate language.out).
    golden_raw_archive = frozenset(golden_curated | {"language.out", "vocal.out"})

    # Diagnostics: cycle.out + high-signal module streams + workspace.broadcast.
    golden_diagnostics = frozenset(
        {
            "cycle.out",
            "interoception.out",
            "sequence.out",
            "vision.out",
            "world_model.out",
            "planning.out",
            "affect.out",
            "audition.out",
            "language.out",
            "vocal.out",
            "episodic_memory.out",
            "sleep.out",
            "self_model.out",
            "social_cognition.out",
            "effectors.out",
            "supervisor.out",
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
    assert canonical_module_streams() == tuple(module_stream(n) for n in names)
    # language.out IS in the canonical set; the language module publishes an aggregate there
    # in addition to the mode-specific language.external / language.internal streams.
    assert "language.out" in canonical_module_streams()


def test_diagnostics_streams_are_known():
    """Every stream the dashboard diagnostics monitor tails is a canonical stream
    in ``kaine.bus.streams.KNOWN_STREAMS``."""
    from kaine.bus import streams
    from kaine.evaluation.stream_registry import diagnostics_streams

    unknown = sorted(set(diagnostics_streams()) - streams.KNOWN_STREAMS)
    assert not unknown, "diagnostics streams not in KNOWN_STREAMS: " + ", ".join(unknown)


def test_module_streams_are_exactly_the_modules():
    """``MODULE_STREAMS`` holds one ``<name>.out`` per module declared under
    ``kaine/modules/`` (a ``name: ClassVar[str]``), no more and no less."""
    import re
    from pathlib import Path

    from kaine.bus import streams

    modules_dir = Path(__file__).resolve().parent.parent / "kaine" / "modules"
    pattern = re.compile(r'name: ClassVar\[str\] = "([a-z_]+)"')
    names = {
        m.group(1)
        for path in modules_dir.rglob("*.py")
        for m in pattern.finditer(path.read_text())
    }
    assert streams.MODULE_STREAMS == {f"{n}.out" for n in names}
