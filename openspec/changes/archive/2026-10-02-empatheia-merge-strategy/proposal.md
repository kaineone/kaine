# Fork merges reconcile Empatheia's agent profiles

## Why
`EmpatheiaMergeStrategy` exists in `kaine/modules/empatheia/store.py` but nothing registers it. `ForkManager` takes its strategies from `default_strategies()` in `kaine/lifecycle/strategies.py`, which maps only Mnemos, Nous, Eidolon and Thymos. Empatheia's state therefore falls through to the union strategy, where parent B's values overwrite parent A's: a merged profile keeps B's interaction count instead of the sum, and B's histogram instead of the weighted average. That breaks the spec scenario "the merged agent profile has an interaction count at least as large as the maximum of the two forked counts" whenever A saw more interactions than B.

The spec also says the merged profile "SHALL be persisted to Qdrant before the merge completes". A merge runs offline over two snapshots and produces a third snapshot; there is no live Empatheia store to write to, and writing to the running entity's collection would be wrong. `apply_merged_state`, written for that purpose, is called from nowhere. The merged profiles reach the store the way any fork's do: the merged snapshot carries them, `deserialize` loads them into the store's cache when the snapshot is restored, `get` and `all_profiles` read the cache first, and the next update of a profile writes it to Qdrant.

Research impact: none. Studies do not merge forks, and the running module-ignition study uses a pinned image.

## What changes
- The strategy and its profile-merge helper move to `kaine/lifecycle/strategies.py`, beside the other module strategies, so the lifecycle layer keeps not importing `kaine.modules`. `default_strategies()` maps `"empatheia"` to it.
- `apply_merged_state` is removed, and the package stops exporting both names. The store's module docstring points to the strategy's new home.
- The Empatheia spec states what actually happens to merged profiles.
- The docs describe Empatheia merges as reconciled.
