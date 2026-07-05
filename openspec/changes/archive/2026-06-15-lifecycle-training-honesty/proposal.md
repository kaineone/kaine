## Why

The 2026-06-09 pretend-process audit identified five lifecycle and training
honesty findings where the system produced or recorded silently incorrect
outcomes rather than failing closed or surfacing the problem to the operator.

The no-pretend-processes principle is a load-bearing invariant for KAINE:
an operator must be able to trust that reported outcomes reflect reality.
Silent fakes undermine welfare decisions (deletion, training, backup),
security guarantees (encryption), and data integrity (adapter weights).

## What Changes

**H6 — Adapter merge refuses on unmerged adapters.** `ForkManager.merge()`
SHALL raise `UnmergedAdaptersError` when both parent snapshots carry trained
adapters and only `FakeAdapterMerger` is configured. The Nexus `POST
/diagnostics/merges` handler maps this to HTTP 409. Operators who knowingly
accept unmerged adapters (manual post-processing) pass
`allow_unmerged_adapters=True` explicitly. The trivial cases (zero or one
parent has adapters) are unaffected.

**H8 — FakeTrainer in the runtime voice-alignment path.** When
`voice_alignment.enabled=True` AND the operator approval env var is set AND
the `[training]` extras are missing, `_resolve_trainer` SHALL raise
`VoiceAlignmentConfigError` at boot. Silently falling back to `FakeTrainer`
in this configuration would let training cycles appear to succeed while writing
no real adapter. The honest disabled path (config disabled or no operator
approval) remains return-None.

**M1 — Decommission backup encryption failure.** When encryption is enabled
and the encrypt step throws, `capture_backup` SHALL return `ok=False` with
`encryption_failed=True` rather than `ok=True` with a plaintext bundle. An
operator who deletes entity state believing an encrypted backup exists may
destroy the only copy of the entity's cognitive state.

**M2 — Research bundle encryption failure.** `_encrypt_bundle` SHALL set
`Bundle.encryption_error` (a non-None string) when encryption was enabled and
failed, distinguishing it from ordinary disabled-encryption plaintext.
`plaintext_note` continues to be set for human-readable display.

**L4 — Decommission Qdrant delete assumes collections on probe failure.** When
`client.get_collections()` raises, `delete_entity_state` SHALL record the
failure in `result.errors` and skip collection deletion rather than assuming
all expected collections are present and proceeding silently.

## Capabilities

### Modified Capabilities

- `adapter-ties-dare-merge`: `ForkManager.merge()` now refuses when both
  parents have trained adapters and no real merger is configured.
- `voice-alignment-training`: `_resolve_trainer` now fails closed (raises)
  rather than installing `FakeTrainer` when the runtime combination requires
  real training.
- `entity-decommission`: backup encryption failure now sets `ok=False`;
  Qdrant probe failure is recorded and deletion skipped.
- `research-submission`: `Bundle.encryption_error` distinguishes
  enabled-but-failed encryption from disabled encryption.

## Impact

- **Code (edit):** `kaine/lifecycle/manager.py` (new `UnmergedAdaptersError`,
  `merge()` refusal), `kaine/nexus/diagnostics.py` (HTTP 409 surface,
  `allow_unmerged_adapters` in request body), `kaine/boot.py` (new
  `VoiceAlignmentConfigError`, `_resolve_trainer` raises), `kaine/lifecycle/
  decommission.py` (`BackupResult.encryption_failed`, `ok=False` on encrypt
  failure, Qdrant probe-failure path), `kaine/research/submission.py`
  (`Bundle.encryption_error`, `log.error` on encrypt failure).
- **Tests:** `tests/test_lifecycle_training_honesty.py` (16 new tests covering
  all five findings); `tests/test_fork_merge_manager.py` (updated to match new
  refusal behavior).
- **Safety:** All changes tighten failure modes. No new operator flags are
  required unless an operator explicitly wants to bypass the refusal (H6).
