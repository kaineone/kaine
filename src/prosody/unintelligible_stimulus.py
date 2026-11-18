"""Syllable/nonlexical prosody content for unintelligible stimulus."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Syllable:
    """A single syllable unit in nonlexical prosody content."""

    consonant: str = ""
    vowel: str = ""
    duration_ms: float = 0.0
    pitch_hz: float = 0.0
    intensity_db: float = 0.0


@dataclass
class ProsodyContour:
    """Pitch/intensity contour metadata for a syllable sequence."""

    pitch_values: List[float] = field(default_factory=list)
    intensity_values: List[float] = field(default_factory=list)
    tempo_bpm: float = 0.0


@dataclass
class UnintelligibleStimulus:
    """Unintelligible stimulus defined by syllable/nonlexical prosody content."""

    syllables: List[Syllable] = field(default_factory=list)
    prosody: ProsodyContour = field(default_factory=ProsodyContour)
    repeat_count: int = 1

    def syllable_count(self) -> int:
        return len(self.syllables)

    def total_duration_ms(self) -> float:
        return sum(s.duration_ms for s in self.syllables) * self.repeat_count