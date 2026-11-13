from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from kaine.modules.sleep.voice_alignment import DPOPair
from kaine.modules.sleep.voice_measures import profile_distance, style_profile


@dataclass
class VoiceCandidateConfig:
    enabled: bool = False
    k_candidates: int = 4
    preference_source: str = "reread"
    max_records: int = 50
    temperature: float = 0.7
    max_tokens: int = 160
    uptake_enabled: bool = False


def _iter_records(corpus_file: Path) -> list[dict[str, Any]]:
    from kaine.persistence.encrypted_jsonl import iter_records
    return [line.record for line in iter_records(corpus_file) if not line.unreadable]


async def _sample_one_completion(
    client: httpx.AsyncClient,
    url: str,
    *,
    model: str,
    system_prompt: str,
    user_input: str,
    config: VoiceCandidateConfig,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    response = await client.post(url, json=payload, timeout=120.0)
    response.raise_for_status()
    data = response.json()
    choice = data["choices"][0]
    message = choice.get("message", {})
    content = message.get("content", "")
    return str(content).strip()


async def sample_and_rank(
    config: VoiceCandidateConfig,
    corpus_file: Path,
    organ_url: str,
    organ_model: str,
    cumulative_profile: dict | None,
    system_prompt: str,
) -> list[DPOPair]:
    """Sample K candidates per corpus entry, rank by re-reading distance."""
    completions_url = f"{organ_url.rstrip('/')}/v1/chat/completions"

    records = _iter_records(Path(corpus_file))
    if config.max_records and config.max_records > 0:
        records = records[: config.max_records]

    pairs: list[DPOPair] = []

    async with httpx.AsyncClient() as client:
        for record in records:
            if record.get("preempted"):
                continue
            generated_text = record.get("generated_text")
            if not generated_text:
                continue

            user_input = (
                record.get("user_input")
                or record.get("user_turn")
                or record.get("prompt")
            )
            if user_input is None:
                continue

            faithful_rendering = (
                record.get("faithful_rendering")
                or record.get("faithful_rendered")
                or generated_text
            )

            if cumulative_profile is not None:
                target_profile = cumulative_profile
            elif faithful_rendering:
                target_profile = style_profile([str(faithful_rendering)])
            else:
                target_profile = None

            if target_profile is None:
                continue

            sampled: list[str] = []
            for _ in range(max(1, int(config.k_candidates or 0))):
                candidate = await _sample_one_completion(
                    client,
                    completions_url,
                    model=organ_model,
                    system_prompt=system_prompt,
                    user_input=str(user_input),
                    config=config,
                )
                sampled.append(candidate)

            if not sampled:
                continue

            scored: list[tuple[float, str]] = []
            for candidate in sampled:
                candidate_profile = style_profile([candidate])
                distance = float(profile_distance(candidate_profile, target_profile))
                scored.append((distance, candidate))

            scored.sort(key=lambda item: item[0])
            best_candidate = scored[0][1]
            worst_candidate = scored[-1][1]

            if config.uptake_enabled:
                pass

            metadata: dict[str, Any] = {
                "preference_source": config.preference_source,
                "candidate_distances": [distance for distance, _ in scored],
                "generated_text": generated_text,
                "faithful_rendering": faithful_rendering,
            }

            pair = DPOPair(
                prompt=str(user_input),
                chosen=best_candidate,
                rejected=worst_candidate,
                metadata=metadata,
                system=system_prompt,
            )
            pairs.append(pair)

    return pairs
