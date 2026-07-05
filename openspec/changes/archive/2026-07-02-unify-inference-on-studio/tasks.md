# Tasks — unify inference on Unsloth Studio

> **DO NOT IMPLEMENT until the operator-supervised first boot is complete and the
> operator explicitly signals go.** The boot runs on the current Ollama stack.
> This change is design-of-record only until then. Section 1 (parity harness) is
> the acceptance gate and SHALL be green before any default is switched.

## 1. Parity harness (acceptance gate — build first)

- [x] 1.1 Reasoning-suppression mapping pinned at the unit level: `OpenAIChatClient`
      and `HTTPBareInferenceClient` send `chat_template_kwargs.enable_thinking`
      (NOT Ollama's native `think`) and retry-without on server reject
      (`tests/test_lingua_client.py`, `tests/test_evaluation_observers.py`).
      **LIVE** end-to-end probe (Ollama `/api/chat {think:false}` vs Studio
      `/v1`, assert no CoT leak) runs at the supervised pre-boot shakedown when
      Studio is serving — services aren't up in CI.
- [x] 1.2 Organ↔baseline served-model parity preserved: baseline derives from
      `[lingua].model_id`, explicit mismatch fails closed
      (`tests/test_evaluation_config.py`, unchanged invariant — now over the
      served GGUF id).
- [x] 1.3 Studio headless soak (V4): serve the organ continuously for a sustained
      run; record latency/stability; confirm no leak/stall before defaulting.
      **LIVE — verified via the `kaine-model-server.service` systemd unit
      (`llama-server` serving `kaineone/Qwen3.5-4B-abliterated-GGUF`
      at `127.0.0.1:11434`): 24h+ continuous `active (running)` with zero
      restarts/crashes in that window and clean per-request timing logs
      (no OOM/segfault/stall signatures) as of the 2026-07-01 verification pass.**

## 2. Lingua: OpenAI-compatible client is the sole production path

- [x] 2.1 `OpenAIChatClient` (`lingua/client.py`) carries reasoning suppression
      via `chat_template_kwargs.enable_thinking`, with fail-safe retry-without.
- [x] 2.2 `module.py` constructs `OpenAIChatClient`; `OllamaChatClient` and its
      `/api/chat` path removed; `cycle/__main__.py` control client switched too.
- [x] 2.3 `config/kaine.toml` `[lingua].chat_url` → `…/v1`; comments rewritten
      (backend-agnostic OpenAI server). `model_id` set to the GGUF id (§4).
- [x] 2.4 `tests/test_lingua_client.py` updated (suppression mapping + retry);
      no Ollama-native client tests remain.

## 3. Evaluation: A/B baseline shares the backend

- [x] 3.1 `HTTPBareInferenceClient` (`ab_divergence.py`) posts to
      `/v1/chat/completions` with the same suppression mechanism; parity tests
      added.
- [x] 3.2 Baseline derives from `[lingua].model_id`, same served model;
      fail-closed preserved.

## 4. Model sourcing: pinned GGUF

- [x] 4.1 `[lingua].model_id` set to `huihui_ai/Huihui-Qwen3.5-9B-abliterated-GGUF`;
      config documents the published GGUF
      (`mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF`). Exact quant + revision
      pin is the operator's choice when loading into Studio (and is captured as
      the research base-model covariate at run time).
- [x] 4.2 Document organ-model provisioning for Studio in the
      operator/external-researcher guides — §7.2 docs pass. Landed in
      `docs/getting-started.md` (GGUF vs safetensors table, turnkey bootstrap),
      `docs/hardware.md` (model-server VRAM budget, vendor split), and
      `docs/modules/lingua.md` (client/config reference).

## 5. GPU preflight: generalize off Ollama

- [x] 5.1 Replaced `/api/ps` + `/api/generate {keep_alive:0}` with report-only
      `/v1/models` listing: single-resident backend → no idle-evict lever; still
      measures headroom, preserves KAINE services, **never terminates** a process.
- [x] 5.2 `config/kaine.toml` `[gpu_preflight]`: `ollama_url` → `model_server_url`,
      `unload_idle_ollama` removed; Nexus block field `unloaded_models` →
      `resident_models`.
- [x] 5.3 `tests/test_gpu_preflight.py` updated for report-only + never-terminate.

## 6. Setup wizard & dependency provisioning

- [x] 6.1 Wizard model discovery moved from `/api/tags` to `/v1/models`
      (`served_models`).
- [x] 6.2 `setup/dependencies.py`: Ollama `DepSpec` replaced by a `model_server`
      dep (Unsloth toolchain, vendor-aware); later promoted from guide-kind to a
      consented `command` dep (`scripts/model-server-bootstrap.sh`) in the
      turnkey published-organ install; Ollama no longer required;
      `implied_external_deps`/tests updated.
- [x] 6.3 `scripts/tier1_smoke.py` probe → `/v1/models`.

## 7. Health, docs, suite

- [x] 7.1 `nexus/health.py` `/v1/models` probe unchanged (already generic);
      preflight block field renamed; Ollama labels updated.
- [x] 7.2 Docs pass (present-tense): single model backend; non-CUDA fallback;
      remove Ollama-as-required wording across `docs/`. Verified: the only
      remaining `docs/` mentions of Ollama are the intentional GGUF-conversion
      caveats in `docs/hardware.md` and `docs/processes/voice-alignment.md`
      (Ollama's non-standard converter output, not a serving dependency).
- [x] 7.3 Targeted + full suite green; import-boundary contracts intact
      (backend reached only over HTTP). `openspec validate --strict` green.

## 8. Archive

- [x] 8.1 After merge, `openspec archive unify-inference-on-studio -y`.
