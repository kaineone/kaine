## Why

Phase 9 wraps the build: full-system integration tests (§9.1),
security audit (§9.2), operator-facing docs + first-boot script that
DOES NOT RUN automatically (§9.3). After this lands the repo tags
`v1.0-ready` and the next action — first boot — belongs to the
operator, in person.

## What Changes

- `tests/test_phase_9_integration.py` — end-to-end fakeredis test
  exercising the full system without initializing entity state:
  cycle ticks at the configured rate with all twelve module names
  publishing, Syneidesis composes broadcasts, ForkManager snapshots
  and restores the full registry, Nexus connects to the same bus
  and emits SSE for both surfaces without leaking content to
  diagnostics. (No real Redis, no real services.)
- `tests/test_phase_9_cycle_rate_stability.py` — verifies the cycle
  holds its target processing/experiential rates within 25% across
  50 ticks at three configurations (1 Hz, 3.333 Hz, 10 Hz).
- `tests/test_phase_9_no_runtime_external_calls.py` — scans the
  built `kaine/` tree for runtime imports of `httpx`/`requests`/etc.
  and verifies every external-call site is gated behind explicit
  module configuration (allowlist of Lingua/Audio-Out/Audio-In's
  localhost endpoints).
- `SECURITY.md` — security audit conclusions: Redis access policy,
  Qdrant auth, Praxis whitelist posture, container isolation,
  state-at-rest posture (no encryption in v1, documented as an
  operator responsibility), Nexus auth posture (loopback only,
  no auth in v1, documented), runtime network-call inventory.
- `ARCHITECTURE.md` — module-by-module mapping from paper §3 to
  code paths, the event-bus topology, and the privacy boundary
  proof sketch.
- `FIRST_BOOT.md` — operator-facing first-boot procedure. The
  document explicitly says "DO NOT run this until you are present
  at the keyboard."
- `scripts/first-boot.sh` — operator script that boots Redis +
  Qdrant compose stacks, then prints instructions. It SHALL fail
  fast if `KAINE_FIRST_BOOT_OPERATOR_PRESENT=1` is not set in the
  environment, so an accidental invocation is a no-op.
- README updates: status moves from "Phase 0" to "v1.0-ready, first
  boot pending operator". Tag `v1.0-ready` after merge.

## Capabilities

### New Capabilities

- `final-integration` — system-level guarantees: full-stack ticking,
  rate stability, no-external-runtime-calls invariant, fork/merge
  roundtrip on populated registries, Nexus + cycle co-existence.

### Modified Capabilities

None — Phase 9 verifies and documents existing capabilities; it
does not modify module behavior.

## Impact

- **No production code changes.** Tests, docs, one operator script.
- **No new deps.**
- Tag `v1.0-ready` published.
- First boot remains operator-supervised; nothing in this change
  starts the cognitive cycle.
