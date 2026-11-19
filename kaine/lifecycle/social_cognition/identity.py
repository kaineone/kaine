# SPDX-FileCopyrightText: 2024 KAINE developers
# SPDX-License-Identifier: MIT
"""Cross‑modal identity binding primitives.

This module provides a lightweight ``Identity`` data‑class and utilities to
bind (merge) multiple identities that refer to the same underlying entity.
The implementation is deliberately minimal – it only covers the behaviour
required by the test‑suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Set


@dataclass(eq=False, frozen=False)
class Identity:
    """A representation of a perceived entity.

    Attributes
    ----------
    identifier:
        A stable string that uniquely identifies the entity across modalities.
    modalities:
        The set of modalities (e.g. ``"vision"``, ``"audio"``) that contributed
        to this identity.
    attributes:
        Arbitrary key‑value pairs describing the entity (e.g. colour,
        voice pitch, bounding‑box).  When identities are merged, later values
        override earlier ones.
    """

    identifier: str
    modalities: Set[str] = field(default_factory=set)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalise modalities to a set of strings.
        if not isinstance(self.modalities, set):
            self.modalities = set(self.modalities)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Identity):
            return NotImplemented
        return self.identifier == other.identifier

    def __hash__(self) -> int:
        return hash(self.identifier)

    def merge(self, other: Identity) -> Identity:
        """Merge *other* into ``self`` and return a new ``Identity``.

        The merge is only defined for identities that share the same
        ``identifier``.  The resulting identity contains the union of the
        modalities and a shallow merge of the attribute dictionaries where
        values from *other* take precedence.

        Parameters
        ----------
        other:
            The identity to merge with this one.

        Returns
        -------
        Identity
            A new identity instance representing the combined information.

        Raises
        ------
        ValueError
            If the identifiers differ.
        """
        if self.identifier != other.identifier:
            raise ValueError(
                f"Cannot merge identities with different identifiers: "
                f"{self.identifier!r} vs {other.identifier!r}"
            )
        merged_modalities = self.modalities | other.modalities
        merged_attributes = {**self.attributes, **other.attributes}
        return Identity(
            identifier=self.identifier,
            modalities=merged_modalities,
            attributes=merged_attributes,
        )


def bind_identities(identities: Iterable[Identity]) -> Identity:
    """Bind (merge) an iterable of ``Identity`` objects.

    The function reduces the supplied ``identities`` by repeatedly applying
    :meth:`Identity.merge`.  All identities must share the same ``identifier``;
    otherwise a ``ValueError`` is raised.

    Parameters
    ----------
    identities:
        An iterable of ``Identity`` objects to bind.

    Returns
    -------
    Identity
        The combined identity.

    Raises
    ------
    ValueError
        If *identities* is empty or contains mismatching identifiers.
    """
    iterator = iter(identities)
    try:
        bound = next(iterator)
    except StopIteration as exc:
        raise ValueError("bind_identities() requires at least one Identity") from exc

    for other in iterator:
        bound = bound.merge(other)

    return bound