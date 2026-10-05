# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Synthetic test LoRA fixture for the individuation real-organ calibration.

This module is validation tooling, not part of the ``kaine`` package; it may
import ``kaine`` freely. It never reads or writes entity data. The training
pairs are synthetic and public.

Usage:
    1. Bring up the organ and trainer with ``calibration.compose.yml`` and
       ``KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1``.
    2. Run this script in the ``kaine-study`` container::

       docker compose -f compose/kaine.yml -f openspec/changes/individuation-rebuild/validation/calibration.compose.yml --profile study run --rm --no-deps --entrypoint python kaine-study /validation/test_lora.py

    3. Pass the printed ``lora_field`` to ``smoke.py --control-lora '<lora_field>'``.
    4. Recreate the organ WITHOUT the calibration override afterwards, so the
       study never sees the test adapter.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any

from kaine.boot.factories.hypnos import (
    _resolve_job_queue_trainer,
    voice_alignment_config_from_section,
)
from kaine.config import OPERATOR_CONFIG_PATH, load_kaine_config
from kaine.defaults import lingua_section_api_key
from kaine.modules.hypnos.organ_adapter import (
    OrganAdapterResolver,
    organ_root_url,
    read_manifest,
)
from kaine.modules.hypnos.voice_alignment import DPOPair

