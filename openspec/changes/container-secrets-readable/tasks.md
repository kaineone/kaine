## 0. Decision

- [x] 0.1 The lead approves the environment route (approved 2026-10-17).

## 1. Loader

- [x] 1.1 `load_secrets_doc` treats an unreadable file as absent with one warning; every reader goes through it.
- [x] 1.2 `load_token` reads `KAINE_CARETAKER_TOKEN_<NAME>` before the file.
- [x] 1.3 Setup writes the dashboard token to `compose/.env` as well.

## 2. Deployment

- [x] 2.1 Compose passes the caretaker and dashboard tokens and stops mounting `config/secrets.toml`.
- [x] 2.2 The quadlet units do the same; the install script creates `compose/caretaker.env`.

## 3. Tests and docs

- [x] 3.1 An unreadable secrets file with the environment set boots the bus, Qdrant and dashboard config; a readable file is unchanged; every former reader calls the loader.
- [x] 3.2 Update the compose, quadlet, services and preservation docs.
