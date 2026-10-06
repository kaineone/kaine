## 1. Clients
- [x] 1.1 Every runtime httpx client and request call in `kaine/` passes `trust_env=False`.
- [x] 1.2 `trainer_service`'s urllib probe opens through an opener with an empty ProxyHandler.
- [x] 1.3 The setup downloaders (`setup/speech_models.py` and `wheel_index.py`) are left proxy-capable and named in the guard's allowlist with the reason. Every allowlisted path must exist, so a change that adds a downloader adds its own entry. The guard also scans `scripts/`, which fixed `scripts/tier1_smoke.py`. Import forms that would hide a client from the scan (an aliased or from-imported httpx or websockets) are refused.

## 2. Tests
- [x] 2.1 A guard test: an AST scan of `kaine/` fails on any httpx client or request call without `trust_env=False`, and on any `urlopen` outside the allowlist. Mutation-check it by removing one keyword.
- [x] 2.2 A real-path test: with proxy variables pointing at a closed port, Lingua's real `OpenAIChatClient` reaches a local HTTP server directly.