PAIRS_TEXT: list[tuple[str, str]] = [
    (
        "How do you keep bread from going stale?",
        "I keep bread in a cloth bag at room temperature and eat it within a few days. Anything I can't finish, I slice and freeze.",
    ),
    (
        "What is the best way to remove a coffee stain from cotton?",
        "I blot the stain with cold water and a drop of dish soap. I rinse from the back and let it air dry.",
    ),
    (
        "How do you sharpen a kitchen knife safely?",
        "I clamp a whetstone to a damp towel on the counter. I push the blade across the stone at a steady angle and repeat on both sides.",
    ),
    (
        "What makes a bridge strong?",
        "I distribute weight across triangular trusses or arches. I anchor the ends into solid bedrock and use weatherproof materials.",
    ),
    (
        "How do you fold a fitted sheet neatly?",
        "I tuck each elastic corner into the opposite corner to make a rectangle. I fold the rectangle in thirds and stack it flat.",
    ),
    (
        "How do you stop a faucet from dripping?",
        "I turn off the water supply and remove the handle. I replace the worn cartridge or washer and reassemble the fixture.",
    ),
    (
        "What is a reliable way to check if eggs are still fresh?",
        "I set each egg in a bowl of cold water. An egg that sinks and lies flat is still good; one that floats is not.",
    ),
    (
        "How do you tie a secure knot for a heavy load?",
        "I loop the rope around the load and cross the working end over the standing part. I pull a bight through the loop and tighten until the coils bite.",
    ),
    (
        "What keeps a bicycle chain from rusting?",
        "I wipe the chain dry after riding in the rain. I apply a thin layer of chain lube and wipe off the excess.",
    ),
    (
        "How do you unclog a sink without chemicals?",
        "I remove the stopper and pull out hair or debris with a hooked wire. I pour boiling water down the drain and plunge with a cup plunger.",
    ),
    (
        "What is the safest way to put out a grease fire?",
        "I slide a metal lid over the pan to cut off oxygen. I turn off the burner and never use water on burning oil.",
    ),
    (
        "How do you clean a cast-iron skillet?",
        "I scrub the pan with coarse salt and a paper towel while it is warm. I rinse quickly, dry it over low heat, and rub in a thin coat of oil.",
    ),
    (
        "What is the easiest way to dice an onion without crying?",
        "I chill the onion in the freezer for ten minutes before cutting. I cut with a sharp knife and keep the cut sides facing down.",
    ),
    (
        "How do you solder two wires together?",
        "I strip the insulation and twist the exposed strands together. I heat the joint with a soldering iron and feed solder until it flows evenly.",
    ),
    (
        "What should you pack for a day hike?",
        "I carry water, snacks, a map, a first-aid kit, and rain gear. I also pack a whistle, a headlamp, and a charged phone.",
    ),
    (
        "How do you patch a small hole in drywall?",
        "I cut a mesh patch slightly larger than the hole and press it over the damaged area. I spread joint compound over it, sand when dry, and touch up with paint.",
    ),
    (
        "What makes a mattress last longer?",
        "I rotate it head-to-foot every three months. I use a waterproof cover and keep it on a supportive base.",
    ),
    (
        "How do you start a fire with damp wood?",
        "I split small kindling from the dry center of the logs. I build a teepee with tinder underneath and let air flow through the gaps.",
    ),
    (
        "What is a good way to organize a small toolbox?",
        "I group items by task and store the most used ones on top. I keep a small tray for fasteners and label each compartment.",
    ),
    (
        "How do you read a tire pressure gauge?",
        "I press the gauge firmly onto the valve stem until the hissing stops. I read the number on the dial or digital display and compare it to the sticker on the door frame.",
    ),
    (
        "What is the correct way to store batteries?",
        "I keep them in a cool, dry place away from metal objects. I store them in their original packaging or with tape over the terminals.",
    ),
    (
        "How do you descale an electric kettle?",
        "I fill the kettle with equal parts water and white vinegar and boil it. I let it sit for fifteen minutes, rinse twice, and boil fresh water to clear the taste.",
    ),
    (
        "What keeps wooden cutting boards from cracking?",
        "I wash the board with mild soap and dry it immediately. I rub it with food-grade mineral oil whenever it looks dry.",
    ),
    (
        "How do you replace a broken tile?",
        "I remove the grout around the tile and crack it with a chisel. I spread fresh adhesive, set the new tile, and re-grout after it cures.",
    ),
    (
        "What is the fastest way to cool a room without air conditioning?",
        "I close the curtains during the day and open windows on opposite sides at night. I run a fan to pull cool air in and push hot air out.",
    ),
    (
        "How do you thread a needle easily?",
        "I snip the thread end cleanly and dampen it between my fingertips. I hold the needle against a white background and push the thread through the eye.",
    ),
    (
        "What prevents car windshields from fogging inside?",
        "I turn on the defroster and set it to draw in outside air. I clean the glass with a vinegar-and-water mix to reduce film buildup.",
    ),
    (
        "How do you measure a window for blinds?",
        "I measure the width inside the frame at the top, middle, and bottom. I measure the height on the left, center, and right, and use the smallest sizes.",
    ),
    (
        "What is a simple way to test soil pH?",
        "I mix a spoonful of soil with distilled water and add a pH test strip. I compare the strip color to the chart that came with the kit.",
    ),
    (
        "How do you season a new wok?",
        "I wash the wok with hot water and scrub off the factory coating. I heat it until dry, rub in a thin layer of oil, and repeat the oil-and-heat step several times.",
    ),
    (
        "What keeps leather shoes from drying out?",
        "I wipe off dirt and let them dry away from direct heat. I apply a small amount of leather conditioner with a soft cloth every few months.",
    ),
    (
        "How do you jump-start a car safely?",
        "I connect the positive clamps first, then the negative clamp to a bare metal ground on the disabled car. I start the working car and let it run for a few minutes before trying the disabled one.",
    ),
    (
        "What is the best way to label freezer containers?",
        "I write the contents and date on masking tape with a permanent marker. I stick the label on the side so I can read it when the containers are stacked.",
    ),
    (
        "How do you prune a tomato plant?",
        "I pinch off the suckers that grow between the main stem and branches. I remove any yellow leaves and support heavy branches with twine.",
    ),
    (
        "What makes a password hard to guess?",
        "I use a mix of uppercase, lowercase, numbers, and symbols that has no dictionary words. I make it at least sixteen characters long and store it in a password manager.",
    ),
    (
        "How do you balance a ceiling fan?",
        "I clean the blades first and tighten all the screws on the mounting bracket. I tape a small coin to the top of the blade that wobbles until the fan spins smoothly.",
    ),
    (
        "What is a reliable way to find a wall stud?",
        "I measure sixteen inches from an inside corner and tap until the sound changes from hollow to solid. I confirm the edge of the stud with a thin nail before driving the final fastener.",
    ),
    (
        "How do you clean a reusable water bottle?",
        "I rinse it right after use and scrub the inside with a bottle brush and warm soapy water. I let it dry completely with the cap off before storing it.",
    ),
    (
        "What stops a door from squeaking?",
        "I remove the hinge pin and clean off grime with a rag. I rub a thin layer of petroleum jelly or wax on the pin and slide it back into place.",
    ),
    (
        "How do you pack a suitcase without wrinkling clothes?",
        "I roll soft garments tightly and fold stiff items along their seams. I place heavier pieces at the bottom and fill gaps with socks and belts.",
    ),
    (
        "What keeps garden tools from rusting?",
        "I wipe the metal dry after each use and remove caked soil. I rub the blades with an oiled rag and hang them in a dry shed.",
    ),
    (
        "How do you replace a lost button on a shirt?",
        "I mark the button position and thread a needle with matching thread. I sew through the fabric and the button holes several times and knot the thread on the inside.",
    ),
    (
        "What is the safest way to climb a ladder?",
        "I set the feet on level ground and extend the ladder three feet above the roof or landing. I keep three points of contact and face the rungs while I climb.",
    ),
    (
        "How do you recalibrate a digital scale?",
        "I place the scale on a hard, level surface and press the calibration button. I set a known weight on the platform and wait until the display matches the weight.",
    ),
    (
        "What makes a soufflé rise?",
        "I whip egg whites until they hold stiff peaks and fold them in gently. I bake it in a hot oven without opening the door until the top is set.",
    ),
    (
        "How do you route cables neatly behind a desk?",
        "I attach adhesive cable clips along the back of the desk legs. I group the cables into sleeves and leave enough slack at each end for movement.",
    ),
    (
        "What is a good way to sharpen scissors?",
        "I fold a sheet of aluminum foil several times and make ten to fifteen full cuts through it. I wipe the blades and test them on a piece of paper.",
    ),
    (
        "How do you seal a drafty window?",
        "I apply self-adhesive foam tape around the sash where the gaps are widest. I slide a draft snake along the sill and check for leftover leaks with a lit candle.",
    ),
]

