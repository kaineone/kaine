## 1. Implementation

- [ ] 1.1 `redis-bootstrap.sh --native`: user-level redis-server, config, password reuse, supervision, PONG check.
- [ ] 1.2 `qdrant-bootstrap.sh --native`: pinned, sha256-verified release binary for x86_64 or aarch64; API key; supervision; `/readyz`.
- [ ] 1.3 Automatic choice (Docker if present, else native) and `--container`.
- [ ] 1.4 `first-boot.sh` accepts native services; `scripts/services.sh`.
- [ ] 1.5 Pin the Qdrant version to the client's range for both paths.
- [ ] 1.6 Docs.

## 2. Verification

- [ ] 2.1 Script tests with stubbed binaries: password reuse and rotate, config contents (loopback, port, requirepass, appendonly), the choice logic, the sha256 refusal on a mismatched download, and supervision without systemd.
- [ ] 2.2 A real native run on this host (redis-server and qdrant started, PONG and readyz answered, then stopped), recorded in the PR.
- [ ] 2.3 Offline suite green; `openspec validate native-services --strict`.
