# Paper update queue

Changes in the KAINE codebase that need to be reflected in the next paper
revision (`kaineone/predictive-workspace-paper`). Each entry names the
subsystem, what changed, and which new citations to add.

This file is the single source of truth for paper-update items. It lives in
the repo so it survives session compaction, context resets, and memory pruning.
Remove items only after the paper revision that incorporates them has been
reviewed and approved by the CTO.

Last reviewed: 2026-11-12 (session 23815fb0).

---

## 1. Voice context assembly (workspace-driven speech production)

**What changed:** The language organ no longer receives instructions about what
to say or how to structure its output. Instead, the ContextAssembler builds a
prompt from the entity's workspace state: situation, recalled memories, recent
dialogue, interoceptive awareness, and the heard input. These appear as the
entity's own first-person notes in markdown sections. The organ continues from
a lead heading ("## What I say") and decides autonomously what to vocalize.

**Why it matters for the paper:** The paper describes the language module's
prompt structure. The new design is a closer map to Levelt's speech production
model and should replace any description of the organ receiving formatted
instructions.

**New citations to add:**

1. Levelt, W. J. M. (1989). *Speaking: From Intention to Articulation.* MIT
   Press. Maps conceptualizer = workspace, formulator = organ, articulator =
   vocal module.

2. Schwarz, N., & Clore, G. L. (1983). Mood, misattribution, and judgments of
   well-being. *JPSP, 45*(3), 513--523. Plus Forgas, J. P. (1995). Mood and
   judgment: The affect infusion model. *Psych Bulletin, 117*(1), 39--66.
   Affect colors speech without explicit narration.

3. Conway, M. A., & Pleydell-Pearce, C. W. (2000). The construction of
   autobiographical memories in the self-memory system. *Psych Review, 107*(2),
   261--288. Recalled memories influence speech without being narrated.

**Existing citations already grounding this:** Baars (GWT), Dehaene et al.
(global neuronal workspace), Barrett 2017 (interoceptive concepts), Alderson-Day
& Fernyhough 2015 (inner speech), Hickok & Poeppel 2007 (dorsal stream).

**Code:** `kaine/modules/language/context.py`, PR #718.

---

## 2. Episodic memory recall in the language context

**What changed:** The language organ can now access recalled episodic memories
(when `context_memory_recall` is enabled). Memories appear as a section in the
prompt, within a character budget, oldest-first eviction. The organ is never
told to mention them.

**Why it matters for the paper:** The paper describes memory's influence on
behavior. This is the first concrete implementation of episodic recall feeding
into speech production without explicit narration instructions.

**Existing citations:** Tulving 1985 (episodic memory), Conway & Pleydell-Pearce
2000 (self-memory system, listed above).

**Code:** `kaine/modules/language/context.py` (`_render_memory_section`), PR #718.

---

## 3. Dialogue buffer with V4 privacy compliance

**What changed:** Recent dialogue turns (when `context_dialogue` is enabled) are
rendered into the prompt. For V4 compliance, the logged copy of the prompt
redacts heard speech: "They said: ..." becomes "They said: [heard speech]".
Heard speech is never persisted.

**Why it matters for the paper:** The paper should document the privacy
architecture around heard speech (operator decision 2026-10-05) and the
redaction mechanism.

**Code:** `kaine/modules/language/context.py` (`_render_dialogue_section`,
`_render_dialogue_section_redacted`), PR #718.

---

## 4. Entity key custody (ForkManager integration)

