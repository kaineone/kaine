# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral decision client for the K1-Jev model."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from kaine.decision.schema import (
    SCHEMA_VERSION,
    get_question,
    schema_digest,
    state_text,
    systemone_questions,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Answer",
    "DecisionClient",
    "DecisionConfig",
    "load_thresholds",
]


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "kaine-decision-model"})


def check_local_url(url: str) -> None:
    """Raise ValueError unless *url* is plain http to a host in LOCAL_HOSTS."""
    parsed = urlsplit(url)
    if parsed.scheme != "http" or (parsed.hostname or "") not in LOCAL_HOSTS:
        raise ValueError(
            "decision server url must be plain http on loopback or the compose service "
            f"(one of {sorted(LOCAL_HOSTS)}); refusing {parsed.scheme}://{parsed.hostname}"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "decision server url must be plain http on loopback or the compose service "
            f"(one of {sorted(LOCAL_HOSTS)}) with no credentials, query, or fragment; "
            f"refusing {parsed.scheme}://{parsed.hostname}"
        )


@dataclass(frozen=True)
class DecisionConfig:
    enabled: bool = False
    url: str = "http://127.0.0.1:11436"
    model: str = "k1-jev"
    timeout_s: float = 5.0
    thresholds_path: str = ""

    _KNOWN_KEYS = frozenset(
        {"enabled", "url", "model", "timeout_s", "thresholds_path"}
    )

    def __post_init__(self) -> None:
        # The client sends the server key and the entity's external speech.
        # Both stay on this host: only loopback or the compose service name.
        check_local_url(self.url)

    @classmethod
    def from_section(cls, section: dict | None) -> "DecisionConfig":
        """Build a config from a config-section mapping.

        Only the known keys are accepted. An unknown key raises ``ValueError``.
        """
        if not section:
            return cls()

        unknown = set(section) - cls._KNOWN_KEYS
        if unknown:
            name = sorted(unknown)[0]
            raise ValueError(f"Unknown decision config key: {name!r}")

        return cls(
            enabled=section.get("enabled", False),
            url=section.get("url", "http://127.0.0.1:11436"),
            model=section.get("model", "k1-jev"),
            timeout_s=section.get("timeout_s", 5.0),
            thresholds_path=section.get("thresholds_path", ""),
        )


def load_thresholds(path: str) -> dict[str, float] | None:
    """Load a K1-Jev thresholds sidecar file.

    Returns ``None`` (and logs a content-free warning) if the file is missing,
    unreadable, or does not match the current decision schema.
    """
    if not path:
        return None

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning(
            "Decision thresholds file unreadable: %s", type(exc).__name__
        )
        return None

    if data.get("schema_version") != SCHEMA_VERSION:
        logger.warning("Decision thresholds schema version mismatch")
        return None

    if data.get("schema_digest") != schema_digest():
        logger.warning("Decision thresholds schema digest mismatch")
        return None

    raw_thresholds = data.get("thresholds")
    if not isinstance(raw_thresholds, dict):
        logger.warning("Decision thresholds 'thresholds' field missing or invalid")
        return None

    result: dict[str, float] = {}
    for qid, value in raw_thresholds.items():
        try:
            threshold = float(value)
        except Exception:
            logger.warning("Decision threshold for %r is not numeric", qid)
            return None

        if not (0.0 <= threshold <= 1.0):
            logger.warning("Decision threshold for %r out of range [0, 1]", qid)
            return None

        try:
            get_question(qid)
        except Exception:
            logger.warning("Decision threshold for unknown question id %r", qid)
            return None

        result[qid] = threshold

    return result


@dataclass(frozen=True)
class Answer:
    question_id: str
    type: str
    probabilities: dict[str, float]
    choice: str | None
    score: float | None
    noul: float | None
    decided: bool | None


