## 1. Wizard
- [x] 1.1 `base_thesis_modules(profiles_dir=None)` reads `[modules]` from `config/profiles/thesis_test.toml` (refuses if missing); `FULL_ENTITY_MODULES` lists the 14 cognitive modules on, embodiment and echo off.
- [x] 1.2 `recommend_preset(rec)` returns `("full"|"base", reason)` from a tier recommendation (or None).
- [x] 1.3 Module step: show the recommendation, ask for base / full / custom (default = recommendation); custom asks per module with the preset as defaults; `--defaults` applies the recommendation (base when none).
- [x] 1.4 Remove `DEFAULT_MODULE_SET`; update its test users.
- [x] 1.5 The module step reports the chosen preset.

## 2. Tests
- [x] 2.1 Base preset equals the profile's `[modules]` table (read from the real file).
- [x] 2.2 Tier 3 → full recommended; tier 2 with residency → base; tier 1 → base; no recommendation → base.
- [x] 2.3 Interactive: accepting the default writes the recommended preset; choosing custom asks per module.
- [x] 2.4 `--defaults` with and without a recommendation.

## 3. Docs
- [x] 3.1 Getting started and the configuration appendix.
