# The wizard offers the base thesis or the full entity, recommended by the hardware

## Why
The first-run wizard asks about each module with its own hard-coded defaults (Soma, Chronos, Thymos, Eidolon, Mnemos and Lingua on; Topos and Audition off) and always writes the full `[modules]` table to `config/kaine.operator.toml`. The operator file merges last, so a wizard-configured install never gets the base-thesis entity the project describes as its default, and nothing tells the operator which set their machine can actually run.

The operator decided (2026-10-02) that the wizard offers a choice between the base thesis and the base thesis plus the other modules, and recommends the full set when the host's hardware can run it.

Research impact: none for studies, which configure modules through their own overlays. A fresh wizard install now gets either the base-thesis module set or the full cognitive set, by choice.

## What changes
- The module step offers three choices:
  - **Base thesis** — exactly the `[modules]` table of `config/profiles/thesis_test.toml`, read from that file.
  - **Full entity** — every cognitive module on (Soma, Chronos, Topos, Audition, Lingua, Thymos, Nous, Mnemos, Eidolon, Praxis, Vox, Hypnos, Empatheia, Phantasia); the embodiment modules (Perception, Mundus) and Echo (test infrastructure) stay off.
  - **Custom** — the existing per-module questions, with the chosen preset's values as the defaults.
- The wizard recommends **Full entity** when the tier probe recommends tier 2 or 3 without module residency, and **Base thesis** otherwise (lower tiers, residency required, or no recommendation available), and says why in one line.
- `--defaults` (non-interactive) applies the recommendation when a tier recommendation is available, and the base thesis otherwise.
- The wizard's own hard-coded module defaults (`DEFAULT_MODULE_SET`) are removed; the presets are the only defaults.
- The module step reports the chosen preset.

## Impact
- Code: `kaine/setup/wizard.py`.
- Specs: `first-run-wizard` (ADDED).
- Docs: Getting started (wizard steps) and the configuration appendix's "Module defaults".
