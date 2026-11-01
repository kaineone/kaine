# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Companion streams: values that never enter a persisted bus stream.

The main Redis bus writes every entry to its append-only file, so a value on it
reaches disk. Some classes of value must never reach disk this way: values
derived from perceptual latents (the latent rule, ``kaine.privacy_filter``) and,
under the change ``heard-text-volatile-bus``, heard and spoken words. Each class
is a *field set*: a rule that splits a payload into the part that may be
persisted and the values that may not.

Every main-bus publish applies every field set (``kaine.bus.client``). The
diverted values go to the companion stream ``<stream>.companion`` of a second,
never-persisted Redis instance (``kaine.bus.volatile``) only when a producer has
declared that stream for that field set; otherwise they are dropped. The
companion entry is written first, and the main entry's envelope (outside its
payload) names it in the field ``companion``, so a consumer that sees the main
entry finds its companion already written. A consumer that finds no companion
entry treats the values as absent. A value is lost, never moved onto the
persisted stream.

This module is pure (no Redis): the field sets, the split, the merge back and
the producer declarations.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

#: Suffix of the companion stream of a main-bus stream, on the volatile instance.
COMPANION_SUFFIX = ".companion"
#: The main entry's envelope field (beside ``payload``) naming its companion entry.
COMPANION_FIELD = "companion"

#: A path into a payload: mapping keys and list indices.
Path = tuple[Any, ...]
#: The values one field set diverted from one payload: ``[(path, value, index)]``,
#: where ``index`` is the key's position among its mapping's keys before the split
#: (so the merge restores the original key order exactly).
Diverted = list[tuple[Path, Any, Any]]


def companion_stream(stream: str) -> str:
    """The companion stream of ``stream`` on the volatile instance."""
    return stream + COMPANION_SUFFIX


def companion_ref(stream: str, entry_id: str) -> str:
    """The envelope value naming a companion entry: ``<companion stream>:<id>``."""
    return f"{stream}:{entry_id}"


def parse_companion_ref(ref: str) -> Optional[tuple[str, str]]:
    """``(companion stream, entry id)`` from an envelope value, or None when it is
    not a companion reference. Redis entry ids hold no colon, so the last colon
    separates them."""
    if not isinstance(ref, str):
        return None
    stream, sep, entry_id = ref.rpartition(":")
    if not sep or not stream.endswith(COMPANION_SUFFIX) or not entry_id:
        return None
    return stream, entry_id


@dataclass(frozen=True)
class FieldSet:
    """A named rule that diverts some values of a payload off the persisted bus.

    ``split(event_type, payload, extra_keys)`` returns ``(main_payload,
    diverted)``: the payload without the diverted values, and each diverted
    value with its path. ``extra_keys`` are field names producers declared into
    this field set (``CompanionDeclaration.extra_fields``), diverted at any
    depth on every event in addition to the set's own rule.
    It returns the very same payload object and an empty list when there is
    nothing to divert. Diverting removes a mapping key; list lengths never
    change, so the paths stay valid in the main payload.
    """

    name: str
    split: Callable[[str, Mapping[str, Any], frozenset[str]], tuple[dict[str, Any], Diverted]]
    #: Undoes what the split added beside the removed values (for example the
    #: spoken-text counts) once they are back; None when it added nothing.
    after_merge: Optional[Callable[[dict[str, Any], Diverted], dict[str, Any]]] = None


def split_keys(payload: Any, keys: frozenset[str]) -> tuple[Any, Diverted]:
    """Remove every mapping key in ``keys`` at any depth, copy on write."""
    diverted: Diverted = []
    out = _split_keys(payload, keys, (), diverted)
    return out, diverted


def _split_keys(node: Any, keys: frozenset[str], path: Path, diverted: Diverted) -> Any:
    if isinstance(node, Mapping):
        changed = False
        out: dict[Any, Any] = {}
        for index, (k, v) in enumerate(node.items()):
            if k in keys:
                diverted.append((path + (k,), v, index))
                changed = True
                continue
            nv = _split_keys(v, keys, path + (k,), diverted)
            changed = changed or nv is not v
            out[k] = nv
        return out if changed else node
    if isinstance(node, (list, tuple)):
        items = [_split_keys(item, keys, path + (i,), diverted) for i, item in enumerate(node)]
        if all(a is b for a, b in zip(items, node)):
            return node
        return items if isinstance(node, list) else tuple(items)
    return node


def _latent_split(
    event_type: str, payload: Mapping[str, Any], extra_keys: frozenset[str] = frozenset()
) -> tuple[dict[str, Any], Diverted]:
    # Imported here: kaine.privacy_filter imports kaine.bus.schema, whose package
    # imports this module.
    from kaine.privacy_filter import LATENT_FIELDS

    return split_keys(payload, LATENT_FIELDS | extra_keys)


#: The latent field set: every key in ``LATENT_FIELDS`` at any depth.
LATENT_FIELD_SET = FieldSet("latent", _latent_split)


def default_field_sets() -> tuple[FieldSet, ...]:
    """The field sets every main-bus publish applies, in split order."""
    return (LATENT_FIELD_SET,)


