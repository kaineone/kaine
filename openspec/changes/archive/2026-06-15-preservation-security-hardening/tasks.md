# Tasks

## 1. S1 — Confine raw archive_dir outside the export allowlist (P1)
- [x] 1.1 `RawArchiveConfig.from_mapping`: reject (fail-closed) when the resolved
      `archive_dir` is under `data/evaluation/` via
      `Path(...).resolve().is_relative_to(Path("data/evaluation").resolve())`.
- [x] 1.2 `RawBusArchiveConsumer.start()`: re-validate confinement before start.
- [x] 1.3 Test: an `archive_dir` under `data/evaluation/` is rejected; the
      shipped default (`state/research/...`) is accepted.

## 2. S2 — Scrub all absolute paths in the incident log (P1)
- [x] 2.1 Extend `_PATH_PATTERNS` with an aggressive absolute-path pattern
      covering the full POSIX absolute-path space.
- [x] 2.2 Tests: `/tmp/...`, `/var/lib/...`, `/opt/...` are scrubbed to `<PATH>`.

## 3. S3 — Encrypt entity inner-life; non-sensitive plaintext manifest only (P1)
- [x] 3.1 Decommission: move `continuity_note` + full `assessment.signals` into
      an encrypted `continuity.json` / `assessment.json` inside the encrypted
      tar; the plaintext manifest keeps only a bare `diverged` bool + inventory.
- [x] 3.2 Preservation: encrypt `continuity`/sensitive fields via `StateEncryptor`;
      the plaintext manifest keeps only non-sensitive inventory.
- [x] 3.3 When encryption disabled: write the sensitive fields to a clearly-named
      SEPARATE plaintext sidecar (honest), not the manifest.
- [x] 3.4 Tests: with encryption ON, the plaintext manifest contains no
      `continuity_note` / no full `signals`; the sensitive content is recoverable
      only after decryption.

## 4. S4 — Restrictive permissions on bundle/snapshot artifacts (P2)
- [x] 4.1 `snapshot.py`, `preservation.py`, `decommission.py`: create bundle/
      snapshot roots with `mkdir(mode=0o700, ...)`; chmod sensitive files 0600.
- [x] 4.2 Decommission: chmod the mkstemp tmp to 0600 before `os.replace`.
- [x] 4.3 Test: the bundle dir mode is 0700 (skip/relax on non-POSIX).

## 5. S5 — Tar + encrypt the preservation bundle (P2)
- [x] 5.1 `preserve_live`: tar content (snapshot + phantasia + sensitive sidecars),
      encrypt the tar via `StateEncryptor`, remove plaintext originals on success;
      keep only the non-sensitive manifest loose. Document the disabled-default
      (plaintext tar) risk.
- [x] 5.2 `revive`: read the tar+encrypted bundle; retain a legacy loose-bundle
      read path.
- [x] 5.3 Update `tests/test_entity_preservation_revive.py` to the new layout.

## 6. S6 — Deny raw perceptual content at the snapshot encoding site (P2)
- [x] 6.1 `_serialize_snapshot`: skip events whose type is in a raw-perceptual
      denylist (`audition.transcription`, `mundus.visual.raw`, …).
- [x] 6.2 Test: a selected `audition.transcription` event's verbatim payload does
      not appear in the serialized memory text.

## 7. S7 — No plaintext entity content on encryption failure (P2)
- [x] 7.1 `capture_backup`: on encryption failure, remove the plaintext bundle
      artifacts (incl. `intent_expression.jsonl`), leave only an error marker,
      then return `ok=False`.
- [x] 7.2 Test: after a forced encryption failure no plaintext entity content
      remains under the bundle dir.

## 8. S8 — Sanitize operator-supplied label (P2)
- [x] 8.1 `preserve_live`: run `label` through `_safe()` before writing the
      manifest.
- [x] 8.2 Test: a `label` with path-like characters is sanitized in the manifest.

## 9. Validate
- [x] 9.1 Targeted pytest selection green.
- [x] 9.2 The two sidecar-boundary tests + `test_entity_preservation_revive.py`
      in full green.
- [x] 9.3 `openspec validate preservation-security-hardening --strict`.
