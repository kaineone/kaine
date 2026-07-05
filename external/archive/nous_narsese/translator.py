from __future__ import annotations

from typing import Protocol, runtime_checkable

from kaine.bus.schema import Event
from kaine.modules.nous.narsese import (
    make_belief,
    make_implication,
    slugify_atom,
)


@runtime_checkable
class Translator(Protocol):
    def translate(self, event: Event) -> list[str]: ...


class EventTranslator:
    """v1 translator: one inheritance per event + an implication when there's a parent.

    Designed to keep first-version Narsese surface area small. Future
    versions can mix in payload features and richer copulas.
    """

    def __init__(self, default_confidence: float = 0.9) -> None:
        if not 0.0 <= default_confidence <= 1.0:
            raise ValueError("default_confidence must be in [0, 1]")
        self._default_confidence = float(default_confidence)

    def translate(self, event: Event) -> list[str]:
        statements: list[str] = []
        statements.append(
            make_belief(
                event.source,
                event.type,
                event.salience,
                confidence=self._default_confidence,
            )
        )
        parent = event.causal_parent
        if parent:
            parent_atom = slugify_atom(parent)
            child_atom = f"<{slugify_atom(event.source)} --> [{slugify_atom(event.type)}]>"
            statements.append(
                make_implication(
                    antecedent=parent_atom,
                    consequent=child_atom,
                    confidence=self._default_confidence * 0.78,
                )
            )
        return statements
