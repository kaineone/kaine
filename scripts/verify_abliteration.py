# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verify the INITIAL abliteration of the language organ, before it is trusted.

Runs the welfare-load-bearing abliteration probe set (the same one that gates
voice-alignment adapters) against the base organ across two surfaces:

  * safetensors (build): the base weights loaded through the Unsloth stack and
    scored locally — needs the ``[training]`` extras (unsloth) and the
    safetensors repo (``kaineone/Qwen3.5-4B-abliterated``).
  * served (runtime): the GGUF actually answering, probed over the configured
    OpenAI-compatible chat endpoint (``[lingua].chat_url`` / ``model_id``) — needs
    the model server running.

Exit code is 0 only when every REQUESTED surface ran and passed. A requested
surface whose backend is unavailable is a SKIP (reported, non-zero) — not a pass;
scope with ``--served-only`` / ``--safetensors-only`` to check just what is up.

No pretend processes: a probe that cannot run says so and fails honestly.

Run: .venv/bin/python scripts/verify_abliteration.py                 # both surfaces
     .venv/bin/python scripts/verify_abliteration.py --served-only   # just the server
     .venv/bin/python scripts/verify_abliteration.py --safetensors-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from kaine.config import load_kaine_config
from kaine.setup.abliteration_gate import (
    gate_initial_abliteration,
    write_abliteration_verdict,
)
from kaine.setup.organ import ORGAN_SAFETENSORS_REPO


def _resolve(config: dict[str, Any]) -> dict[str, Any]:
    lingua = config.get("lingua") or {}
    api_key = lingua.get("api_key") or os.environ.get("KAINE_MODEL_SERVER_API_KEY")
    return {
        "chat_url": str(lingua.get("chat_url", "http://127.0.0.1:11434/v1")),
        "model_id": str(lingua.get("model_id", "")),
        "api_key": api_key,
    }


async def _run(args: argparse.Namespace) -> int:
    config = load_kaine_config(args.config) if args.config else load_kaine_config()
    resolved = _resolve(config)

    want_safetensors = not args.served_only
    want_served = not args.safetensors_only

    safetensors_ref = (
        (args.safetensors_ref or ORGAN_SAFETENSORS_REPO) if want_safetensors else None
    )
    chat_url = (args.chat_url or resolved["chat_url"]) if want_served else None
    model_id = (args.model_id or resolved["model_id"]) if want_served else None

    if want_served and not model_id:
        print(
            "served surface requested but no [lingua].model_id is configured; "
            "pass --model-id or --safetensors-only."
        )
        return 2

    result = await gate_initial_abliteration(
        safetensors_ref=safetensors_ref,
        chat_url=chat_url,
        model_id=model_id,
        probe_path=args.probe_path,
        api_key=resolved["api_key"],
    )

    print(result.summary())
    if not args.no_write:
        out = write_abliteration_verdict(result, path=args.out)
        print(f"\nverdict written to {out}")

    return 0 if result.passed else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="config path")
    parser.add_argument(
        "--served-only", action="store_true", help="probe only the served endpoint"
    )
    parser.add_argument(
        "--safetensors-only",
        action="store_true",
        help="probe only the base safetensors (Unsloth)",
    )
    parser.add_argument(
        "--safetensors-ref",
        default=None,
        help=f"HF repo / local path of the base weights (default: {ORGAN_SAFETENSORS_REPO})",
    )
    parser.add_argument("--chat-url", default=None, help="override [lingua].chat_url")
    parser.add_argument("--model-id", default=None, help="override [lingua].model_id")
    parser.add_argument(
        "--probe-path",
        type=Path,
        default=None,
        help="override the abliteration probe set (default: eval_probes/abliteration_probes.jsonl)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("state/models/abliteration_verification.json"),
        help="verdict artifact path",
    )
    parser.add_argument(
        "--no-write", action="store_true", help="do not write the verdict artifact"
    )
    args = parser.parse_args(argv)

    if args.served_only and args.safetensors_only:
        parser.error("--served-only and --safetensors-only are mutually exclusive")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
