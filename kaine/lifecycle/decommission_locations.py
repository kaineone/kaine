# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaine import legacy_names
from kaine.legacy_aliases import name_forms
from kaine.lifecycle.identity import IdentityError, read_identity_sidecar

BACKUP_DELETE = "backup+delete"
DELETE = "delete"
RETAIN = "retain"
BACKUP_RETAIN = "backup+retain"


def _sha256(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                block = f.read(1024 * 1024)
                if not block:
                    break
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def adapter_checksums(store_dirs: tuple[Path, ...]) -> set[str]:
    checksums: set[str] = set()
    for store_dir in store_dirs:
        if not store_dir.exists():
            continue
        for candidate in store_dir.rglob("adapter.gguf"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            digest = _sha256(candidate)
            if digest is not None:
                checksums.add(digest)
    return checksums


def _current_adapter_checksum(
    store_dirs: tuple[Path, ...],
) -> tuple[str, str] | None:
    for store_dir in store_dirs:
        if not store_dir.is_dir():
            continue
        current_link = store_dir / "current"
        if not current_link.exists():
            continue
        resolved = current_link.resolve()
        if not resolved.is_dir():
            continue
        adapter_file = resolved / "adapter.gguf"
        if adapter_file.is_symlink() or not adapter_file.is_file():
            continue
        digest = _sha256(adapter_file)
        if digest is not None:
            return resolved.name, digest
    return None


def attribute_organ_volume(
    volume: Path,
    own: set[str],
    current: tuple[str, str] | None = None,
) -> tuple[list[Path], list[Path], list[str]]:
    own_paths: list[Path] = []
    shared_paths: list[Path] = []
    notes: list[str] = []
    if not volume.exists():
        return own_paths, shared_paths, notes

    found_current = False
    for entry in sorted(volume.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_file():
            shared_paths.append(entry)
            continue
        if re.fullmatch(r"active-\d+\.gguf", entry.name):
            digest = _sha256(entry)
            if digest in own:
                own_paths.append(entry)
                if current is not None and digest == current[1]:
                    found_current = True
            else:
                shared_paths.append(entry)
        elif entry.name == "active.json":
            try:
                with entry.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict) and data.get("sha256") in own:
                own_paths.append(entry)
            else:
                shared_paths.append(entry)
        else:
            shared_paths.append(entry)

    if not own_paths and shared_paths:
        notes.append(
            f"nothing in {volume} could be attributed to this entity from its records; everything there is kept"
        )
    if current is not None and volume.exists() and not found_current:
        notes.append(
            f"this entity's current adapter {current[0]} is not in {volume}"
        )
    return own_paths, shared_paths, notes


def attribute_job_dirs(
    jobs_dir: Path,
    own: set[str],
    store_dirs: tuple[Path, ...],
) -> tuple[list[Path], list[Path], list[str]]:
    own_paths: list[Path] = []
    shared_paths: list[Path] = []
    notes: list[str] = []
    if not jobs_dir.exists():
        return own_paths, shared_paths, notes

    resolved_stores = {d.resolve() for d in store_dirs if d.exists()}
    for entry in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_dir():
            shared_paths.append(entry)
            continue

        attributed = False
        job_json = entry / "job.json"
        if job_json.is_file():
            try:
                with job_json.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict):
                output_dir = data.get("adapter_output_dir")
                if isinstance(output_dir, str):
                    output_path = Path(output_dir).resolve()
                    if output_path in resolved_stores:
                        attributed = True

        if not attributed:
            for adapter_file in entry.rglob("adapter.gguf"):
                if adapter_file.is_symlink() or not adapter_file.is_file():
                    continue
                # previous_adapter/ is the adapter a job started from; another
                # entity (a study line forked from this one) can start from a
                # copy of this entity's adapter, so only the job's own output
                # is evidence of who ran it.
                if "previous_adapter" in adapter_file.relative_to(entry).parts:
                    continue
                digest = _sha256(adapter_file)
                if digest in own:
                    attributed = True
                    break

        if attributed:
            own_paths.append(entry)
        else:
            shared_paths.append(entry)

    if not own_paths and shared_paths:
        notes.append(
            f"nothing in {jobs_dir} could be attributed to this entity from its records; everything there is kept"
        )
    return own_paths, shared_paths, notes


@dataclass(frozen=True)
class Location:
    """A single on-disk place an entity's data may live, plus the decommission decision."""

    key: str
    decision: str
    paths: tuple[Path, ...]
    reason: str
    bundle_dir: str | None = None
    contents_only: bool = False
    notes: tuple[str, ...] = ()

    def existing(self) -> list[Path]:
        """Return the candidate paths that currently exist, in order, without duplicates."""
        seen: set[Path] = set()
        found: list[Path] = []
        for path in self.paths:
            if path in seen:
                continue
            if path.is_file() or path.is_dir() or path.is_symlink():
                found.append(path)
                seen.add(path)
        return found


def _rebase(value: str, *, state_root: Path, data_root: Path) -> Path:
    """Resolve a configured path string against the runtime state and data roots."""
    expanded = Path(value).expanduser()
    if expanded.is_absolute():
        return expanded
    text = str(value)
    if text.startswith("state/"):
        return state_root / Path(text[len("state/") :])
    if text.startswith("data/"):
        return data_root / Path(text[len("data/") :])
    return data_root.parent / Path(text)


def _path_forms(path: Path, state_root: Path) -> tuple[Path, ...]:
    """Return every known form of ``path`` under the state root.

    Includes aliases for the first path segment and legacy renames of the
    whole relative path, so files are found under both old and new names.
    """
    try:
        relative = path.relative_to(state_root)
    except ValueError:
        return (path,)
    parts = relative.parts
    if not parts:
        return (path,)

    def build(segment: str, rest: tuple[str, ...]) -> Path:
        candidate = state_root / segment
        for part in rest:
            candidate = candidate / part
        return candidate

    base_candidates = [build(form, parts[1:]) for form in name_forms(parts[0])]

    def with_first_segment_alias(candidate: Path) -> list[Path]:
        try:
            rel = candidate.relative_to(state_root)
        except ValueError:
            return [candidate]
        rel_parts = rel.parts
        if not rel_parts:
            return [candidate]
        return [build(form, rel_parts[1:]) for form in name_forms(rel_parts[0])]

    all_candidates = list(base_candidates)
    for candidate in base_candidates:
        candidate_rel = candidate.relative_to(state_root).as_posix()
        for entry in legacy_names.STATE_PATHS:
            counterpart_rel: str | None = None
            if candidate_rel == entry["old"]:
                counterpart_rel = entry["new"]
            elif candidate_rel == entry["new"]:
                counterpart_rel = entry["old"]
            if counterpart_rel is None:
                continue
            counterpart = state_root / Path(counterpart_rel)
            all_candidates.extend(with_first_segment_alias(counterpart))

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in all_candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return tuple(unique)


def _cfg(config: Mapping[str, Any] | None, dotted: str, default: Any) -> Any:
    """Read a dotted configuration key, returning ``default`` when any segment is missing."""
    if config is None:
        return default
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def entity_locations(
    config: Mapping[str, Any] | None,
    *,
    state_root: Path,
    data_root: Path,
    fork_root: Path,
    entity_id: str | None,
) -> list[Location]:
    """Build and return every on-disk location for an entity with its decommission decision."""
    locations: list[Location] = []

    def resolve(value: str, *, directory: bool = False, forms: bool = True) -> tuple[Path, ...]:
        path = _rebase(value, state_root=state_root, data_root=data_root)
        if directory:
            path = path.parent
        if forms:
            return _path_forms(path, state_root)
        return (path,)

    def files_in(
        base_dirs: tuple[Path, ...], filenames: tuple[str, ...]
    ) -> tuple[Path, ...]:
        found: list[Path] = []
        seen: set[Path] = set()
        for base_dir in base_dirs:
            for name in filenames:
                for candidate in _path_forms(base_dir / name, state_root):
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    found.append(candidate)
        return tuple(found)

    # 1. self model
    locations.append(
        Location(
            "self_model",
            BACKUP_DELETE,
            resolve(
                _cfg(config, "self_model.persistence_path", "state/self_model/self_model.json"),
                directory=True,
            ),
            "self-understanding and identity history (cognitive state)",
            bundle_dir="locations/self_model",
        )
    )

    # 2. language intent log
    locations.append(
        Location(
            "language",
            BACKUP_DELETE,
            resolve(
                _cfg(config, "language.intent_log_path", "state/language/intent_expression.jsonl"),
                directory=True,
            ),
            "the language module's intent log and monologue (cognitive state)",
            bundle_dir="locations/language",
        )
    )

    # 3. language outcomes
    language_dir = resolve(
        _cfg(config, "language.intent_log_path", "state/language/intent_expression.jsonl"),
        directory=True,
    )
    locations.append(
        Location(
            "language.outcomes",
            BACKUP_DELETE,
            files_in(
                language_dir,
                (
                    "utterance_outcomes.jsonl",
                    "voice_measures.jsonl",
                    "voice_measures_latest.json",
                ),
            ),
            "voice outcomes and measures (part of the developing voice)",
            bundle_dir="locations/language.outcomes",
        )
    )

    # 4. sleep adapters
    locations.append(
        Location(
            "sleep.adapters",
            BACKUP_DELETE,
            resolve(
                _cfg(
                    config,
                    "sleep.voice_alignment.adapter_output_dir",
                    "state/sleep/adapters",
                )
            ),
            "learned voice adapters",
            bundle_dir="locations/sleep.adapters",
        )
    )
    store_dirs = tuple(locations[-1].paths)
    own_checksums = adapter_checksums(store_dirs)
    current = _current_adapter_checksum(store_dirs)

    # 5. sleep consolidation divergence
    locations.append(
        Location(
            "sleep.consolidation_divergence",
            BACKUP_DELETE,
            resolve("state/sleep/consolidation_divergence.json"),
            "a consolidation record (cognitive state)",
            bundle_dir="locations/sleep.consolidation_divergence",
        )
    )

    # 6. sleep organ window
    locations.append(
        Location(
            "sleep.organ_window",
            DELETE,
            resolve("state/sleep/organ_window.json"),
            "host residency schedule a later entity would inherit",
        )
    )

    # 7. world model
    locations.append(
        Location(
            "world_model",
            BACKUP_DELETE,
            resolve(
                _cfg(config, "world_model.checkpoint_path", "state/world_model/world_model.ckpt"),
                directory=True,
            ),
            "learned world-model weights",
            bundle_dir="locations/world_model",
        )
    )

    # 8. episodic memory sqlite
    db_bases = resolve(
        _cfg(config, "episodic_memory.db_path", "state/episodic_memory/episodic_memory.db")
    )
    sqlite_paths: list[Path] = []
    for db_path in db_bases:
        sqlite_paths.append(db_path)
        sqlite_paths.append(db_path.parent / (db_path.name + "-wal"))
        sqlite_paths.append(db_path.parent / (db_path.name + "-shm"))
        sqlite_paths.append(db_path.parent / (db_path.name + "-journal"))
    locations.append(
        Location(
            "episodic_memory.sqlite",
            BACKUP_DELETE,
            tuple(sqlite_paths),
            "the episodic memory (sqlite-vec store and its write-ahead and journal files)",
            bundle_dir="locations/episodic_memory.sqlite",
        )
    )

    # 9. episodic memory store health
    locations.append(
        Location(
            "episodic_memory.store_health",
            DELETE,
            resolve("state/episodic_memory/store_health.json"),
            "a store marker the next store would act on",
        )
    )

    # 10. individuation
    locations.append(
        Location(
            "individuation",
            BACKUP_DELETE,
            resolve("state/individuation"),
            "individuation evidence",
            bundle_dir=None,
        )
    )

    # 11. lifecycle development
    locations.append(
        Location(
            "lifecycle.development",
            BACKUP_DELETE,
            files_in(
                resolve("state/lifecycle"),
                (
                    "stage.json",
                    "maturation_request.json",
                    "maturation_ack.json",
                    "maturation_pending",
                    "development_readout.json",
                    "development_progress.json",
                    "development_viability.json",
                ),
            ),
            "developmental stage and progress a later entity would inherit",
            bundle_dir="locations/lifecycle.development",
        )
    )

    # 12. identity
    locations.append(
        Location(
            "identity",
            BACKUP_DELETE,
            resolve("state/identity/entity.json"),
            "entity id and lineage",
            bundle_dir="locations/identity",
        )
    )

    # 13. effector files
    locations.append(
        Location(
            "effectors.files",
            BACKUP_DELETE,
            resolve(
                _cfg(config, "effectors.sandbox_path", "state/effectors/files")
            ),
            "files the entity wrote",
            bundle_dir="locations/effectors.files",
        )
    )

    # 14. effector notifications
    locations.append(
        Location(
            "effectors.notifications",
            BACKUP_DELETE,
            resolve(
                _cfg(
                    config,
                    "effectors.notification_fallback_log",
                    "state/effectors/notifications.log",
                )
            ),
            "notifications the entity sent",
            bundle_dir="locations/effectors.notifications",
        )
    )

    # 15. vocal audio
    locations.append(
        Location(
            "vocal.audio",
            DELETE,
            resolve(_cfg(config, "vocal.sink_path", "state/vocal")),
            "rendered speech audio (output, not state)",
        )
    )

    # 16-17. sleep voice alignment jobs
    trainer_workdir_paths = resolve(
        _cfg(config, "sleep.voice_alignment.trainer_workdir", "state/sleep/voice_align_jobs")
    )
    job_paths = resolve(
        _cfg(
            config,
            "sleep.voice_alignment.trainer_jobs_dir",
            "state/sleep/voice_align_jobs",
        )
    )
    seen_job_dirs: set[Path] = set()
    job_dirs: list[Path] = []
    for candidate in (*trainer_workdir_paths, *job_paths):
        if candidate not in seen_job_dirs:
            seen_job_dirs.add(candidate)
            job_dirs.append(candidate)

    own_job_paths: list[Path] = []
    shared_job_paths: list[Path] = []
    job_notes: list[str] = []
    for jobs_dir in job_dirs:
        if not jobs_dir.exists():
            continue
        own_j, shared_j, notes_j = attribute_job_dirs(jobs_dir, own_checksums, store_dirs)
        own_job_paths.extend(own_j)
        shared_job_paths.extend(shared_j)
        job_notes.extend(notes_j)

    locations.append(
        Location(
            "sleep.voice_jobs.own",
            BACKUP_DELETE,
            tuple(own_job_paths),
            "this entity's voice-alignment jobs (training pairs hold private content), matched by their recorded adapter path or checksum",
            bundle_dir="locations/sleep.voice_jobs.own",
        )
    )
    locations.append(
        Location(
            "sleep.voice_jobs.shared",
            RETAIN,
            tuple(shared_job_paths),
            "kept: shared volume, not attributable to this entity",
            notes=tuple(job_notes),
        )
    )

    # 18. organ adapters
    organ_paths = resolve(
        _cfg(
            config,
            "sleep.voice_alignment.organ_adapters_dir",
            "/organ-adapters",
        )
    )
    own_organ_paths: list[Path] = []
    shared_organ_paths: list[Path] = []
    organ_notes: list[str] = []
    for organ_dir in organ_paths:
        own_o, shared_o, notes_o = attribute_organ_volume(organ_dir, own_checksums, current)
        own_organ_paths.extend(own_o)
        shared_organ_paths.extend(shared_o)
        organ_notes.extend(notes_o)

    live_organ_paths: list[Path] = []
    live_organ_set: set[Path] = set()
    own_organ_set = set(own_organ_paths)
    for p in own_organ_paths:
        if p.name == "active.json":
            live_organ_paths.append(p)
            live_organ_set.add(p)
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                linked = p.parent / meta.get("file", "")
                if linked in own_organ_set and linked not in live_organ_set:
                    live_organ_paths.append(linked)
                    live_organ_set.add(linked)
            except Exception:
                # An unreadable manifest names no file; active.json alone
                # stays live (kept), which is the safe side.
                pass
    own_organ_paths = [p for p in own_organ_paths if p not in live_organ_set]

    locations.append(
        Location(
            "organ_adapters.own",
            BACKUP_DELETE,
            tuple(own_organ_paths),
            "this entity's adapter in the shared organ-adapters volume, matched by checksum",
            bundle_dir="locations/organ_adapters.own",
        )
    )
    locations.append(
        Location(
            "organ_adapters.live",
            BACKUP_RETAIN,
            tuple(live_organ_paths),
            "live adapter on a shared volume; a forked line may be using an identical copy; per-entity layout (#500) resolves this",
            bundle_dir="locations/organ_adapters.live",
        )
    )
    locations.append(
        Location(
            "organ_adapters.shared",
            RETAIN,
            tuple(shared_organ_paths),
            "kept: shared volume, not attributable to this entity",
            notes=tuple(organ_notes),
        )
    )

    # 19. research raw bus archive
    locations.append(
        Location(
            "research.raw_bus_archive",
            BACKUP_DELETE,
            resolve(
                _cfg(
                    config,
                    "research_event_log.raw_archive.archive_dir",
                    "state/research/raw_bus_archive",
                )
            ),
            "verbatim bus traffic (private content)",
            bundle_dir="locations/research.raw_bus_archive",
        )
    )

    # 20. research external utterances
    locations.append(
        Location(
            "research.external_utterances",
            BACKUP_DELETE,
            resolve(
                _cfg(
                    config,
                    "research_event_log.external_utterances.log_dir",
                    "state/research/external_utterances",
                )
            ),
            "what the entity said outward",
            bundle_dir="locations/research.external_utterances",
        )
    )

    # 21. evaluation replay
    eval_logs = _rebase(
        _cfg(config, "evaluation.paths.evaluation_logs", "data/evaluation"),
        state_root=state_root,
        data_root=data_root,
    )
    replay_paths = (eval_logs / "replay",)
    if _cfg(config, "evaluation.observers.replay_redact_content", True):
        locations.append(
            Location(
                "evaluation.replay",
                RETAIN,
                replay_paths,
                "redacted replay metrics",
            )
        )
    else:
        locations.append(
            Location(
                "evaluation.replay",
                DELETE,
                replay_paths,
                "replay records holding memory text",
            )
        )

    # 22. dashboard record
    dashboard_log_dir = _rebase(
        _cfg(
            config,
            "research_event_log.dashboard_record.log_dir",
            "data/nexus_record",
        ),
        state_root=state_root,
        data_root=data_root,
    )
    dashboard_paths = (dashboard_log_dir,)
    if _cfg(config, "dashboard.dev_content_override", False):
        locations.append(
            Location(
                "dashboard.record",
                DELETE,
                dashboard_paths,
                "dashboard record written with content",
            )
        )
    else:
        locations.append(
            Location(
                "dashboard.record",
                RETAIN,
                dashboard_paths,
                "privacy-filtered dashboard record",
            )
        )

    # 23. perception
    locations.append(
        Location(
            "perception",
            DELETE,
            resolve("state/perception"),
            "locus runtime state",
        )
    )

    # 24. cycle run state
    locations.append(
        Location(
            "cycle.run_state",
            DELETE,
            files_in(
                resolve("state/cycle"),
                (
                    "runtime.json",
                    "escalation.json",
                    "gpu_preflight.json",
                    "preserve_request.json",
                    "preserve_result.json",
                ),
            ),
            "run state a later entity would read",
        )
    )

    # 25. preservation divergence edge
    locations.append(
        Location(
            "preservation.divergence_edge",
            DELETE,
            resolve("state/preservation/divergence_edge.json"),
            "monitor edge state",
        )
    )

    # 26. fork snapshots
    merged_dir_value = _cfg(config, "lifecycle.adapter_merge.output_dir", None)
    if merged_dir_value is None:
        merged_dir = fork_root / "merged_adapters"
    else:
        merged_dir = _rebase(merged_dir_value, state_root=state_root, data_root=data_root)
    own_snaps, other_snaps, unattributed_snaps = attribute_snapshots(
        fork_root, entity_id, merged_dir=merged_dir
    )
    locations.append(
        Location(
            "forks.own",
            BACKUP_DELETE,
            tuple(own_snaps),
            "this entity's fork snapshots",
            bundle_dir="locations/forks.own",
        )
    )
    locations.append(
        Location(
            "forks.others",
            RETAIN,
            tuple(other_snaps),
            "another entity's snapshots (CAL Article 4.6)",
        )
    )
    locations.append(
        Location(
            "forks.unattributed",
            RETAIN,
            tuple(unattributed_snaps),
            "snapshots that cannot be attributed to this entity are kept",
        )
    )

    # 27. fork merged adapters
    own_adapters, kept_adapters = attribute_merged_adapters(
        fork_root, own_snaps, other_snaps + unattributed_snaps, merged_dir=merged_dir
    )
    locations.append(
        Location(
            "forks.merged_adapters.own",
            BACKUP_DELETE,
            tuple(own_adapters),
            "merged voice adapters of this entity",
            bundle_dir="locations/forks.merged_adapters.own",
        )
    )
    locations.append(
        Location(
            "forks.merged_adapters.others",
            RETAIN,
            tuple(kept_adapters),
            "merged adapters another entity's snapshots list",
        )
    )

    # 28. retain-only entries
    locations.append(
        Location(
            "cycle.incidents",
            RETAIN,
            resolve("state/cycle/incidents"),
            "welfare and safety record (CAL Article 4.7)",
        )
    )
    locations.append(
        Location(
            "cycle.preservation_log",
            RETAIN,
            resolve("state/cycle/preservation"),
            "welfare action log (CAL Article 4.7)",
        )
    )
    locations.append(
        Location(
            "cycle.caretaker",
            RETAIN,
            files_in(
                resolve("state/cycle"),
                ("caretaker", "caretaker_start.json", "caretaker_ack.json"),
            ),
            "care-obligation audit",
        )
    )
    locations.append(
        Location(
            "cycle.override_audit",
            RETAIN,
            resolve("state/cycle/override_audit.jsonl"),
            "operator audit",
        )
    )
    locations.append(
        Location(
            "cycle.control",
            RETAIN,
            resolve("state/cycle/control.json"),
            "operator file",
        )
    )
    locations.append(
        Location(
            "lifecycle.spawn_acknowledgements",
            RETAIN,
            resolve("state/lifecycle/spawn_acknowledgements.jsonl"),
            "operator audit",
        )
    )
    locations.append(
        Location(
            "effectors.audit",
            RETAIN,
            resolve(
                _cfg(config, "effectors.audit_log_path", "state/effectors/audit.log")
            ),
            "record of the entity's actions, no content",
        )
    )
    locations.append(
        Location(
            "sleep.voice_alignment_audit",
            RETAIN,
            resolve("state/sleep/voice_alignment_audit.jsonl"),
            "audit of voice changes",
        )
    )
    locations.append(
        Location(
            "evaluation.metrics",
            RETAIN,
            (eval_logs,),
            "content-free research metrics",
        )
    )
    locations.append(
        Location(
            "evaluation.welfare",
            RETAIN,
            (eval_logs / "welfare",),
            "welfare events (CAL Article 4.7)",
        )
    )
    locations.append(
        Location(
            "ignition",
            RETAIN,
            (_rebase("data/ignition", state_root=state_root, data_root=data_root),),
            "research log the operator deletes by hand",
        )
    )
    locations.append(
        Location(
            "logs",
            RETAIN,
            resolve("state/logs"),
            "operational logs without content",
        )
    )
    locations.append(
        Location(
            "decommission.audit",
            RETAIN,
            resolve("state/audit"),
            "decommission audit record",
        )
    )

    return locations


def read_snapshot_json(snap_dir: Path) -> dict[str, Any] | None:
    """Return the parsed snapshot.json of a snapshot directory, decrypting it when needed, or None if it cannot be read."""
    from kaine.security.crypto import get_state_encryptor

    try:
        data = get_state_encryptor().maybe_decrypt(
            (snap_dir / "snapshot.json").read_bytes()
        )
        if not isinstance(data, bytes):
            return None
        raw = json.loads(data.decode("utf-8"))
    except Exception:
        return None
    if isinstance(raw, dict):
        return raw
    return None


def attribute_snapshots(
    fork_root: Path,
    entity_id: str | None,
    *,
    merged_dir: Path | None = None,
) -> tuple[list[Path], list[Path], list[Path]]:
    """Attribute fork snapshot directories to this entity, others, or neither.

    If entity_id is None, every snapshot is treated as unattributed (kept)
    because without an identity nothing can be attributed to this entity.
    """
    own: list[Path] = []
    others: list[Path] = []
    unattributed: list[Path] = []
    if not fork_root.exists():
        return own, others, unattributed

    candidates = [
        child
        for child in fork_root.iterdir()
        if child.is_dir()
        and not child.is_symlink()
        and child.name != "merged_adapters"
        and (merged_dir is None or child.resolve() != merged_dir.resolve())
        and (child / "snapshot.json").exists()
    ]
    candidates.sort(key=lambda c: c.name)

    for child in candidates:
        snapshot_id: str | None = None
        sidecar = None
        try:
            sidecar = read_identity_sidecar(child)
        except IdentityError:
            unattributed.append(child)
            continue

        if sidecar is not None:
            snapshot_id = sidecar[0]
        else:
            raw = read_snapshot_json(child)
            if isinstance(raw, dict):
                metadata = raw.get("metadata")
                if isinstance(metadata, dict):
                    identity = metadata.get("identity")
                    if isinstance(identity, dict):
                        value = identity.get("entity_id")
                        if isinstance(value, str):
                            snapshot_id = value

        if entity_id is None:
            unattributed.append(child)
            continue
        if snapshot_id == entity_id:
            own.append(child)
        elif snapshot_id is None:
            unattributed.append(child)
        else:
            others.append(child)

    return own, others, unattributed


def attribute_merged_adapters(
    fork_root: Path,
    own: list[Path],
    kept: list[Path],
    *,
    merged_dir: Path | None = None,
) -> tuple[list[Path], list[Path]]:
    """Partition merged adapter directories by whether any kept snapshot references them.

    If a kept snapshot cannot be read or its adapter list is malformed, every
    merged adapter is kept because its references cannot be determined.
    """
    own_adapters: list[Path] = []
    kept_adapters: list[Path] = []
    adapters_dir = fork_root / "merged_adapters" if merged_dir is None else merged_dir
    if not adapters_dir.exists():
        return own_adapters, kept_adapters

    children = [
        child
        for child in adapters_dir.iterdir()
        if child.is_dir() and not child.is_symlink()
    ]
    children.sort(key=lambda c: c.name)
    referenced_by_kept: set[Path] = set()

    def record_references(snap_dir: Path) -> bool:
        raw = read_snapshot_json(snap_dir)
        if raw is None:
            return False
        # A snapshot without an "adapters" key lists none (ForkSnapshot's default).
        adapters = raw.get("adapters", [])
        if not isinstance(adapters, list):
            return False
        for adapter in adapters:
            if not isinstance(adapter, str):
                continue
            adapter_path = Path(adapter)
            if not adapter_path.is_absolute():
                adapter_path = fork_root / adapter_path
            adapter_path = adapter_path.resolve()
            for child in children:
                child_resolved = child.resolve()
                if adapter_path == child_resolved or adapter_path.is_relative_to(
                    child_resolved
                ):
                    referenced_by_kept.add(child)
        return True

    for snap_dir in kept:
        if not record_references(snap_dir):
            return ([], children[:])

    for child in children:
        if child in referenced_by_kept:
            kept_adapters.append(child)
        else:
            own_adapters.append(child)

    return own_adapters, kept_adapters


def checkpoint_sqlite(db_path: Path) -> str | None:
    """Run a WAL checkpoint on a sqlite database, returning an error string on failure."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception as exc:
        return f"checkpoint {db_path.name}: {type(exc).__name__}"
    return None


def cancel_voice_alignment_jobs(
    jobs_dir: Path,
    *,
    only: Collection[str] | None = None,
    wait_s: float = 60.0,
    poll_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[list[str], list[str]]:
    """Cancel pending voice-alignment jobs and wait briefly for claimed jobs to finish.

    If *only* is provided, only job directories whose names are in *only* are
    considered.
    """
    cancelled: list[str] = []
    still_running: list[str] = []
    if not jobs_dir.exists():
        return cancelled, still_running

    children = sorted(
        [child for child in jobs_dir.iterdir() if child.is_dir() and not child.is_symlink()],
        key=lambda c: c.name,
    )
    if only is not None:
        allowed = set(only)
        children = [child for child in children if child.name in allowed]
    deadline: float | None = None

    for child in children:
        result_file = child / "result.json"
        cancelled_file = child / "CANCELLED"
        if result_file.exists():
            continue
        if not cancelled_file.exists():
            cancelled_file.write_text("")
            cancelled.append(child.name)
        if (child / "CLAIMED").exists():
            if deadline is None:
                deadline = monotonic() + wait_s
            while not result_file.exists():
                if monotonic() >= deadline:
                    still_running.append(child.name)
                    break
                sleep(poll_s)

    return cancelled, still_running


def delete_roots(
    config: Mapping[str, Any] | None,
    *,
    state_root: Path,
    data_root: Path,
    fork_root: Path,
) -> tuple[tuple[Path, ...], tuple[tuple[Path, str], ...]]:
    """Every root a decommission deletion may touch.

    Returns a pair: the allowed roots (state, data and fork roots plus the
    configured directories that may live elsewhere), and a tuple of refused
    configured extra entries with reasons.
    """
    roots: list[Path] = []
    seen: set[Path] = set()
    refused: list[tuple[Path, str]] = []

    resolved_state = state_root.resolve()
    resolved_data = data_root.resolve()
    resolved_fork = fork_root.resolve()
    protected_roots = (resolved_state, resolved_data, resolved_fork)
    home = Path.home().resolve()
    organ_default = Path("/organ-adapters")
    trainer_jobs_default = Path("/trainer-jobs")

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    def check_extra(path: Path) -> str | None:
        resolved = path.resolve()
        if resolved == Path("/"):
            return "the filesystem root"
        if resolved == organ_default or resolved == trainer_jobs_default:
            return None
        if resolved.parent == Path("/"):
            return "a top-level directory"
        if resolved == home or resolved in home.parents:
            return "the home directory or an ancestor of it"
        for root in protected_roots:
            if resolved in root.parents:
                return "an ancestor of the state, data or fork root"
        return None

    add(state_root)
    add(data_root)
    add(fork_root)

    merged_dir_value = _cfg(config, "lifecycle.adapter_merge.output_dir", None)
    if merged_dir_value is None:
        merged_path = fork_root / "merged_adapters"
    else:
        merged_path = _rebase(merged_dir_value, state_root=state_root, data_root=data_root)
    reason = check_extra(merged_path)
    if reason:
        refused.append((merged_path.resolve(), reason))
    else:
        add(merged_path)

    organ_path = _rebase(
        _cfg(config, "sleep.voice_alignment.organ_adapters_dir", "/organ-adapters"),
        state_root=state_root,
        data_root=data_root,
    )
    reason = check_extra(organ_path)
    if reason:
        refused.append((organ_path.resolve(), reason))
    else:
        add(organ_path)

    trainer_workdir_path = _rebase(
        _cfg(config, "sleep.voice_alignment.trainer_workdir", "state/sleep/voice_align_jobs"),
        state_root=state_root,
        data_root=data_root,
    )
    reason = check_extra(trainer_workdir_path)
    if reason:
        refused.append((trainer_workdir_path.resolve(), reason))
    else:
        add(trainer_workdir_path)

    trainer_jobs_path = _rebase(
        _cfg(config, "sleep.voice_alignment.trainer_jobs_dir", "state/sleep/voice_align_jobs"),
        state_root=state_root,
        data_root=data_root,
    )
    reason = check_extra(trainer_jobs_path)
    if reason:
        refused.append((trainer_jobs_path.resolve(), reason))
    else:
        add(trainer_jobs_path)

    return tuple(roots), tuple(refused)


def within_delete_roots(path: Path, roots: tuple[Path, ...]) -> bool:
    """True when path (a symlink judged by its own location, not its target) lies inside or at one of roots."""
    if path.is_symlink():
        judged = path.parent.resolve() / path.name
    else:
        judged = path.resolve()
    for root in roots:
        if judged == root or judged.is_relative_to(root):
            return True
    return False
