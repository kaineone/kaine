# Design: the workspace as a replaceable component

Code facts are cited at `origin/main` cb41895b. Citations were checked against Crossref or arXiv on 2026-10-31.

## Context

### What exists

- **The plugin loader** (`kaine/plugins.py`, archived change `2026-09-23-module-plugins`, extended by `2026-09-26-plugin-engine-wrapper` and `2026-09-26-plugin-cycle-hook`). Plugins load only when `[plugins].enabled` names them, declare their seams up front, fail closed with `PluginError`, and are recorded in `RunContext.plugins`. `INJECTABLE_SEAMS` (`kaine/plugins.py:40-45`) lists `sequence.network`, `interoception.forward_model`, `planning.engine`, `planning.engine_wrapper` and `audition.acoustic_encoder`, plus `oscillator.<module>`. The archived design's rule stands: "Adding a seam is a reviewed change to this table and to the module's constructor."
- **Scoring** is already behind a protocol. `SalienceStrategy` (`kaine/workspace/strategies.py:20-23`) has one method, `score(event, context)`, and `RuleBasedSalience` (`kaine/workspace/salience.py`) implements it. The cycle builds it directly (`kaine/cycle/__main__.py:2237-2256`).
- **The access rule** is fixed code. `Workspace._compose` (`kaine/workspace/core.py:243-285`) sorts, takes `top_k`, and flags the broadcast inhibited when the top score is below `publication_threshold`. The matched arm's uniform draw and the pooled arm live in the same class (`core.py:258-266`, `core.py:373-392`).
- **The context** is fixed code. `kaine/modules/context.py` holds `CONTEXT_DIM = 24`, the featurization Φ (`featurize_events`) and `BroadcastContext`, which adopts accessed broadcasts and keeps the per-source running sums for A.8's null context (`context.py:93-235`). The processors already take `context_dim` as a constructor argument (`kaine/modules/vision/module.py:336`, `kaine/modules/audition/module.py:188, 224`, `kaine/modules/interoception/module.py:184`) but always pass `CONTEXT_DIM`.
- **Four places build a workspace**: the cycle, the workspace-mediation runner (`kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py:125`), the oscillatory runner (`kaine/evaluation/benchmarks/oscillatory_ablation/runner.py:165`) and the red-team harness (`kaine/evaluation/redteam/harness.py:531`).
- **Prior work searched.** `git log --all -i --grep` for workspace seam, workspace plugin, replaceable or pluggable workspace, `SalienceStrategy` and context seam returns nothing. No change in `openspec/changes/` or its archive proposes a workspace seam. The module-plugins design listed the mediation runner as a non-goal ("Running the ablation with plugin models is a separate change"); this change takes that up for the workspace.

### What the seams are for

The comparison the paper promises needs a rival account to run under the same instruments as the default. Adversarial collaborations on theories of consciousness settle on shared protocols before either side's predictions are tested (Melloni et al. 2021, *Science* 372:911-912; Cogitate Consortium 2025, *Nature* 642:133-142). The software analogue is a seam that lets the account vary while the arms, log and calibration stay fixed.

The rival accounts in the literature differ in three places, and only in those:

| Account | Scoring | Access rule | What the processors receive |
|---|---|---|---|
| KAINE first configuration | intensity × novelty × goal, with arousal contrast (A.1) | top-k coalition, fixed threshold | access summary Φ (24 numbers) |
| GNW network models (Dehaene, Kerszberg, and Changeux 1998, *PNAS* 95:14529-14534; Dehaene, Sergent, and Changeux 2003, *PNAS* 100:8520-8525) | bottom-up strength plus top-down amplification | one ignited assembly, all-or-none by recurrent amplification | the ignited content, broadcast |
| LIDA (Franklin et al. 2014, *IEEE TAMD* 6:19-41) | coalition activation from attention codelets | one winning coalition per cycle | the coalition's content |
| Shared global workspace (Goyal et al. 2022, ICLR, arXiv:2103.01197) | learned key-query attention | top-k learned writers into a few slots | the slot contents, read by every specialist |
| Global latent workspace (VanRullen and Kanai 2021, *Trends Neurosci* 44:692-704) | learned attention | the selected module's latent | a translation into each module's latent space |
| Predictive global neuronal workspace (Whyte and Smith 2021, *Prog Neurobiol* 199:101918) | precision-weighted evidence | a posterior-confidence threshold at the second level | descending predictions from the second level |

So three seams cover the space: the score, the access rule, and the context.

