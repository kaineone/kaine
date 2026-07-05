## 1. Implement the secrets merge in the cycle config loader

- [x] 1.1 In `kaine/cycle/__main__.py`, after `_load_kaine_config` parses
      `config/kaine.toml`, read `config/secrets.toml` tolerantly (missing file
      is OK), reusing the same reading approach as `load_bus_config`.
      (Factored `load_secrets_doc` into `kaine/bus/config.py`, shared by both.)
- [x] 1.2 Resolve the Qdrant API key with precedence `KAINE_QDRANT_API_KEY` env
      → `secrets["qdrant"]["api_key"]`. Only when a non-empty key resolves,
      inject it into `config["mnemos"]["qdrant"]["api_key"]`, creating the
      `mnemos` and `mnemos.qdrant` sub-dicts if absent.
- [x] 1.3 Do not overwrite an existing `config["mnemos"]["qdrant"]["api_key"]`
      already set in `kaine.toml`; leave it intact.
- [x] 1.4 Emit the same world/group-readable file-mode warning for
      `config/secrets.toml` that `load_bus_config` emits, when the file exists.
      (Now lives once in `load_secrets_doc`.)
- [x] 1.5 Ensure the resolved key is never logged and never written to
      `state/cycle/runtime.json` (verify `_write_runtime_state` is unchanged).

## 2. Regression tests

- [x] 2.1 Test: with the key only in a temp `secrets.toml [qdrant].api_key`
      (no env var, no key in `kaine.toml`), the loader returns a config whose
      `mnemos.qdrant.api_key` equals the secrets value.
- [x] 2.2 Test: `KAINE_QDRANT_API_KEY` env var takes precedence over a
      different `secrets.toml [qdrant].api_key` value.
- [x] 2.3 Test: with no key anywhere, the loader injects no empty key (Mnemos's
      explicit "requires qdrant_api_key" raise is already covered by
      `tests/test_mnemos_module.py`). Plus a 5th test: an explicit
      `kaine.toml [mnemos.qdrant].api_key` is left intact over env+secrets.
- [x] 2.4 Test: missing `secrets.toml` plus `KAINE_QDRANT_API_KEY` set resolves
      from env without error.

## 3. Verify and boot

- [x] 3.1 Run the full suite (`.venv/bin/python -m pytest -q`) — all green
      (791 passed, 12 skipped, with shipped all-off `[modules]` defaults).
- [x] 3.2 Re-run the first boot (`KAINE_CYCLE_OPERATOR_PRESENT=1
      .venv/bin/python -m kaine.cycle`) and confirm `state/cycle/runtime.json`
      appears with `tick_index` advancing and the seven enabled modules listed.
      (Verified: tick_index 97→107 over 3s at 3.333 Hz; modules = chronos,
      eidolon, lingua, mnemos, nous, soma, thymos. Mnemos→Qdrant auth 200.
      NOTE: required reconciling an orphaned `kaine-qdrant` container — see
      below — which is infra state, not part of this change's code.)
- [x] 3.3 Confirm `http://127.0.0.1:8088/diagnostics/` shows
      `cycle_status: running` and the expected module set. (Verified, HTTP 200.)
