# Decision server

## Why
K1-Jev (`k1-jev-decision-model`) answers typed questions about external speech through llama-server's native `/v1/systemone`. The instruments (`instrument-graders-v2`) and the welfare signals (`welfare-expressed-preference-signals`) need a place to call it. That place must not be the language organ:
- An adapter on the organ disables prompt caching for all Lingua traffic.
- Changing an adapter restarts llama-server.
- An empty `"lora": []` does not zero an adapter (llama.cpp #28674, open).
- `/v1/systemone` ignores per-request adapters.

The inference-backend spec also binds "exactly one local model server" to organ inference. A decision server falls outside that scope, but the spec has to say so explicitly.

## What changes
- **A second, on-demand llama-server, `kaine-decision-model`.**
  - It uses the same pinned llama.cpp build as the organ, which has `/v1/systemone`.
  - It serves only the K1-Jev GGUF (or the bake-off winner).
  - It listens on loopback, requires an API key, and sleeps when idle (`--sleep-idle-seconds`).
  - It runs only while an entity runs and `[decision].enabled` is true.
  - The compose and quadlet service belongs to the integrator.
- **A self-contained client, `kaine/decision/client.py`,** in the boundary-neutral `kaine.decision` package (registered in the import-linter contract by the integrator). It:
  - builds requests from the schema;
  - sends the key on every call;
  - applies the per-question thresholds sidecar;
  - returns typed answers.

  On any failure it returns no answer and never raises into a caller's loop. A caller that is raise-only treats "no answer" as "no signal", never as a negative.
- **Spec amendments:**
  - `inference-backend`: the single-server requirement covers language-organ inference and the A/B baseline only; the decision server is separate and serves only `/v1/systemone`.
  - `abliterated-organ`: K1-Jev is trained offline, is never the organ, and is never an adapter on it; sleep-cycle DPO remains the only training that touches the organ.

## Impact
- New code: `kaine/decision/client.py` plus tests.
- **Shared files, through the integrator:**
  - `config/kaine.toml` gains `[decision]` (shipped `enabled = false`);
  - `pyproject.toml` registers `kaine.decision` in the boundary-neutral contract;
  - compose and quadlet gain the `kaine-decision-model` service.
- **Research impact.** None until a caller uses it. With `[decision].enabled = false` (the shipped default) nothing starts or changes.
