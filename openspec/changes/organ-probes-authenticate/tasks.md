## 1. Organ healthcheck

- [x] 1.1 `compose/kaine.yml` `kaine-model-server` healthcheck curls `http://127.0.0.1:8080/health`
- [x] 1.2 `quadlet/kaine-model-server.container` `HealthCmd` curls the same URL
- [x] 1.3 A test pins both healthchecks to `/health` and to the same URL

## 2. Preflight resident-models probe

- [x] 2.1 `_server_resident_models` sends the bearer key when one is configured, and no `Authorization` header otherwise
- [x] 2.2 Tests cover both cases against a fake HTTP layer

## 3. Verification

- [x] 3.1 The organ container reports healthy on the pinned llama.cpp image with `--api-key` set
