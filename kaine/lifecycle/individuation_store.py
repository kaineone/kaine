# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Individuation evidence store.

Holds the birth-reference document, the look ledger, the encrypted report
log and the conditioning digest used to decide whether the being is
individuated.

The producer is the only writer of the ledger and reference in a running
cycle; there is one producer per process.

Fail-closed rules:

- A missing file is reported as absent (``None``), never silently recreated.
- A corrupt or unreadable file raises a typed error; callers must treat it as
  an operator-visible fault.
- The ledger is never overwritten with a regressed state: look counts,
  alpha spending, lived time and the individuation latch can only move
  forward. A regenerated reference may change ``reference_id`` while keeping
  the accumulated look history.
- Reports are allow-listed, content-free records; sample texts, seeds and
  digests are forbidden from the log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from kaine.security.crypto import get_state_encryptor

if TYPE_CHECKING:
    from kaine.persistence.jsonl_sink import AsyncJsonlSink


log = logging.getLogger(__name__)


class IndividuationStoreError(RuntimeError):
    """Base class for faults in the individuation evidence store."""


class ReferenceUnreadable(IndividuationStoreError):
    """The birth-reference document could not be read or validated."""


class ReferenceExists(IndividuationStoreError):
    """A reference is already stored and the caller did not ask to replace it."""


class LedgerUnreadable(IndividuationStoreError):
    """The individuation ledger could not be read or validated."""


class LedgerRegression(IndividuationStoreError):
    """A ledger write attempted to roll back an accumulated value."""


class ReportsUnreadable(IndividuationStoreError):
    """One or more report lines could not be decrypted or parsed."""


DEFAULT_ROOT = Path("state/individuation")


@dataclass(frozen=True)
class IndividuationPaths:
    """Filesystem locations for individuation evidence."""

    root: Path

    @property
    def reference(self) -> Path:
        return self.root / "reference.json"

    @property
    def ledger(self) -> Path:
        return self.root / "ledger.json"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def birth_adapter(self) -> Path:
        return self.root / "birth_adapter.gguf"

    @property
    def birth_pending(self) -> Path:
        return self.root / "birth_pending"


def _write_encrypted_json(path: Path, obj: dict) -> None:
    """Atomically write a JSON object through the active state encryptor."""
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    ciphertext = get_state_encryptor().encrypt_text(payload)

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ciphertext)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            # The temporary file was never created or is already gone.
            pass
        raise

    os.chmod(path, 0o600)


