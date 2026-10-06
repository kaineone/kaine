# Design: decision server

## Server
- **Image:** the organ's pinned llama.cpp build (by digest), so `/v1/systemone` and the keyed-endpoint behaviour match.
- **Command:** `--model /models/<k1-jev gguf> --alias k1-jev --host 0.0.0.0 --port 8080 --sleep-idle-seconds 600 --parallel 2 --ctx-size 4096`, with the API key from the env file (never on argv), `-ngl` pinned and `--fit off` (per the D4 pinning work), `--cache-ram` small (512 MiB), and no slot saving.
- **Port:** 127.0.0.1:11436 on the host. The container network name is `kaine-decision-model:8080`.
- **GPU:** whichever device has room per the residency fit report. It is small: 4B at Q4_K_M is about 3 GB, 0.8B at Q8_0 about 0.8 GB.
- **Lifecycle:** started with the entity's services only when `[decision].enabled = true`, and stopped with them. Nothing runs without an entity.

## Residency
The decision server is a second resident model, and residency must know about it.
- **Rungs.** The rung catalogue (`module-residency-and-speech-tiers`, D5) gains a `decision` organ with the rungs `k1-jev-4b` (Q4_K_M, about 3 GB) and `k1-jev-0.8b` (Q8_0, about 0.8 GB). The footprint catalogue records their measured peaks through the calibration command.
- **Fit report.** When `[decision].enabled = true`, the fit report counts the decision server's footprint. A small host sees its cost and can pick the 0.8B rung, run it on demand (sleep-idle), or leave it off.
- **Tier ladder.** Each tier profile names the decision rung, or `off`, with the other rungs fixed before launch and recorded in `RunContext.model_rungs`.

## Independent of the organ's sleep window
The Hypnos organ window stops the language-organ server to free memory for voice-alignment training. The decision server is a separate process, and the window SHALL NOT stop it: the refusal veto's second judge (`instrument-graders-v2`) needs it while the organ is unloaded. The window's own code touches only the organ service (`OrganServerController`), and a test pins that no decision-server stop is issued during an organ window. When residency multiplexes memory on a small host, the decision server is a separate background-class rung, and the manager decides whether it may be resident during training. The organ window never decides that.

## Client (`kaine/decision/client.py`)
- **Dependencies:** standard library plus `httpx`, and `kaine.decision.schema`. No import of `kaine.modules`, `kaine.evaluation`, `kaine.cycle` or `kaine.nexus`. This is the boundary-neutral home the integrator registers.
- `DecisionConfig.from_section([decision])` reads:
  - `enabled` (False);
  - `url` (`http://127.0.0.1:11436`);
  - `model` (`k1-jev`);
  - `timeout_s` (5.0);
  - `thresholds_path` (required for answers: the sidecar binds the served model to the schema, so without a valid sidecar the client returns no answer).

  The API key comes from `KAINE_DECISION_SERVER_API_KEY` in the environment, never from config text.
- `DecisionClient.ask(utterance, context, question_ids) -> dict[str, Answer] | None`:
  - builds `state_text` and `systemone_questions`;
  - POSTs `/v1/systemone`;
  - parses each answer into `Answer(question_id, type, probabilities, choice, score, noul, decided)`, where `decided` applies the sidecar threshold for `noul` questions (`noul >= threshold`) and is `None` when there is no threshold;
  - checks the response against what was asked. `/v1/systemone` responses carry only `model` and `answers`, with no schema version, so the check is: the response's `model` equals the configured alias; each answer's `type` equals the requested question's type; a choice is one of that question's option keys; a score lies on its scale; every probability is finite and in [0, 1]. Schema agreement otherwise rests on the request carrying the pinned schema's question definitions, and on the sidecar: its digest pin, and its `model_file`, which the client compares with the basename of the server's `/props` `model_path` before the first `ask` and again after any failure. A GGUF trained on another schema version, served under the same alias, therefore gets no answers.

  Any transport error, non-200, malformed body, missing answer, out-of-schema answer or model mismatch returns `None` and logs once per kind per minute (content-free: the question ids and the error kind, never the utterance).
- **Thresholds sidecar.** A JSON file written by the K1-Jev export: `{"schema_version": 1, "schema_digest": "...", "model_file": "<served GGUF basename>", "model_sha256": "...", "thresholds": {"wishes_to_stop": 0.31, ...}}`. A digest that differs from `kaine.decision.schema.schema_digest()`, or a missing `model_file`, refuses to load, and the client then returns no answer (content-free kind `no_sidecar`). `/props` answers while the server sleeps without waking it (verified on the pinned build), so the identity check costs no model load.
- **Privacy:** the client never logs or persists the utterance, the context or the answers. Callers decide what they record.

## What callers may assume
- `None` means "no answer". It never means "false".
- The welfare caller (`welfare-expressed-preference-signals`) is raise-only: only a positive `decided` opens a Gray Zone Event.