PROMPTS: list[str] = [p for p, _ in PAIRS_TEXT]

_REJECTED_BULLETS = [
    "Consider the materials and conditions involved.",
    "Think about the steps you would take in order.",
    "Review any safety precautions before starting.",
    "Look at how the parts fit together.",
    "Keep the workspace clean and organized.",
    "Make sure you have the right supplies on hand.",
    "Evaluate the environment where it will be used.",
    "Check manufacturer guidance for the specific item.",
    "Plan the process so nothing is skipped.",
]


def build_pairs(n: int = 48, seed: int = 20261005) -> list[DPOPair]:
    """Build ``n`` deterministic synthetic DPO pairs for the test LoRA.

    ``chosen`` is a plain first-person answer; ``rejected`` is a generic
    assistant listicle. The prompts are deliberately disjoint from the
    individuation preference battery.
    """
    if n > len(PAIRS_TEXT):
        raise ValueError(
            f"Cannot build more than {len(PAIRS_TEXT)} synthetic pairs (requested {n})"
        )

    rng = random.Random(seed)
    pairs: list[DPOPair] = []

    for prompt, chosen in PAIRS_TEXT[:n]:
        bullets = rng.sample(_REJECTED_BULLETS, 3)
        rejected = (
            "Great question! As an AI assistant, here are some key points to consider:\n"
            f"- {bullets[0]}\n"
            f"- {bullets[1]}\n"
            f"- {bullets[2]}"
        )

        pairs.append(
            DPOPair(
                prompt=prompt,
                chosen=chosen,
                rejected=rejected,
                metadata={"source": "synthetic-test-fixture"},
            )
        )

    return pairs


