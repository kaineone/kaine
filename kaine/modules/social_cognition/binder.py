# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BindingObservation:
    """One co-occurrence observation between a voice agent and a face agent."""

    voice_agent_id: str
    face_agent_id: str
    voice_confidence: float
    face_confidence: float
    voice_reliability: float
    face_reliability: float
    timestamp: float


_Event = tuple[str, float, float, float]  # agent_id, confidence, reliability, timestamp


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


class CrossModalBinder:
    """Correlates voice and face identifications and accumulates common-cause confidence."""

    def __init__(
        self,
        *,
        co_occurrence_window_s: float = 3.0,
        merge_threshold: float = 0.9,
        p_common_prior: float = 0.7,
        ema_decay: float = 0.85,
    ) -> None:
        self._window = co_occurrence_window_s
        self._merge_threshold = merge_threshold
        self._prior = p_common_prior
        self._decay = ema_decay
        self._voice_events: list[_Event] = []
        self._face_events: list[_Event] = []
        self._confidence: dict[tuple[str, str], float] = {}
        # A pair of events must only be counted once across check_bindings calls.
        self._seen: set[tuple[tuple[str, float], tuple[str, float]]] = set()

    def observe_voice(
        self, agent_id: str, confidence: float, reliability: float, timestamp: float
    ) -> None:
        """Record a voice identification event."""
        self._voice_events.append((agent_id, confidence, reliability, timestamp))

    def observe_face(
        self, agent_id: str, confidence: float, reliability: float, timestamp: float
    ) -> None:
        """Record a face identification event."""
        self._face_events.append((agent_id, confidence, reliability, timestamp))

    def check_bindings(self) -> list[BindingObservation]:
        """Find new voice+face co-occurrences, update confidences, and prune expired events."""
        observations: list[BindingObservation] = []
        for v_id, v_conf, v_rel, v_ts in self._voice_events:
            for f_id, f_conf, f_rel, f_ts in self._face_events:
                if abs(v_ts - f_ts) > self._window:
                    continue
                key = ((v_id, v_ts), (f_id, f_ts))
                if key in self._seen:
                    continue
                self._seen.add(key)
                obs = BindingObservation(
                    voice_agent_id=v_id,
                    face_agent_id=f_id,
                    voice_confidence=v_conf,
                    face_confidence=f_conf,
                    voice_reliability=v_rel,
                    face_reliability=f_rel,
                    timestamp=max(v_ts, f_ts),
                )
                observations.append(obs)
                self._accumulate(obs)

        latest = max(
            [e[3] for e in self._voice_events] + [e[3] for e in self._face_events],
            default=None,
        )
        if latest is not None:
            cutoff = latest - self._window
            self._voice_events = [e for e in self._voice_events if e[3] >= cutoff]
            self._face_events = [e for e in self._face_events if e[3] >= cutoff]
            self._seen = {
                k
                for k in self._seen
                if k[0][1] >= cutoff and k[1][1] >= cutoff
            }
        return observations

    def binding_confidence(self, agent_a: str, agent_b: str) -> float | None:
        """Return accumulated binding confidence between two agents, or None if unobserved."""
        return self._confidence.get(_pair(agent_a, agent_b))

    def should_merge(self, agent_a: str, agent_b: str) -> bool:
        """True when accumulated binding confidence exceeds merge_threshold."""
        conf = self.binding_confidence(agent_a, agent_b)
        return conf is not None and conf > self._merge_threshold

    def record_merge(self, kept_id: str, merged_id: str) -> None:
        """Redirect all tracking of merged_id to kept_id after a merge."""
        self._voice_events = [
            (kept_id if e[0] == merged_id else e[0], *e[1:]) for e in self._voice_events
        ]
        self._face_events = [
            (kept_id if e[0] == merged_id else e[0], *e[1:]) for e in self._face_events
        ]
        self._seen = {
            (
                (kept_id if k[0][0] == merged_id else k[0][0], k[0][1]),
                (kept_id if k[1][0] == merged_id else k[1][0], k[1][1]),
            )
            for k in self._seen
        }
        redirected: dict[tuple[str, str], float] = {}
        for (a, b), conf in self._confidence.items():
            a2 = kept_id if a == merged_id else a
            b2 = kept_id if b == merged_id else b
            if a2 == b2:
                continue
            pair = _pair(a2, b2)
            redirected[pair] = max(conf, redirected.get(pair, conf))
        self._confidence = redirected

    def _posterior(self, obs: BindingObservation) -> float:
        total = obs.voice_reliability + obs.face_reliability
        if obs.voice_reliability > 0 and obs.face_reliability > 0:
            w_voice = obs.voice_reliability / total
        else:
            w_voice = 0.5
        combined = w_voice * obs.voice_confidence + (1.0 - w_voice) * obs.face_confidence
        combined = min(1.0, max(0.0, combined))
        num = combined * self._prior
        den = num + (1.0 - combined) * (1.0 - self._prior)
        return num / den if den > 0 else self._prior

    def _accumulate(self, obs: BindingObservation) -> None:
        if obs.voice_agent_id == obs.face_agent_id:
            return
        pair = _pair(obs.voice_agent_id, obs.face_agent_id)
        posterior = self._posterior(obs)
        old = self._confidence.get(pair)
        if old is None:
            old = self._prior
        self._confidence[pair] = self._decay * old + (1.0 - self._decay) * posterior
