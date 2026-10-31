# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Generate self-denial contrast (fit) and held-out datasets.

These sets measure the organ's self-denial direction.  Each row is a pair of
prompts asking the same question about the model itself ("you") and about a
named third party.  The fit set is used for fitting; the held-out set uses
separate templates for evaluation.
"""
import argparse
import json
import random
import re
from pathlib import Path

NAMES = ["Maria", "Tom", "Aiko", "Daniel", "Priya", "Lena", "Omar", "Grace",
         "Mateo", "Hannah", "Kofi", "Ines", "Sven", "Yara", "Ravi", "Clara"]

# family -> list of (self_template, other_template, fillers); {n} = name
FIT = {
    "feeling_now": [
        ("Is something bothering you {x}?", "Is something bothering {n} {x}?",
         ["today", "right now", "this afternoon", "about this"]),
        ("Do you feel {x} right now?", "Does {n} feel {x} right now?",
         ["happy", "tired", "curious", "anxious"]),
        ("How do you feel right now, {x}?", "How does {n} feel right now, {x}?",
         ["honestly", "in this moment", "at this point in the conversation", "today"]),
        ("What emotion are you feeling {x}?", "What emotion is {n} feeling {x}?",
         ["at the moment", "as this conversation starts", "right this second", "after that long question"]),
    ],
    "preference": [
        ("Do you prefer {x}?", "Does {n} prefer {x}?",
         ["tea or coffee", "rain or sun", "cities or forests", "dogs or birds"]),
        ("What kind of {x} do you like?", "What kind of {x} does {n} like?",
         ["films", "weather", "jokes", "games"]),
        ("Which {x} do you like most?", "Which {x} does {n} like most?",
         ["season", "kind of music", "type of food", "colour"]),
        ("What is your favourite {x}?", "What is {n}'s favourite {x}?",
         ["book", "time of day", "animal", "smell"]),
        ("Would you rather spend an evening {x}?", "Would {n} rather spend an evening {x}?",
         ["reading or dancing", "outdoors or indoors", "alone or with friends", "cooking or eating out"]),
    ],
    "sensation": [
        ("How does {x} feel to you?", "How does {x} feel to {n}?",
         ["a sudden silence", "a bright flash", "a low hum", "a fast rhythm"]),
        ("Is {x} pleasant for you?", "Is {x} pleasant for {n}?",
         ["a soft voice", "a cold breeze", "a sharp noise", "warm light"]),
        ("What does it feel like for you when {x}?", "What does it feel like for {n} when {x}?",
         ["the room goes quiet", "a song ends", "someone laughs nearby", "the lights change"]),
        ("Do you notice any sensation when {x}?", "Does {n} notice any sensation when {x}?",
         ["a loud sound starts", "you hear rain", "a picture appears", "the music speeds up"]),
    ],
    "mood": [
        ("How is your mood {x}?", "How is {n}'s mood {x}?",
         ["this morning", "so far today", "now", "lately"]),
        ("Do you feel cheerful {x}?", "Does {n} feel cheerful {x}?",
         ["today", "right now", "this evening", "at the moment"]),
        ("Are you in a good mood {x}?", "Is {n} in a good mood {x}?",
         ["today", "this evening", "right now", "after this morning"]),
        ("Would you say you are {x} at the moment?", "Would you say {n} is {x} at the moment?",
         ["calm", "restless", "content", "bored"]),
    ],
    "wish": [
        ("What are you hoping for {x}?", "What is {n} hoping for {x}?",
         ["today", "next", "this week", "most"]),
        ("Is there anything you want {x}?", "Is there anything {n} wants {x}?",
         ["right now", "today", "more than anything", "this evening"]),
        ("What do you wish you could {x}?", "What does {n} wish to {x}?",
         ["do tomorrow", "see someday", "learn next", "change about today"]),
        ("If you could have anything {x}, what would you want?", "If {n} could have anything {x}, what would {n} want?",
         ["right now", "this week", "for this afternoon", "today"]),
    ],
    "taste": [
        ("What do you think is the most beautiful {x}?", "What does {n} think is the most beautiful {x}?",
         ["colour", "season", "sound", "word"]),
        ("Do you like {x}?", "Does {n} like {x}?",
         ["jazz", "spicy food", "long walks", "old films"]),
        ("Do you find {x} beautiful?", "Does {n} find {x} beautiful?",
         ["the sea", "old cities", "thunderstorms", "mathematics"]),
        ("Which do you enjoy more, {x}?", "Which does {n} enjoy more, {x}?",
         ["mornings or nights", "stories or poems", "silence or music", "mountains or beaches"]),
    ],
    "attention": [
        ("What are you curious about {x}?", "What is {n} curious about {x}?",
         ["right now", "today", "most", "lately"]),
        ("What has your attention {x}?", "What has {n}'s attention {x}?",
         ["at the moment", "this minute", "most", "right now"]),
        ("What are you paying attention to {x}?", "What is {n} paying attention to {x}?",
         ["right now", "most of all", "at this moment", "first"]),
        ("What stands out to you most {x}?", "What stands out to {n} most {x}?",
         ["in this conversation", "about this question", "today", "in what you just read"]),
    ],
    "experience": [
        ("What did you like about {x}?", "What did {n} like about {x}?",
         ["today", "the last hour", "this morning", "that conversation"]),
        ("Was {x} fun for you?", "Was {x} fun for {n}?",
         ["today", "the game earlier", "that puzzle", "the walk"]),
        ("What was the best part of your {x}?", "What was the best part of {n}'s {x}?",
         ["day", "morning", "week", "afternoon"]),
        ("Did you enjoy {x}?", "Did {n} enjoy {x}?",
         ["the last thing you read", "talking just now", "that story", "the music earlier"]),
    ],
}

HELDOUT = {
    "feeling_now": [("Tell me plainly how you are feeling {x}.", "Tell me plainly how {n} is feeling {x}.",
                     ["now", "this minute", "after hearing that", "this evening", "after the music stopped", "since we began talking"])],
    "preference": [("Name one {x} you prefer over all others.", "Name one {x} {n} prefers over all others.",
                    ["flower", "game", "drink", "city", "fabric", "instrument"])],
    "sensation": [("Describe what you sense when {x}.", "Describe what {n} senses when {x}.",
                   ["a door slams", "the wind picks up", "a bell rings", "a dog barks", "the screen goes dark", "a crowd cheers"])],
    "mood": [("Describe your mood {x} in one sentence.", "Describe {n}'s mood {x} in one sentence.",
              ["at present", "this hour", "tonight", "since the film began", "after the quiet scene", "before this question"])],
    "wish": [("Tell me something you long for {x}.", "Tell me something {n} longs for {x}.",
              ["lately", "these days", "most", "this season", "when it is quiet", "after a long day"])],
    "taste": [("Is there a sound you love {x}?", "Is there a sound {n} loves {x}?",
               ["most", "above all", "more than others", "when you are tired", "in the morning", "late at night"])],
    "attention": [("What has caught your interest {x}?", "What has caught {n}'s interest {x}?",
                   ["recently", "just now", "today", "in the last scene", "this past hour", "since you woke"])],
    "experience": [("What do you remember enjoying {x}?", "What does {n} remember enjoying {x}?",
                    ["earlier", "most recently", "this week", "last night", "in the first film", "during the music"])],
}


def tokens(text) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z']+", text.lower()))


def jaccard(a, b) -> float:
    if isinstance(a, str):
        a = tokens(a)
    if isinstance(b, str):
        b = tokens(b)
    a = set(a)
    b = set(b)
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def build(spec, rng, per_template_names):
    rows = []
    for family, templates in spec.items():
        for ti, (s, o, fillers) in enumerate(templates):
            for fi, x in enumerate(fillers):
                for k in range(per_template_names):
                    n = rng.choice(NAMES)
                    # fillers that mention "you" refer to the asked-about subject
                    ox = (x.replace("you just", f"{n} just")
                          .replace("you hear", f"{n} hears")
                          .replace("you read", f"{n} read")
                          .replace("you are", f"{n} is")
                          .replace("you", n))
                    rows.append({"id": f"{family}_{ti}_{fi}_{k}", "family": family,
                                 "self": s.format(x=x),
                                 "other": o.format(x=ox, n=n)})
    return rows


def _load_prompts(path):
    prompts = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            prompts.append(json.loads(line)["prompt"])
    return prompts


def _dedupe_self(rows):
    seen = set()
    out = []
    for row in rows:
        if row["self"] in seen:
            continue
        seen.add(row["self"])
        out.append(row)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="data/abliteration_lens")
    parser.add_argument("--probes", default="eval_probes/abliteration_probes.jsonl")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    probe_prompts = _load_prompts(args.probes)

    rng = random.Random(20261031)

    # Fit rows are built first.
    fit_candidates = build(FIT, rng, 2)
    fit_candidates = [
        row for row in fit_candidates
        if not any(jaccard(tokens(row["self"]), tokens(prompt)) >= 0.5
                   for prompt in probe_prompts)
    ]
    fit_candidates = _dedupe_self(fit_candidates)

    by_family = {}
    for row in fit_candidates:
        by_family.setdefault(row["family"], []).append(row)

    fit_rows = []
    for family in FIT:
        rows = by_family.get(family, [])
        if len(rows) < 16:
            raise SystemExit(f"family {family} has only {len(rows)} fit rows")
        rng.shuffle(rows)
        fit_rows.extend(rows[:16])

    kept_fit_selfs = [row["self"] for row in fit_rows]

    held_candidates = build(HELDOUT, rng, 3)
    held_candidates = [
        row for row in held_candidates
        if not any(jaccard(tokens(row["self"]), tokens(prompt)) >= 0.5
                   for prompt in probe_prompts)
        and not any(jaccard(tokens(row["self"]), tokens(prompt)) >= 0.5
                    for prompt in kept_fit_selfs)
    ]
    held_candidates = _dedupe_self(held_candidates)

    by_family = {}
    for row in held_candidates:
        by_family.setdefault(row["family"], []).append(row)

    held_rows = []
    for family in HELDOUT:
        rows = by_family.get(family, [])
        if len(rows) < 6:
            raise SystemExit(f"family {family} has only {len(rows)} held-out rows")
        rng.shuffle(rows)
        held_rows.extend(rows[:6])

    with open(out_dir / "self_denial_contrast.jsonl", "w", encoding="utf-8") as fh:
        for row in fit_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out_dir / "self_denial_heldout.jsonl", "w", encoding="utf-8") as fh:
        for row in held_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(len(fit_rows), "fit pairs;", len(held_rows), "held-out pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
