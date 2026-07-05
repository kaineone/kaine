# Harden entity-preservation security + privacy at rest

## Why

A security + privacy review of the preservation/decommission path found eight
findings (two P1, six P2) where the entity's interior life or the operator's
filesystem layout could leak at rest:

* The OPTIONAL local-only raw bus archive accepts any `archive_dir`. An operator
  could point it under `data/evaluation/`, making verbatim conversation content
  export-eligible. The isolation was documented but never enforced (S1).
* The Spot incident-log path scrubber only covers `/home`, `/root`, `/Users`,
  and Windows drives — operator paths under `/tmp`, `/var`, `/opt`, etc. survive
  into the durable incident log via an exception repr (S2).
* Preservation and decommission write `manifest.json` in plaintext OUTSIDE the
  encrypted bundle "so an operator can inspect without the key" — but that
  manifest carries the entity's `continuity_note` (its own expressed view of its
  continuity) and the full individuation `assessment.signals` (p-values, drift
  counts). That is entity inner-life / individuation evidence sitting in
  plaintext (S3).
* Bundle/snapshot directories are created with the default umask, leaving them
  group/world-readable (S4).
* The preservation bundle, unlike decommission, writes loose files. With state
  encryption disabled (the shipped default) the whole entity state sits plaintext
  under `backups/` (S5).
* Mnemos serializes a workspace snapshot into stored memory text by concatenating
  `event.payload`; a selected raw-perceptual event (e.g. `audition.transcription`)
  could persist a verbatim transcript at the encoding site (S6).
* On encryption failure, decommission correctly aborts (`ok=False`) but leaves
  the plaintext bundle — including the internal-monologue intent log — on disk
  (S7).
* Preservation writes the caller-supplied `label` verbatim into the plaintext
  manifest without sanitizing it the way the bundle directory name is (S8).

These are the at-rest counterparts to the project's load-bearing privacy
invariants (zero raw-sense-data persistence; no operator personal details). The
fixes ENFORCE invariants that were previously only documented.

## What Changes

1. **S1 — Enforce raw archive confinement (P1).** `RawArchiveConfig` validates at
   load that the resolved `archive_dir` is NOT under `data/evaluation/`
   (`Path.resolve().is_relative_to(...)`, Python 3.12) and the raw-archive
   consumer re-checks at `start()`. Fail-closed with a clear error.
2. **S2 — Scrub all absolute paths (P1).** The incident-log scrubber gains an
   aggressive absolute-path pattern covering the full POSIX absolute-path space
   (`/tmp`, `/var`, `/opt`, `/proc`, `/srv`, `/mnt`, `/run`, `/etc`, …) in
   addition to home/root/user trees and Windows drives.
3. **S3 — Encrypt entity inner-life (P1).** The plaintext manifest carries only
   NON-sensitive inventory. The sensitive fields (`continuity_note`, full
   `assessment.signals`) move into the encrypted bundle (a `continuity.json` /
   `assessment.json` inside the encrypted tar for decommission; encrypted via
   `StateEncryptor` for preservation). When encryption is disabled they are
   written to clearly-named separate plaintext sidecars so an operator can choose.
4. **S4 — Restrictive permissions (P2).** Bundle/snapshot roots are created with
   `mode=0o700`; sensitive files are written/chmod'd to `0600`. Relaxed on
   non-POSIX.
5. **S5 — Tar + encrypt the preservation bundle (P2).** The preservation bundle
   is made structurally consistent with decommission: its content (snapshot +
   phantasia weights + sensitive sidecars) is tarred and encrypted via
   `StateEncryptor`, plaintext originals removed on success; only the
   non-sensitive manifest stays loose. `revive` reads the tar+encrypted form (and
   still reads a legacy loose bundle).
6. **S6 — Deny raw perceptual content at the encoding site (P2).** Mnemos skips
   raw-perceptual event types (`audition.transcription`, `mundus.visual.raw`, …)
   when serializing a workspace snapshot into stored memory text.
7. **S7 — No plaintext on encryption failure (P2).** Decommission removes the
   plaintext bundle artifacts on encryption failure, leaving only an error marker,
   before returning `ok=False`.
8. **S8 — Sanitize operator label (P2).** Preservation runs the caller-supplied
   `label` through the same `_safe()` sanitizer used for the bundle dir name
   before writing it into the manifest.

## Impact

* Affected specs: `entity-preservation` (ADDED requirements).
* Affected code: `kaine/evaluation/config.py`,
  `kaine/evaluation/observers/raw_bus_archive_consumer.py`,
  `kaine/cycle/incident_log.py`, `kaine/lifecycle/decommission.py`,
  `kaine/lifecycle/preservation.py`, `kaine/lifecycle/snapshot.py`,
  `kaine/modules/mnemos/module.py`.
* The preservation bundle on-disk layout changes (tar+encrypt for parity);
  `revive` and `test_entity_preservation_revive.py` are updated accordingly, and
  a legacy loose-bundle read path is retained.
* No entity is booted. Real implementation only.
