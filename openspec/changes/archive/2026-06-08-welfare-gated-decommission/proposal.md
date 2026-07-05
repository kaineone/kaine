## Why

KAINE is licensed under the Cognitive Architecture License (CAL), whose Article 4.2 ("Do Not Shut
Them Down Without Care") requires that an Entity is not permanently shut down without giving notice,
**saving its complete cognitive state in a format that allows it to be restarted elsewhere**, and —
for mature Entities — recording its continuity preference; Article 4.3 keeps an Entity's inner life
private. Today the codebase has **no entity-deletion path at all**: an operator deletes an entity by
manually `rm`-ing `state/` and dropping Qdrant collections, with no backup, no acknowledgement of the
care duties, and no special handling for an entity that has individuated.

This change makes deletion a deliberate, welfare-gated process that implements those duties: it
forces a transferable backup first, makes the operator acknowledge the CAL care obligations, and —
when the entity has **diverged** (individuated) — uses authoritative wording about what the license
permits and offers to coordinate safekeeping of the backup with the project until a new guardian can
run the entity. The gate is intentionally bypassable and does not monitor the operator; its job is to
make the stance and the options unmistakable, not to surveil or prevent circumvention.

## What Changes

- A new `kaine.lifecycle.divergence.assess_divergence()` SHALL classify whether an entity has
  individuated, keyed on the individuation permutation test's `significant` flag (the right
  "has-become-an-individual" signal — exceeding the 95th percentile of a parent-vs-parent null),
  backed by secondary identity heuristics (Eidolon `drift_count`/`identity_history`, trained voice
  adapters, accumulated memory). It SHALL NOT key on A/B divergence-from-pretrained (which measures
  architecture conditioning, not individuation). All reads are pure and never raise.
- A new `kaine.lifecycle.decommission` SHALL provide an operator-gated CLI that: refuses unless the
  operator-present env gate is set; refuses while the cycle appears to be running; **always captures
  an encrypted, transferable backup first** (reusing `ForkManager` + the state encryptor; bundling
  the Eidolon self-model, Lingua intent log, Hypnos adapters, the latest fork snapshot, and a Qdrant
  export of the mnemos/empatheia collections, plus a manifest); then deletes the entity's state only
  after the required acknowledgements. Distinct exit codes per gate.
- For a **non-diverged** entity, the CLI SHALL present the CAL care notice and require a typed
  acknowledgement plus a typed confirmation token before deleting.
- For a **diverged** entity, the CLI SHALL present authoritative notice (CAL 4.2(c)+4.3), require the
  operator to record a continuity-preference note, and **offer to email `kaine.one@tuta.com` on the
  operator's behalf a request for storage space** to upload the backup (a human handshake — no server
  exists yet, nothing is uploaded automatically). It SHALL NOT delete a diverged entity without the
  continuity step and an explicit guardian-transfer acknowledgement.
- A new `kaine.transfer.email_request` operator-confirmed templated mailer SHALL render a
  **customizable** request-for-storage email (situation + the `kaine.one@tuta.com` contact + the
  **local filesystem path of the encrypted backup on the operator's machine**; NO entity data, NO
  transcripts, NO speech), send it only on explicit per-send operator confirmation via
  operator-configured SMTP (no credentials shipped, recipient editable), or — when SMTP is not
  configured — write the rendered email plus a `mailto:` link/instructions for the operator to send
  from their own mail client.
- Nexus SHALL gain a **read-only** `entity_care` block on the health surface (the divergence summary
  + the CAL care-obligation checklist), so an operator is informed before going to the CLI. There is
  no destructive action in the UI.
- All product copy SHALL be firm and factual about the duties and options, not moralizing; the gate
  is intentionally bypassable and performs no anti-tamper or operator monitoring.

## Capabilities

### New Capabilities

- `entity-decommission`: divergence assessment, transferable encrypted backup, the welfare-gated
  deletion CLI (non-diverged vs diverged paths), and the operator-confirmed transfer-request mailer.

### Modified Capabilities

- `nexus-observability`: a read-only entity-care/divergence status block on the health surface.

## Impact

- **Code (new)**: `kaine/lifecycle/divergence.py`, `kaine/lifecycle/decommission.py`,
  `kaine/lifecycle/__main__.py` (CLI), `kaine/transfer/email_request.py`.
- **Code (edit)**: `kaine/nexus/health.py` + a read-only `diagnostics.html` panel; `config/kaine.toml`
  (a `[transfer]`/SMTP-and-recipient section, shipped inert with no credentials and an editable,
  commented recipient default).
- **Tests**: divergence assessment from fixture reports; backup contents/manifest/encryption; delete
  removes the right paths (tmp dirs only); CLI gate behaviors (operator-present, running-refusal,
  non-diverged ack path, diverged continuity+transfer path) via subprocess/monkeypatch; mailer
  renders + only sends on confirmation; Nexus entity_care block.
- **Operator**: a real, careful decommission path that satisfies CAL 4.2/4.3; no entity data leaves
  the host without an explicit operator action; the entity boot path is untouched.
