# Tasks — Default real adapter merge

> **Design-of-record.** This change ratifies real-by-default adapter merging as the
> shipped design. The behavior is realized in code; each task is checked off against
> the concrete code/config/docs/tests that satisfy it. No fail-loud behavior changes.

- [x] 1.1 Default to the real TIES/DARE `AdapterMerger` when the PEFT extra is present.
      — `ForkManager.__init__` resolves `merger_from_name("auto")` by default
      (`kaine/lifecycle/manager.py:99`); `"auto"` selects `TiesDareAdapterMerger` when
      `check_peft_available()` passes (`manager.py:349-364`).
- [x] 1.2 Retain `FakeAdapterMerger` only as an explicit dev/no-extra fallback.
      — `"fake"` is an explicit selection (`manager.py:347-348`); `"auto"` only falls
      back to `FakeAdapterMerger` when the extra is missing (`manager.py:356-364`).
- [x] 1.3 Keep `UnmergedAdaptersError` fail-loud when the extra is absent and both
      parents have trained adapters; improve the message to name the extra to install.
      — `ForkManager.merge` raises with a remediation naming `pip install -e .[training]`
      / `kaine[training]` (`manager.py:211-231`).
- [x] 1.4 Document the default in `config/kaine.toml` + lifecycle docs.
      — `[lifecycle].adapter_merger = "auto"` with the real-by-default comment
      (`config/kaine.toml:1044-1052`); `kaine/lifecycle/ADAPTER_MERGING.md`
      ("real by default when installed").
- [x] 1.5 Tests: real merge runs when the extra is present; fail-loud preserved when
      absent. — `tests/test_lifecycle_adapter_merge_default.py` covers both spec
      scenarios (`test_real_merge_runs_via_forkmanager_when_peft_present`,
      `test_fail_loud_when_peft_absent_and_both_parents_trained`).
