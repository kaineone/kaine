## 1. Fixes

- [ ] 1.1 Research No writes `research_submission.enabled = false`, and a test re-runs the wizard over an opted-in file.
- [ ] 1.2 CL1 No removes the wizard-owned CL1 entries through `merge_owned`'s `REMOVE` marker. Unowned keys are still refused, and there's a test.
- [ ] 1.3 Encryption No while it is on keeps it on and prints why. Test it.
- [ ] 1.4 `kaine.setup.web` is imported only on `--web`. A test imports `kaine.setup.__main__` with fastapi blocked.
- [ ] 1.5 The individuation alert carries `kind`, `reference_id`, `last_reason`, `inconclusive_since` and `days`, and the caretaker kind `individuation_conditions_changed` exists. Test both alerts.
