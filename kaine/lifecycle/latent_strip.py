# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The latent strip for module-state captures.

A module's serialized state holds no latent-derived value except learned
parameters that the module reads back on restore (the latent rule,
``kaine.privacy_filter``). Every capture of module states (the fork snapshot,
the preservation capture and the rolling resume checkpoint) passes its states
through ``strip_module_states``: a state that holds a key in ``LATENT_FIELDS``
at any depth loses it, the capture's metadata names the module under
``LATENT_STRIPPED_KEY`` and an error is logged.

The strip never refuses a capture. Refusing would block the welfare net's
preservation of an entity in distress over a privacy defect, and the entity's
preservation is the higher duty. A state the scan cannot walk is kept as it is,
named under ``LATENT_SCAN_FAILED_KEY`` and logged. The log names modules only,
never a value.

The strip is copy on write: a state with no latent field is the very same
object afterwards, so learned weights (lists of numbers under keys such as
``layers``) come back exactly as they went in.

One narrow exemption: in the episodic memory module's state, exactly the
field ``memory_state.<short_term | persisted.<collection>>[i].payload.
latent_derived.identity_bound`` of a stored trace is kept, rebuilt from its
three keys ``code``, ``code_id`` and ``generation`` (the entity's own encrypted
memory of a content code, ``kaine.modules.episodic_memory.identity_bound``), so
a preservation carries it with the store. Everything else, inside that field
included, is stripped and recorded as usual; no other module and no other
path has the exemption.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

from kaine.privacy_filter import (
    IDENTITY_BOUND_KEY,
    LATENT_DERIVED_KEY,
    identity_bound_value,
    without_latent_fields,
)

log = logging.getLogger(__name__)

# Capture metadata key naming the modules whose state held a latent field.
LATENT_STRIPPED_KEY = "latent_stripped"
# Capture metadata key naming the modules whose state could not be scanned.
LATENT_SCAN_FAILED_KEY = "latent_scan_failed"
#: The module whose state keeps identity-bound content, and the one subkey kept.
IDENTITY_BOUND_MODULE = "episodic_memory"

#: The longest exception message a module-state capture records or logs.
ERROR_MESSAGE_LIMIT = 200


def capped_error_text(exc: BaseException) -> str:
    """The exception type and at most ``ERROR_MESSAGE_LIMIT`` characters of its
    message, for a capture's record and log.

    The cap bounds size; it is not a privacy guarantee (200 characters still
    hold a short vector at full precision). Where a message could carry module
    state, a caller should record the type alone (``type(exc).__name__``).
    """
    try:
        message = str(exc)
    except Exception:
        message = "<message unavailable>"
    return f"{type(exc).__name__}: {message[:ERROR_MESSAGE_LIMIT]}"


def _trace_lists(state: Mapping[str, Any]) -> list[tuple[tuple[Any, ...], list]]:
    """The trace lists of an episodic memory state, with their paths: the
    short-term buffer and every persisted collection of ``memory_state``."""
    memory = state.get("memory_state") if isinstance(state, Mapping) else None
    if not isinstance(memory, Mapping):
        return []
    out: list[tuple[tuple[Any, ...], list]] = []
    short = memory.get("short_term")
    if isinstance(short, list):
        out.append((("memory_state", "short_term"), short))
    persisted = memory.get("persisted")
    if isinstance(persisted, Mapping):
        for name, points in persisted.items():
            if isinstance(points, list):
                out.append((("memory_state", "persisted", name), points))
    return out


def _set_path(root: Any, path: tuple[Any, ...], value: Any) -> Any:
    """A copy of ``root`` with ``value`` at ``path``, copying only the
    containers on the path."""
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(root, list):
        out = list(root)
        out[head] = _set_path(root[head], rest, value)
        return out
    out = dict(root)
    out[head] = _set_path(root.get(head, {}), rest, value)
    return out


