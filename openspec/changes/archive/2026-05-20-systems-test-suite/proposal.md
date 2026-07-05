## Why

The existing unit tests under `tests/test_*.py` cover internal class
behavior. They don't answer "does this subsystem fulfill its
bus-level contract?" If an operator (or a future maintainer) wants
to know whether a single module reads what it should and publishes
what it should — without booting the whole entity — they have to
read the source.

The systems suite fills this gap. One file per subsystem.
Each test exercises the subsystem's externally-visible I/O against
a fakeredis bus using a small harness, with no other modules
running. Out-of-process services (Unsloth, Speaches, Chatterbox,
ONA, Qdrant) are skip-gated by env var so the suite stays green on
any host.

This is the harness an operator can run before first boot to verify
the build's per-subsystem contracts. It's also the test pattern
future module additions should follow.

## What Changes

- New `tests/systems/` package:
  - `_harness.py` — `SubsystemHarness` builds a fakeredis-backed
    `AsyncBus` + a single module instance, exposes `inject(stream,
    event)` and `collect(stream)` helpers, handles initialize +
    shutdown.
  - `conftest.py` — common fixtures + env-var skip markers
    (`KAINE_HAS_UNSLOTH`, `KAINE_HAS_SPEACHES`, `KAINE_HAS_CHATTERBOX`,
    `KAINE_HAS_QDRANT`, `KAINE_HAS_NAR_BINARY`). Without any of
    them set, the related subsystem tests fall back to fake
    collaborators so the contract is still tested, just against the
    fake.
  - One test file per subsystem:
    - `test_bus_subsystem.py` — publish/read roundtrip, schema
      validation, audit refuses unauthenticated boot.
    - `test_cycle_subsystem.py` — tick collects events, calls
      syneidesis, broadcasts on `workspace.broadcast`.
    - `test_workspace_subsystem.py` — Syneidesis composes from
      candidates, applies inhibition, top-k.
    - `test_soma_subsystem.py` — feed cycle latency event, expect
      `soma.out` wellness event.
    - `test_chronos_subsystem.py` — feed workspace broadcast,
      expect `chronos.out` events.
    - `test_topos_subsystem.py` — feed an image-path event, expect
      `topos.out` (skipped when transformers can't fetch the model
      and no local fallback).
    - `test_nous_subsystem.py` — feed a fact event, expect
      `nous.belief` (skipped without NAR binary; FakeNARProcess
      always tested).
    - `test_mnemos_subsystem.py` — store + recall via in-memory
      backend, observe `mnemos.out`.
    - `test_eidolon_subsystem.py` — feed internal speech, expect
      drift event + persistence.
    - `test_thymos_subsystem.py` — feed soma + chronos events,
      expect dimensional state output + drive crossings.
    - `test_praxis_subsystem.py` — issue file_write / notify /
      shell, observe sandbox effect + audit log + denials.
    - `test_lingua_subsystem.py` — feed workspace broadcast,
      expect `lingua.external` or `lingua.internal` (uses FakeChat
      when no Unsloth).
    - `test_audio_in_subsystem.py` — feed audio bytes, expect
      transcription event (FakeSTT when no Speaches).
    - `test_audio_out_subsystem.py` — feed `lingua.external` +
      Thymos state, expect TTS request observed by Fake client.
    - `test_hypnos_subsystem.py` — fire began_rest, execute one
      phase, fire ended_rest; observe event order.
    - `test_lifecycle_subsystem.py` — snapshot a stub registry,
      restore into fresh modules; verify state matches.
    - `test_boot_subsystem.py` — build registry from a real config
      dict; every enabled module registers.
    - `test_nexus_subsystem.py` — diagnostics + conversation
      routes return expected JSON shapes.
    - `test_sidecar_subsystem.py` — registry boots, each observer
      writes one JSONL line, no core import.
- pyproject `[tool.pytest.ini_options]` — add a `systems` marker so
  operators can run just the systems suite via
  `pytest -m systems`.

## Capabilities

### New Capabilities

- `systems-test-suite` — per-subsystem I/O verification. Operators
  can validate each subsystem independently before first boot.

### Modified Capabilities

None — tests are added; no production code changes.

## Impact

- **No new external deps.**
- Adds `tests/systems/` (~18 files).
- Full suite remains green; new tests skip cleanly when external
  services are absent.
- README + FIRST_BOOT.md gain a brief note pointing operators at
  `pytest -m systems` as the pre-boot per-subsystem check.
