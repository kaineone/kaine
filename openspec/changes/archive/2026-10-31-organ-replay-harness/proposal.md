## Why

Prompt changes to the language organ (persona wording, layout, when the situation facts appear) are judged today by booting the whole entity, where each organ text is one draw under conditions that never repeat. The ninth test boot showed AI self-descriptions ("I am a language model", "I am a new AI"), an 1850-character bulleted loop, and an echo of the individuation disclosure, and the candidate fixes need a controlled comparison before any of them ships. The intent log already holds what such a comparison needs: each request's exact own-turn prompt, its mode and the digest of its system prompt, stored in the system-prompt store.

## What Changes

- A maintainer tool, `tools/maintainer/organ_replay.py`, with three steps:
  - `extract` decrypts an entity's intent log and system-prompt store (the state key from the environment) into a plain case file, skipping records whose logged prompt holds the heard-speech placeholder, since their real prompt is not recoverable.
  - `run` sends every case under each named prompt variant and several seeds to a served organ through the language module's own chat client and request shape: own turn, thinking off, temperature, DRY penalty, stop sequence, length caps and the sentence cut. A raw-completion variant without chat roles goes to llama-server's `/completion`.
  - `score` classifies each text and prints a table with intervals and the decision rule fixed before the run.
- The variants are pure text transforms of the logged prompt and system text: V0 (as logged), V1 (no situation section), V2 (persona without its opening "I am this entity."), V3 (awareness lines as one prose paragraph), V123 (all three), and raw (V0's text with no chat roles, exploratory only).
- The organ runs in its own pinned llama.cpp container, under its own name and port and under the GPU lock, never in the entity's compose project.

## Capabilities

### Modified Capabilities

- `language`: an offline replay reproduces organ requests from the intent log under named prompt variants.

## Impact

- New `tools/maintainer/organ_replay.py`, `tests/test_organ_replay.py`; `tools/maintainer/README.md`.
- Runtime behaviour is unchanged. The tool reads decrypted prompts, so its case and result files are kept in a private scratch directory and never committed.