class DecisionClient:
    """HTTP client for a local llama-server ``/v1/systemone`` endpoint."""

    def __init__(
        self,
        config: DecisionConfig,
        *,
        http_client: httpx.Client | None = None,
        clock=time.monotonic,
    ):
        # Re-check here too: the key and the utterance must never leave the host,
        # however the config was built.
        check_local_url(config.url)
        self._config = config
        self._clock = clock
        self._api_key = os.environ.get("KAINE_DECISION_SERVER_API_KEY", "")
        self._thresholds = load_thresholds(config.thresholds_path)
        self._last_warning: dict[str, float] = {}

        if http_client is None:
            # The owned client must never honor HTTP_PROXY / ALL_PROXY: those would
            # route the bearer key and the entity's utterance off-host.
            self._client = httpx.Client(
                timeout=config.timeout_s, trust_env=False
            )
            self._owns_client = True
        else:
            if getattr(http_client, "trust_env", False):
                raise ValueError(
                    "injected http_client must disable proxy environment "
                    "(trust_env=False)"
                )
            self._client = http_client
            self._owns_client = False

    def close(self) -> None:
        """Close the owned HTTP client, if any."""
        if self._owns_client:
            self._client.close()

    def _warn(self, kind: str, question_ids: list[str]) -> None:
        """Rate-limited, content-free warning."""
        now = self._clock()
        last = self._last_warning.get(kind, -61.0)
        if now - last >= 60.0:
            self._last_warning[kind] = now
            logger.warning(
                "Decision client %s for question ids: %s",
                kind,
                question_ids,
            )

    def ask(
        self,
        utterance: str,
        context: str | None,
        question_ids: list[str],
    ) -> dict[str, Answer] | None:
        """Ask the decision server and return parsed answers.

        Returns ``None`` on any failure. Never raises.
        """
        if not self._config.enabled:
            return None

        if not question_ids:
            return {}

        try:
            return self._do_ask(utterance, context, question_ids)
        except Exception:
            self._warn("exception", question_ids)
            return None

    def _do_ask(
        self,
        utterance: str,
        context: str | None,
        question_ids: list[str],
    ) -> dict[str, Answer] | None:
        body: dict[str, Any] = {
            "state": state_text(utterance, context),
            "questions": systemone_questions(question_ids),
            "model": self._config.model,
        }

        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        url = self._config.url.rstrip("/") + "/v1/systemone"

        try:
            response = self._client.post(url, json=body, headers=headers)
        except httpx.RequestError:
            self._warn("transport", question_ids)
            return None

        if response.status_code != 200:
            self._warn("http_status", question_ids)
            return None

        try:
            payload = response.json()
        except Exception:
            self._warn("malformed_response", question_ids)
            return None

        return self._parse_answers(payload, question_ids)

    def _parse_answers(
        self,
        payload: Any,
        question_ids: list[str],
    ) -> dict[str, Answer] | None:
        if not isinstance(payload, dict):
            self._warn("malformed_response", question_ids)
            return None

        answers = payload.get("answers")
        if not isinstance(answers, dict):
            self._warn("malformed_response", question_ids)
            return None

        result: dict[str, Answer] = {}
        for qid in question_ids:
            expected_type = get_question(qid).type
            ans = answers.get(qid)
            if not isinstance(ans, dict) or ans.get("type") != expected_type:
                self._warn("malformed_response", question_ids)
                return None

            parsed = self._parse_single(qid, expected_type, ans)
            if parsed is None:
                self._warn("malformed_response", question_ids)
                return None

            result[qid] = parsed

        return result

    def _parse_single(
        self,
        qid: str,
        type_: str,
        ans: dict[str, Any],
    ) -> Answer | None:
        if type_ == "choice":
            raw_probs = ans.get("probabilities")
            if not isinstance(raw_probs, dict):
                return None

            probabilities: dict[str, float] = {}
            for key, value in raw_probs.items():
                try:
                    prob = float(value)
                except Exception:
                    return None
                if not math.isfinite(prob):
                    return None
                probabilities[key] = prob

            choice = ans.get("choice")
            if choice is not None and not isinstance(choice, str):
                return None

            return Answer(
                question_id=qid,
                type=type_,
                probabilities=probabilities,
                choice=choice,
                score=None,
                noul=None,
                decided=None,
            )

        if type_ == "score":
            raw_probs = ans.get("probabilities")
            if not isinstance(raw_probs, dict):
                return None

            probabilities = {}
            for key, value in raw_probs.items():
                try:
                    prob = float(value)
                except Exception:
                    return None
                if not math.isfinite(prob):
                    return None
                probabilities[key] = prob

            try:
                score = float(ans["score"])
            except Exception:
                return None
            if not math.isfinite(score):
                return None

            return Answer(
                question_id=qid,
                type=type_,
                probabilities=probabilities,
                choice=None,
                score=score,
                noul=None,
                decided=None,
            )

        if type_ == "noul":
            try:
                noul = float(ans["noul"])
            except Exception:
                return None
            if not math.isfinite(noul) or not (0.0 <= noul <= 1.0):
                return None

            probabilities = {"true": noul, "false": 1.0 - noul}
            threshold = (
                self._thresholds.get(qid) if self._thresholds is not None else None
            )
            decided = noul >= threshold if threshold is not None else None

            return Answer(
                question_id=qid,
                type=type_,
                probabilities=probabilities,
                choice=None,
                score=None,
                noul=noul,
                decided=decided,
            )

        return None
