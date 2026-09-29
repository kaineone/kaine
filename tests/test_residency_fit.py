# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json

from kaine.residency.budget import MemoryDomain, ResidencyBudget
from kaine.residency.catalogue import FootprintCatalogue, FootprintEntry
from kaine.residency.fit import Demand, Rung, fit_report


def _budget_bytes(budget_mib: int) -> ResidencyBudget:
    # The budget is given in MiB, like the footprints in _entry.
    domain = MemoryDomain(
        name="system",
        total_bytes=(budget_mib * 2) << 20,
        available_bytes=budget_mib << 20,
        reserve_bytes=0,
        provenance="test",
        unknown_reason=None,
    )
    return ResidencyBudget(
        topology="unified",
        system=domain,
        devices=(),
        notes=(),
    )


def _entry(component, backend, model_id, peak_mib, host_class="desktop"):
    return FootprintEntry(
        component=component,
        backend=backend,
        model_id=model_id,
        peak_bytes=peak_mib << 20,
        device_peak_bytes=None,
        weights_mapped=None,
        host_class=host_class,
        measured_at="2026-01-01T00:00:00Z",
        kaine_version="0.0.1",
        source="calibration",
    )


def test_fit_co_resides():
    catalogue = (
        FootprintCatalogue(())
        .merge(_entry("lingua", "llamacpp", "small", 2048))
        .merge(_entry("vox.tts", "chatterbox", "chatterbox", 1024))
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
        Demand(
            component="vox.tts",
            configured=Rung("chatterbox", "chatterbox"),
            installed=(Rung("chatterbox", "chatterbox"),),
            interactive=False,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(8192),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    assert report.verdict == "co_resides"
    assert report.shortfall_bytes == 0
    assert any(p.mode == "pinned" for p in report.placements)
    assert all(p.mode in ("pinned", "resident") for p in report.placements)


def test_fit_unknown_uncalibrated():
    catalogue = FootprintCatalogue(()).merge(
        _entry("lingua", "llamacpp", "small", 2048)
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
        Demand(
            component="audition.stt",
            configured=Rung("speaches", "medium.en"),
            installed=(Rung("speaches", "medium.en"),),
            interactive=True,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(8192),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    assert report.verdict == "unknown"
    assert "audition.stt" in report.uncalibrated
    assert any("python -m kaine.setup.footprint" in note for note in report.notes)
    assert len(report.placements) == 1
    assert report.placements[0].component == "lingua"


def test_fit_multiplex_8gb_unified_forces_stt_down():
    catalogue = (
        FootprintCatalogue(())
        .merge(_entry("lingua", "llamacpp", "small", 3072))
        .merge(_entry("vox.tts", "chatterbox", "chatterbox", 5120))
        .merge(_entry("vox.tts", "sherpa_onnx", "kokoro-en", 256))
        .merge(_entry("audition.stt", "speaches", "medium.en", 6144))
        .merge(_entry("audition.stt", "sherpa_onnx", "moonshine-base-en", 512))
        .merge(_entry("audition.stt", "sherpa_onnx", "moonshine-tiny-en", 256))
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
        Demand(
            component="vox.tts",
            configured=Rung("chatterbox", "chatterbox"),
            installed=(
                Rung("chatterbox", "chatterbox"),
                Rung("sherpa_onnx", "kokoro-en"),
            ),
            interactive=False,
        ),
        Demand(
            component="audition.stt",
            configured=Rung("speaches", "medium.en"),
            installed=(
                Rung("speaches", "medium.en"),
                Rung("sherpa_onnx", "moonshine-base-en"),
                Rung("sherpa_onnx", "moonshine-tiny-en"),
            ),
            interactive=True,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(8192),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    assert report.verdict == "multiplexed"
    stt = next(p for p in report.placements if p.component == "audition.stt")
    tts = next(p for p in report.placements if p.component == "vox.tts")
    assert stt.rung == Rung("sherpa_onnx", "moonshine-base-en")
    assert stt.mode == "resident"
    assert tts.rung == Rung("chatterbox", "chatterbox")
    assert tts.mode == "multiplexed"
    assert any("medium.en" in p.reason and "pinned lingua" in p.reason for p in report.placements)
    assert report.shortfall_bytes == (3072 + 5120 + 6144 - 8192) << 20


def test_fit_greedy_interactive_first():
    catalogue = (
        FootprintCatalogue(())
        .merge(_entry("lingua", "llamacpp", "small", 1024))
        .merge(_entry("audition.stt", "sherpa_onnx", "moonshine-tiny-en", 512))
        .merge(_entry("vox.tts", "chatterbox", "chatterbox", 3072))
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
        Demand(
            component="audition.stt",
            configured=Rung("sherpa_onnx", "moonshine-tiny-en"),
            installed=(Rung("sherpa_onnx", "moonshine-tiny-en"),),
            interactive=True,
        ),
        Demand(
            component="vox.tts",
            configured=Rung("chatterbox", "chatterbox"),
            installed=(Rung("chatterbox", "chatterbox"),),
            interactive=False,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(4096),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    stt = next(p for p in report.placements if p.component == "audition.stt")
    tts = next(p for p in report.placements if p.component == "vox.tts")
    assert stt.mode == "resident"
    assert tts.mode == "multiplexed"


def test_fit_does_not_fit_pinned_exceeds_budget():
    catalogue = FootprintCatalogue(()).merge(
        _entry("lingua", "llamacpp", "small", 4096)
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(2048),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    assert report.verdict == "does_not_fit"
    assert report.shortfall_bytes == (4096 - 2048) << 20
    assert report.placements == ()


def test_fit_never_upgrades_above_configured_rung():
    catalogue = (
        FootprintCatalogue(())
        .merge(_entry("lingua", "llamacpp", "small", 1024))
        .merge(_entry("audition.stt", "sherpa_onnx", "moonshine-base-en", 512))
        .merge(_entry("audition.stt", "speaches", "medium.en", 6144))
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
        Demand(
            component="audition.stt",
            configured=Rung("sherpa_onnx", "moonshine-base-en"),
            installed=(
                Rung("sherpa_onnx", "moonshine-base-en"),
                Rung("speaches", "medium.en"),
            ),
            interactive=True,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(4096),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    stt = next(p for p in report.placements if p.component == "audition.stt")
    assert stt.rung == Rung("sherpa_onnx", "moonshine-base-en")
    assert "Upgraded" not in stt.reason


def test_fit_no_pin_adds_note():
    catalogue = FootprintCatalogue(()).merge(
        _entry("lingua", "llamacpp", "small", 1024)
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(4096),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin=None,
    )
    assert any("no pinned organ among the demands" in note for note in report.notes)
    assert report.verdict == "co_resides"
    assert all(p.mode == "resident" for p in report.placements)


def test_fit_render_includes_shortfall_and_placements():
    catalogue = (
        FootprintCatalogue(())
        .merge(_entry("lingua", "llamacpp", "small", 2048))
        .merge(_entry("vox.tts", "chatterbox", "chatterbox", 1024))
    )
    demands = [
        Demand(
            component="lingua",
            configured=Rung("llamacpp", "small"),
            installed=(Rung("llamacpp", "small"),),
            interactive=False,
        ),
        Demand(
            component="vox.tts",
            configured=Rung("chatterbox", "chatterbox"),
            installed=(Rung("chatterbox", "chatterbox"),),
            interactive=False,
        ),
    ]
    report = fit_report(
        budget=_budget_bytes(8192),
        catalogue=catalogue,
        demands=demands,
        host_class="desktop",
        pin="lingua",
    )
    text = report.render()
    assert "Shortfall:" in text
    assert "lingua/llamacpp/small: pinned" in text
    assert "vox.tts/chatterbox/chatterbox: resident" in text
    assert "Expected feel:" in text
    assert json.dumps(report.to_dict())
