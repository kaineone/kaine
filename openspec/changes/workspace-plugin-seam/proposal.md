## Why

The paper's first contribution is a platform on which competing accounts can be compared "under the same instruments" (§1.4, §3.1, §5.2). The revised paper now says what is true of the code: the models inside four modules can be swapped at declared plugin seams, and "the workspace itself is one fixed implementation, and swapping it or a whole module currently requires code changes" (§1.4). The audit of 2026-10-31 confirmed it (TRIAGE M03, K4; the GLW comparison report's finding F4): `INJECTABLE_SEAMS` in `kaine/plugins.py:40-45` names `sequence`, `interoception`, `planning` and `audition` and nothing in the workspace. Selection, the access rule and the context the processors read are fixed code in `kaine/workspace/core.py`, `kaine/workspace/salience.py` and `kaine/modules/context.py`.

The workspace is the part of the architecture whose rival accounts the field argues about: a fixed top-k coalition with a threshold (the first configuration), one ignited content at a time (Dehaene, Kerszberg, and Changeux 1998; Dehaene, Sergent, and Changeux 2003), a single winning coalition per cycle (LIDA, Franklin et al. 2014), learned specialists writing into a limited shared workspace (Goyal et al. 2022), or a context that carries what was accessed (VanRullen and Kanai 2021; Whyte and Smith 2021). None of these can be run on KAINE without editing the workspace, and an edited workspace no longer shares the instruments of the unedited one. This change makes the workspace's three replaceable parts declared seams, so a rival account can be loaded as a plugin and compared with the default under the same arms, log and calibration.

The change does not build any rival account and does not presume one. Whether KAINE builds a content-bearing workspace level is an open operator decision; the seam neither requires nor anticipates it.

Design only. Nothing is built until the first module-addition study has finished. The shipped default stays bit for bit the current workspace, so later studies are unaffected unless a study file names a workspace plugin.

## What Changes

- Three workspace seams join the plugin loader's declared seams:
  - `workspace.salience`: the per-candidate score (the existing `SalienceStrategy` protocol).
  - `workspace.access`: the access rule. From the scored candidates of one broadcast tick it returns an access decision: the ordered coalition, the accessed members, and whether the broadcast is inhibited.
  - `workspace.context`: the context encoder. From the accessed members and their age it returns the processors' context vector of a declared width, and it returns the null context the information-gain measure needs (A.8).
- The current code becomes the default implementation of each seam with no change in behaviour: `RuleBasedSalience`, the coalition-and-threshold rule of A.1 (in the form the pre-study capacity change leaves it), and the 24-component featurization Φ of A.1 with A.8's null construction.
- The instruments stay outside the seams, so every account shares them: the candidate pool and tick loop, the matched and pooled control arms (rebuilt around the access decision, so they are defined for any access rule), the tier-1 regulation bias and the coherence factor (applied to scores before the access rule), the broadcast record, the graph-only research log and the inhibition flag the action layer reads.
- One construction function builds the workspace for the cycle, the workspace-mediation runner, the oscillatory runner and the red-team harness, so an ablation can run a plugin account through the same path as a live boot.
- The processors size their context weights from the encoder's declared width and record the encoder's id with their checkpoints. A checkpoint trained under another encoder is refused unless the operator sets a one-boot flag to start the context weights from zero.
- Every run manifest and every planned-test settings record names the workspace account (the plugin and the id of each seam's implementation). Calibration refuses a settings record from another account.
- In research mode a filled workspace seam stops the boot unless the study file names the same plugin and seams. The planned experiments name none.
- An access decision that is malformed or raises makes that tick's broadcast inhibited, and the share of such ticks is recorded; the run-admissibility scan marks a run whose share exceeds a preset bound.

## Capabilities

### Modified Capabilities

- `module-plugins`: three workspace seams are declared; the seam list in the spec is brought up to the code (it omits `planning.engine_wrapper` and `audition.acoustic_encoder`).
- `workspace`: the workspace delegates scoring, the access rule and the context to its seams; the control arms are defined over the access decision; a failed access decision inhibits the broadcast and is counted.
- `planned-test-calibration`: settings records carry the workspace account and are refused for another one.
- `run-admissibility`: the scan reports the share of failed access decisions and bounds it.

## Impact

- Code: `kaine/workspace/core.py`, `kaine/workspace/strategies.py`, new `kaine/workspace/seams.py` (protocols and defaults), `kaine/modules/context.py` (the default encoder behind a protocol), `kaine/plugins.py`, `kaine/boot/` (construction path), `kaine/cycle/__main__.py`, the vision, audition and interoception modules and their factories (context width), `kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py`, `kaine/evaluation/benchmarks/oscillatory_ablation/runner.py`, `kaine/evaluation/redteam/harness.py`, `kaine/experiment/calibrate.py`, `kaine/experiment/run_context.py`, `kaine/cycle/research_gate.py`, the run-admissibility scan.
- Config: a `[workspace.seams]` table with `reinit_context_weights = false`; study files may name a workspace account.
- Behaviour: none with the shipped configuration.
- Welfare: a rival account changes what reaches access, and so what the entity experiences. Every PR of this change gets the independent second review.
- Paper: §1.4 contribution 1, §3.1 ("Replaceable modules"), §5.2 (the seam list), §8.3, A.1 (Φ as the default encoder) and Table A1.
