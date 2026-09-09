# Tasks — Harden security boundaries

> **Status: implemented (14/14).** All five hardening items ship in code and are
> under CI (import-boundary + redteam security-boundary gate). Tasks 2.3 and 3.1
> are resolved as documented won't-do decisions (see their notes): both are the
> optional/"preferred-but-not-minimum" branch of the proposal, neither is required
> by a spec delta, and the delivered work meets every `entity-preservation` and
> `praxis` requirement. Each item is independent.

## 1 — P1: fork/merge id validation (path traversal)
- [x] 1.1 Add a strict id validator `^[0-9a-f]{16}(\+[0-9a-f]{16})?$`; reject at the
      `/diagnostics/forks` and `/diagnostics/merges` endpoints with HTTP 422.
      (`is_valid_snapshot_id` in `snapshot.py`; enforced in `diagnostics.py`.)
- [x] 1.2 In `snapshot_dir`/`snapshot_path` (`kaine/lifecycle/snapshot.py`), resolve
      the candidate path and confirm containment under `root` (reuses the Praxis
      `_resolve_sandbox_path` approach); raises `InvalidSnapshotId` on escape.
- [x] 1.3 Tests: endpoint 422 (`test_nexus_routers.py`) + path-builder raise
      (`test_fork_merge_snapshot.py`) for absolute/`..`/separator ids; valid 16-hex
      and `<hex>+<hex>` still resolve; server-generated write path unaffected.

## 2 — P2: tamper-evident Praxis audit log
- [x] 2.1 Added `prev_hash`/`this_hash` hash-chaining with canonical (sorted,
      compact) serialization over the record substance.
- [x] 2.2 Added `verify()` -> `AuditChainResult(ok, broken_index, detail)`.
- [x] 2.3 (Optional, best-effort) append-only FS attribute — RESOLVED: won't-do. Not
      required by the `praxis` spec delta (only hash-chaining + verifier + 0600/0700
      are), and explicitly optional in the proposal ("Optionally set the append-only
      FS attribute where supported"). Rejected as portability-fragile: `chattr +a`
      /`FS_APPEND_FL` is Linux/ext-family only and needs `CAP_LINUX_IMMUTABLE`
      (root), so it is a no-op under the non-root CI/test umask and would add
      privileged, unverifiable platform-branching. The 0600/0700 perms (task 5) are
      the shipped line of defense; the hash chain (2.1/2.2) supplies tamper-evidence.
      Evidence (shipped alternative): `kaine/modules/praxis/audit_log.py`
      — `ActionAuditLog.append` writes via `os.open(..., O_CREAT|O_APPEND, 0o600)`
      (atomic create-at-0600, no world-readable window) and `ActionAuditLog.verify`
      -> `AuditChainResult` detects edit/reorder/truncation; the module docstring's
      "Threat model" section states append-only-FS is deliberately out of scope.
- [x] 2.4 Tests: edited + middle-truncated historical records detected
      (`test_praxis_audit_log.py`).

## 3 — P2: privacy filter allowlist (or guard)
- [x] 3.1 Allowlist — RESOLVED: won't-do (denylist + CI guard kept instead). The
      proposal offers allowlist OR "keep the denylist but add a CI guard test" and
      names the guard "the minimum" (delivered in 3.2/3.3); no spec delta in this
      change mandates an allowlist (it adds only entity-preservation + praxis
      deltas). Documented decision in `privacy_filter.py`: the
      diagnostics surface reads DYNAMIC nested keys (`metadata.coherence.<pair>`,
      `state.valence/arousal`) that a key-name allowlist would blank, and the
      recursive scrub is load-bearing for `workspace.broadcast` embedded payloads;
      a safe inversion needs a live-dashboard boot to verify. (The export-eligible
      research surface already IS a per-event-type allowlist — `research_event_observer`.)
      Evidence (shipped alternative): `kaine/privacy_filter.py` — the
      "Denylist vs. allowlist" comment block records this decision, `CONTENT_FIELDS`
      (incl. the audit-found `description`/`statement`), and `PrivacyFilter`'s
      recursive `_scrub`; regression-guarded by `tests/test_nexus_privacy.py`
      (`test_no_uncovered_content_key_in_module_publishers` AST-scans every module
      `publish()` payload and fails on a new content-capable key).
- [x] 3.2 Minimum: added `test_no_uncovered_content_key_in_module_publishers`
      (AST-scans every module `publish()` payload; fails on a new content-capable
      key). Also closed the concrete leaks the audit found by adding `description`
      + `statement` to `CONTENT_FIELDS`.
- [x] 3.3 Tests: `test_novel_thymos_goal_description_is_scrubbed_at_top_level_and_nested`
      + the publisher-scan guard (`test_nexus_privacy.py`).

## 4 — P2: red-team + suite in CI
- [x] 4.1 Added `.github/workflows/redteam.yml` running
      `pytest tests/test_evaluation_redteam.py` on push/PR.
- [x] 4.2 Extended to a fast, torch-free security-boundary subset (fork/merge id,
      audit chain, Praxis perms, privacy guard) as a merge gate.

## 5 — P3: Praxis file permissions
- [x] 5.1 `chmod` the audit log to `0600` (`audit_log.py`) and the sandbox dir to
      `0700` (`effectors.py`) after creation, mirroring `snapshot.py`.
- [x] 5.2 Tests under umask `0002` (`test_praxis_audit_log.py`, `test_praxis_effectors.py`).
