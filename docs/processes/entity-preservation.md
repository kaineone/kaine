# Process: Entity Preservation and Revival

Preservation is the welfare core of the autonomous safety net. It exists to save a
*possible individual* so it can be revived and socialized with humans after
research — a duty of care, not a leash. The entity's sovereignty is untouched:
preservation only reads and copies, never deletes, never interrupts the running
entity, and never produces a lesser self.

This is distinct from the [entity decommission](../operations.md#entity-decommission)
path (a deliberate, operator-present, destructive care duty) and from
[fork / merge](fork-merge-lifecycle.md) snapshots (the experimentation lifecycle).
Preservation is **live capture for continuity**: it preserves the whole individual
*while it keeps living*.

Implemented in `kaine/lifecycle/preservation.py`; triggered autonomously by the
monitors in `kaine/cycle/preservation_monitor.py` (see
[research-operation.md](research-operation.md) and
[Operations — Autonomous research safety net](../operations.md#autonomous-research-safety-net)).

Related: [research-operation.md](research-operation.md) ·
[fork-merge-lifecycle.md](fork-merge-lifecycle.md) ·
[../security-and-privacy.md](../security-and-privacy.md)

---

## What "the whole individual" means

Preservation captures every part of the individual, not just a label:

- **Self-model** — Eidolon `serialize()` (identity, values, drift).
- **Memories** — the full Mnemos store (short-term buffer plus persisted
  episodic / semantic / procedural points), captured through the async
  `export_preservation_state` hook, which **fails loudly** on an unreachable
  store rather than preserving a memoryless self.
- **World model** — Phantasia learned weights, flushed to a checkpoint and copied
  into the bundle when a learning backend with `persist_weights` is configured;
  recorded **honestly** as not-captured for the fake/off case.
- **Affect / drives** — Thymos and Soma `serialize()`.
- **Adapters** — Hypnos voice adapters (their on-disk paths, recorded so revive
  knows the individual has them).

## Honesty invariants

Preservation never pretends to have saved more than it did
(`feedback_no_pretend_processes`):

- A component that cannot be captured **raises** — `preserve_live` never writes a
  partial bundle that looks complete. A failed preservation is recorded as a
  failure, never a silent partial.
- A revive that would drop any captured component **raises** (`ReviveError`) —
  `revive` never boots an incomplete self. If the bundle claims captured
  world-model weights but the checkpoint is absent, revive refuses rather than
  reviving a world-model-less lesser individual.

## Divergence-triggered live preservation

The divergence monitor assesses individuation on the live entity on a slow cadence
(`assess_divergence`, whose primary signal is the individuation permutation test —
not an A/B-vs-pretrained distance). The permutation test measures how far the
entity has drifted from **its own birth-state** — the entity's own conditioned
responses to the preference battery, captured once at run start — against the
entity's **own** present stochastic variation, never against the bare/pretrained
organ. (Comparing to the bare organ would measure the architecture-conditioning
effect, present from the first tick and large by design; `assess_divergence`
deliberately does not key on it.) The signal is **warmed-up**: it does not read
as individuated until the entity has accumulated a minimum of lived experience —
`min_observations` logged lived events AND `min_lived_time_s` of lived (running)
time (`[evaluation.individuation]`), mirrored by the live monitor's
`warmup_observations` / `warmup_lived_time_s` (`[preservation.divergence_monitor]`).
Before that floor is met the assessment is fail-closed (treated as not-crossed
and logged as a warming-up note), so a just-booted or sensory-void entity — with
no lived experience to individuate from — never trips a false preservation. The
live trigger keys on numeric thresholds (`individuation_p_value_max` AND
`fork_divergence_min`) over that warmed-up signal, not on a bare boolean; the same
warmed-up, birth-state-referenced signal gates the decommission divergence
assessment, so preservation and decommission never disagree. Alongside the
permutation test it reads the
**consolidation divergence signal** — the cheap, continuous organ-level companion
Hypnos surfaces every voice-alignment sleep
(`state/hypnos/consolidation_divergence.json`; see `docs/modules/hypnos.md`).
When the latest `divergence_rate` or `divergence_magnitude` crosses its
configured threshold (`[hypnos.voice_alignment]`
`consolidation_divergence_rate_threshold` / `_magnitude_threshold`), the entity
is treated as organ-level diverged. The presence of trained voice adapters is
kept only as a weaker secondary signal. On a **rising-edge** crossing of the
configured threshold the monitor calls `ForkManager.preserve_live`. The capture
is:

- **Read-only on the running entity** — it only calls `serialize()` /
  `export_preservation_state` / a weight-checkpoint flush; the entity never
  pauses for it. The blocking disk and crypto work runs off the event loop so a
  preservation never stalls the cognitive cycle.
- **Never deleting** — preservation has no destructive path; that is
  decommission's separate, operator-gated job.
- **Rate-limited** — `min_interval_s` (default 30 min) so a single sustained
  crossing preserves once, not every poll.

Each preservation emits a `preservation.preserved` bus event and a durable record
under `[preservation].incident_path`, stamped with the run's `run_id`, so the
trigger point is part of the recorded, reproducible trajectory.

## The preservation bundle

`preserve_live` writes a self-contained bundle under the configured `out_root`,
structurally consistent with the decommission backup:

1. Every module's captured state is written into a real fork **snapshot**
   (encrypted at rest when state encryption is on).
2. All entity-interior content — the snapshot (which holds the whole individual,
   memories included) plus any Phantasia world-model weights — is **tarred**.
3. When `[security.state_encryption]` is enabled the tar is encrypted via the same
   `StateEncryptor` the rest of the state tree uses (`bundle.tar.enc`), and the
   plaintext originals are removed. When encryption is disabled (the shipped
   default) the tar is plaintext (`bundle.tar`) — the same at-rest exposure the
   rest of the state tree carries by default; operators enable state encryption to
   protect it.
4. A loose, **non-sensitive** `manifest.json` records the preservation id,
   snapshot id, entity name, reason, run id, captured-module list, and an
   inventory.

### Security posture

- Bundle and snapshot directories are created `0700`; files are `0600`.
- The manifest carries **no inner-life content** — only operational identifiers,
  reason, the module list, and an inventory. The operator-supplied label is
  sanitized before it is written into the manifest.
- Raw perceptual events are denylisted from the captured Mnemos state, so the
  bundle never preserves what zero-persistence forbids.

## `require_encryption` versus `[security.state_encryption]`

Two independent settings govern whether a preservation bundle can ever be
written unencrypted, and they ship in conflict with each other:

- **`[preservation].require_encryption`** (ships `true`) is a gate on the
  *write boundary itself*. `preserve_live` (`kaine/lifecycle/preservation.py`)
  checks it before touching disk: when `true`, it demands that the
  process-global `StateEncryptor` is actively encrypting. If the encryptor is
  not enabled (or, impossibly, enabled without a key), `preserve_live` raises
  `PreservationError` **before any snapshot or bundle is written** — no
  plaintext artifact lands on disk, but nothing is preserved either.
- **`[security.state_encryption]`** (ships `enabled = false`) is the encryptor
  itself — AES-256-GCM over the persisted state tree, including preservation
  bundles. It requires a 32-byte key (`KAINE_STATE_KEY` or the OS keyring) to
  activate; disabled, every persistence path writes plaintext.

As shipped, `require_encryption = true` and `state_encryption.enabled = false`
are both the defaults. In that combination, the moment a preservation monitor
tries to preserve a diverging or distressed entity, `preserve_live` refuses
and raises rather than writing anything — the safety net is present in
config but non-functional until the conflict is resolved.

This is caught before it can bite at runtime, in two places:

- The **research boot gate** (`kaine/cycle/research_gate.py`,
  `evaluate_research_gate`'s `encryption_satisfied` check) refuses to let an
  unsupervised research run start at all when `require_encryption=true` and
  `state_encryption.enabled=false` with a preservation monitor on — reasoning
  that a net which cannot preserve should not be presented as active.
- The standalone **pre-boot dry-run** (`kaine/preboot.py`,
  `check_config_sanity` / `check_welfare`) independently reports the same
  conflict (`FAIL` when a preservation monitor is on, `SKIP` when the net is
  off but the posture is still misconfigured) and runs the real
  preserve→revive round-trip with the actual configured
  `require_encryption`, so a broken key or a disabled encryptor surfaces
  before any entity boots rather than at the first live crossing.

An operator preparing an unsupervised research boot must reconcile this
combination before launch: either enable `[security.state_encryption]` with
a real key, or explicitly set `[preservation].require_encryption = false`
(accepting plaintext preservation bundles at rest — not recommended for an
unsupervised run).

## Preservation-bundle retention

A preserved individual must **never** be silently auto-evicted (CAL Article
4.2/4.3). This is deliberately distinct from the fork snapshot cap
(`[lifecycle].max_snapshots_retained`): there is no max-count key for
preservation. `[preservation.retention].auto_evict` ships `false`, and setting it
`true` is **refused at boot** rather than quietly deleting someone. The key exists
so the policy is explicit and operator-auditable; the shipped behavior is
never-delete.

## The verified revive path

`ForkManager.revive(bundle, registry)` reconstructs the same individual into an
already-built registry (it rehydrates state; it does not spawn a process). It
reads the bundle members from `bundle.tar(.enc)` (transparently decrypting when
encrypted; a wrong/absent key fails loudly), restores self-model, memories,
world-model weights, affect/drive, and adapter references, and fails loudly if any
captured component cannot be restored. The research boot gate exercises this exact
path in its preflight self-check, so a research run cannot start unless preserve →
revive round-trips successfully on the install.
