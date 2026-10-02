# Security policy

## Reporting a vulnerability

If you find a security vulnerability in KAINE, please report it **privately** so
it can be fixed before public disclosure. Do **not** open a public issue for a
security report.

- Preferred: GitHub private vulnerability reporting — the **Security → Report a
  vulnerability** button on this repository
  (`https://github.com/kaineone/kaine/security/advisories/new`).
- Or email **kaine.one@tuta.com** with a description and, if possible, a
  proof of concept.

This is a solo-maintained research project, so responses are best-effort: expect
acknowledgement within a few days, and we will coordinate a fix and a disclosure
timeline with you. Please allow reasonable time to remediate before disclosing
publicly.

## 4. State at rest

Every persisted store of cognitive state, and how it is protected. The shipped
configuration has `[security.state_encryption].enabled = true` and refuses to boot
without a key. Key sources, rotation and the cryptographic details are in
[Security and privacy](docs/13-security-and-privacy.md#state-at-rest).

| Store or file | Contents | Protection |
|---|---|---|
| `state/eidolon/self_model.json` | Eidolon self-model: name, values, norms, identity history | App-layer AES-256-GCM |
| `state/forks/<id>/snapshot.json` | Fork and merge bundles, including Phantasia world-model weights | App-layer AES-256-GCM |
| `data/evaluation/<observer>/` | Evaluation sidecar observer JSONL logs | App-layer AES-256-GCM per line |
| `state/phantasia/world_model.ckpt` | Phantasia world-model weights | App-layer AES-256-GCM |
| Mnemos Qdrant collection (`kaine-qdrant-data`) | Memory embeddings and payloads | Qdrant API key; plain HTTP on the host or compose network (no TLS); OS-layer |
| Empatheia Qdrant collection (`kaine-qdrant-data`) | Agent-model embeddings | Qdrant API key; plain HTTP on the host or compose network (no TLS); OS-layer |
| `state/lingua/intent_expression.jsonl` | Intent and expression pairs, **high sensitivity** | OS-layer |
| `state/hypnos/adapters/`, `kaine-organ-adapters` | Voice-alignment adapters | OS-layer |
| `state/hypnos/voice_align_jobs/` | Trainer job data (deleted when a job ends) | OS-layer |
| `state/praxis/audit.log`, `state/praxis/files/` | Praxis audit log and written files | OS-layer |
| `state/vox/` | Retained speech output, when the sink is enabled | OS-layer |
| `kaine-redis-data` volume | Bus AOF | OS-layer |

Anything marked OS-layer needs disk encryption (LUKS, FileVault or equivalent)
on any backup-exposed or multi-user host.

## Supported versions

Security fixes land on `main`. There are no maintained release branches.

## Threat model and design

The threat model, the enforced boundaries (bus authentication, the Praxis
sandbox, state encryption, the Nexus access modes and privacy filter) and the
operator's responsibilities are documented in
[Security and privacy](docs/13-security-and-privacy.md).
