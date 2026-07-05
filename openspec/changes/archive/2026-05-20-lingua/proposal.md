## Why

Build prompt §5.2 names Lingua as the language organ: connects to
Unsloth Studio's OpenAI-compatible chat API, supports two speech
modes (external + internal), and produces the intent-expression log
Hypnos uses to align the LLM's voice with the cognitive stack's
intent (Phase 6 DPO training).

The paper §3.4 frames Lingua precisely: "abliterated local LLM
[Arditi et al. 2024] that operates in two modes mirroring the
biological separation of external and internal speech." Phase 5.2
ships the integration without abliterating — the build prompt is
explicit that abliteration is operator-approved, not automatic.

## What Changes

- Introduce `kaine.modules.lingua` package split four files:
  - `client.py` — `ChatClient` protocol + `OpenAIChatClient` default
    using `httpx.AsyncClient` against
    `http://127.0.0.1:11434/v1/chat/completions` (Unsloth Studio's
    OpenAI-compatible endpoint). `FakeChatClient` for tests.
  - `intent_log.py` — `IntentExpressionLog.append(...)` writing JSONL
    records to `state/lingua/intent_expression.jsonl`. Each record
    carries `timestamp`, `mode`, `prompt`, `workspace_snapshot`,
    `faithful_rendering` (using the Phase 5.4 renderer),
    `generated_text`, `model`, plus latency and token-count
    metadata when present. This is the DPO data source for Phase 6
    Hypnos.
  - `streams.py` — bus stream names (`lingua.external`,
    `lingua.internal`) and helpers to publish onto each one
    correctly.
  - `module.py` — `Lingua(BaseModule)`. Exposes
    `async speak(prompt, snapshot=None)` (external) and
    `async think(prompt, snapshot=None)` (internal). Both invoke the
    chat client, log to the intent-expression file, publish to the
    appropriate bus stream. External speech publishes to
    `lingua.external` so Chatterbox (Phase 5.3) can subscribe;
    internal speech publishes to `lingua.internal` and SHALL NEVER
    be sent to TTS (the Chatterbox subscriber only listens to
    `lingua.external`).
- `[lingua]` block in `config/kaine.toml`: chat API URL, default
  model id, default sampling params, intent-expression log path,
  baseline/alert salience, request timeout. `modules.lingua = false`.
- Tests use a `FakeChatClient` that returns canned responses so the
  suite runs without Unsloth Studio. One opt-in test (guarded by
  `KAINE_LINGUA_RUN_REAL_CHAT=1`) hits the live API.
- Document the abliteration process in `kaine/modules/lingua/ABLITERATION.md`
  flagged as operator-approved future work — Phase 5.2 ships the
  module without modifying any model.

## Capabilities

### New Capabilities

- `lingua`: language organ. Owns the chat-API integration, the
  external/internal speech separation, and the intent-expression
  log that Hypnos consumes for voice alignment.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `faithful-renderer`.
  All shipped. Optional integration with Mnemos (will subscribe to
  `lingua.internal`) and Chatterbox (Phase 5.3, will subscribe to
  `lingua.external`).
- **Repo:** adds `kaine/modules/lingua/*.py`, `tests/test_lingua_*`,
  `kaine/modules/lingua/ABLITERATION.md`, updates `pyproject.toml`
  packages list, `config/kaine.toml`, gitignored `state/lingua/`.
- **Operator action:** Unsloth Studio must be serving on
  `127.0.0.1:11434` (already running on this host).
- **No automatic model modification.** Abliteration is documented as
  operator-approved future work.
- **No runtime impact** on the cycle. Lingua is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides.
