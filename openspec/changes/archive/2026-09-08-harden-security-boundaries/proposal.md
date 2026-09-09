# Harden fork/merge inputs, the audit log, the privacy filter, and CI

## Why

A security review (2026-07-01, follow-up to the archived
`2026-06-15-preservation-security-hardening` S1–S8 pass) found one P1 and several
P2/P3 issues in boundaries the paper treats as load-bearing. Each is a real gap
between the claimed posture and the code. The bus auth, effector gate, crypto,
secrets handling, and Nexus XSS/CSRF posture were reviewed and found **sound** —
those are not touched here.

**P1 — Path traversal via fork/merge (arbitrary `snapshot.json` read).**
`POST /diagnostics/forks` and `/diagnostics/merges` pass the HTTP body's
`parent_id` / `snapshot_a_id` / `snapshot_b_id` straight into
`snapshot_dir(root, id) = root / id` (`kaine/lifecycle/snapshot.py:71-79`) with no
validation. Because `Path("root") / "/abs/path"` discards the left operand, an
absolute or `..`-bearing id escapes the snapshot root, and `load_snapshot` calls
`maybe_decrypt` — so with state-encryption disabled (the shipped default) any
local process reaching the Nexus API (or any remote client if `nexus.host` is ever
widened) can read any `snapshot.json` on the host, including other entities'
plaintext cognitive-state bundles. Legitimate ids are 16-hex UUIDs (or
`<hex>+<hex>` for merges), so any id containing a path separator is definitionally
invalid.

**P2 — Praxis audit log is append-only but not tamper-evident.**
`kaine/modules/praxis/audit_log.py` writes plain JSONL with `open(path, "a")`. A
local actor with filesystem write can edit or truncate history undetectably,
which contradicts the "tamper-evident audit" framing.

**P2 — Privacy filter is a content-field denylist, not an allowlist.**
`kaine/privacy_filter.py:26-40` strips a fixed set of named keys. Any future
content-bearing payload key under a new name (e.g. `reasoning`, `utterance`) flows
to the Nexus diagnostics SSE unfiltered, silently breaking the metadata-only
invariant. No active leak was found; the pattern is brittle and untested against
regression.

**P2 — The red-team suite is genuine but not CI-enforced.**
`tests/test_evaluation_redteam.py` drives the real gate/sandbox/audit and is
sound, but the only CI workflow is the import-boundary lint. A regression
reopening a blocked bypass would not fail any PR check.

**P3 — Praxis audit/sandbox files inherit umask permissions** (group/world-
readable under a permissive umask), unlike snapshot dirs which are hardened to
`0700`/`0600`.

## What Changes

**Plan-only. Ships no behavior code.** Design-of-record and task roadmap.

1. **Validate fork/merge ids** against a strict pattern (`^[0-9a-f]{16}(\+[0-9a-f]{16})?$`)
   at the Nexus request boundary AND apply the same containment check Praxis uses
   (`effectors.py:_resolve_sandbox_path`) in `snapshot_dir`/`snapshot_path`, so the
   resolved path must stay under `root`. Reject with 422 otherwise. Defense in depth
   at both the endpoint and the path builder.
2. **Hash-chain the Praxis audit log**: each record carries `prev_hash` and
   `this_hash = sha256(prev_hash || canonical(record))`; add a verifier that
   detects truncation/edits. Optionally set the append-only FS attribute where
   supported.
3. **Invert the privacy filter to an allowlist** (pass only explicitly-reviewed
   metadata keys per event type), OR keep the denylist but add a CI guard test that
   fails when a `publish()` call site introduces a payload key not covered by the
   filter's known-safe set. Allowlist is preferred; the guard test is the minimum.
4. **Add a CI job** running `pytest tests/test_evaluation_redteam.py` (ideally the
   full suite) on push/PR, gating merge.
5. **Harden Praxis file perms**: `chmod` the audit log to `0600` and the sandbox
   dir to `0700` after creation, mirroring `snapshot.py`.

## Impact

- Affected specs: `entity-preservation` / `entity-decommission` (snapshot id
  validation), `praxis` (tamper-evident audit, file perms), `nexus-privacy` /
  `evaluation-observers` (allowlist), `enforcement-red-team` (CI enforcement).
- Affected code (later pass): `kaine/lifecycle/snapshot.py`,
  `kaine/nexus/diagnostics.py`, `kaine/modules/praxis/audit_log.py`,
  `kaine/modules/praxis/effectors.py`, `kaine/privacy_filter.py`,
  `.github/workflows/`, `.pre-commit-config.yaml`.
- No functional behavior change for legitimate callers; all five are defense-in-depth
  hardening of existing boundaries.