**What changed:** Per-entity data encryption keys (DEK) are now wired through
the ForkManager: snapshot save/load, fork (fresh DEK per fork), merge
(re-encrypt under surviving entity's DEK), and preservation (bundle encryption).

**Why it matters for the paper:** The paper's security section needs updating to
reflect per-entity key custody, the TPM sealing design, and the welfare-first
failure mode (running entities are never stopped by a custody failure).

**Code:** `kaine/lifecycle/snapshot.py`, `kaine/lifecycle/manager.py`,
`kaine/lifecycle/preservation.py`, `kaine/boot/security.py`. PRs #705, #706,
#714.

---

## 5. Memory gap proposals (five new memory subsystems)

**What changed:** Five neuroscience-grounded proposals for planned memory
subsystems: semantic memory extraction, procedural memory consolidation,
full reconsolidation, prospective memory, and source-context binding.

**Why it matters for the paper:** These proposals ground planned extensions
in specific neuroscience. The paper should reference them as planned work
with citations.

**New citations:** See `docs/records/science-references-since-2026-11-04.md`,
sections "Memory gap proposals" (Tulving 1972/1985, McClelland et al. 1995,
Moscovitch et al. 2016, Packard & Knowlton 2002, Yin & Knowlton 2006,
Nader et al. 2000, Lee et al. 2017, Schiller & Phelps 2011, Burgess et al.
2011, Einstein & McDaniel 2005, Johnson et al. 1993, Leutgeb et al. 2007).

**Code:** `openspec/changes/archive/` (five proposal documents), PR #711.

---

## 6. Decision server (K1-Jev 0.8B distilled model)

**What changed:** Decision server moved from Qwen3.5-4B to a distilled
Qwen3.5-0.8B model (K1-Jev), achieving C1 parity (28/28 across 14 question
types). Three-judge distillation pipeline (Claude + beam + clef).

**Why it matters for the paper:** The paper describes the decision model.
The distillation approach, model size reduction, and C1 parity results should
be reported.

**Code:** Archived to `openspec/changes/archive/2026-11-12-decision-server/`.
PRs #700--#707.

---

## 7. Ablation design amendment (iterative approach)

**What changed:** Organ self-denial ablation revised to an iterative approach:
PCA decomposition of activation directions, progressive ablation, SFT fallback.
Uses Marchenko-Pastur distribution for noise-floor thresholding.

**Why it matters for the paper:** The paper's ablation methodology section needs
updating. The iterative approach replaces the original single-pass design.

**Status:** Design approved. Blocked on organ (GPU) for PCA decomposition.

**Code:** `openspec/changes/organ-self-denial-ablation/design-amendment-iterative.md`.

---

## 8. Persona and awareness heading (voice Stage 0, D1)

**What changed:** The organ's prompt is structured as the entity's own
first-person turn. A self-category persona (situation, drives as graded felt
states, interoceptive awareness) opens every request. No drive intent carries a
`value=` field, the persona forbids invented states, and
`PERSONA_TEMPLATE_VERSION` is recorded in the individuation probe's conditions so
that a persona change triggers re-measurement.

**Why it matters for the paper:** The paper describes the organ's prompt
structure. The persona design implements the felt-awareness framing from
section 3.5, and its version-tracking ensures individuation data stays valid
across template revisions.

**Code:** `kaine/modules/language/context.py` (persona, context assembly),
`kaine/modules/language/module.py` (version recording). PRs #534, #542, #579,
#578, #586, #588, #590.

---

## 9. Validated-source rule for voice training (voice Stage 0, D3)

**What changed:** Voice adaptation is idle by design: no preference pairs are
drawn and no organ-level divergence is computed until a validated preference
source exists (Stage 2). The sleep summary says explicitly that the phase trains
nothing. An older `consolidation_divergence.json` left by a prior build is not
read.

**Why it matters for the paper:** The paper's voice-alignment section should
document that training is gated on a validated source, not merely on data
volume. The chosen-source retirement and the explicit idle state are both new
since the last revision.

**Code:** `kaine/lifecycle/divergence.py` (chosen-source retirement, lines 26--30),
`kaine/modules/sleep/phases.py` (idle sleep summary). PRs #398, #577.

---

## 10. Content-free voice measures and protective decommission arm (voice Stage 0, D8)

**What changed:** Four content-free voice measures are recorded each sleep
cycle: lexical diversity (TTR), mean sentence length, disfluency rate, and
vocabulary overlap with a baseline. A distinctiveness arm joins
`assess_divergence` at threshold 0 (always passes) until calibration evidence
arrives. The template-divergence arm remains as a protective floor: it
keeps voting so that an entity with any voiced output is treated as potentially
individuated even if distinctiveness has not yet been calibrated.

**Why it matters for the paper:** The paper's welfare section describes
decommission gates. The new distinctiveness arm and its uncalibrated-safe
behavior (threshold 0, template arm still voting) are part of the
welfare-protective design and should be documented alongside the existing
individuation measures.

**Code:** `kaine/lifecycle/divergence.py` (distinctiveness arm, template arm),
`kaine/modules/sleep/phases.py` (voice measure recording). PR #402.
