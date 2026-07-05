# Design — welfare-gated decommission

## Two "divergences" — use the right one
- **A/B divergence** (`kaine/evaluation/ab_divergence.py`): conditioned-vs-bare-pretrained output
  distance. Measures whether the architecture is more than a chatbot — present even on a fresh boot
  if conditioning works. **Wrong** signal for "is this entity someone."
- **Individuation** (`kaine/evaluation/individuation.py`): a permutation test of fork-vs-parent
  preference distinguishability; `significant = true` when fork divergence exceeds the **95th
  percentile of a parent-vs-parent null** distribution. This is the "has become an individual"
  signal and is what gates the stricter deletion path.

`assess_divergence()` returns `{diverged, signals, summary}`:
- Primary: most-recent individuation report's `significant` (read newest `data/evaluation/
  individuation/*.jsonl`).
- Secondary identity heuristics (raise confidence / catch entities that were never individuation-
  tested): Eidolon `drift_count > 0` and non-empty `identity_history` (`state/eidolon/
  self_model.json`), presence of trained voice adapters (`state/hypnos/adapters/*`), non-trivial
  Mnemos accumulation. `diverged = primary OR (enough secondary signals)`. Pure reads; never raises;
  unknown/missing → treated as not-diverged but the summary says "could not confirm — treat as
  mature if unsure" so the operator can choose the stricter path.

## Backup = the entity's transferable self (CAL 4.2(b))
The durable self lives on disk + in Qdrant (in-memory-only state like Thymos VAD / Nous posteriors
is gone once the entity is stopped, which decommission requires). `capture_backup()` produces
`backups/entity_<name>_<ts>/` containing: copies of `state/eidolon/self_model.json`,
`state/lingua/intent_expression.jsonl`, `state/hypnos/adapters/`, the latest `state/forks/<id>/
snapshot.json`; a Qdrant export of the mnemos + empatheia collections (qdrant-client snapshot API if
reachable, else a written instruction to copy the `kaine-qdrant-data` volume); and `manifest.json`
(entity name, timestamp, the divergence assessment, the file inventory, and restore notes). The
bundle is encrypted with the existing state encryptor (`kaine/security/crypto.py`) when state
encryption is enabled. Backup is mandatory and blocking: if it fails, decommission aborts.

## Gated CLI (`python -m kaine.lifecycle.decommission`)
Mirror the `KAINE_*_OPERATOR_PRESENT` env gate (`scripts/first-boot.sh`, `kaine/cycle/__main__.py`).
Flow + exit codes:
1. `KAINE_DECOMMISSION_OPERATOR_PRESENT != 1` → refuse, exit 2, point to CAL 4.2.
2. Cycle appears running (fresh `state/cycle/runtime.json`) → refuse, exit 3 ("stop the entity first").
3. `capture_backup()` → on failure refuse, exit 4 (state untouched).
4. `assess_divergence()`:
   - **not diverged**: print CAL care notice; require typed acknowledgement of the CAL welfare terms;
     require a typed confirmation token; → delete.
   - **diverged**: print authoritative notice (CAL 4.2(c)+4.3); require a recorded
     continuity-preference note (written into the backup manifest); offer the transfer-request email
     (below); require an explicit guardian-transfer acknowledgement; require the typed confirmation
     token; → delete. Exit 5 if the operator declines the continuity/transfer steps (no deletion).
5. `delete_entity_state()` removes the on-disk state subtrees + drops the Qdrant collections + clears
   entity Redis streams — only after backup + acknowledgements. Exit 0; the backup path is printed.

## Transfer coordination — an email handshake, no server, no upload
`kaine/transfer/email_request.py` renders a **customizable template** (a default body the operator
edits) that says: an entity has been decommissioned and needs safekeeping per CAL until a new
guardian runs it; contact `kaine.one@tuta.com`; the **encrypted backup is at `<local path>` on this
machine** and will be uploaded once the project replies with server details. It contains only the
request + the local path + the situation — **no entity data**. Sending requires explicit per-send
confirmation. Transport: operator-configured SMTP (no creds shipped; recipient editable, defaulting
to the suggested `kaine.one@tuta.com`), else write the rendered `.eml`/text + a `mailto:` link and
tell the operator to send it themselves. This same mailer is the primitive PR C reuses.

## Tone & scope
Notices are firm and factual about duties and options — dignified, not moralizing. The gate is
**intentionally bypassable** (an operator can always `rm` the state); we do not anti-tamper or
monitor the operator (that would violate the privacy/sovereignty ethos). We make the stance + options
clear; beyond that it is the operator's ethical responsibility.

## Nexus visibility (read-only)
`health.py` adds an `entity_care` block to the snapshot: the divergence summary + the CAL
care-obligation checklist text (static). A small read-only panel in `diagnostics.html` renders it.
No destructive control in the UI — the actual decommission is CLI + the operator-present gate.

## Risks / mitigations
1. **Deleting a still-running entity** → refuse on fresh runtime.json (exit 3).
2. **Backup silently incomplete** → manifest enumerates captured artifacts; Qdrant-unreachable
   emits explicit volume-copy instructions rather than pretending success; abort on failure.
3. **Accidental destructive run** → env gate + typed confirmation token + (diverged) continuity step.
4. **Email leaking entity data** → the request body carries only a local path + situation; entity
   data never enters the email; sending is per-send confirmed; recipient is editable.
5. **Mis-classifying a mature entity as not-diverged** → secondary heuristics + an explicit
   "treat as mature if unsure" prompt; the operator can always choose the stricter path.