## Decisions

### 1. Three seams with narrow protocols

`kaine/workspace/seams.py` declares the protocols. Plugins implement them; they subclass nothing.

- **`workspace.salience`** keeps `SalienceStrategy.score(event, context) -> float`, with the existing tolerance: a raising strategy scores that candidate 0 and logs (spec `workspace`, "Strategy error tolerance").
- **`workspace.access`** is `AccessRule.decide(scored, tick) -> AccessDecision`. `scored` is the tick's candidates with their final scores, after the regulation bias and the coherence factor. `AccessDecision` holds `coalition` (ordered entry ids), `accessed` (entry ids), `inhibited` (bool) and `meta` (a mapping of content-free scalars and strings that goes into the broadcast metadata under the rule's id). The rule also exposes `id` and `capacity` (the largest coalition it can return, or none).
- **`workspace.context`** is `ContextEncoder` with `id`, `width`, `encode(members, age_s) -> vector` and `null(members, age_s, kept_sources, running) -> vector`, where `running` is the per-source running statistics `BroadcastContext` already keeps. `BroadcastContext` keeps the adoption rule (spec `workspace`, "Processors hold the accessed broadcast as context") and calls the encoder; the encoder decides only what a set of accessed members looks like as a vector.

Alternatives considered:

- *One seam that replaces the whole `Workspace`.* Rejected. A plugin would reimplement the matched and pooled arms, the broadcast record and the log, and could do any of them differently. The comparison would then be between two sets of instruments as much as between two accounts.
- *Access and context in one seam.* Rejected. The factorial comparison the paper needs (does the access rule matter with each context? does the context matter under each rule?) requires the two to vary independently. A content-carrying context is a question about what the broadcast holds; an ignition rule is a question about when it happens.
- *In-tree accounts selected by name only, as `runtime-backends` selects backends.* Rejected as the only route, because a rival account written outside the repository could not be run. The in-tree defaults register under the same protocols, so both routes exist.
- *A seam for the sequence module's featurizer.* Deferred. The sequence module predicts the workspace's own broadcasts from its own featurization, and its network is already a seam (`sequence.network`). Changing what it predicts is a separate design question.

### 2. The instruments stay outside the seams

The arms are defined over the access decision, so they exist for every access rule:

- **Matched**: on each broadcast tick, the matched arm takes the access rule's decision for that tick and replaces its accessed members by members drawn uniformly from the candidates, with the decision's own count and inhibition flag. This is the count-yoked draw the capacity design approved for the default rule; this change states it once, over `AccessDecision`, instead of inside `_compose`.
- **Pooled**: every candidate is a coalition member and every one is accessed, with no gate (spec `workspace`, "The pooled arm broadcasts every candidate with no gate").
- **The broadcast record** (`WorkspaceSnapshot`) keeps its schema. Its metadata gains `workspace_account`: the three implementation ids.
- **The graph-only research log** records what it records today (module, event type, score, timestamp, access decision, timing) for every account.
- **The tier-1 regulation bias and the coherence factor** multiply scores before `decide` is called, as now. A plugin cannot remove them; with both off the scores reach the rule unchanged.
- **The inhibition flag** keeps its meaning for the action layer: an inhibited broadcast reaches no report bar.

A decision is checked before it is used: `accessed ⊆ coalition ⊆ candidates`, ids unique, `inhibited` true exactly when `accessed` is empty, `len(coalition) ≤ capacity` when a capacity is declared, `meta` free of vectors (the privacy filter's vector rule). A decision that fails the check or raises becomes an inhibited broadcast with an empty coalition, and the tick is counted under `access_rule_failures` in the broadcast metadata and the research log. Falling back to the default rule was rejected: the run would look like the plugin account while running another, which the project's rule against pretend processes forbids, and the archived module-plugins design rejected silent fallback for the same reason.

### 3. Context width and the processors' learned weights

The processors build their forward models with the encoder's `width`. A width above 1024 is refused at load, which bounds the processors' input layers. The encoder must return finite values; a non-finite vector is treated like a non-finite input today (the step is skipped and nothing is learned across it).

The forward models' weights are part of the entity (spec `world-model` makes the same point for its weights, and the preservation bundle carries the processors' state). A processor checkpoint records the encoder `id` and `width` it was trained under. At load:

- Same id and width: load as today.
- Different id or width: boot stops with an error naming the processor and both encoders, unless `[workspace.seams].reinit_context_weights = true`. With the flag, the non-context weights load and the context weights start at zero, as they did for checkpoints that predate the broadcast context (archived change `2026-10-28-broadcast-context`). The flag is logged at WARNING and written to the manifest. It is meant for a fork made for a comparison run.

