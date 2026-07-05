"""Pure-Python Narsese helpers.

KAINE talks to ONA through plain text lines. This module owns the small
parsing surface — converting between Python and Narsese — so the module
and the subprocess wrapper stay simple.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TruthValue:
    """ONA's (frequency, confidence) pair."""

    frequency: float
    confidence: float

    def as_narsese(self) -> str:
        return f"%{self.frequency};{self.confidence}%"


# ONA atoms must be alphanumeric + underscore. Anything else gets collapsed.
_ATOM_SAFE = re.compile(r"[^A-Za-z0-9_]")


def slugify_atom(s: str) -> str:
    """Coerce an arbitrary string into a Narsese-safe atom.

    Empty input becomes the string "unknown" so the result is always a
    valid Narsese term.
    """
    if not s:
        return "unknown"
    cleaned = _ATOM_SAFE.sub("_", s)
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "unknown"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def make_belief(
    source: str,
    type_: str,
    salience: float,
    *,
    confidence: float = 0.9,
) -> str:
    """Build the v1 Narsese statement for a KAINE event.

    `<{source} --> [{type}]>. :|: %{salience};{confidence}%`

    Salience is clamped into `[0, 1]` so the resulting truth-value
    stays valid even when the publisher emits an out-of-range salience
    (the bus schema enforces this too, but this helper is robust on
    its own).
    """
    src_atom = slugify_atom(source)
    type_atom = slugify_atom(type_)
    f = max(0.0, min(1.0, float(salience)))
    c = max(0.0, min(1.0, float(confidence)))
    return f"<{src_atom} --> [{type_atom}]>. :|: %{f};{c}%"


def make_implication(antecedent: str, consequent: str, *, confidence: float = 0.7) -> str:
    """Temporal implication used when an event carries a causal_parent.

    `<{antecedent} =/> {consequent}>. :|: %1.0;{confidence}%`
    """
    c = max(0.0, min(1.0, float(confidence)))
    return f"<{antecedent} =/> {consequent}>. :|: %1.0;{c}%"


# Lines we extract from NAR output.
_LINE_KINDS = ("Input", "Selected", "Derived", "Revised", "Answer")

_LINE_RE = re.compile(
    r"^(?P<kind>Input|Selected|Derived|Revised|Answer):\s+"
    r"(?P<body>.*?)"
    r"\s+(?:Priority=[\d.]+\s+)?(?:Stamp=\[[^\]]*\]\s+)?"
    r"Truth:\s*frequency=(?P<freq>-?[\d.]+)\s*,\s*confidence=(?P<conf>-?[\d.]+)"
    r"\s*$"
)


@dataclass(frozen=True)
class Derivation:
    """A single line from NAR output that carries a truth-value."""

    kind: str  # "Input" | "Selected" | "Derived" | "Revised" | "Answer"
    statement: str
    truth: TruthValue


def parse_derivation_line(line: str) -> Optional[Derivation]:
    """Parse one NAR output line. Returns None for lines we don't recognize."""
    line = line.strip()
    if not any(line.startswith(prefix + ":") for prefix in _LINE_KINDS):
        return None
    m = _LINE_RE.match(line)
    if not m:
        return None
    body = m.group("body").strip()
    # ONA prefixes time-related lines with `dt=N.NNNNNN ` followed by the
    # actual statement. Strip that prefix so the statement is clean.
    body = re.sub(r"^dt=-?[\d.]+\s+", "", body).strip()
    # Some lines end with `occurrenceTime=N` between the statement and
    # Priority/Truth. Strip that too.
    body = re.sub(r"\s+occurrenceTime=-?\d+(?=\s|$)", "", body).strip()
    return Derivation(
        kind=m.group("kind"),
        statement=body,
        truth=TruthValue(
            frequency=float(m.group("freq")),
            confidence=float(m.group("conf")),
        ),
    )
