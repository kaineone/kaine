# CI hygiene and unified-config repair

## Why
The `unified-instance-configuration` change was executed by the dark factory, but
independent review (`.dark-factory-triage.md`) flagged two tasks as blocked
failures and the resulting PR (#828) is failing CI on both `ruff` and `tests`.
The defects are mechanical: missing SPDX headers, a missing `__version__`, an
incomplete package-data glob, an unclassified import-boundary set, a
broken reference-config generator, a preboot stub that replaced (rather than
appended to) the real module, and operator-added keys absent from the shipped
defaults. None of them change KAINE's behaviour; all block merging and unattended
factory runs.

## What changes
- Repair the mechanical CI failures so the offline suite is green again.
- Replace the `kaine/preboot/__main__.py` stub with a real append-only
  `ConfigValid` check in `kaine/preboot.py`.
- Rewrite `scripts/generate_reference_config.py` to consume the dict returned by
  `list_all_defaults()` and emit valid TOML, with inline explanations and tier
  metadata.
- Add a `tier_for_key()` helper (basic/standard/advanced) so the wizard and
  questionnaire can filter by tier; record tier metadata in a code-side map to
  avoid changing the `list_all_defaults()` contract.
- Promote `storage` and `vocal.qwen3_*` to uncommented defaults in shipped
  `config/kaine.toml` so the shipped file stays the single source of truth.
- Update `docs/appendix-d-roadmap.md` to reflect the actual unified-config status.

## Scope
Code hygiene + config tooling only. No module behaviour, no new features, no
operator/hardware/GPU work.

## Risks
Low. All edits are additive or header-only. The one behavioural touch is the
new preboot check, which is append-only and reports rather than raises.
