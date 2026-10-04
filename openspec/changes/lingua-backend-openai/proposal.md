# Name the Lingua default backend after what it is

## Why

The complexity audit of 2026-10-03 (W14) found that Lingua's backend registry names its default HTTP backend `"ollama"`. The organ is served by an OpenAI-compatible server (llama-server), not Ollama, so the name misleads anyone reading the config or the registry. The shipped tier profiles repeat it.

## What changes

- The Lingua registry's default backend is `"openai"`. `"ollama"` stays registered as an accepted alias that builds the same HTTP client, so existing configs keep working.
- The edge `llama_cpp` backend falls back to `"openai"`.
- The tier2 and tier3 profiles set `backend = "openai"`.
- The configuration appendix describes `"openai"` as the HTTP backend and `"ollama"` as its alias.

The audit also asked whether `kaine/setup/organ.py` and `kaine/setup/model_server.py` overlap enough to merge. They do not:
- `organ.py` acquires and verifies the organ (consented download, served-alias check, revision state).
- `model_server.py` launches and supervises the server process.
- `model_server.py` already reuses `organ.py`'s `detect_organ_backend`, `verify_served_alias` and `ORGAN_GGUF_REPO` instead of copying them.

## Impact

- **Behaviour:** none. Both names build the same `OpenAIChatClient`. A fallback from `llama_cpp` now reports `openai` instead of `ollama` as the backend it fell back to.
- **Research:** none. No study is running, and the organ client is unchanged.
