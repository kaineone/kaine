## 1. Registry and profiles
- [x] 1.1 `build_chat_client_registry`: default `"openai"`, `"ollama"` registered as an alias, `llama_cpp` falls back to `"openai"`.
- [x] 1.2 The tier2 and tier3 profiles set `[lingua].backend = "openai"`.
- [x] 1.3 The boot comment and the configuration appendix name `"openai"` with `"ollama"` as its alias.

## 2. Tests
- [x] 2.1 The registry default is `"openai"`; `"openai"`, `"ollama"` and an unset backend all build the HTTP client; the tier profiles ship `"openai"`.

## 3. Review
- [x] 3.1 Record why `kaine/setup/organ.py` and `kaine/setup/model_server.py` stay separate.
