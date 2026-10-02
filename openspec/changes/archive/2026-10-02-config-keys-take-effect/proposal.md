# Configuration keys that are accepted take effect, or are refused

## Why
A documentation audit against the code found configuration keys that boot accepts and then ignores. An operator who sets one gets the default without any sign of it:

- `[hypnos].requested_rest_min_interval_s` is read by Volition's rest proposals but never passed to Hypnos, whose own `too_soon` check stays at 1800 s. The `hypnos` spec already requires Hypnos to honour the key.
- `[lingua].api_key` never reaches the job-queue voice-alignment trainer: `_resolve_job_queue_trainer` reads a `kaine_config` name that is not in scope, the `NameError` is swallowed, and only `KAINE_MODEL_SERVER_API_KEY` works.
- `[topos].habituation_window` is allow-listed but never forwarded; the habituator always uses 16.
- `[topos].encoder_revision` is allow-listed but never forwarded; the loader always uses its pinned revision. Accepting a different value silently is worse than refusing it, because the pin protects which vendored code and weights load.
- `[logging].level` is read by nothing; the cycle always logs at INFO.
- `expose_<name>` keys under `[mundus.<adapter>]` all land in the symbolic action-family map, so continuous channels cannot be exposed from configuration, and a misspelled key is accepted.

Research impact: none for the running MoC7 study (its image is pinned) and none for future runs that keep the shipped values, which equal the defaults the code already used (1800 s, 16, the pinned revision, INFO). Runs that set different values get the behaviour they asked for.

## What changes
- `make_hypnos` passes `requested_rest_min_interval_s` to `Hypnos` (validated: a number greater than 0).
- The job-queue trainer gets the organ API key with the same precedence as Lingua's client: `[lingua].api_key`, then `KAINE_MODEL_SERVER_API_KEY`. `make_hypnos` passes the merged configuration to `_resolve_trainer`, which passes it on; nothing reads an undefined global.
- `make_topos` builds the habituator with `RollingMeanHabituator(window=habituation_window)` (an integer of at least 2).
- `make_topos` refuses to boot when `encoder_revision` is set to anything other than the loader's `PINNED_REVISION`, naming both values. The shipped value equals the pin.
- The cycle sets the root log level from `[logging].level` (`DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`, case-insensitive) once the configuration is loaded; any other value is a configuration error (exit 1, no traceback).
- `make_mundus` routes each `expose_<name>` key by what the selected body declares: a continuous channel goes to continuous exposure, an action family to symbolic exposure, and any other name is a configuration error naming the key and the body's declared names.

## Impact
- Code: `kaine/boot.py` (`make_hypnos`, `_resolve_trainer`, `_resolve_job_queue_trainer`, `make_topos`, `make_mundus`), `kaine/cycle/__main__.py` (log level).
- Specs: `hypnos`, `topos`, `voice-alignment-training`, `configuration-loading` (MODIFIED/ADDED); new `embodiment-exposure`.
- Docs: the configuration appendix and the Topos, Hypnos and Mundus pages drop their "accepted but ignored" notes.