def merge_diverted(payload: Mapping[str, Any], diverted: Iterable[tuple[Any, ...]]) -> dict[str, Any]:
    """A copy of ``payload`` with each diverted value put back at its path, a
    mapping key at its original position.

    A path whose parent is missing or of the wrong kind is skipped, so a
    malformed companion entry never raises into a consumer.
    """
    out = copy.deepcopy(dict(payload))
    for item in diverted:
        path, value = tuple(item[0]), item[1]
        index = item[2] if len(item) > 2 else None
        if not path:
            continue
        node: Any = out
        ok = True
        for step in path[:-1]:
            if isinstance(node, dict) and step in node:
                node = node[step]
            elif isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
                node = node[step]
            else:
                ok = False
                break
        if not ok:
            continue
        last = path[-1]
        if isinstance(node, dict):
            _insert_at(node, last, copy.deepcopy(value), index)
        elif isinstance(node, list) and isinstance(last, int) and 0 <= last < len(node):
            node[last] = copy.deepcopy(value)
    return out


def _insert_at(node: dict, key: Any, value: Any, index: Any) -> None:
    """Set ``node[key]``, at position ``index`` among the keys when given."""
    if key in node or isinstance(index, bool) or not isinstance(index, int):
        node[key] = value
        return
    items = list(node.items())
    items.insert(max(0, min(index, len(items))), (key, value))
    node.clear()
    node.update(items)


@dataclass(frozen=True)
class CompanionDeclaration:
    """A producer's declaration that ``stream`` carries ``field_set`` values a
    consumer needs, so they travel on ``<stream>.companion``."""

    producer: str
    stream: str
    field_set: str
    #: Optional age bound, in wall-clock seconds: entries of this companion
    #: stream older than it are trimmed (``XTRIM MINID``) on every write and read
    #: as missing. A bound declared by any producer of a stream bounds the whole
    #: companion stream. None: the stream is bounded by its cap alone.
    max_age_s: Optional[float] = None
    #: Field names this producer adds to ``field_set``: diverted at any depth on
    #: every event, on every stream, while the producer is enabled.
    extra_fields: frozenset[str] = frozenset()


class CompanionRegistry:
    """The active field sets, in split order, and the declared companion streams."""

    def __init__(
        self,
        field_sets: Optional[Iterable[FieldSet]] = None,
        declarations: Iterable[CompanionDeclaration] = (),
    ) -> None:
        self._field_sets = tuple(field_sets) if field_sets is not None else default_field_sets()
        names = [fs.name for fs in self._field_sets]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate field set names: {names}")
        self._declarations: tuple[CompanionDeclaration, ...] = ()
        self.declare(declarations)

    @property
    def field_sets(self) -> tuple[FieldSet, ...]:
        return self._field_sets

    @property
    def declarations(self) -> tuple[CompanionDeclaration, ...]:
        return self._declarations

    def declare(self, declarations: Iterable[CompanionDeclaration]) -> None:
        known = {fs.name for fs in self._field_sets}
        added = list(self._declarations)
        for decl in declarations:
            if decl.field_set not in known:
                raise ValueError(
                    f"{decl.producer} declares {decl.stream} for unknown field set {decl.field_set!r}"
                )
            if decl.max_age_s is not None and (
                isinstance(decl.max_age_s, bool)
                or not isinstance(decl.max_age_s, (int, float))
                or not math.isfinite(decl.max_age_s)
                or decl.max_age_s <= 0
            ):
                raise ValueError(
                    f"{decl.producer} declares {decl.stream} with an invalid age bound {decl.max_age_s!r}"
                )
            if decl not in added:
                added.append(decl)
        self._declarations = tuple(added)

    def declared(self, stream: str, field_set: str) -> bool:
        return any(d.stream == stream and d.field_set == field_set for d in self._declarations)

    def extra_fields(self, field_set: str) -> frozenset[str]:
        """The field names declarations add to ``field_set``."""
        out: set[str] = set()
        for d in self._declarations:
            if d.field_set == field_set:
                out |= set(d.extra_fields)
        return frozenset(out)

    def max_age_s(self, stream: str) -> Optional[float]:
        """The age bound of ``stream``'s companion stream: the smallest any of its
        declarations sets, or None when none sets one (off means absent)."""
        ages = [float(d.max_age_s) for d in self._declarations if d.stream == stream and d.max_age_s is not None]
        return min(ages) if ages else None

    def has_age_bounds(self) -> bool:
        return any(d.max_age_s is not None for d in self._declarations)

    def companion_streams(self) -> list[str]:
        """Every declared companion stream, sorted."""
        return sorted({companion_stream(d.stream) for d in self._declarations})

    def producers(self) -> list[str]:
        return sorted({d.producer for d in self._declarations})

    def split(
        self, stream: str, event_type: str, payload: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], dict[str, Diverted], bool]:
        """Apply every field set in order.

        Returns ``(main_payload, to_companion, diverted_any)``: the payload for
        the persisted stream, the diverted values of each field set declared
        for ``stream`` (undeclared ones are dropped), and whether anything was
        diverted at all. With nothing to divert the payload object is returned
        unchanged.
        """
        main: Any = payload
        to_companion: dict[str, Diverted] = {}
        diverted_any = False
        for fs in self._field_sets:
            main, diverted = fs.split(event_type, main, self.extra_fields(fs.name))
            if diverted:
                diverted_any = True
                if self.declared(stream, fs.name):
                    to_companion[fs.name] = diverted
        return main, to_companion, diverted_any

    def merge(self, payload: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
        """Put a companion entry's values back, in the reverse of split order."""
        out: Any = payload
        for fs in reversed(self._field_sets):
            diverted = values.get(fs.name)
            if isinstance(diverted, list):
                items = [
                    (tuple(item[0]), item[1], item[2] if len(item) > 2 else None)
                    for item in diverted
                    if isinstance(item, (list, tuple)) and len(item) in (2, 3)
                    and isinstance(item[0], (list, tuple))
                ]
                out = merge_diverted(out, items)
                if fs.after_merge is not None:
                    out = fs.after_merge(out, items)
        return dict(out)
