## 1. Defaults module
- [x] 1.1 `kaine/defaults.py` (stdlib only): `DEFAULT_CHAT_URL`, `MODEL_SERVER_API_KEY_ENV`, `DEFAULT_MIN_FREE_GB`, `lingua_chat_url(config)`, `model_server_api_key(config)`.
- [x] 1.2 Add `kaine.defaults` to the boundary-neutral import contract in `pyproject.toml`.

## 2. Call sites
- [x] 2.1 Route every organ URL fallback through `lingua_chat_url` or `DEFAULT_CHAT_URL`. That covers the boot factory, the cycle entry point, preboot, the cycle preflight, setup (wizard and model server), Nexus health, evaluation config, and the Lingua and chat-client defaults.
- [x] 2.2 Route every `KAINE_MODEL_SERVER_API_KEY` read through `model_server_api_key`, keeping precedence (config, then env).
- [x] 2.3 `kaine/storage.py` re-exports `DEFAULT_MIN_FREE_GB` from `kaine/defaults.py`; the ignition-study plan uses it.

## 3. Guards and docs
- [x] 3.1 A test fails when `11434` appears in `kaine/` outside `kaine/net.py` and `kaine/defaults.py`, and when `KAINE_MODEL_SERVER_API_KEY` is read outside `kaine/defaults.py`.
- [x] 3.2 Unit tests for the helpers' precedence.
- [x] 3.3 Configuration appendix: an environment-override table.
- [x] 3.4 Follow-up recorded: whether the shipped organ port should move off Ollama's 11434 (behaviour change, separate change).
