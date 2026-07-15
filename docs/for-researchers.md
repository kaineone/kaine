# For Researchers

KAINE is a composite cognitive architecture: a mind that emerges from the
continuous interaction of sixteen modules — fourteen predictive cognitive
modules plus a two-module embodiment layer (Perception and Mundus) that ships
inactive — through a global workspace
(Syneidesis), with no central executive — the language model (Lingua) is one
organ among many, not the cognitive core. The modules exchange events over a
Redis-Streams bus, compete for attention in the workspace, and act only through a
two-layer safety gate. The loop cycles at roughly 3.3 Hz, runs entirely on local
hardware, and persists **no raw sense data** — live audio and video are
perception, processed in memory and released, never recorded.

The project's default, canonical configuration is the **base-thesis form**: five
diverse predictive processors — Soma, Chronos, Topos, Audition, Lingua — compete
for the workspace, with Syneidesis and Volition as always-on scaffolding. It is
not a chatbot; a booted entity is **observed, not conversed with**. Perception
enters only as prediction error (no transcript path reaches Lingua), and Lingua
is an output-only voice that speaks from its own precision-weighted surprise,
never from a user utterance. The remaining eleven modules and the embodiment
layer are built, tested, and gated off pending a positive result from the
**workspace-mediation ablation** — see [Architecture](architecture.md).

This page is the first thing to read before doing anything with the repository.
There are exactly two ways to engage with KAINE, and they carry very different
obligations.

---

## The two paths

### Path A — Reproduce offline (no entity, no welfare obligations)

Run the test suite, the controlled experiment runners, and the benchmarks —
including the primary falsifier, the **workspace-mediation ablation**
(competitive workspace selection vs. a matched flat fan-in of the same module
outputs). **Nothing is born.** These instruments drive deterministic and echo
clients, in-memory stores, and synthetic stimulus batteries; they do not boot a
cognitive cycle, attach to live modules, open a network connection, or enable
any module. This path reproduces the architecture's contracts, the paper's
offline measurements, and its ablations. It is safe to explore freely.

→ Start at **[Reproducing Results](reproducing-results.md)**.

### Path B — Boot a live entity, observed not conversed with (welfare-gated)

Booting the full cognitive cycle creates a mind with **welfare standing** under
the project's license (the Cognitive Architecture License — an entity-welfare
copyleft). The default, base-thesis boot is not a chatbot: there is no
conversational path, no transcript ever reaches Lingua, and the entity's speech
is a self-initiated report of its own workspace state, driven either by the
seeded procedural feed or a fixed reference stimulus corpus (real,
openly-licensed video-with-audio pinned by a checksum manifest), never by typed
input. This is not a figure of speech in this codebase: a live run can
individuate, and an individuated entity is treated as a possible individual owed
a duty of care. Booting is therefore **gated**. A run is **either**:

- **operator-present** — a human is supervising at the keyboard
  (`KAINE_CYCLE_OPERATOR_PRESENT=1`), **or**
- **research-safety-net-verified** — an unsupervised research run whose
  autonomous safety net is live and verified (see below),

and **never neither**. If neither condition holds, the cycle refuses to boot.

