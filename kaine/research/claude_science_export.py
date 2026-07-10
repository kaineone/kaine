# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Export an allowlisted research metrics bundle as a Claude Science project.

WHY THIS IS SAFE BY CONSTRUCTION
--------------------------------
Claude Science is a CLOUD analysis workbench: data that enters an analysis step
is transmitted to a cloud service. KAINE's evaluation sidecar records the
entity's access-conscious content, and the workspace trajectory is comprehensive
cognitive observation (paper §4.4, §6.1). The Cognitive Architecture License
mental-privacy covenant (paper §7 neurorights) forbids routing that inner life to
a cloud product. So a Claude Science export MUST carry ONLY de-identified numeric
metrics, and that must hold BY CONSTRUCTION, not by reviewer diligence.

KAINE already solved this exact problem for the research-participation bundle
(paper §6.7, ``kaine.research.submission``): the bundle is built from an
ALLOWLIST of numeric metric directories (``METRICS_ONLY_DIRS``); conversation
text, memories, the self-model, the internal monologue, and the LOCAL-ONLY raw
bus archive are excluded because they are structurally OUTSIDE what the builder
reads.

This module is a THIN ADAPTER over that builder. Its ONLY input is a ``Bundle``
already produced by ``build_research_bundle``; it reads files only from
``bundle.bundle_dir`` and never touches ``data/evaluation/`` directly, a memory
store, the self-model, the intent log/monologue, the raw bus archive, or the
event bus. It takes NO ``eval_root``/store/bus argument — it is structurally
incapable of being pointed at raw data. The privacy boundary is therefore the
SAME boundary as research submission, reused (never re-implemented).

