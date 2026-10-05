## Why

Current llama-server builds (llama.cpp build 11382 and later) require the API key on every endpoint except `/health`: `/v1/models`, `/props`, `/slots` and `/lora-adapters` all answer 401 without it. Compose passes the organ `LLAMA_API_KEY` from `KAINE_MODEL_SERVER_API_KEY` (empty means no auth). On a host that sets a key, two probes that sent no key stopped working when the organ image moved to such a build:

- The organ container's healthcheck (`compose/kaine.yml` and `quadlet/kaine-model-server.container`) curls `/v1/models`. It now fails, and the container is reported unhealthy even though the organ is serving.
- `kaine.cycle.preflight._server_resident_models` reads `/v1/models` for the preflight report. It now gets 401, swallows the error, and reports that no model is resident. That is a silent wrong answer.

Every other organ probe already sends the key: the trainer's sleep probe, `kaine.organ_server.served`, Nexus's organ probe and the adapter resolver.

## What Changes

- The organ healthcheck, in both the compose service and the Quadlet unit, probes `/health`. It is llama-server's unauthenticated liveness endpoint, which answers 503 while the model loads and 200 once it serves. The key never has to reach the healthcheck's command line.
- `_server_resident_models` sends `Authorization: Bearer <key>` when a model-server key is configured, taken from the same source as the other probes (`kaine.defaults.model_server_api_key`).

## Impact

- Affected specs: `distributed-deployment`, `inference-backend`.
- Affected code: `compose/kaine.yml`, `quadlet/kaine-model-server.container`, `kaine/cycle/preflight.py`, and tests.
- Research impact: none. The healthcheck gates no service, and the preflight report doesn't change any decision. Both are fixed before the next study launches.
