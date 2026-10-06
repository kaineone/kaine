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
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from kaine.decision.schema import (
    SCHEMA_VERSION,
    Question,
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
    "Sidecar",
    "load_sidecar",
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
        if not isinstance(self.enabled, bool):
            raise ValueError(
                f"decision config key 'enabled' must be a bool, got {type(self.enabled).__name__}"
            )

        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float)):
            raise ValueError(
                f"decision config key 'timeout_s' must be a finite number greater than 0, "
                f"got {type(self.timeout_s).__name__}"
            )
        timeout = float(self.timeout_s)
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError(
                f"decision config key 'timeout_s' must be a finite number greater than 0, "
                f"got {self.timeout_s!r}"
            )

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

        enabled = section.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"decision config key 'enabled' must be a bool, got {type(enabled).__name__}"
            )

        return cls(
            enabled=enabled,
            url=section.get("url", "http://127.0.0.1:11436"),
            model=section.get("model", "k1-jev"),
            timeout_s=section.get("timeout_s", 5.0),
            thresholds_path=section.get("thresholds_path", ""),
        )


@dataclass(frozen=True)
class Sidecar:
    thresholds: dict[str, float]
    model_file: str
    model_sha256: str | None


def load_sidecar(path: str) -> Sidecar | None:
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

    if not isinstance(data, dict):
        logger.warning("Decision thresholds top level is not a JSON object")
        return None

    if data.get("schema_version") != SCHEMA_VERSION:
        logger.warning("Decision thresholds schema version mismatch")
        return None

    if data.get("schema_digest") != schema_digest():
        logger.warning("Decision thresholds schema digest mismatch")
        return None

    model_file = data.get("model_file")
    if not isinstance(model_file, str) or not model_file:
        logger.warning("Decision sidecar model_file missing or empty")
        return None

    model_sha256 = data.get("model_sha256")
    if model_sha256 is not None and not isinstance(model_sha256, str):
        logger.warning("Decision sidecar model_sha256 is not a string")
        return None

    raw_thresholds = data.get("thresholds")
    if not isinstance(raw_thresholds, dict):
        logger.warning("Decision sidecar 'thresholds' field missing or invalid")
        return None

    result: dict[str, float] = {}
    for qid, value in raw_thresholds.items():
        if isinstance(value, bool):
            logger.warning("Decision threshold for %r is not numeric", qid)
            return None

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

    return Sidecar(
        thresholds=result,
        model_file=model_file,
        model_sha256=model_sha256,
    )