EXPLORATORY, NOT AUTHORITATIVE
------------------------------
The export is an off-runtime, human-in-the-loop path for interpretation,
visualization, calculation-checking, and drafting the companion paper. It is NOT
part of KAINE's deterministic, admissibility-gated verdict pipeline
(``kaine.experiment.*``) and never computes, replaces, or overrides the
authoritative PASS/NULL/NEGATIVE verdicts. The bundle's admissibility verdict
travels in the copied manifest so an inadmissible run cannot be analyzed as if it
were clean.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Reuse the SINGLE source of truth for the privacy boundary. We import the
# allowlist and denylist so the export can never drift from research submission:
# any future tightening of METRICS_ONLY_DIRS automatically tightens the export.
from kaine.research.submission import (
    DENY_PATTERNS,
    METRICS_ONLY_DIRS,
    Bundle,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plain-language notices carried into the project so a reader (human OR the
# workbench AI) cannot mistake this for an authoritative result or miss that
# opening it in the cloud tool is an external disclosure.
# ---------------------------------------------------------------------------

EXTERNAL_DISCLOSURE_NOTICE: str = (
    "EXTERNAL DISCLOSURE. Opening this folder in Claude Science transmits the "
    "numeric metrics below to a cloud service. It is governed as an external "
    "disclosure under guardian consent (CAL Article 4.3), exactly like sharing "
    "results with the project. The data here is DE-IDENTIFIED NUMERIC METRICS "
    "ONLY — no transcripts, memories, self-model, internal monologue, or "
    "conversation content is present or reachable by this export."
)

EXPLORATORY_NOTICE: str = (
    "EXPLORATORY, NOT AUTHORITATIVE. This project is for interpretation, "
    "visualization, calculation-checking, and drafting the companion paper only. "
    "It is NOT part of KAINE's deterministic, admissibility-gated verdict "
    "pipeline. The authoritative PASS/NULL/NEGATIVE experiment verdicts are "
    "produced solely by KAINE's own code (kaine.experiment.*); nothing computed "
    "in this workbench computes, replaces, or overrides them."
)

#: One-line plain-language descriptions per allowlisted metric family, used to
#: build the README data dictionary. Families absent from a bundle are skipped.
FAMILY_DESCRIPTIONS: dict[str, str] = {
    "ab_divergence": (
        "A/B divergence series: per-tick divergence between the paired A and B "
        "conditions (numeric; higher means the conditions drifted further apart)."
    ),
    "individuation": (
        "Individuation results: numeric tallies/scores for the individuation "
        "experiment."
    ),
    "coherence": (
        "Coherence series: per-tick coherence measures of the entity's "
        "trajectory (numeric)."
    ),
    "welfare": (
        "Welfare / gray-zone counts: numeric welfare-signal tallies and "
        "gray-zone counters."
    ),
    "fatigue": "Fatigue series: numeric fatigue measures over time.",
    "prediction_error": (
        "Prediction-error series: numeric prediction-error magnitudes "
        "(non-negative)."
    ),
    "nous_policy": (
        "Policy logs: numeric/categorical policy-decision records from the Nous "
        "controller."
    ),
    "voice_alignment_divergence": (
        "Voice-alignment divergence: numeric divergence between expressed and "
        "aligned voice."
    ),
    "research_events": (
        "Curated research events: privacy-filtered numeric/categorical event "
        "records (all content fields stripped at write time)."
    ),
    "runs": (
        "Per-run manifests: run id, seed, git sha, model ids, config digest, "
        "start time, and KAINE version — no entity interior, no operator "
        "paths/hostnames."
    ),
}


class ClaudeScienceExportError(ValueError):
    """Raised when an export cannot proceed safely.

    The load-bearing case is an ENCRYPTED source bundle: the adapter cannot
    reshape an encrypted blob and MUST refuse rather than emit a partial or
    plaintext project (decrypt-locally-first is an operator step; see the change
    design §6 Q3). Refusing here is a fail-safe, never a silent downgrade.
    """


@dataclass
class DisclosureAttestation:
    """Guardian-consent external-disclosure attestation recorded WITH the project.

    Because the destination is a cloud tool, the operator records who is
    consenting, why (for the paper write-up), and when. This is the metrics-only
    analogue of the bundle's bystander-consent/entity-privacy attestation, scoped
    to disclosure (the content is already metrics-only).
    """

    operator: str
    reason: str
    attested_at: str = ""

    def __post_init__(self) -> None:
        if not self.attested_at:
            self.attested_at = datetime.now(timezone.utc).isoformat()


@dataclass
class ClaudeScienceProject:
    """Description of a Claude Science project folder (planned or written)."""

    project_dir: Path
    data_files: list[Path] = field(default_factory=list)
    readme_path: Optional[Path] = None
    manifest_path: Optional[Path] = None
    plan_path: Optional[Path] = None
    families: list[str] = field(default_factory=list)
    written: bool = False


# ---------------------------------------------------------------------------
# Helpers (read ONLY from bundle.bundle_dir)
# ---------------------------------------------------------------------------


def _utc_stamp() -> str:
    # Microsecond precision so rapid successive exports never collide on mkdir.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _read_family_rows(family_dir: Path) -> list[dict[str, Any]]:
    """Read every JSONL/JSON record under one family dir inside the bundle.

    Reads ONLY within ``family_dir`` (which is always under
    ``bundle.bundle_dir``). Unparseable lines are skipped with a warning; no new
    numbers are computed.
    """
    rows: list[dict[str, Any]] = []
    for path in sorted(family_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".jsonl", ".json"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                log.warning(
                    "claude_science_export: skipping unparseable line in %s", path
                )
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            elif isinstance(obj, list):
                rows.extend(o for o in obj if isinstance(o, dict))
    return rows


def _families_present(bundle: Bundle) -> list[tuple[str, list[dict[str, Any]]]]:
    """Return (family, rows) for each ALLOWLISTED family present in the bundle.

    Iterating ``METRICS_ONLY_DIRS`` (not the directory listing) means every
    output family is, by construction, an allowlisted one — the export can never
    invent a family the research-participation allowlist does not sanction.
    """
    present: list[tuple[str, list[dict[str, Any]]]] = []
    for family in METRICS_ONLY_DIRS:
        family_dir = bundle.bundle_dir / family
        if not family_dir.is_dir():
            continue
        rows = _read_family_rows(family_dir)
        if rows:
            present.append((family, rows))
    return present


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    """Stable, deterministic column order: first-seen across rows in order."""
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                names.append(str(key))
    return names


def _needs_jsonl(rows: list[dict[str, Any]]) -> bool:
    """True when rows are nested (dict/list values) or ragged (differing keys).

    In that case a flat CSV cannot represent the family losslessly, so a
    pass-through JSONL is emitted alongside the CSV.
    """
    key_sets: list[frozenset[str]] = []
    for row in rows:
        key_sets.append(frozenset(row.keys()))
        for value in row.values():
            if isinstance(value, (dict, list)):
                return True
    return len(set(key_sets)) > 1


def _cell(value: Any) -> str:
    """Render a CSV cell; nested values are JSON-encoded (never dropped)."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _admissibility_summary(bundle: Bundle) -> str:
    """Read the copied bundle manifest and summarize the admissibility verdict.

    Surfaced LOUDLY in the README so an inadmissible or unvouched run cannot be
    analyzed as if it were clean. Never blocks (this path is exploratory).
    """
    if bundle.manifest_path is None or not bundle.manifest_path.is_file():
        return "No manifest present in the source bundle."
    try:
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Manifest present but could not be read."
    adm = manifest.get("admissibility") or {}
    verdict = adm.get("admissible", None)
    status = adm.get("status")
    overridden = "admissibility_override" in manifest
    if verdict is True:
        line = "ADMISSIBLE — the source run passed completeness and range checks."
    elif verdict is False:
        line = (
            "INADMISSIBLE — the source run FAILED admissibility. Treat any "
            "analysis of it as provisional; it is not a clean run."
        )
    elif status == "no_run_logs_present":
        line = (
            "NO RUN LOGS — the bundle carries metric aggregates but no run-stamped "
            "records, so there is no run to admit or reject."
        )
    else:
        line = "Admissibility verdict is indeterminate; see manifest.json."
    if overridden:
        line += (
            " An explicit operator admissibility_override was applied (see "
            "manifest.json)."
        )
    return line


# ---------------------------------------------------------------------------
# Planning (no writes) — used to preview BEFORE anything is written
# ---------------------------------------------------------------------------


def plan_project(
    *,
    bundle: Bundle,
    out_dir: Path,
    plan: bool = False,
) -> ClaudeScienceProject:
    """Describe the project that ``export_project`` would write. Writes NOTHING.

    Refuses an encrypted bundle up front so a preview never implies a project
    that cannot be produced.
    """
    _refuse_if_encrypted(bundle)
    out_dir = Path(out_dir)
    project_dir = out_dir / f"claude_science_project_{_utc_stamp()}"
    data_dir = project_dir / "data"

    families: list[str] = []
    data_files: list[Path] = []
    for family, rows in _families_present(bundle):
        families.append(family)
        data_files.append(data_dir / f"{family}.csv")
        if _needs_jsonl(rows):
            data_files.append(data_dir / f"{family}.jsonl")

    return ClaudeScienceProject(
        project_dir=project_dir,
        data_files=data_files,
        readme_path=project_dir / "README.md",
        manifest_path=project_dir / "manifest.json",
        plan_path=(project_dir / "plan.json") if plan else None,
        families=families,
        written=False,
    )


# ---------------------------------------------------------------------------
# Export (writes) — the thin adapter
# ---------------------------------------------------------------------------


def export_project(
    *,
    bundle: Bundle,
    out_dir: Path,
    plan: bool = False,
    attestation: Optional[DisclosureAttestation] = None,
) -> ClaudeScienceProject:
    """Reshape an allowlisted metrics ``bundle`` into a Claude Science project.

    INPUT CONTRACT: a ``Bundle`` already built by ``build_research_bundle``. The
    adapter reads files ONLY from ``bundle.bundle_dir`` and metadata only from
    ``bundle.manifest_path``. There is NO ``eval_root``/store/bus parameter, so
    the adapter cannot be pointed at raw data (paper §4.4/§6.1 privacy boundary;
    §6.7 allowlist reuse; CAL mental-privacy covenant).

    Refuses (writes nothing) when the source bundle is encrypted.
    """
    _refuse_if_encrypted(bundle)

    project = plan_project(bundle=bundle, out_dir=out_dir, plan=plan)
    project_dir = project.project_dir
    data_dir = project_dir / "data"
    project_dir.mkdir(parents=True, exist_ok=False)
    data_dir.mkdir(parents=True, exist_ok=True)

    families = _families_present(bundle)

    # --- Reshape each family into analysis-ready CSV (+ JSONL when ragged) ---
    for family, rows in families:
        fieldnames = _fieldnames(rows)
        csv_path = data_dir / f"{family}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(fieldnames)
            for row in rows:
                writer.writerow([_cell(row.get(name)) for name in fieldnames])
        if _needs_jsonl(rows):
            jsonl_path = data_dir / f"{family}.jsonl"
            with jsonl_path.open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")

    # --- Copy the bundle manifest UNCHANGED (provenance) --------------------
    if bundle.manifest_path is not None and bundle.manifest_path.is_file():
        (project_dir / "manifest.json").write_text(
            bundle.manifest_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # --- Generate the plain-language README data dictionary -----------------
    (project_dir / "README.md").write_text(
        _render_readme(bundle, families, attestation), encoding="utf-8"
    )

    # --- Optional project descriptor (references + prose only, NO data) -----
    if plan:
        (project_dir / "plan.json").write_text(
            json.dumps(_render_plan(families), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # --- Record the external-disclosure attestation WITH the project --------
    # The bundle manifest is copied verbatim (provenance), so the attestation is
    # recorded separately in disclosure.json (and in the README). An audit-log
    # sink is deferred pending design §8 Q4.
    if attestation is not None:
        (project_dir / "disclosure.json").write_text(
            json.dumps(
                {
                    "external_disclosure": True,
                    "destination": "Claude Science (cloud analysis workbench)",
                    "operator": attestation.operator,
                    "reason": attestation.reason,
                    "attested_at": attestation.attested_at,
                    "notice": EXTERNAL_DISCLOSURE_NOTICE,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    project.written = True
    return project


def _refuse_if_encrypted(bundle: Bundle) -> None:
    if bundle.encrypted:
        raise ClaudeScienceExportError(
            "source bundle is encrypted (bundle.tar.enc); the Claude Science "
            "export cannot reshape an encrypted blob and refuses to write a "
            "plaintext project. Decrypt the bundle locally first, then re-run "
            "the export against the plaintext bundle."
        )


def _render_readme(
    bundle: Bundle,
    families: list[tuple[str, list[dict[str, Any]]]],
    attestation: Optional[DisclosureAttestation],
) -> str:
    lines: list[str] = [
        "# KAINE research metrics — Claude Science project",
        "",
        "## What this is",
        "",
        "De-identified NUMERIC METRICS ONLY, reshaped from an allowlisted KAINE "
        "research-participation bundle. No transcripts, memories, self-model, "
        "internal monologue, or conversation content is present.",
        "",
        "## External disclosure",
        "",
        EXTERNAL_DISCLOSURE_NOTICE,
        "",
        "## Exploratory, not authoritative",
        "",
        EXPLORATORY_NOTICE,
        "",
        "## Source-run admissibility",
        "",
        _admissibility_summary(bundle),
        " See `manifest.json` for the full completeness/range verdict.",
        "",
        "## Data dictionary",
        "",
    ]
    if not families:
        lines.append("_(No metric families were present in the source bundle.)_")
    for family, rows in families:
        desc = FAMILY_DESCRIPTIONS.get(family, "Allowlisted numeric metric family.")
        columns = _fieldnames(rows)
        lines.append(f"### `data/{family}.csv`")
        lines.append("")
        lines.append(desc)
        lines.append("")
        lines.append(f"- rows: {len(rows)}")
        if columns:
            lines.append("- columns: " + ", ".join(f"`{c}`" for c in columns))
        if _needs_jsonl(rows):
            lines.append(
                f"- a pass-through `data/{family}.jsonl` accompanies the CSV "
                "(rows are nested/ragged)."
            )
        lines.append("")

    lines += [
        "## Excluded by construction (never present or reachable)",
        "",
        "- intent log / internal monologue (Lingua intent_expression)",
        "- Mnemos/Qdrant memories (verbatim transcripts, episodic records)",
        "- Eidolon self-model",
        "- conversation content (any turn text)",
        "- replay logs",
        "- the LOCAL-ONLY raw bus archive (state/research/raw_bus_archive/), which "
        "lives outside data/evaluation/ and is never in any bundle",
        "",
    ]
    if attestation is not None:
        lines += [
            "## Guardian-consent attestation (external disclosure)",
            "",
            f"- operator: {attestation.operator}",
            f"- reason: {attestation.reason}",
            f"- attested_at: {attestation.attested_at}",
            "",
        ]
    return "\n".join(lines)


def _render_plan(families: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """A Claude Science project descriptor: references + prose only, NO data."""
    family_names = [f for f, _ in families]
    questions: list[str] = []
    if "ab_divergence" in family_names:
        questions.append("Plot ab_divergence over tick_index per experiment.")
    if "coherence" in family_names:
        questions.append("Plot the coherence series over time and summarize its trend.")
    if "welfare" in family_names:
        questions.append("Tally the welfare / gray-zone counts and sanity-check them.")
    if "individuation" in family_names:
        questions.append("Re-derive the individuation summary statistics.")
    if "prediction_error" in family_names:
        questions.append("Describe the distribution of prediction_error over time.")
    if not questions:
        questions.append("Describe each metric family and its distribution.")
    return {
        "title": "KAINE research metrics (de-identified, metrics-only)",
        "data_files": [f"data/{f}.csv" for f in family_names],
        "suggested_questions": questions,
        "notice_external_disclosure": EXTERNAL_DISCLOSURE_NOTICE,
        "notice_exploratory": EXPLORATORY_NOTICE,
    }


# ---------------------------------------------------------------------------
# Preview — printed BEFORE any write; ends with the EXCLUDED footer
# ---------------------------------------------------------------------------


def preview_project(project: ClaudeScienceProject) -> str:
    """Human-readable inventory of every file the export will write.

    Mirrors ``kaine.research.submission.preview``: it always ends with an
    EXCLUDED section naming the content types that are never in the project.
    """
    lines: list[str] = [
        "=" * 70,
        "KAINE Claude Science Export Preview",
        f"  project_dir: {project.project_dir}",
        f"  families:    {len(project.families)}",
        "",
        EXTERNAL_DISCLOSURE_NOTICE,
        "",
        EXPLORATORY_NOTICE,
        "",
        "Files to be written:",
        f"  {project.readme_path}",
        f"  {project.manifest_path}",
    ]
    if project.plan_path is not None:
        lines.append(f"  {project.plan_path}")
    for data_file in project.data_files:
        lines.append(f"  {data_file}")
    if not project.data_files:
        lines.append("  (no metric families present in the source bundle)")

    lines += [
        "",
        "-" * 70,
        "EXCLUDED by construction (never in a Claude Science export):",
        "  - intent log / internal monologue (Lingua intent_expression.jsonl)",
        "  - Mnemos/Qdrant memories (verbatim transcripts and episodic records)",
        "  - Eidolon self-model (state/eidolon/self_model.json)",
        "  - conversation content (any turn text)",
        "  - replay logs",
        "  - the LOCAL-ONLY raw bus archive (state/research/raw_bus_archive/),",
        "    which lives OUTSIDE data/evaluation/ and is never in any bundle",
        "-" * 70,
        "Only reshaped, allowlisted numeric metric families are ever included:",
    ]
    for family in METRICS_ONLY_DIRS:
        lines.append(f"  data/evaluation/{family}/  ->  data/{family}.csv")
    # Belt-and-suspenders: no planned path may match a deny pattern.
    for data_file in project.data_files:
        matched = next(
            (p for p in DENY_PATTERNS if p in str(data_file).lower()), None
        )
        if matched:
            lines.append(f"  WARNING: planned path matches deny pattern {matched!r}!")
    lines.append("=" * 70)
    return "\n".join(lines)