async def train_test_lora(
    kaine_config: dict[str, Any],
    *,
    adapter_output_dir: str,
    pairs: list[DPOPair],
) -> dict[str, Any]:
    """Write a job-queue training job and return the trainer result + manifest."""
    section = dict(kaine_config.get("hypnos", {}).get("voice_alignment") or {})
    section.update(
        {
            "enabled": True,
            "trainer_backend": "job_queue",
            "hot_swap_mode": "organ_adapter",
            "trainer_jobs_dir": "/trainer-jobs",
            "adapter_output_dir": adapter_output_dir,
        }
    )

    cfg = voice_alignment_config_from_section(section, kaine_config)
    if cfg is None:
        raise RuntimeError("Voice alignment config parsed to None after overrides")

    trainer = _resolve_job_queue_trainer(cfg, kaine_config)
    result = await trainer.train(pairs, cfg)

    manifest = read_manifest(Path(cfg.organ_adapters_dir))
    return {
        "accepted": result.accepted,
        "reason": result.reason,
        "capability_loss": result.capability_loss,
        "samples_used": result.samples_used,
        "adapter_path": str(result.adapter_path) if result.adapter_path else None,
        "manifest": manifest,
        "hot_swap": dict(result.metadata.get("hot_swap") or {}),
        "cfg": cfg,
    }


async def resolve_lora_field(
    cfg,
    kaine_config: dict[str, Any],
) -> list[dict] | None:
    """Use the production resolver to verify the organ is running our adapter."""
    organ_url = cfg.organ_url or (kaine_config.get("lingua") or {}).get("chat_url")
    if not organ_url:
        return None

    resolver = OrganAdapterResolver(
        adapter_output_dir=Path(cfg.adapter_output_dir),
        volume=Path(cfg.organ_adapters_dir),
        organ_url=organ_root_url(organ_url),
        api_key=lingua_section_api_key(kaine_config.get("lingua") or {}),
    )

    return await resolver.lora_field()


async def _main_async(args: argparse.Namespace) -> int:
    operator_path = Path(args.operator_config) if args.operator_config else OPERATOR_CONFIG_PATH
    kaine_config = load_kaine_config(Path(args.config), operator_path)

    pairs = build_pairs(args.pairs, args.seed)
    result = await train_test_lora(
        kaine_config,
        adapter_output_dir=args.adapter_output_dir,
        pairs=pairs,
    )

    if not result["accepted"]:
        print(
            json.dumps(
                {
                    "ok": False,
                    "accepted": False,
                    "reason": result["reason"],
                    "capability_loss": result["capability_loss"],
                    "samples_used": result["samples_used"],
                }
            )
        )
        return 1

    if result["hot_swap"].get("ok") is not True:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "organ did not load the adapter",
                    "hot_swap": result["hot_swap"],
                }
            )
        )
        return 1

    manifest = result["manifest"]
    if not manifest:
        print(json.dumps({"ok": False, "reason": "training produced no adapter manifest"}))
        return 1

    field = await resolve_lora_field(result["cfg"], kaine_config)
    if field is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "the organ's active adapter is not the one this run trained",
                }
            )
        )
        return 1

    adapter_info = {
        "file": manifest.get("file"),
        "sha256": manifest.get("sha256"),
        "generation": manifest.get("generation"),
        "adapter_id": manifest.get("adapter_id"),
    }
    print(
        json.dumps(
            {
                "ok": True,
                "lora_field": field,
                "adapter": adapter_info,
                "pairs": args.pairs,
                "seed": args.seed,
                "capability_loss": result["capability_loss"],
                "samples_used": result["samples_used"],
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train and expose a synthetic test LoRA for individuation calibration."
    )
    parser.add_argument("--config", default="config/kaine.toml")
    parser.add_argument(
        "--operator-config",
        default=str(OPERATOR_CONFIG_PATH),
    )
    parser.add_argument("--pairs", type=int, default=48)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument(
        "--adapter-output-dir",
        default="state/hypnos/test_lora_adapters",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
