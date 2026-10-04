# One definition of the base-thesis module set

## Why

The complexity audit of 2026-10-03 (W15) found two definitions of the base-thesis module set:
- `config/profiles/thesis_test.toml` enabled six modules (Soma, Chronos, Topos, Audition, Lingua, Thymos);
- the operator overlay added Hypnos.

The settled base thesis has seven modules. Thymos and Hypnos were both added deliberately on 2026-09-08, as the overlay's comments record, and the module-ignition study starts from those seven. The shipped profile and the spec were stale copies. The spec still listed Thymos and Hypnos as disabled, and the first-run wizard's base-thesis preset, which reads the profile, offered six.

## What changes

- `config/profiles/thesis_test.toml` enables Hypnos, with the reason recorded beside it. Voice alignment stays off in `[hypnos.voice_alignment]`.
- **The rule:** the profile is the single definition of a module set. The operator overlay carries host-local values (paths, endpoints, keys) and deliberate deviations. The wizard's base-thesis preset reads the profile. The loader docstring and the configuration docs state the rule.
- The spec's thesis-test module set lists the seven modules.
- The book's module lists and counts follow.

The settled module set is not changed; its shipped copies are brought into line with it.

## Impact

A fresh install with no operator `[modules]` table now runs Hypnos's sleep cycles, as the settled base thesis does. Installs whose overlay already sets `[modules]` (the wizard always writes one) are unaffected. No study is running.
