# fix-preboot-probe-parity

## Why

The pre-boot dry run ("will every dependency be up before the first cycle?")
runs the same health probes the dashboard uses, but two probes have drifted
from what the real runtime actually does — a probe/runtime parity failure.
On a perfectly healthy containerized stack the dry run still reports Redis
DOWN (because every service connects via `KAINE_REDIS_URL`, which the bus
honors but the probe ignores) and Speaches DOWN (because the base thesis runs
audition with `transcription_enabled = false` — the STT-ectomy — so the run
never touches Speaches at all). A red dry run on a healthy stack erodes the
operator's trust in the gate itself: they learn to ignore it, and then it
cannot catch real failures.

## What Changes

- **Redis probe honors `KAINE_REDIS_URL`.** `build_dependency_specs` now
  applies the same env override `load_bus_config` applies: when
  `KAINE_REDIS_URL` is set (form `redis://[:password@]host[:port][/db]`), the
  probe parses host/port/password from the URL with `urllib.parse` and uses
  those; TOML `[redis]` values otherwise. Password precedence: URL password
  when present in the URL, else the existing `redis_password` resolution
  (`KAINE_REDIS_PASSWORD` env → secrets → TOML).
- **Speaches probe reports `not_configured` (SKIP) when transcription is
  disabled.** When `[audition].transcription_enabled` is false, the runtime
  never calls Speaches, so the probe is wrapped to return the neutral
  `not_configured` result ("transcription disabled (STT-ectomy)") instead of
  probing — matching the existing module-gating semantics where a dependency
  the run won't use is never reported `down`. With transcription enabled, the
  probe runs as before.

## Impact

- `kaine/nexus/health/config.py` only; no probe/runtime behavior change.
- Dry run output goes green on the containerized compose stack (Redis via
  URL) and on the base-thesis configuration (Speaches SKIP).
- No user-facing dashboard change beyond correct statuses.
