## 0. Decision

- [ ] 0.1 The lead approves the environment route (or picks an alternative).

## 1. Loader

- [ ] 1.1 `load_secrets_doc` treats an unreadable file as absent with one warning; every reader goes through it.
- [ ] 1.2 `load_token` reads `KAINE_CARETAKER_TOKEN_<NAME>` before the file.
- [ ] 1.3 Setup writes the dashboard token to `compose/.env` as well.

## 2. Deployment

- [ ] 2.1 Compose passes the caretaker and dashboard tokens and stops mounting `config/secrets.toml`.
- [ ] 2.2 The quadlet units do the same.

## 3. Tests and docs

- [ ] 3.1 An unreadable secrets file with the environment set boots the bus, Qdrant and dashboard config; a readable file is unchanged.
- [ ] 3.2 Update the compose, quadlet, services and preservation docs.