def _without_latent_keeping_identity_bound(state: Any) -> Any:
    """``without_latent_fields`` on an episodic memory state, except exactly
    one field: the ``latent_derived.identity_bound`` of a trace's payload in
    ``memory_state`` (the short-term buffer or a persisted collection), rebuilt
    from its three keys (``kaine.privacy_filter.identity_bound_value``). A
    malformed field, any other key of that ``latent_derived`` mapping, a latent
    field nested inside the field, and the same key anywhere else are
    stripped. Copy on write: a state that already holds only well-formed
    fields is returned as the same object."""
    keep: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for base, traces in _trace_lists(state):
        for i, trace in enumerate(traces):
            payload = trace.get("payload") if isinstance(trace, Mapping) else None
            latent = payload.get(LATENT_DERIVED_KEY) if isinstance(payload, Mapping) else None
            if isinstance(latent, Mapping) and IDENTITY_BOUND_KEY in latent:
                bound = identity_bound_value(latent[IDENTITY_BOUND_KEY])
                if bound is not None:
                    keep.append((base + (i, "payload", LATENT_DERIVED_KEY), {IDENTITY_BOUND_KEY: bound}))
    clean = without_latent_fields(state)
    for path, field in keep:
        clean = _set_path(clean, path, field)
    if clean is not state and clean == state:
        return state
    return clean


def strip_module_states(
    modules: Mapping[str, Any], *, capture: str
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Return ``(states, metadata)``: the module states without latent fields,
    and the metadata entries to merge into the capture's metadata (empty when
    every state was clean). ``capture`` names the capture in the log."""
    out: dict[str, Any] = {}
    stripped: list[str] = []
    unscanned: list[str] = []
    for name, state in modules.items():
        try:
            if name == IDENTITY_BOUND_MODULE:
                clean = _without_latent_keeping_identity_bound(state)
            else:
                clean = without_latent_fields(state)
        except Exception as exc:
            # Never refuse the capture; keep the state and say so.
            log.error(
                "%s: the state of module %s could not be scanned for latent fields "
                "(%s); it is kept as serialized",
                capture,
                name,
                type(exc).__name__,
            )
            unscanned.append(name)
            out[name] = state
            continue
        if clean is not state:
            stripped.append(name)
        out[name] = clean
    metadata: dict[str, list[str]] = {}
    if stripped:
        metadata[LATENT_STRIPPED_KEY] = sorted(stripped)
        log.error(
            "%s: removed latent fields from the state of %s; a module state may "
            "hold no latent value other than learned parameters (the latent rule, "
            "kaine.privacy_filter)",
            capture,
            ", ".join(sorted(stripped)),
        )
    if unscanned:
        metadata[LATENT_SCAN_FAILED_KEY] = sorted(unscanned)
    return out, metadata


def _content_free_summary(summary: Any) -> dict[str, Any]:
    """The three-scalar form of a buffer summary (an older per-dimension one
    keeps its count, with zero for the other two)."""

    def _number(value: Any, *, integer: bool) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return 0 if integer else 0.0
        return int(value) if integer else float(value)

    if not isinstance(summary, Mapping):
        return {"n_frames": 0, "mean_norm": 0.0, "mean_variance": 0.0}
    count = summary.get("n_frames", summary.get("n_utterances", 0))
    return {
        "n_frames": max(0, _number(count, integer=True)),
        "mean_norm": _number(summary.get("mean_norm", 0.0), integer=False),
        "mean_variance": _number(summary.get("mean_variance", 0.0), integer=False),
    }


def content_free_buffer_summaries(modules: Mapping[str, Any]) -> dict[str, Any]:
    """Module states with every forward-model buffer summary in the
    content-free three-scalar form: ``vision.buffer_summary``,
    ``audition.auditory_buffer_summary`` and each entry's ``buffer_summary`` of
    ``audition.acoustic_forward_models``. A fork or merge of a snapshot written
    by an older build would otherwise copy its per-dimension means into a new
    file. Copy on write; learned weights are untouched."""
    out = dict(modules)
    vision = out.get("vision")
    if isinstance(vision, Mapping) and "buffer_summary" in vision:
        fixed = _content_free_summary(vision["buffer_summary"])
        if fixed != vision["buffer_summary"]:
            out["vision"] = {**vision, "buffer_summary": fixed}
    audition = out.get("audition")
    if isinstance(audition, Mapping):
        new = dict(audition)
        if "auditory_buffer_summary" in new:
            new["auditory_buffer_summary"] = _content_free_summary(new["auditory_buffer_summary"])
        acoustic = new.get("acoustic_forward_models")
        if isinstance(acoustic, Mapping):
            new["acoustic_forward_models"] = {
                k: ({**v, "buffer_summary": _content_free_summary(v["buffer_summary"])}
                    if isinstance(v, Mapping) and "buffer_summary" in v else v)
                for k, v in acoustic.items()
            }
        if new != audition:
            out["audition"] = new
    return out
