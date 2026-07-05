## 1. H6 — Adapter merge refusal (`kaine/lifecycle/manager.py`, `kaine/nexus/diagnostics.py`)
- [x] 1.1 Add `UnmergedAdaptersError(RuntimeError)` to `manager.py`
- [x] 1.2 `ForkManager.merge()`: add `allow_unmerged_adapters: bool = False` parameter
- [x] 1.3 After `_adapter_merger.merge()`, when `adapter_merge_skipped` is set AND both
        parent adapter lists are non-empty AND `allow_unmerged_adapters` is False, raise
        `UnmergedAdaptersError` with a message naming both parents and the reason
- [x] 1.4 `kaine/nexus/diagnostics.py`: import `UnmergedAdaptersError`; add
        `allow_unmerged_adapters: bool = False` to `MergeRequestBody`; thread it through
        `fork_manager.merge()`; catch `UnmergedAdaptersError` → HTTP 409

## 2. H8 — FakeTrainer error at boot (`kaine/boot.py`)
- [x] 2.1 Add `VoiceAlignmentConfigError(ConfigurationError)` to `boot.py`
- [x] 2.2 In `_resolve_trainer`, replace the `log.warning + return None` fallback
        (extras missing path) with `raise VoiceAlignmentConfigError` that names the
        missing extras and gives the operator the install command
- [x] 2.3 Update `_resolve_trainer` docstring to reflect the new raise behaviour

## 3. M1 — Decommission backup encryption failure (`kaine/lifecycle/decommission.py`)
- [x] 3.1 Add `encryption_failed: bool = False` field to `BackupResult`
- [x] 3.2 In the `except Exception` block of the encryption step: call `log.error`
        (not `log.warning`), return `BackupResult(ok=False, encryption_failed=True, ...)`
        instead of falling through to `BackupResult(ok=True, ...)`

## 4. M2 — Research bundle encryption error (`kaine/research/submission.py`)
- [x] 4.1 Add `encryption_error: Optional[str] = None` field to `Bundle`
- [x] 4.2 In `_encrypt_bundle`'s except block: call `log.error`; set both
        `bundle.encryption_error` and `bundle.plaintext_note`

## 5. L4 — Qdrant probe failure (`kaine/lifecycle/decommission.py`)
- [x] 5.1 Add `probe_ok: bool = False` guard in `delete_entity_state`
- [x] 5.2 On `get_collections()` failure: call `log.warning`, append to
        `result.errors`, leave `probe_ok=False`
- [x] 5.3 Gate the per-collection deletion loop on `if probe_ok:`

## 6. Tests (`tests/test_lifecycle_training_honesty.py`,
##           `tests/test_fork_merge_manager.py`)
- [x] 6.1 H6: test_h6_merge_refuses_when_both_parents_have_adapters
- [x] 6.2 H6: test_h6_merge_proceeds_with_allow_flag
- [x] 6.3 H6: test_h6_merge_no_refusal_when_only_one_parent_has_adapters
- [x] 6.4 H6: test_h6_merge_no_refusal_when_neither_parent_has_adapters
- [x] 6.5 H8: test_h8_raises_when_enabled_approved_extras_missing
- [x] 6.6 H8: test_h8_returns_none_when_disabled
- [x] 6.7 H8: test_h8_returns_none_when_not_approved
- [x] 6.8 H8: test_h8_returns_none_when_voice_config_is_none
- [x] 6.9 M1: test_m1_backup_encryption_failure_returns_not_ok
- [x] 6.10 M1: test_m1_backup_encryption_success_still_ok
- [x] 6.11 M1: test_m1_backup_plaintext_when_encryption_disabled_is_ok
- [x] 6.12 M2: test_m2_bundle_encryption_error_set_on_failure
- [x] 6.13 M2: test_m2_bundle_encryption_error_none_when_disabled
- [x] 6.14 M2: test_m2_bundle_encryption_error_none_on_success
- [x] 6.15 L4: test_l4_get_collections_failure_records_error_and_skips_delete
- [x] 6.16 L4: test_l4_get_collections_success_deletes_normally
- [x] 6.17 Update test_fork_merge_manager.py::test_merge_combines_adapters_via_fake_merger
        to assert UnmergedAdaptersError on default path + allow_unmerged_adapters=True bypass
