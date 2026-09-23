## Context

`load_kaine_config` merges four layers and returns a plain dict. Ten callers read it: the runtime entrypoints (the cycle, the pre-boot check, the lifecycle and research CLIs) and read-only surfaces (Nexus readers, the perception preview server, the setup helpers). None validates types, and several read toggles by truthiness.

## Decisions

**One validation point, after the merge.** Shape is checked once, on the merged dict, inside `load_kaine_config`. Checking each layer separately would reject legitimate partial overlays; checking in each consumer is how the gap arose. Only sections the runtime depends on are validated. This is not a full schema, and unknown sections and keys pass through untouched.

**Errors are `ProfileError`s.** `ConfigShapeError` subclasses `ProfileError`, so the handlers already in the cycle and the pre-boot check report it as a configuration error without new plumbing. The message names the dotted key, the expected type and the actual type, never the value (operator values can include private voice or path names).

**Strict where it matters, logged elsewhere.** The runtime path (`load_runtime_config`) refuses an unparsable operator file, because booting on defaults the operator did not choose is unsafe. Read-only surfaces keep the existing tolerance so a typo cannot take down the dashboard, but the skip is logged at WARNING with the file path and the parse error.

**Fail closed for security-relevant sections.** A reader must not translate "configuration could not be loaded" into a weaker security posture. The Nexus state-encryption reader raises instead of returning `{}`, and Nexus treats a failed encryption setup as disqualifying for state I/O: it logs an error and leaves the fork manager unconstructed, rather than logging a warning and continuing on the process-global default, which is a disabled pass-through encryptor. The rest of Nexus (monitoring, conversation) keeps running, so the failure is visible without taking the dashboard down. The lifecycle reader, whose empty default only selects the automatic adapter merger, keeps its fallback.

## Risks

- An operator config that relied on truthy strings or integers stops loading. That is the intended outcome, and the error names the key to fix.
- Callers that catch `Exception` and fall back to `{}` now receive shape errors too. Each caller was reviewed: the Nexus state-encryption reader and the research submission CLI weaken safety on fallback and change to fail closed; the health board, the perception preview server and the model-server setup only lose display or defaults and keep a logged fallback. The decommission CLI did not use this loader at all and now does, strictly.