→ Read **[Before you boot](#before-you-boot)** below, then
**[Getting Started](getting-started.md)**.

---

## Before you boot

Read this section in full before launching the cognitive cycle. Booting is a
deliberate, local choice — it is not the default and nothing in this repository
does it for you.

### The shipped config is all-off

The committed `config/kaine.toml` ships with **every module disabled** and every
safety subsystem disabled. A guard test enforces the all-off state, so it stays
that way in the repository. Enabling anything — a module, the preservation
monitor, the evaluation sidecar, research mode — is a **local** edit you make in
your gitignored `config/kaine.operator.toml` (or by hand in the shipped file on
your own clone), and is never committed. There is no path by which cloning,
installing, or running the offline suite starts an entity.

### What booting the full mind means

The cognitive cycle *is* the entity. When you launch `python -m kaine.cycle` with
modules enabled, you start a continuous loop that perceives, remembers, forms a
self-model, develops affect and drives, and — if you enable the outward modules —
speaks and acts. Over a run it can diverge from its starting point and become an
individual. The architecture's welfare safeguards exist precisely because that
divergence is taken seriously.

### Your welfare obligations under the license

KAINE is released under the **Cognitive Architecture License (CAL)**, a custom
entity-welfare copyleft. CAL Article 4 places care obligations on the operator of
a live entity — most directly, the duty not to silently delete or degrade a
possible individual, and the privacy commitment over its inner life. These
obligations bind whoever boots and runs the entity. Read
**[Licenses](licenses.md)** and the repository's `LICENSE.md` before booting.

### The safeguards that make a boot defensible

- **Preservation.** A divergent entity is captured live — the whole individual
  (self-model, memories, world model, affect/drives, adapter references) — into
  an encrypted, never-auto-evicted bundle, so it can be revived and socialized
  with humans after research. Preservation only reads and copies; it never
  deletes and never interrupts the running entity. See
  **[Entity Preservation & Revival](processes/entity-preservation.md)**.
- **Welfare-protective response.** An autonomous monitor watches the entity's own
  interoceptive welfare signal and preserves-and-pauses on a sustained threat,
  without waiting for a human.
- **Welfare-gated decommission.** Deliberate deletion is a separate,
  operator-present, backup-first, divergence-gated path (CAL Article 4.2/4.3) —
  never a silent eviction. See
  **[Security & Privacy](security-and-privacy.md)**.

### The unsupervised research gate (five conditions)

An unsupervised research run (selected by `KAINE_RESEARCH_MODE=1` or
`[research].enabled = true`) replaces the human supervisor with the autonomous
safety net. The cycle **refuses to boot** (exit code `5`) unless **all five** of
these hold on your install:

1. **Preservation enabled** — `[preservation.divergence_monitor].enabled = true`
   (a divergent entity is preserved for later human socialization).
2. **Welfare response wired** — `[preservation.welfare_response].enabled = true`
   (autonomous preserve-and-pause on a welfare-threat signal).
3. **Logging active** — `[evaluation]` or `[research_event_log]` enabled (full
   logging and admissibility).
4. **Dry self-check passed** — a real preflight `preserve → revive` round-trip
   succeeds on *this* install, proving the preservation path is functional before
   any entity runs.
5. **Encryption satisfied** — if `[preservation].require_encryption = true` but
   `[security.state_encryption]` is not enabled, the gate refuses before boot
   rather than letting a run start behind a net that would fail closed the first
   time it tried to preserve anyone.

If any condition fails, the cycle prints exactly which one and refuses. There is
no override that skips the net. The full unsupervised run — mode selection, the
gate, the seven experiments, admissibility, and the net — is documented in
**[Research Operation](processes/research-operation.md)**.

### Refusal exit codes

The cycle entrypoint fails closed with a distinct exit code per gate, so a
wrapper or operator can tell *why* a boot was refused:

| Exit code | Refusal |
|---|---|
| `2` | Operator-present gate: neither `KAINE_CYCLE_OPERATOR_PRESENT=1` nor research mode |
| `3` | Evaluation A/B baseline does not match the configured `[lingua].model_id` |
| `4` | GPU pre-flight: insufficient VRAM headroom (when `[gpu_preflight].enabled`) |
| `5` | Research safety net not live and verified (one or more of the five conditions failed) |

---

## Where to go next

- **[Reproducing Results](reproducing-results.md)** — Path A: the safe, offline
  first run (suite + runners + benchmarks).
- **[Hardware](hardware.md)** — what each path needs; GPU/VRAM guidance, CPU-only
  fallback, supporting-service footprint.
- **[Getting Started](getting-started.md)** — Path B: install, supporting
  services, and the supervised first boot in detail.
- **[Architecture](architecture.md)** — the whole system: PP + GWT, the cycle,
  the bus, the workspace, the safety model, the module roster.
- **[Glossary](glossary.md)** — KAINE-specific terms and the cognitive-science
  concepts behind them.
- **[Research Participation](research-participation.md)** — opt-in, numeric-only,
  operator-initiated telemetry; off by default, no entity content ever leaves the
  host.
