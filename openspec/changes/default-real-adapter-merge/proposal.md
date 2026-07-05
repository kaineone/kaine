# Make lineage fork/merge perform a real weight merge by default

## Why

The paper treats forking and merging as a real cognitive-lineage operation. In code,
`FakeAdapterMerger` is the shipped default (`kaine/lifecycle/manager.py:128,363`): it
unions the two adapters' path lists **without any weight merge**. A real TIES/DARE
merge exists (`kaine/lifecycle/adapter_merge.py`) but requires the
`[lifecycle.adapter_merge]` opt-in plus the PEFT extra. The default is honest (it
logs, and `merge()` raises `UnmergedAdaptersError` when both parents have trained
adapters unless `allow_unmerged_adapters` is passed), so nothing is silently faked —
but by default the lineage lifecycle does no learned-weight merge, which is a gap
against the paper's design.

This is lower priority than the salience, security, and evaluation changes because it
only bites once forks have *trained* adapters (post voice-alignment divergence), and
the fail-loud guard prevents a silent wrong merge. It is filed so the gap is tracked,
not lost.

## What Changes

**Plan-only. Ships no behavior code.**

1. Make the real TIES/DARE `AdapterMerger` the **default** when the PEFT extra is
   present, with `FakeAdapterMerger` retained only as an explicit dev/no-extra
   fallback (mirroring the DreamerV3/EMA and CfC-fallback pattern).
2. When the extra is absent and both parents have trained adapters, keep failing loud
   (`UnmergedAdaptersError`) rather than silently unioning — but make the remediation
   message name the extra to install.
3. Document the default in `config/kaine.toml` and the lifecycle docs.

## Impact

- Affected specs: `adapter-ties-dare-merge`, `entity-preservation`.
- Affected code (later pass): `kaine/lifecycle/manager.py`,
  `kaine/lifecycle/adapter_merge.py`, `config/kaine.toml`.
- No change to the fail-loud safety behavior; this only flips which merger is the
  default when a real merge is possible.