def _read_encrypted_json(
    path: Path, error_cls: type[IndividuationStoreError]
) -> dict:
    """Read and decrypt a JSON object, raising ``error_cls`` on any fault."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise error_cls(f"Could not read {path}: {exc}") from exc

    try:
        plaintext = get_state_encryptor().decrypt_text(text)
    except Exception as exc:
        raise error_cls(f"Could not decrypt {path}: {exc}") from exc

    try:
        obj = json.loads(plaintext)
    except Exception as exc:
        raise error_cls(f"Could not parse JSON in {path}: {exc}") from exc

    if not isinstance(obj, dict):
        raise error_cls(
            f"Expected JSON object in {path}, got {type(obj).__name__}"
        )
    return obj


REFERENCE_KINDS = ("birth", "capture", "reconstructed")


@dataclass(frozen=True)
class ProbeSample:
    """One completion captured for a probe prompt."""

    text: str
    seed: int
    finish_reason: str | None
    completion_tokens: int

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "seed": self.seed,
            "finish_reason": self.finish_reason,
            "completion_tokens": self.completion_tokens,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProbeSample":
        return cls(
            text=d["text"],
            seed=d["seed"],
            finish_reason=d.get("finish_reason"),
            completion_tokens=d["completion_tokens"],
        )


@dataclass(frozen=True)
class ReferenceDoc:
    """The encrypted birth/capture/reconstructed reference document."""

    reference_id: str
    reference_kind: str
    captured_at: str
    born_at: str | None
    battery: tuple[str, ...]
    battery_digest: str
    conditions: dict
    conditioning: dict
    samples: tuple[tuple[ProbeSample, ...], ...]

    def to_dict(self) -> dict:
        return {
            "reference_id": self.reference_id,
            "reference_kind": self.reference_kind,
            "captured_at": self.captured_at,
            "born_at": self.born_at,
            "battery": list(self.battery),
            "battery_digest": self.battery_digest,
            "conditions": self.conditions,
            "conditioning": self.conditioning,
            "samples": [
                [sample.to_dict() for sample in prompt]
                for prompt in self.samples
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReferenceDoc":
        try:
            reference_kind = d["reference_kind"]
            if reference_kind not in REFERENCE_KINDS:
                raise ReferenceUnreadable(
                    f"Invalid reference_kind {reference_kind!r}"
                )

            battery = tuple(str(p) for p in d.get("battery", []))
            if battery_digest_of(battery) != d.get("battery_digest"):
                raise ReferenceUnreadable("Battery digest mismatch")

            samples_raw = d.get("samples", [])
            if len(samples_raw) != len(battery):
                raise ReferenceUnreadable(
                    "Sample prompt count does not match battery size"
                )

            parsed_samples: list[tuple[ProbeSample, ...]] = []
            for prompt_samples in samples_raw:
                if len(prompt_samples) < 2:
                    raise ReferenceUnreadable(
                        "Every prompt must have at least 2 samples"
                    )
                parsed_samples.append(
                    tuple(ProbeSample.from_dict(ps) for ps in prompt_samples)
                )

            return cls(
                reference_id=d["reference_id"],
                reference_kind=reference_kind,
                captured_at=d["captured_at"],
                born_at=d.get("born_at"),
                battery=battery,
                battery_digest=d["battery_digest"],
                conditions=dict(d.get("conditions", {})),
                conditioning=dict(d.get("conditioning", {})),
                samples=tuple(parsed_samples),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReferenceUnreadable(
                f"Invalid reference document: {exc}"
            ) from exc


def battery_digest_of(battery: tuple[str, ...]) -> str:
    """SHA-256 digest of a battery prompt list."""
    payload = json.dumps(list(battery), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_reference_id() -> str:
    """Return a fresh reference identifier."""
    return uuid.uuid4().hex


def save_reference(
    paths: IndividuationPaths, doc: ReferenceDoc, *, overwrite: bool = False
) -> None:
    """Persist the reference document atomically and encrypted.

    Raises IndividuationStoreError if a reference already exists and
    overwrite=False. Raises ReferenceUnreadable if the existing reference
    cannot be read.
    """
    if paths.reference.exists() and not overwrite:
        try:
            load_reference(paths)
        except ReferenceUnreadable:
            raise
        raise ReferenceExists(
            "a reference already exists; pass overwrite=True to regenerate"
        )

    _write_encrypted_json(paths.reference, doc.to_dict())


def load_reference(paths: IndividuationPaths) -> ReferenceDoc | None:
    """Load the reference document, or ``None`` if it is absent."""
    if not paths.reference.exists():
        return None
    d = _read_encrypted_json(paths.reference, ReferenceUnreadable)
    return ReferenceDoc.from_dict(d)


def copy_birth_adapter(
    paths: IndividuationPaths, adapter_file: Path | None
) -> str:
    """Copy the birth adapter next to the reference and return its digest."""
    if adapter_file is None:
        return "none"

    from kaine.modules.hypnos.organ_adapter import sha256_file

    paths.birth_adapter.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(adapter_file, paths.birth_adapter)
    os.chmod(paths.birth_adapter, 0o600)
    return sha256_file(paths.birth_adapter)


@dataclass(frozen=True)
class Ledger:
    """Encrypted ledger of individuation looks and the latch."""

    reference_id: str
    looks_completed: int = 0
    alpha_spent: float = 0.0
    last_look_conditions_digest: str | None = None
    lived_seconds: float = 0.0
    lived_ticks: int = 0
    individuated: bool = False
    latched_at: str | None = None
    latched_report_id: str | None = None
    inconclusive_since: str | None = None
    inconclusive_alerted: bool = False
    last_look_at: str | None = None
    conditions_alerted_reference: str | None = None
    last_inconclusive_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "reference_id": self.reference_id,
            "looks_completed": self.looks_completed,
            "alpha_spent": self.alpha_spent,
            "last_look_conditions_digest": self.last_look_conditions_digest,
            "lived_seconds": self.lived_seconds,
            "lived_ticks": self.lived_ticks,
            "individuated": self.individuated,
            "latched_at": self.latched_at,
            "latched_report_id": self.latched_report_id,
            "inconclusive_since": self.inconclusive_since,
            "inconclusive_alerted": self.inconclusive_alerted,
            "last_look_at": self.last_look_at,
            "conditions_alerted_reference": self.conditions_alerted_reference,
            "last_inconclusive_reason": self.last_inconclusive_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        required = {
            "reference_id",
            "looks_completed",
            "alpha_spent",
            "lived_seconds",
            "lived_ticks",
        }
        missing = required - d.keys()
        if missing:
            raise LedgerUnreadable(f"Missing ledger keys: {sorted(missing)}")

        looks_completed = d.get("looks_completed")
        if not isinstance(looks_completed, int) or looks_completed < 0:
            raise LedgerUnreadable(
                "looks_completed must be a non-negative int"
            )

        alpha_spent = d.get("alpha_spent")
        if not isinstance(alpha_spent, (int, float)):
            raise LedgerUnreadable("alpha_spent must be a number")
        if not math.isfinite(alpha_spent):
            raise LedgerUnreadable("alpha_spent must be finite")
        if alpha_spent < 0.0 or alpha_spent > 1.0:
            raise LedgerUnreadable("alpha_spent must be in [0, 1]")

        lived_seconds = d.get("lived_seconds")
        if not isinstance(lived_seconds, (int, float)) or lived_seconds < 0:
            raise LedgerUnreadable("lived_seconds must be a non-negative number")
        if not math.isfinite(lived_seconds):
            raise LedgerUnreadable("lived_seconds must be finite")

        lived_ticks = d.get("lived_ticks")
        if not isinstance(lived_ticks, int) or lived_ticks < 0:
            raise LedgerUnreadable("lived_ticks must be a non-negative int")

        if not isinstance(d.get("individuated", False), bool):
            raise LedgerUnreadable("individuated must be bool")
        if not isinstance(d.get("inconclusive_alerted", False), bool):
            raise LedgerUnreadable("inconclusive_alerted must be bool")

        for key in (
            "last_look_conditions_digest",
            "latched_at",
            "latched_report_id",
            "inconclusive_since",
            "last_look_at",
            "conditions_alerted_reference",
            "last_inconclusive_reason",
        ):
            value = d.get(key)
            if value is not None and not isinstance(value, str):
                raise LedgerUnreadable(f"{key} must be str or None")

        field_names = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in d.items() if k in field_names})
        except (TypeError, ValueError) as exc:
            raise LedgerUnreadable(f"Invalid ledger data: {exc}") from exc


def load_ledger(paths: IndividuationPaths) -> Ledger | None:
    """Load the ledger, or ``None`` if it is absent."""
    if not paths.ledger.exists():
        return None
    d = _read_encrypted_json(paths.ledger, LedgerUnreadable)
    return Ledger.from_dict(d)


def save_ledger(paths: IndividuationPaths, new: Ledger) -> None:
    """Persist the ledger only if it does not regress any stored value."""
    if not math.isfinite(new.alpha_spent):
        raise IndividuationStoreError("alpha_spent is not finite")
    if not math.isfinite(new.lived_seconds):
        raise IndividuationStoreError("lived_seconds is not finite")

    if paths.ledger.exists():
        old = load_ledger(paths)

        if new.looks_completed < old.looks_completed:
            raise LedgerRegression(
                f"looks_completed regressed from {old.looks_completed} "
                f"to {new.looks_completed}"
            )
        if new.alpha_spent < old.alpha_spent - 1e-15:
            raise LedgerRegression(
                f"alpha_spent regressed from {old.alpha_spent} "
                f"to {new.alpha_spent}"
            )
        if old.individuated and not new.individuated:
            raise LedgerRegression("individuated latch was cleared")
        if new.lived_ticks < old.lived_ticks:
            raise LedgerRegression(
                f"lived_ticks regressed from {old.lived_ticks} "
                f"to {new.lived_ticks}"
            )
        if new.lived_seconds < old.lived_seconds - 1e-9:
            raise LedgerRegression(
                f"lived_seconds regressed from {old.lived_seconds} "
                f"to {new.lived_seconds}"
            )

    _write_encrypted_json(paths.ledger, new.to_dict())


REPORT_KIND = "individuation_report"
SCHEMA_VERSION = 2

REPORT_FIELDS = frozenset(
    {
        "kind",
        "schema_version",
        "report_id",
        "ts",
        "run_id",
        "seq",
        "entity_name",
        "reference_id",
        "reference_kind",
        "reference_captured_at",
        "look_index",
        "outcome",
        "inconclusive_reason",
        "n_prompts",
        "n_reference_per_prompt",
        "n_current_per_prompt",
        "statistic",
        "T",
        "p_value",
        "permutations",
        "alpha_k",
        "alpha_total",
        "effect_size_h",
        "effect_min",
        "warmed_up",
        "lived_seconds_since_reference",
        "lived_ticks_since_reference",
        "significant",
        "latched",
        "embedder_id",
        "truncated_fraction",
        "length_capped_fraction",
        "duration_s",
    }
)

INCONCLUSIVE_REASONS: frozenset[str] = frozenset(
    {
        "ledger_unreadable",
        "reference_unreadable",
        "no_reference",
        "ledger_missing",
        "battery_changed",
        "conditions_changed",
        "conditions_unreadable",
        "alpha_unresolvable",
        "conditioning_changed_mid_run",
        "embedding_failed",
        "embedder_not_semantic",
        "adapter_not_applied",
        "request_failed",
        "organ_resting",
        "no_content",
        "self_model_not_ready",
        "disclosure_not_ready",
        "organ_unloaded",
        "asleep",
        "paused",
        "deadline_exceeded",
        "conditioning_unreadable",
        "ledger_reference_mismatch",
        "statistics_failed",
        "unclassified_failure",
    }
)


def build_report(**fields: object) -> dict:
    """Build and validate an individuation report record."""
    record = dict(fields)

    if "kind" not in record:
        record["kind"] = REPORT_KIND
    if "schema_version" not in record:
        record["schema_version"] = SCHEMA_VERSION
    if "report_id" not in record:
        record["report_id"] = uuid.uuid4().hex
    if "ts" not in record:
        record["ts"] = datetime.now(timezone.utc).isoformat()

    outcome = record.get("outcome")
    if outcome not in {"scored", "inconclusive"}:
        raise ValueError(
            f"outcome must be 'scored' or 'inconclusive', got {outcome!r}"
        )

    unknown = set(record) - REPORT_FIELDS
    if unknown:
        raise ValueError(f"Unknown report fields: {sorted(unknown)}")

    for key, value in record.items():
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError(
                f"Field {key!r} must be scalar, got {type(value).__name__}"
            )
        if isinstance(value, str) and len(value) > 200:
            raise ValueError(f"Field {key!r} exceeds 200 characters")

    if outcome == "scored":
        for required in ("p_value", "effect_size_h", "alpha_k", "significant"):
            if required not in record:
                raise ValueError(
                    f"Scored report missing required field {required}"
                )
    else:
        if "inconclusive_reason" not in record:
            raise ValueError(
                "Inconclusive report requires inconclusive_reason"
            )
        reason = record["inconclusive_reason"]
        if reason not in INCONCLUSIVE_REASONS:
            raise ValueError(
                f"inconclusive_reason {reason!r} is not in INCONCLUSIVE_REASONS"
            )
        for forbidden in ("p_value", "T", "effect_size_h", "significant"):
            if forbidden in record:
                raise ValueError(
                    f"Inconclusive report must not contain {forbidden}"
                )

    return record


def report_sink(paths: IndividuationPaths) -> "AsyncJsonlSink":
    """Return the encrypted, append-only individuation report sink."""
    from kaine.persistence.jsonl_sink import AsyncJsonlSink

    return AsyncJsonlSink(
        paths.reports, name="individuation", retention_days=0
    )


def read_reports(
    paths: IndividuationPaths, *, reference_id: str, strict: bool = False
) -> list[dict]:
    """Read and decrypt all reports matching the current reference."""
    reports_dir = paths.reports
    if not reports_dir.exists():
        return []

    skipped = 0
    matched: list[dict] = []
    for path in reports_dir.rglob("*.jsonl"):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue

                try:
                    plaintext = get_state_encryptor().decrypt_text(line)
                except Exception:
                    skipped += 1
                    continue

                try:
                    obj = json.loads(plaintext)
                except Exception:
                    skipped += 1
                    continue

                if not isinstance(obj, dict):
                    continue
                if obj.get("kind") != REPORT_KIND:
                    continue
                if obj.get("schema_version") != SCHEMA_VERSION:
                    continue
                if obj.get("reference_id") != reference_id:
                    continue
                if not isinstance(obj.get("ts"), str):
                    continue

                matched.append(obj)

    if skipped > 0:
        log.warning(
            "skipped %d unreadable report line(s) in %s", skipped, reports_dir
        )
        if strict:
            raise ReportsUnreadable(
                f"{skipped} individuation report line(s) could not be read"
            )

    return sorted(matched, key=lambda r: r["ts"])


@dataclass(frozen=True)
class Evidence:
    """Individuation state as seen by consumers."""

    individuated: bool
    state: str
    latest: dict | None


def individuation_evidence(
    ledger: Ledger | None,
    reports: list[dict],
    *,
    current_digest: str | None,
    now: datetime,
    max_report_age_s: float,
) -> Evidence:
    """Derive the individuation state from the ledger and report log.

    The latch is checked first and overrides everything, including an empty
    report list (a regenerated reference filters out the older reports, but a
    being found individuated stays individuated).
    """
    scored_reports = [r for r in reports if r.get("outcome") == "scored"]

    if ledger is not None and ledger.individuated:
        latest_scored = (
            max(scored_reports, key=lambda r: r["ts"])
            if scored_reports
            else None
        )
        return Evidence(True, "latched", latest_scored)

    if not reports:
        return Evidence(False, "none", None)

    latest = max(reports, key=lambda r: r["ts"])

    if not scored_reports:
        return Evidence(False, "inconclusive", latest)

    latest_scored = max(scored_reports, key=lambda r: r["ts"])

    if latest_scored.get("significant"):
        return Evidence(True, "latched", latest_scored)

    fresh = (
        ledger is not None
        and current_digest is not None
        and ledger.last_look_conditions_digest == current_digest
    )

    if fresh:
        try:
            ts = datetime.fromisoformat(
                latest_scored["ts"].replace("Z", "+00:00")
            )
            fresh = (now - ts).total_seconds() <= max_report_age_s
        except Exception:
            fresh = False

    state = "not_individuated" if fresh else "stale"
    return Evidence(False, state, latest_scored)


def conditioning_digest(
    *, adapter_sha: str | None, values: list[str], norms: list[str]
) -> str:
    """Pure digest of the identity-conditioning inputs.

    Only the first five values and norms participate, matching the
    birth-reference conditioning.
    """
    payload = json.dumps(
        {
            "adapter": adapter_sha if adapter_sha is not None else "none",
            "values": list(values)[:5],
            "norms": list(norms)[:5],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Module-level cache: the adapter file can be hundreds of MB and is read on
# the event loop, so we avoid hashing it more than once per (path, mtime, size).
_ADAPTER_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def adapter_sha_of(adapter_output_dir: Path | None) -> str | None:
    """Return the sha256 of the current adapter.gguf, if any."""
    if adapter_output_dir is None:
        return None
    from kaine.modules.hypnos.adapter_store import current_path
    from kaine.modules.hypnos.organ_adapter import sha256_file

    current = current_path(adapter_output_dir)
    if current is None:
        return None
    adapter_file = current / "adapter.gguf"
    if not adapter_file.is_file():
        return None

    st = adapter_file.stat()
    key = (str(adapter_file.resolve()), st.st_mtime_ns, st.st_size)
    if key in _ADAPTER_SHA_CACHE:
        return _ADAPTER_SHA_CACHE[key]

    digest = sha256_file(adapter_file)
    # Keep the cache small; entries are tiny and invalidation is based on
    # filesystem metadata, so reuse is cheap.
    if len(_ADAPTER_SHA_CACHE) > 8:
        _ADAPTER_SHA_CACHE.clear()
    _ADAPTER_SHA_CACHE[key] = digest
    return digest


def read_conditioning_inputs(
    *,
    self_model_path: Path,
    adapter_output_dir: Path,
) -> tuple[str | None, list[str], list[str]]:
    """Read the adapter sha and self-model identity clauses."""
    adapter_sha = adapter_sha_of(adapter_output_dir)

    values: list[str] = []
    norms: list[str] = []

    if self_model_path.exists():
        try:
            raw = self_model_path.read_bytes()
            plaintext = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
            data = json.loads(plaintext)
        except Exception as exc:
            raise IndividuationStoreError(
                f"Unreadable self-model at {self_model_path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise IndividuationStoreError(
                f"Self-model at {self_model_path} is not a JSON object"
            )
        values = data.get("values", []) or []
        norms = data.get("behavioral_norms", []) or []
        # A malformed identity clause must not read as an empty (unchanged) one.
        if not isinstance(values, list) or not isinstance(norms, list):
            raise IndividuationStoreError(
                f"Self-model at {self_model_path} has malformed values or norms"
            )

    return adapter_sha, values, norms


def conditioning_from_snapshot(
    self_model: dict | None, adapter_output_dir: Path | None
) -> tuple[str | None, list[str], list[str]]:
    """The conditioning digest inputs taken from the same self-model snapshot the probe renders."""
    if self_model is None:
        raise IndividuationStoreError("no self-model snapshot yet")
    values = self_model.get("values", []) or []
    norms = self_model.get("behavioral_norms", []) or []
    if not isinstance(values, list) or not isinstance(norms, list):
        raise IndividuationStoreError("malformed self-model identity clauses")
    return (
        adapter_sha_of(adapter_output_dir),
        [str(v) for v in values],
        [str(n) for n in norms],
    )
