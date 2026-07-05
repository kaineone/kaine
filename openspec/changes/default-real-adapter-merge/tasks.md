# Tasks — Default real adapter merge

> **Design-of-record only.** Plan, not implement. Lower priority; no fail-loud
> behavior changes.

- [ ] 1.1 Default to the real TIES/DARE `AdapterMerger` when the PEFT extra is present.
- [ ] 1.2 Retain `FakeAdapterMerger` only as an explicit dev/no-extra fallback.
- [ ] 1.3 Keep `UnmergedAdaptersError` fail-loud when the extra is absent and both
      parents have trained adapters; improve the message to name the extra to install.
- [ ] 1.4 Document the default in `config/kaine.toml` + lifecycle docs.
- [ ] 1.5 Tests: real merge runs when the extra is present; fail-loud preserved when
      absent.