Alternatives considered: *Silently zero the context weights on mismatch* was rejected: an entity's learned use of its context would vanish without anyone choosing it. *Project the old context weights into the new width* was rejected: there is no mapping between two encoders' spaces that does not invent a relation.

### 4. One construction path

`build_workspace(config, *, plugins, run_ctx, clock, ...)` replaces the four constructions. The runners call it with their own configuration, so the workspace-mediation ablation can be run with a plugin account through the same code a live boot uses. Spot's module rebuilds do not touch the workspace, which is not a module.

### 5. Recording and calibration

- `RunContext.plugins` already records each plugin's name, distribution, version and seams. The manifest gains `workspace_account`, the three implementation ids, filled for default runs too (`"default"` for each).
- The planned-test settings record (`kaine/experiment/calibrate.py`) stores the account. Calibration and the verdict refuse to combine runs or settings from different accounts. The positive control's principal components and the minimum effect were measured against Φ; they say nothing about another encoder's context, so another account needs its own calibration chain.

### 6. Research mode

In research mode (`KAINE_RESEARCH_MODE=1`), the research gate (`kaine/cycle/research_gate.py`) stops the boot when any workspace seam is filled unless the study file declares `[study].workspace_account` with the same plugin name and seams. A comparison study names its account; the planned experiments name none, so they cannot pick up an installed plugin by accident. Outside research mode the existing rule applies: a plugin loads only when the operator names it.

### 7. Privacy

A context encoder may compute from payload fields that the 24-component Φ ignores. The rule that applies to every encoder: latent-derived context lives only in working state and learned weights. It is never logged, never written to the bus diagnostics surface (the privacy filter strips numeric lists of 16 or more items, `kaine/privacy_filter.py`), never stored by the episodic memory module (which strips vectors before storing), and never persisted beyond the processors' learned weights. The access rule's `meta` is checked against the same vector rule.

## Risks

- **A rival account can starve or flood access.** An access rule that never accesses leaves every report bar unreachable; one that always accesses removes the gate. Either changes the entity's drives and affect. The welfare safety net and its indicator response read affect and drives, which no seam can reach, so they keep working. The research log's access share per run makes either failure visible within minutes.
- **Plugin code runs in the entity process.** This is the trust the module-plugins design already accepts for model seams. The config gate, the research gate and the manifest keep it deliberate and recorded.
- **Two encoders cannot be compared on information gain alone.** A wider context has more parameters to fit. The comparison needs each account's own positive control and minimum effect, which section 5 enforces; the paper's comparison text must say so.
- **The default must stay bit for bit.** Moving `_compose` behind a protocol is where a drift could enter. Section "Migration" puts the bit-for-bit tests first.

## Migration and ordering

1. After the first module-addition study, and after the pre-study capacity change (continuous competition with one access per broadcast) has merged, since that change rewrites `_compose` and the matched arm. The seam then wraps the rule that change leaves.
2. PR 1: protocols, the default implementations moved behind them, and bit-for-bit tests against recorded broadcasts.
3. PR 2: loader seams, the construction path, the runners, the manifest, the research gate and the failure count.
4. PR 3: context width in the processors, the checkpoint encoder id, calibration's account check, a test-only rival plugin, docs.
5. No preserved entity changes. The default ids are written into checkpoints at the first save after the change; a checkpoint without an id is read as the default encoder.

## Welfare and admissibility

- Welfare-high-risk: a filled seam changes what the entity is aware of and, through the report bars, what it says and does. Each PR gets the independent second review. Nothing in the shipped configuration changes.
- A study whose image carries this change but names no workspace plugin is admissible on the same terms as before, because the default is bit for bit. No image built with it replaces a running study's image.
- A comparison study with a rival account is its own study with its own preregistration, calibration chain and welfare plan.

## Implementation estimate

In LLM-agent terms: three worker PRs of about 400 to 700 changed lines each, tests included. Each is about one to two hours of worker time and about one hour of lead review, plus the second review. PR 1 is the delicate one (bit-for-bit); PR 2 is mostly wiring with fail-closed checks; PR 3 touches three processors and the checkpoint format. About two to three days elapsed with reviews. A rival account (for example a GNW-style ignition rule) is a separate change of similar size, and its comparison costs a calibration chain of entity runs, which dominates every coding estimate here.