def load_thresholds(path: str) -> dict[str, float] | None:
    """Load the thresholds mapping from a K1-Jev sidecar file.

    Returns ``None`` if the sidecar is missing or does not validate.
    """
    sidecar = load_sidecar(path)
    return sidecar.thresholds if sidecar is not None else None


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

    _IDENTITY_TTL_S = 60.0

    def __init__(
        self,
        config: DecisionConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Construct a client.

        *transport* and *clock* are test-only and must not be used in
        production.
        """
        # Re-check here too: the key and the utterance must never leave the host,
        # however the config was built.
        check_local_url(config.url)
        self._config = config
        self._clock = clock
        self._api_key = os.environ.get("KAINE_DECISION_SERVER_API_KEY", "")
        self._sidecar = load_sidecar(config.thresholds_path)
        self._thresholds = (
            self._sidecar.thresholds if self._sidecar is not None else None
        )
        self._identity_verified = False
        self._identity_verified_at: float | None = None
        self._last_warning: dict[str, float] = {}

        # The owned client must never honor HTTP_PROXY / ALL_PROXY: those would
        # route the bearer key and the entity's utterance off-host.  Redirects
        # are also rejected so the local endpoint cannot bounce the data away.
        self._client = httpx.Client(
            timeout=config.timeout_s,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        """Close the owned HTTP client."""
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

    def _verify_identity(self) -> str | None:
        """Return a warning kind on failure, or ``None`` on success.

        The served model's GGUF basename must match the sidecar's model_file.
        Never log the path itself.
        """
        if self._sidecar is None:
            return "no_sidecar"

        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        url = self._config.url.rstrip("/") + "/props"

        try:
            response = self._client.get(url, headers=headers)
        except httpx.RequestError:
            return "identity_unavailable"

        if response.status_code != 200:
            return "identity_unavailable"

        try:
            payload = response.json()
        except Exception:
            return "identity_unavailable"

        if not isinstance(payload, dict):
            return "identity_unavailable"

        model_path = payload.get("model_path")
        if not isinstance(model_path, str):
            return "identity_unavailable"

        served_file = PurePosixPath(model_path).name
        if served_file != self._sidecar.model_file:
            return "identity_mismatch"

        return None

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
            self._identity_verified = False
            return None

    def _do_ask(
        self,
        utterance: str,
        context: str | None,
        question_ids: list[str],
    ) -> dict[str, Answer] | None:
        if self._sidecar is None:
            self._warn("no_sidecar", question_ids)
            return None

        body: dict[str, Any] = {
            "state": state_text(utterance, context),
            "questions": systemone_questions(question_ids),
            "model": self._config.model,
        }

        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        identity_stale = (
            not self._identity_verified
            or self._identity_verified_at is None
            or self._clock() - self._identity_verified_at >= self._IDENTITY_TTL_S
        )
        if identity_stale:
            identity_kind = self._verify_identity()
            if identity_kind is not None:
                self._warn(identity_kind, question_ids)
                self._identity_verified = False
                return None
            self._identity_verified = True
            self._identity_verified_at = self._clock()

        url = self._config.url.rstrip("/") + "/v1/systemone"

        try:
            response = self._client.post(url, json=body, headers=headers)
        except httpx.RequestError:
            self._warn("transport", question_ids)
            self._identity_verified = False
            return None

        if response.status_code != 200:
            self._warn("http_status", question_ids)
            self._identity_verified = False
            return None

        try:
            payload = response.json()
        except Exception:
            self._warn("malformed_response", question_ids)
            self._identity_verified = False
            return None

        parsed = self._parse_answers(payload, question_ids)
        if parsed is None:
            self._identity_verified = False
            return None

        return parsed

    def _parse_answers(
        self,
        payload: Any,
        question_ids: list[str],
    ) -> dict[str, Answer] | None:
        if not isinstance(payload, dict):
            self._warn("malformed_response", question_ids)
            return None

        if payload.get("model") != self._config.model:
            self._warn("model_mismatch", question_ids)
            return None

        answers = payload.get("answers")
        if not isinstance(answers, dict):
            self._warn("malformed_response", question_ids)
            return None

        result: dict[str, Answer] = {}
        for qid in question_ids:
            question = get_question(qid)
            ans = answers.get(qid)
            if not isinstance(ans, dict) or ans.get("type") != question.type:
                self._warn("out_of_schema", question_ids)
                return None

            parsed = self._parse_single(question, ans)
            if parsed is None:
                self._warn("out_of_schema", question_ids)
                return None

            result[qid] = parsed

        return result

    def _parse_single(
        self,
        question: Question,
        ans: dict[str, Any],
    ) -> Answer | None:
        qid = question.id
        type_ = question.type

        if type_ == "choice":
            option_keys = {opt.key for opt in question.options}

            raw_probs = ans.get("probabilities")
            probabilities: dict[str, float] = {}
            if raw_probs is not None:
                if not isinstance(raw_probs, dict):
                    return None
                for key, value in raw_probs.items():
                    if key not in option_keys:
                        return None
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        return None
                    prob = float(value)
                    if not math.isfinite(prob) or not (0.0 <= prob <= 1.0):
                        return None
                    probabilities[key] = prob

            choice = ans.get("choice")
            if choice is None or not isinstance(choice, str) or choice not in option_keys:
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
            levels = len(question.options)

            raw_probs = ans.get("probabilities")
            probabilities: dict[str, float] = {}
            if raw_probs is not None:
                if not isinstance(raw_probs, dict):
                    return None
                for key, value in raw_probs.items():
                    if not isinstance(key, str):
                        return None
                    try:
                        idx = int(key)
                    except Exception:
                        return None
                    if str(idx) != key or not (0 <= idx < levels):
                        return None
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        return None
                    prob = float(value)
                    if not math.isfinite(prob) or not (0.0 <= prob <= 1.0):
                        return None
                    probabilities[key] = prob

            raw_score = ans.get("score")
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                return None
            score = float(raw_score)
            if not math.isfinite(score) or not (0.0 <= score <= levels - 1):
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
            raw_noul = ans.get("noul")
            if isinstance(raw_noul, bool) or not isinstance(raw_noul, (int, float)):
                return None
            noul = float(raw_noul)
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
