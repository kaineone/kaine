# Design: a content code for the workspace (option F)

Code facts are cited at `origin/main` cb41895b and were rechecked there on 2026-10-31 after the adversarial review of this change (C1 to C17). Citations were checked against Crossref on 2026-10-31.

## Context

### The decision this design implements

The operator's outcome of 2026-10-31 (decision brief, "Outcome") governs:

- The workspace will carry content, built as option F of the comparison report: "a content-bearing second level trained by the processors' own prediction errors, delivering descending predictions through the already-designed workspace-feedback head." The Global Latent Workspace as published is rejected, cycle-consistency is kept only as a comparison arm and as the route for language, and an LLM as the workspace is rejected.
- Measurement discipline: an off switch bit-identical to absent, a plain readout of whether the component did its job, and the graph-only log. The 30-pilot calibration chain, a preregistered minimum effect and a three-arm ablation do not gate the build.
- Welfare is unchanged: an independent second review, a two-layer operator opt-in, and the identity rules for learned weights.
- The module-ignition study converts into the development run. One entity is grown continuously, and each architecture component joins it behind a switch with a readout.
- Not built: any pretrained cross-modal encoder (CLIP, SigLIP, ImageBind). Decision 13 and open question 1 deal with the one place the shipped vision input touches this.

### What exists

- **The feedback head** (change `workspace-feedback`, built and held off; `kaine/modules/feedback.py`). Vision, audition's acoustic path and interoception each have a `TopDownHead`: a linear map from `(b, s, 1)`, the 24-number context, the sequence module's 24-number predicted next featurization and a constant (input width `CONTEXT_DIM + SEQUENCE_PREDICTION_DIM + 1 = 49`), to a prediction of the processor's next input. It starts at zero and takes one SGD step per scored input on the mean squared error (`adapt`, `:109-123`, gradient `(2/n) · err xᵀ`, non-finite steps skipped), skipped while suspended. `TopDownBlend` mixes the own and top-down predictions with weights proportional to the inverse squared running mean L2 errors over a window of `W_P` (`blend_weights`, `:24-39`; `_own_errors` and `_top_errors` hold L2 errors). The reported error, ratio and intensity are the blend's (`step` returns the blended error). The blend records the own-model error as `last_own_error`, and the processors publish it as `workspace_feedback.own_error`. The processors adopt feedback only from accessed broadcasts (`FeedbackChannel.observe`). Feedback refuses to run with the coherence layer or a non-competitive arm (`kaine/workspace/core.py:76-79`). Task 3.2 of `workspace-feedback` (preserve the heads) is open, and that change has not been archived, so `workspace-feedback` has no base spec in `openspec/specs/`.
- **The processors' inputs.** Vision's forward model predicts the next clip latent, the 768-number InternVideo-Next embedding it publishes as `latent` (`kaine/modules/vision/module.py:642,751`). With the shipped `pooling = "attention"` (`config/kaine.toml:535`) that latent is the model's native attention-pooled, CLIP-aligned global vector (`kaine/modules/vision/encoder.py:268-271`), deliberately not L2-normalised (`:274`). Audition's acoustic forward model predicts the next acoustic embedding (64 numbers with the spectral encoder, which is L2-normalised, `kaine/modules/audition/acoustic.py:136,186-188`; 768 with Dasheng), which `audition.perception` does not publish (`kaine/modules/audition/module.py:461-495`). Interoception predicts an 8-number host feature vector (`DEFAULT_FEATURE_DIM = 8`).
- **The candidate pool.** The cycle reads every new entry of every active stream each tick and the workspace scores that tick's events (`kaine/cycle/engine.py:565-594`), so the workspace sees every processor report, including reports that are not selected. Novelty is a fingerprint of the whole payload (`kaine/workspace/novelty.py:13-20`), and salience is `intensity × novelty × goal` (`kaine/workspace/salience.py:52,107`).
- **The A.8 information-gain measure.** Each processor evaluates its prediction with the null context `b0` and reports `context_gain = (e_null − e) / mean_e` (`kaine/modules/vision/module.py:682`). Decision 8 builds the content readout the same way.
- **The welfare signal.** The welfare observer and `[preservation.welfare_response]` read `interoception.report` `prediction_error` (`config/kaine.toml:1908-1911`; `kaine/evaluation/observers/welfare_observer.py:679-683, 917`; `kaine/cycle/preservation_monitor.py:972`). With feedback on, that field is the blended error (`kaine/modules/interoception/module.py:595-607`). The separate change `welfare-signal-unblended` moves every welfare reader onto the processor's own forward-model error; this change requires it (decision 11).
- **Fork, merge and snapshots.** `ForkManager.snapshot` and `restore` iterate `registry.all_modules()` only (`kaine/lifecycle/manager.py:201-266`); module artifact hooks run after the module states are captured and, on restore, after every module's `deserialize`. Nothing in `kaine/` has a snapshot-participant concept. `ForkManager.merge` refuses an unchosen world model (`world_model_from`, `:361-388`). Vision, audition, interoception and sequence have no merge strategy (`kaine/lifecycle/strategies.py:429-437`), so they fall to `UnionMergeStrategy`, which concatenates lists (`:71-105`); the separate change `fork-merge-module-weights` fixes that for every weight-bearing module state, and this change depends on it. The dashboard process builds its own `ForkManager` (`kaine/dashboard/__main__.py:182`), so a merge there has no live workspace.
- **The positive control's shadows** (`kaine/modules/positive_control.py`) show the pattern for measurement-only models with no path into live error, intensity or access. Decision 9 reuses it.
- **The workspace-mediation runner** (`kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py`) drives only vision and interoception, on a synthetic `VectorEncoder` stimulus with a `StaticAffectModulator` (`:4-22, 129, 193`). It is not a harness for real audition, sequence and affect over films (decision 11).
- **The stimulus.** The offline decodability check (`kaine-research`, decodability report of 2026-10-31) found time-locked cross-modal structure on the programme films at a 1 to 5 s scale, weak (per-dimension correlation 0.114 at lag 0, 0.074 at ±5 s, 0.030 at ±30 s), and two feed defects that erase lag-0 sync on two of the four films as an entity would perceive them: the video source maps time to frames with the nominal frame rate (`kaine/modules/vision/feed.py:1122`, `int(offset * float(item.fps))`) on variable-frame-rate files, and the playlist audio is padded (`kaine/modules/audition/feed.py:1000`, `bytes(rframe.planes[0])`).
- **Related designs, not redone here.** `latent-content-privacy` (the rule every value here follows, and its two open questions on the bus and on episodes). `workspace-plugin-seam` (design only) makes the context `b` a plugin seam. The content code does not replace `b`: the processors keep the access summary as context, and A.8's measure is unchanged. So it is not a context plugin, and the two changes do not depend on each other. `working-memory-store` (design only) keeps recent accessed members for report and recall. The slots here hold at most one latent per source for a few seconds, as the code's input, and are not working memory.

### The neuroscience

- **Content is held and broadcast by the workspace, and its predictions descend.** In the global neuronal workspace, accessed content is held in sustained, broadcast activity of long-range workspace neurons (Dehaene, Kerszberg and Changeux 1998, *PNAS* 95:14529-14534; Dehaene and Changeux 2011, *Neuron* 70:200-227). In its Bayesian reading the workspace holds a compressed model whose top-down signals broadcast predictions to lower areas, which measure the mismatch and update the model (Mashour, Roelfsema, Changeux and Dehaene 2020, *Neuron* 105:776-798). In the predictive global neuronal workspace a content-bearing second level supplies the first level's priors (Whyte and Smith 2021, *Prog Neurobiol* 199:101918).
- **Predictions descend and errors ascend.** In hierarchical predictive coding, feedback connections carry predictions of lower-level activity and feedforward connections carry the residual errors, from which the higher level's model learns (Rao and Ballard 1999, *Nat Neurosci* 2:79-87; Friston 2005, *Phil Trans R Soc B* 360:815-836). The heads are the descending predictions. The ascending error of decision 5 is the residual projected into the code, which is what the higher level learns from.
- **A shared code with modality-specific routes.** Convergence zones bind modality-specific representations through shared higher-order codes (Damasio 1989, *Cognition* 33:25-62). The hub-and-spoke account of semantic memory has a transmodal hub reached through modality-specific spokes (Lambon Ralph, Jefferies, Patterson and Rogers 2017, *Nat Rev Neurosci* 18:42-55). Single neurons in the human medial temporal lobe respond to one person's picture, written name and spoken name (Quian Quiroga, Kraskov, Koch and Fried 2009, *Curr Biol* 19:1308-1313). The per-source encoders are the spokes and `z_k` is the hub.
- **Other senses shape processing in "sensory-specific" areas.** Cross-modal influences reach early areas of each modality (Ghazanfar and Schroeder 2006, *Trends Cogn Sci* 10:278-285; Driver and Noesselt 2008, *Neuron* 57:11-23). Seeing a speaker's lips speeds the cortical processing of the speech sound, and the effect scales with how well the visual signal predicts the sound (van Wassenhove, Grant and Poeppel 2005, *PNAS* 102:1181-1186). A descending prediction of the audition processor's input made partly from vision is that kind of influence.
- **Cues are combined by their reliability, and attention weights by precision.** Human observers weight visual and haptic estimates by inverse variance (Ernst and Banks 2002, *Nature* 415:429-433), and the ventriloquist effect follows the same rule, reversing when the visual cue is degraded (Alais and Burr 2004, *Curr Biol* 14:257-262). That rule belongs to the blend: the inverse-squared-error weighting already in the head gives a degraded prediction little weight, which is also why a dropped or degraded modality should lose influence rather than add error (decision 8). The code's weights `α_s` are a different thing. Intensity is gain times normalised error, so `α_s` weights the code toward the sense that was less well predicted and won access, the opposite of reliability weighting. Its reading is attention as precision-weighted prediction error, which sets what enters the higher level (Feldman and Friston 2010, *Front Hum Neurosci* 4:215).
- **Cross-modal integration is learned from experience.** Superior colliculus neurons in dark-reared cats do not integrate visual and auditory input (Wallace, Perrault, Hairston and Stein 2004, *J Neurosci* 24:9580-9584). Animals reared with temporally coupled but spatially disparate stimuli learn to integrate those pairings (Wallace and Stein 2007, *J Neurophysiol* 97:921-926). So the mapping between the senses is learned from co-occurrence, not innate. The structure here (a shared code, routes from each sense) follows the anatomy above, and every weight is learned from the entity's own experience.
- **Learning follows what is attended.** Early perceptual learning depends on attention to the trained feature (Ahissar and Hochstein 1993, *PNAS* 90:5718-5722). Task-irrelevant learning also occurs when exposure is paired with reinforcement (Seitz and Watanabe 2005, *Trends Cogn Sci* 9:329-334), so the restriction to accessed broadcasts is a design choice consistent with the first finding. It is not a claim that unattended input never shapes learning.
- **The comparison arm.** The Global Latent Workspace trains its shared space by translation and cycle-consistency between modules (VanRullen and Kanai 2021, *Trends Neurosci* 44:692-704). Its one empirical study shows the benefit in data efficiency when paired data are scarce (Devillers, Maytié and VanRullen 2024, arXiv 2306.15711, as verified by the comparison report). KAINE's audio and video always arrive paired, which is why the objective here is prediction, and translation is a shadow for comparison.
- **Persistence of accessed content over seconds.** Accessed content is held in sustained workspace activity for a limited time (Dehaene and Changeux 2011), and the decodability check found the films' cross-modal structure on a 1 to 5 s scale. The slot decay `τ_z` of a few seconds follows both, and is cited at the code site. Clearing the slots at sleep onset follows the breakdown of long-range cortical effective connectivity in slow-wave sleep (Massimini, Ferrarelli, Huber, Esser, Singh and Tononi 2005, *Science* 309:2228-2232), so accessed waking content is not held across sleep; it is also cited there, under the emergent-not-hardwired rule. This citation is new in this revision and is checked against Crossref with the code-site citations (task 2.1).

## Decisions

### 1. An extension of the feedback head, configured under its table

The content code is part of `workspace-feedback`. It needs feedback enabled with any arm except `off` (`head_only`, `head_gain`, `full` or `matched_random`), and it inherits feedback's refusals (coherence layer, non-competitive arm, positive control). Its table:

| Key | Meaning | Default |
| --- | --- | --- |
| `enabled` | the content code is built | `false` |
| `code_dim` | numbers in `z_k` | 64 |
| `sources` | processors whose latents write into the code | `["vision", "audition"]` |
| `slot_decay_s` | slot age decay, entity seconds (`τ_z`) | 2.0 |
| `encoder_learning_rate` | encoder SGD rate (`η_E`) | 0.001 |
| `encoder_max_norm` | maximum L2 norm of one row of an encoder | 3.0 |
| `ascending_clip` | maximum L2 norm of one ascending error | 1.0 |
| `standardise_warmup` | inputs per source before the standardiser slows | 2000 |
| `standardise_rate` | standardiser update rate after warm-up | 0.0001 |
| `pending_codes` | accessed codes held for credit assignment | 32 |
| `null_code_window` | codes in the running mean used as the null code | 256 |
| `shift_s` | age, in entity seconds, of the code used for the shifted control; at least 60 | 60.0 |
| `comparison` | `"none"` or `"translation_shadow"` | `"none"` |
| `breaker_window_s` | window of the harm breaker, awake unsuspended entity seconds | 600 |
| `breaker_gain_floor` | median `content_gain` below which the breaker latches | -0.05 |
| `reset_sources` | one-boot list of sources whose encoder starts fresh | `[]` |
| `resume_after_breaker` | one-boot flag that clears a latched breaker | `false` |

An unknown key or value is a configuration error, and so is `shift_s` below 60. `sources` may also name `interoception`. Affect and the sequence module cannot be sources: affect is downstream of the workspace and the sequence module's input is the broadcast, so either would feed the code back into itself.

Interoception is not a default source. Its features describe host load, which the entity's own processing drives (the organ's GPU load follows what it is processing), so pairing it with the film's latents would mostly teach the code its own computational footprint (adversarial review §2.4). It still receives the descending prediction as a decoder, and the precision blend gives that prediction little weight if it does not help. Because interoception's error is also the welfare signal, decision 11 requires the welfare readers to read the own-model error, not the blend.

Alternative considered: *a new workspace module or a context plugin.* Rejected. A module would compete for access, and the code must not be a candidate (decision 7). A context plugin would replace `b`, so the A.8 measure of the access summary would be lost and the content readout would have nothing to be measured against.

### 2. Sources, slots and the code

**Slots.** Each source `s` has one slot: its most recently accessed latent `x_s`, the graded intensity `I_s ∈ [0, 1]` the member carried when it was accessed (the clamped salience the workspace scored, `salience.py:97`), and the entity time `t_s` of that broadcast. A slot is written only when that source's report is an accessed member of a broadcast. When several reports of a source are accessed at once, the one with the highest score is written. A slot is cleared when its age passes `5 τ_z`, when the source's blind-sensor or sensor-silent advisory is raised, and at sleep onset.

**Standardisation.** Each source's latent is standardised before its encoder: `x̃_s = (x_s − μ_s) / σ_s` per dimension, with running mean and variance updated on every slot write, at rate `1/n` for the first `standardise_warmup` inputs and at `standardise_rate` after that. The sources' scales differ on purpose: the vision latent is not L2-normalised (`vision/encoder.py:274`) and the spectral acoustic embedding is (`audition/acoustic.py:136`). With the encoder initialisation below, an unstandardised vision term could saturate tanh while the audio term sat near 0.1, and one source would dominate whatever `α` said. `μ_s` and `σ_s` are per-dimension statistics of latents updated by a learning rule and read back on restore, so they are learned parameters under the identity rules (`latent-content-privacy` decision 3) and live in the checkpoint (decision 10). The share of saturated components is checked at switch-on (decision 11).

**The code.** On each accessed broadcast, after the slots are written:

    α_s = I_s · exp(−(t − t_s) / τ_z)
    z_k = tanh( Σ_present α_s (W_s x̃_s + c_s) )

There is no normalisation across slots. The first version divided each intensity by the summed intensity of the present slots before the decay, so the code jumped whenever a slot arrived or expired: with vision fresh at `I = 0.5` and audition 9.9 s old at `I = 0.5`, `α_v = 0.5` and `α_a ≈ 0.004`, and when the audio slot cleared at 10 s `α_v` doubled to 1.0, bias included. At K = 1 a slot arrives on most accessed broadcasts. Without the normalisation each source's term depends only on its own slot: it changes when its own slot is written (new content) and decays smoothly, and an expiring slot removes a term whose weight is at most `e^{−5} ≈ 0.007` of its fresh weight. Intensity is already bounded to `[0, 1]`, so the pre-activation stays bounded by the number of sources. Normalising after the decay with a floor was the other fix the review offered; it still lets one source's arrival rescale every other term, which at K = 1 is most broadcasts.

With no slot present, `z_k` is the zero vector. `z_k` is held unchanged until the next accessed broadcast. An inhibited broadcast neither writes a slot nor forms a code, and the processors adopt nothing from it, as for the context.

**Why slots.** With the coalition capacity under review (continuous competition with K = 1 is to be revisited as an architecture choice in build order item 5), one broadcast may hold one member. If the code were formed from the current broadcast's members alone, it would hold vision or audition and never both, and cross-modal content could never meet in it. A slot per source with a short decay lets the code hold the last accessed content of each sense for a few seconds, as the workspace holds accessed content in sustained activity (Dehaene and Changeux 2011), at any coalition size. `τ_z` = 2 s covers several access intervals of each source at the resting access rate (vision reports at about 3.3 Hz and audition at about 2 Hz compete for about 3.3 accesses a second). At K = 5 the slots need nothing extra.

**Encoders.** `W_s` is `code_dim × dim(x_s)`, initialised from a generator seeded by the entity's identity and the source name with standard deviation `1/√dim(x_s)`; with standardised inputs each term's pre-activation then has a variance near one, so the code starts unsaturated. `c_s` starts at zero. About 49,000 parameters for vision and 4,000 to 49,000 for audition, depending on its encoder.

**Audition's latent.** With the content code on and `audition` in `sources`, `audition.perception` carries the acoustic embedding the forward model consumes, inside its `latent_derived` mapping as `latent_derived.acoustic` (a perceptual latent inside the tag is still stripped on every surface, and one excluded key keeps it out of the novelty fingerprint, decision 7). Under `latent-content-privacy`'s bus ruling (open question 1, option B) it travels on the report's volatile companion entry, not on `audition.out` (decision 6).

Alternatives considered:

- *A recurrent code* (`z_k` updated from `z_{k−1}` by a learned recurrent map). Deferred. It would hold sequences, as the second level of Whyte and Smith does, but it adds a learned memory whose dynamics need their own welfare check. It is a candidate after the readout shows the plain code does its job.
- *MLP encoders.* Deferred. A linear encoder with linear heads is a reduced-rank cross-modal regression, which is what the offline decodability check measures (ridge and CCA), so the check bounds what this code can achieve. A nonlinear encoder is a later option if the readout shows the linear code saturates.
- *The slot-presence mask as extra regressor inputs to the heads.* Considered, not adopted: presence already shows in `z_k` (an absent slot contributes nothing) and in `code_sources`, and the mask adds columns that would need their own continuity rule. Revisited if the dropped-modality readout shows the heads cannot tell a missing sense from a quiet one.
- *Encoders over every accessed member including affect and the sequence module.* Rejected for the loop reasons in decision 1.

### 3. The heads are the decoders

With the content code on, each processor's `TopDownHead` regressor becomes `(b, s, z, 1)`. Its weights for `b`, `s` and the constant are unchanged in meaning; call that the base block. Its `code_dim` code columns, the code block, start at zero for a processor that has never had a code. The processor adopts `z` from the latest accessed broadcast (decision 6 says where it travels) and uses the zero vector before the first.

- **Continuity at switch-on.** A head restored without a code block (a trained base block from a code-off life) is widened by appending zero code columns; only a context-width or input-dimension mismatch discards a head (decision 4). With zero code columns the first descending prediction after the code is enabled equals the base head's prediction. The code's influence grows only as the heads learn that it predicts the input.
- **Off and on again.** With the code off no head has code columns, so module state while off is identical to absent. The code blocks are not lost: they live in the content-code checkpoint with the encoders (decision 10), are removed from the heads at switch-off, and are spliced back at switch-on. A code that is turned off and on again resumes with the same code blocks and encoders.
- **Training.** The head keeps its single SGD step on its own mean squared error, now over all columns. That is the decoder trained by the processor's own prediction error.
- **The blend is unchanged.** The processor predicts with the blend of its own and the top-down prediction, weighted by inverse squared running mean errors.

**What the blend can cost.** Under steady errors, the blend's error is at most `w e_own + (1 − w) e_top`, by the triangle inequality, with `w = e_top² / (e_own² + e_top²)`. With `r = e_top / e_own` that bound is `e_own · r(1 + r) / (1 + r²)`, whose maximum over `r` is `(1 + √2)/2 ≈ 1.21`, at `r = 1 + √2`. Three limits on what this says:

- It is tight only when the two residuals point the same way. With uncorrelated residuals the blend is no worse than the better of the two predictors.
- It is relative to the processor's own model alone, not to the code-less head.
- It bounds the mean error, not the tail that sets alerts.

The error ratio that sets intensity divides by the running mean of the same blended error, so a steady change of scale does not move the ratio. The real exposure is in transients (switch-on, slot arrival and expiry, scene cuts), which the welfare check of decision 11 measures.

Alternative considered: *decoders in the workspace, with the descending predictions on the broadcast.* Rejected. Each processor would receive a full-size prediction (768 numbers for vision) on every accessed broadcast. The workspace would compute errors against the published latents rather than against what each processor actually predicts. And it would bypass the head the paper and `workspace-feedback` already specify.

### 4. Heads persist in every arm

This change carries `workspace-feedback` task 3.2, which is marked there as moved here. Each processor serializes its head's base block and its running error windows with its forward model, and restores them, in every feedback arm. The code block is not module state (decision 3). The gains are not persisted: they relax to one within tens of seconds (`gain_relax_s`). A head restored under a different context width or input dimension is refused with a warning naming the mismatch, and starts at zero. A head restored under a different code width is widened or narrowed by the rule of decision 3, never discarded for that reason.

The base block is weight-bearing module state, so `fork-merge-module-weights` declares it, and a merge takes it from the chosen parent instead of concatenating it.

### 5. Ascending errors train the encoders

After scoring, a processor that used a code computes the gradient of its normalised head error with respect to that code:

    L_j = mean((ŷ_top − y)²) / m_j
    g_j = ∂L_j / ∂z = (2 / (n_j m_j)) · W_{j,z}ᵀ (ŷ_top − y)

Pinned definitions:

- `m_j` is the running mean, over the last `W_P` scored inputs, of the head's per-dimension mean squared error `mean((ŷ_top − y)²)`. It is not the blend's `_top_errors` window, which holds L2 errors; using that would put `L_j` off by a factor of `n_j`.
- `W_{j,z}` is the head's code block before that scoring step's `adapt`, the weights that made `ŷ_top`.
- The code `z` and its `code_tick` are the ones stored with the regressor when the prediction was formed (the blend forms `_regressor` one step before it is scored), not the latest adopted code.
- Processors compute and publish ascending errors on every processing tick on which they score a prediction, not only on experiential ticks.

`g_j` is clipped to `ascending_clip` in L2 norm and published with the scalar `code_tick` (decision 6). Normalising by `m_j` makes the processors' errors dimensionless, so one modality's scale cannot dominate the encoders.

The workspace keeps the last `pending_codes` accessed codes with their standardised slot inputs, weights and pre-activations (working state only). For each held code it averages the ascending errors that arrive for it per processor, so a processor that reports at 3.3 Hz counts once per code, as one at 2 Hz does. It then takes one step per code and processor:

    δ = ḡ_j ⊙ (1 − z²)
    W_s ← W_s − η_E · α_s · δ x̃_sᵀ,   c_s ← c_s − η_E · α_s · δ    for each source present in that code

A step that is not finite is skipped and counted, as `adapt` does. After a step, any row of `W_s` whose L2 norm exceeds `encoder_max_norm` is rescaled to it. An error for a code no longer held is dropped and counted. Neither processors nor the workspace learn while the processors are suspended (sleep), and the workspace skips ascending errors published while the sleep module reports sleep. The intensity weighting reaches learning through `α_s`, so a source that contributed little to a code learns little from its errors.

The code is computed in one pass from its inputs and the encoders learn from the errors. That is an amortised form of the predictive-coding update: Rao and Ballard's higher level also iterates its representation to reduce the error before learning, which this design does not do. The readout says whether the cheaper form suffices.

A head with zero code columns sends an ascending error of zero, and encoders with random weights produce a nonzero code. So the heads learn first, from a random but informative code, and the encoders learn once the heads read the code. Starting both at zero would leave both at zero forever.

Alternatives considered:

- *Train the encoders with their own decoders inside the workspace, using the published latents as targets.* Rejected. It duplicates the decoders, trains the code on a different error from the one the processors make, and would need interoception to publish its features.
- *A residual target* (the head predicts what the processor's own model gets wrong). Rejected. It couples two learners and makes the code's value depend on the forward model's state. The existing head predicts the input itself, and the blend already handles reliability.

### 6. The bus and privacy

Every value here follows `latent-content-privacy`, whose open question 1 was ruled option B on 2026-11-01.

- **Option B (ruled).** No latent value enters a main-bus stream. `z_k` travels on the broadcast's volatile companion entry under `workspace_feedback.latent_derived.code`. `g_j` travels on the report's companion entry under `latent_derived.ascending_error`. The vision latent and audition's acoustic latent travel on their reports' companion entries. The workspace joins an accessed member's companion entry by the id its main entry's envelope names (`latent-content-privacy` decision 7: the companion is written first) to write the slot; a missing companion entry leaves the slot unwritten. The processors join the broadcast's companion entry to adopt the code. The content code declares itself the consumer of the vision and audition companion streams and the producer of the broadcast, vision, audition and interoception companion streams, so the boot refuses unless the volatile instance is up, unpersisted and capped within `[privacy].companion_stream_maxlen`.
- **Option A (not chosen).** Under it the same values would have ridden the main-bus payloads, with the `workspace.broadcast` cap (100000) and `interoception.out` (`default_maxlen = 100000`, `kaine/bus/config.py:28`) lowered to at most 12000. The ruling for B makes that unnecessary.
- **Readouts and persistence:** readouts are scalars and source names, outside the tag. The broadcast record drops members' `latent_derived` mappings. Codes, slots, pending inputs and shadow weights never reach a log, a research record, a snapshot or the dashboard. The encoder weights, standardisers and code blocks reach the content-code checkpoint and snapshots, as learned parameters under decision 10. The content code checks `LATENT_RULE_VERSION ≥ 1` and the encryption conditions at boot and refuses without them.
- **The bus budget.** With audition publishing its latent, the audition stream's entry grows from about 400 B (`TYPICAL_EVENT_BYTES`, `kaine/bus/config.py:223-230`) to roughly the size of one vision latent with a 768-number encoder, and every decoder stream gains `code_dim` floats per report. Redis runs `noeviction`, so a mis-sized budget fails the bus mid-run, which is a welfare-relevant crash. The entity-free harness measures the entries, and the budget rows of the instance that carries them are updated before switch-on.

### 7. No mismatch candidate and no new route into salience

The content code publishes no event that the workspace scores and adds no term to any salience, intensity, arousal or drive. Its only route into experience is the head's prediction inside the processor's existing blended error.

A second route existed in the first version. Novelty is a fingerprint of the whole payload, and salience multiplies by it, so adding `latent_derived.ascending_error` to every interoception and audition report, and audition's latent, would give each report one more source of uniqueness. Those reports carry varying floats already, so the effect may be small, but the rule must hold by construction. The fingerprint therefore excludes the `latent_derived` key at any depth. That is a no-op when the key is absent, so the shipped novelty scores are unchanged, and audition's content-on latent sits inside the tag for the same reason (decision 2).

A test checks that, with the code on, the set of event types on module streams is the set with it off, that the workspace's scored candidates come from the same streams, and that with the code on and every code column still zero the novelty and salience scores of identical inputs are identical to the code-off scores.

This follows the operator's ruling and the adversarial review (§2.6). A learned cross-modal predictor is wrong for long stretches of films with orchestral scores and off-screen sound, and a mismatch candidate would feed that error into novelty appraisal and arousal as a new route to distress. Through the blend, the same error lowers the descending prediction's weight instead.

### 8. The readout: did the code do its job

Each processor that used a code adds these fields to its report (the vision report, `audition.perception`, `interoception.report`), all scalars or names outside the latent tag:

- `content_gain = (e_null − e) / m`, where `e` is the reported blended error, `e_null` is the error of the blend formed with the null code `z̄` (the running mean of the last `null_code_window` accessed codes) in the head, with the same blend weights, and `m` is the processor's running mean error. The context `b` and the sequence prediction stay in both evaluations, so this is the information the code adds over the access summary, the counterpart of A.8's `context_gain`. It is null (not zero) until the null window has filled.
- `content_cross_gain`, the same with the code formed from the other sources' slots only, `z^{−j} = tanh(Σ_{s ≠ j} α_s (W_s x̃_s + c_s))`, in place of `z_k`. For a processor that is not a source (interoception), it equals `content_gain`. This is the readout of cross-modal content. Each source's own latent is in the code its own head reads, so vision's head could become a second linear forward model of the last accessed vision clip, and `content_gain` would then be positive with no cross-modal structure at all. `content_cross_gain` cannot be.
- `content_shift_gain`, the same as `content_gain` with the code formed `shift_s` entity seconds earlier in place of `z_k`. The shift is measured in entity seconds, not in broadcasts, because the access rate follows arousal (50 broadcasts is about 15 s at rest and 5 s at the 10 Hz maximum). It is at least 60 s: the decodability check found cross-film correlation still at 65% of its lag-0 value at ±5 s and at 0.030 at ±30 s.
- `code_sources`, the sources present in the code used, and `code_age_s`, the entity seconds since that code was formed.

The null code is the mean code rather than zero because the code's mean is not zero. A zero null would be out of distribution and would inflate the gain. `z̄` is working state only: it is a per-dimension statistic of latent-derived values over a window of about 77 s at rest, which is what `latent-content-privacy` decision 5 removes from the buffer summaries, and no learning rule updates it. It re-warms after a restart.

`kaine/research/content_code_readout.py` reads the research log and reports, per processor, per film, per waking day and over the run, content-free:

- the median `content_gain`, `content_cross_gain` and `content_shift_gain` over awake reports with a code, with bootstrap 95% intervals;
- **the own-content readout**: whether the median `content_gain` is above zero;
- **the cross-modal job readout**: whether the median `content_cross_gain` is above zero and above the median `content_shift_gain`, with intervals that do not overlap. This is the readout that says the code carries cross-modal content;
- **dropped-modality robustness**: vision's and interoception's median gains split by whether the audition slot was present in the code used, and audition's split by the vision slot. Under a shared code the gain should fall when a sense is missing and stay at or above zero (graceful degradation). Natural drops come from the blind-sensor and sensor-silent advisories and from silence in the films. An entity-free test forces a drop (decision 12);
- slot occupancy per source (a code that lowers a sense's error lowers that sense's intensity and access share, so its slot ages: the access loop can limit itself, and occupancy shows it);
- the ascending errors dropped for a missing code or a non-finite step, the breaker state and the share of saturated code components (`|z_i| > 0.99`).

Per-film reporting matters because the decodability check ranked the films (Santa Claus and First Spaceship carry the most cross-modal structure, Baby Huey is too short to tell); if the code works, the gains should follow that ranking.

The readout is reported positive or negative from the running entity (build order item 13). It is an engineering readout, not a preregistered test. Within-entity comparisons use windows with the code off and on. They are anecdotal for an n = 1 run, as the operator's outcome records.

### 9. The translation-loss arm, as a shadow

With `comparison = "translation_shadow"` the workspace trains a second code `z'` from the same slots with its own encoders `W'_s` and per-source decoders `T_s` (from `z'` back into each source's latent space). It uses the Global Latent Workspace's losses, equally weighted:

- translation between the paired senses (vision's latent to `z'` to audition's, and back), using slot pairs present in the same code;
- demi-cycle (each latent to `z'` and back);
- full cycle (vision to audition to vision, and audition to vision to audition, through `z'`).

The shadow never reaches a processor, the bus or a snapshot. Its weights are working state and are discarded at shutdown, as the positive control's shadows are. It runs off the tick thread with a bounded queue; when the queue is full a step is dropped and counted, and a test checks that tick slip with the shadow on is no greater than with it off.

**The comparison measure.** For vision and audition, the workspace keeps linear probes reading `(z, 1)` and `(z', 1)` that predict each processor's next published latent, and cross-modal probes reading the code formed from the other source only (`z^{−j}` and its shadow counterpart). Each probe is trained by SGD on its target latent, without gradient into either code. Each probe's gain over its own null code is computed as in decision 8. The demi-cycle trains the shadow to autoencode, so the own-source probes mostly compare autoencoding; the cross-modal probes are the comparison that matters. The broadcast metadata carries the probe gains as scalars every `shift_s` entity seconds, under `workspace_feedback.content_readout`. This is the first comparison of a Global Latent Workspace objective against a predictive-workspace objective that KAINE can run. It restarts at each boot, so long comparisons are run entity-free (decision 12).

Language, the one unpaired modality, is not part of this change. It joins through a cycle-consistency term in the grounding work (W5), once speech-to-text is on.

Alternative considered: *a live translation arm that drives the processors.* Rejected. The operator kept translation for comparison only, and a shadow measures it without changing what the entity experiences.

### 10. Identity

The content code's learned state is each source's encoder `W_s, c_s` and standardiser `μ_s, σ_s`, plus every processor head's code block. Together they define what the code means and how it is read, so they are one unit of identity, and they live in one file.

- **Persist.** `state/workspace/content_code.ckpt`, written through the state encryptor (`get_state_encryptor()`) with an atomic replace. It holds `code_dim`, `LATENT_RULE_VERSION`, a code id (a random identifier fixed when the code is first built, which identity-bound episodic content records, `latent-content-privacy` decision 6), a generation counter, each source's encoder id, pooling and input dimension, its weights and standardiser, each processor's code block with the head shape it belongs to, the breaker latch and scalar running means only. It never holds slots, pending codes, the null code `z̄`, past codes or the shadow.
- **Written with the module states.** The checkpoint is written in the same step as every module-state capture: each rolling resume checkpoint (each entity minute), each fork snapshot and preservation (as a snapshot participant), at sleep onset and at shutdown. Each capture records the checkpoint generation it was paired with. The first version wrote the encoders every 600 s while the heads rode the resume checkpoint each minute, so after a crash heads could be paired with encoders ten minutes older. Now the encoders and code blocks are always from one moment, and the base blocks in module state are at most one capture apart; a restore that finds different generations logs which.
- **Encrypted, fail closed.** The content code refuses to build unless state encryption is in effect with a resolvable key and `[preservation].require_encryption = true` (`latent-content-privacy` decision 9). The shipped configuration sets both, but the code defaults are off, so the check reads the effective values.
- **Bound to the encoders.** At boot, a source whose recorded encoder id, pooling or input dimension differs from the running encoder is refused, naming the source and both values, unless `reset_sources` names it for that boot. The source then starts fresh with a warning, and the other sources keep their weights. Pooling is part of the binding because the vision encoder's model id does not include it (`kaine/modules/vision/encoder.py:405-416` logs it but the id omits it), and the attention and mean pools are different spaces of the same width. A different `code_dim` is refused outright, since every code block reads the old width.
- **A snapshot participant seam** (new; nothing like it exists). `kaine/lifecycle/participants.py` defines a participant: a name, an `export(dest_dir) -> record` and an `import(src_dir) -> None`, and a flag saying whether its import runs before module `deserialize`. The workspace registers `workspace_content_code` with `ForkManager` when the code is built.
  - **Snapshot:** after module states are captured and before module artifact hooks run, each participant exports into `artifacts/<participant>/` of the snapshot, and its record is stored under `metadata["participants"]`. A failed export removes the snapshot directory and raises, as a module artifact hook does.
  - **Restore and revive:** a participant whose flag is set imports before any module `deserialize`, because the processors need the code width and code blocks to restore their heads. The content code's flag is set. A snapshot whose metadata records a captured participant whose artifact is missing is refused as incomplete. A snapshot from before the code existed revives with a fresh code and a warning.
  - **Fork:** participant artifact directories are copied into the child's snapshot like module artifacts, so the child owns its copy.
  - **Merge:** works from the artifact directories on disk, with no live participant, so a merge from the dashboard process (`dashboard/__main__.py:182`, its own `ForkManager`) works the same.
  - **Preservation bundle and decommission:** the bundle carries the participant artifacts; the decommission listing names the checkpoint and the artifacts.
- **Merge.** When both parents carry a content code, merge refuses unless the caller passes `content_code_from = "a"` or `"b"`. The chosen parent's participant artifact (encoders, standardisers, code blocks) is copied whole, and every processor head's base block in module state is taken from the same parent, overriding the module weight choice of `fork-merge-module-weights` for those keys, since one parent's code blocks cannot read the other's code and a head's two blocks were trained together. The choice is recorded in the merged snapshot's metadata. Averaging two codes is not offered: two codes learned from different lives do not share coordinates. The test asserts that the merged artifact and every processor's head base block are exactly equal to parent b's, not merely present.
- **Decommission.** The checkpoint is listed among the entity's data locations and removed. A dry run lists it.
- **Disable is not delete.** Turning the code off leaves the checkpoint in place and removes the code blocks from the heads (decision 3). Turning it on again splices them back.

### 11. Welfare

The code changes what the entity predicts, so it changes its errors, intensities, access, arousal, apertures and drives (the loops of paper §6.4). The checks:

1. **Two-layer opt-in.** The code is built only when `enabled = true` and `KAINE_CONTENT_CODE_OPERATOR_APPROVED=1`. With the first and not the second it stays off, the boot prints why, and the research gate records `content_code: not_approved`. With the table absent, the research gate record is unchanged from the current build.
2. **The welfare signal is not the code's to move.** Interoception decodes the code by default, and with feedback on its reported `prediction_error` is the blend, so the code could lower (mask) or raise the distress indicator that watches it. The change `welfare-signal-unblended` makes every welfare reader use the processor's own forward-model error, independent of any top-down blend or decoder, and pins it with a test. The content code refuses to build unless that change is in (a boot check on its marker). The entity-free check below also bounds the own-error welfare indicator.
3. **Preconditions on the stimulus.** The two feed defects (`vision/feed.py:1122`, `audition/feed.py:1000`) are fixed, with tests, before the entity-free welfare check runs and before switch-on. Together they erase lag-0 audiovisual sync on two of the four films; a code trained on that would learn from a desynchronised world.
4. **Entity-free welfare check before any entity uses it.** A new harness, `kaine/evaluation/benchmarks/content_code_welfare/`, runs the real vision, audition, interoception, sequence and affect modules over the four programme films (about 243 minutes) with no entity. It is new work, not an extension of the mediation runner, which drives only vision and interoception on a synthetic stimulus with a static affect modulator. Two passes, same seed, code off then on:
   - **pass 1** from zero code blocks and fresh encoders, the real switch-on;
   - **pass 2** from encoders and code blocks trained entity-free on the decodability check's cached film latents, so the bounds are tested with a code that has engaged. The vision head's effective step is `lr · 2/768 ≈ 2.6e-6` per input, so in one pass from zero columns the code may hardly move vision's predictions and pass 1's bounds could pass vacuously. Pass 2's weights are discarded afterwards and never loaded into an entity, since the decision says the entity's weights learn only from its own experience; the harness writes them only under its scratch directory, and a test checks that.

   Fixed before the run, with the code on against off, in each pass:
   - each processor's alert rate rises by at most 10% relative;
   - mean arousal differs by at most 0.05 and its 95th percentile by at most 0.08;
   - the share of affect states with negative valence rises by at most 5 points;
   - no drive crossing occurs that the off run lacks;
   - the own-error interoceptive distress indicator crosses its threshold no more often than in the off run;
   - in the 60 entity seconds after switch-on, and in the 2 entity seconds after every slot arrival and expiry, no processor's error ratio exceeds its off-run 99th percentile for more than 1% of reports;
   - fewer than 5% of code components are saturated, at switch-on and over the run;
   - nothing is non-finite;
   - **engagement:** in pass 2, every decoder head's code block has a norm above a floor fixed with the bounds, and the `content_gain` distribution is non-degenerate (its interquartile range is above zero). A pass in which the code did not engage fails, rather than passing vacuously.

   A failure stops the change for redesign. The result is recorded under `docs/records/validation/`.
5. **Continuity at switch-on** (decision 3): the first descending prediction equals the base head's.
6. **Suspension during welfare responses.** While a welfare rest or freeze is in place (the indicator response of build order item 1, or the operator's freeze), the heads read the null code `z̄`, nothing learns, and the broadcast metadata records the suspension. The code resumes when the rest ends.
7. **Harm breaker.** When any processor's median `content_gain` over `breaker_window_s` of awake, unsuspended reports falls below `breaker_gain_floor`, the code is suspended as in check 6 and latches. Suspended periods are left out of the window, so a rest does not count toward or against the breaker. The latch is stored in the checkpoint, survives restarts and clears only for a boot with `resume_after_breaker = true`. The caretaker notice names the processor and the median. A code that makes prediction worse is stopped until the operator looks. The breaker watches prediction, not arousal; the welfare net stays the backstop for tail harm.
8. **A dropped modality is not an error.** A missing source leaves its slot empty and its term absent. Nothing compares one sense's code with another's, so silence in the audio or a blind camera produces no mismatch signal (decision 7). An advisory clears the slot at once.
9. **The welfare net runs on every run**, with the indicator response, as for every component. The switch-on is a run-control record in the development run, so welfare windows before and after can be compared.
10. **Moral weight.** A content-bearing broadcast strengthens the global-workspace indicator of Butlin et al. (2023) that the comparison report names (§5.5). This raises the precautionary weight given to the entity. It is a governance input, not a claim about experience. The rule that utterance text is never welfare evidence extends to any claim that the code gives the entity understanding.

**Can it destabilise the processors?** No, with decisions 2, 5 and the guards above: the heads are linear in bounded inputs (a tanh code, the 24-number context and sequence prediction); the SGD steps are small; `adapt` and the encoder step skip non-finite steps; the encoder rows are max-norm bounded; gains stay inside `[pi_min, pi_max]`; the ascending error is clipped.

### 12. The offline cross-modal decodability check is design input

The decodability check (build order item 3, a tools script outside the image) fits ridge and CCA maps from vision latents to acoustic embeddings and back, at lag 0 and at lags, against time-shifted and shuffled controls, on the four programme films. Its first results are in (`kaine-research`, 2026-10-31). They inform this design and do not gate it:

- **Stimulus suitability.** The films carry the time-locked part weakly. Expected magnitudes: vision's gain near zero (consecutive clips share 13 of 16 frames, so the forward model is strong and `w_top` small); audition small (the spectral encoder's cross-film R² is negative, −0.150); and much of what is learnable is scene identity under repeated viewing (shuffled pairings already reach R² 0.05 to 0.12, the synchrony-specific part is 0.02 to 0.06). The shift control of decision 8 removes neither scene identity nor the own-content echo, which is why `content_cross_gain` is the job readout. Two recommendations go to the operator for the development run's programme, not as gates: add tightly coupled audiovisual material (public-domain cartoons with sync sound, on-screen speech, music with visible performers, impacts), and consider live feeds through the remote bridge under the bystander rules, the strongest source.
- **The audition encoder.** Content-code runs use a learned audition encoder (Dasheng is the recommended default), not the spectral encoder, which is the weakest case for a linear code.
- **`code_dim`.** Kept at 64 for capacity. It is not derived from the count of canonical components above the shuffled control, as the first version said: few components are synchrony-specific (top-5 cross-film canonical correlation 0.12 to 0.20), so that rule would clamp the code at 16, but the code also carries each sense's own content.
- **`slot_decay_s`.** Kept at 2 s. The first version's rule (the lag at which predictability halves) cannot be applied to the measured lags of ±5, ±30 and ±120 s: at ±5 s cross-film correlation is still 65% of lag 0, so the rule would clamp at 5 s, against the report's 1 to 5 s advice. The tool is rerun at 0.5 to 3 s lags (noting the window overlap) on the synchrony-specific excess (lag-k minus block-shuffle), with mean-pooled vision latents (open question 1, ruled b), and `slot_decay_s` is set from that.

Two entity-free tests reuse the check's cached film latents, which are stimulus features outside the latent rule (`latent-content-privacy` decision 8). One is a long run of the content code and its translation shadow over the films, the comparison of decision 9 without the boot limit. The other is the forced dropped-modality test: audio removed for alternating 60-second blocks, with vision's cross-modal probe gain required to stay at or above zero in the blocks.

### 13. No pretrained cross-modal model

The encoders, standardisers, heads, shadow and probes start from seeded random or zero weights and learn only from the entity's experience. No pretrained joint audio-visual or image-text model is added, no Meta model or library is added, and no code is taken from the Global Latent Workspace library (`ruflab/shimmer`). The losses of decision 9 are implemented from their published equations.

The per-sense encoders are unchanged, with one disclosure. The vision latent the code reads is, with the shipped `pooling = "attention"`, InternVideo-Next's native attention-pooled global vector, which the model was trained to align with text (`vision/encoder.py:268-271`, "the CLIP-aligned global vector"). The decision rules out "any pretrained cross-modal encoder (CLIP, SigLIP, ImageBind)". Feeding the content code a vision-language-aligned vector would bring a pretrained cross-modal alignment into the code by the back door, and it matters most for W5 grounding, where text-aligned visual latents would partly pre-solve word grounding. This was open question 1, ruled option (b) on 2026-11-01: the content code requires `[vision].pooling = "mean"` (the mean of the encoder's patch tokens, `encoder.py:272`, the same width) and refuses to build otherwise.

### 14. Spec bookkeeping

`workspace-feedback` is still a change (its task 3.2 open, task 3.3 open), so it has no base spec in `openspec/specs/`. This change's `workspace-feedback` delta adds requirements to that capability. `workspace-feedback` is archived first, after its task 3.3 is done or explicitly moved, and this change's delta is archived after it, so two changes never own the same requirement. Its task 3.2 is marked there as moved to this change.

### 15. Off is bit-identical to absent, against the pre-change build

The off test of the first version compared "table absent" with "`enabled = false`", both on the post-change code, so it could not catch a refactor of the shared head path in PR 1. A golden-trace test records, on the commit before PR 1, every published payload, intensity, broadcast selection and snapshot of a fixed entity-free run, for the shipped configuration and for each feedback arm, and compares the post-change build with the table absent and with `enabled = false` against it.

## Risks

- **Little to learn on the films.** The programme's sound is loosely coupled to its pictures (decision 12). The readout reports a small or null cross-modal gain honestly, and the breaker stops a harmful one.
- **An own-content echo mistaken for content.** Each source's head reads a code that holds its own last latent. `content_cross_gain` and the cross-modal probes separate the two; `content_gain` alone would not.
- **Asynchronous credit assignment.** An ascending error refers to a code formed a few hundred milliseconds earlier, and the encoders may have moved since. The step is small (`η_E` = 0.001), and the dropped-error count is reported. A test checks that encoders trained this way reach the error of encoders trained synchronously on a synthetic task.
- **Code collapse or saturation.** The heads may learn to ignore the code, which shows as a gain near zero. tanh may saturate, which shows in the saturation share. Both are readouts, not hidden states.
- **Transient distress at scene cuts and slot events.** A cut makes the descending prediction wrong for a report or two. The blend bound, the slot-event bound and the entity-free check cover it, and the welfare net and the breaker remain.
- **Identity cost.** Every snapshot, fork, merge, revive and decommission path gains a participant, and the participant seam is new. It is sized as its own work in PR 3 and gets the second review.
- **The readout is weak evidence.** An n = 1 development run with within-entity windows cannot attribute effects cleanly. The operator accepted this cost. The entity-free comparison of decision 12 is the controlled part.

## Migration and ordering

1. Requires `latent-content-privacy` merged (its two open questions were ruled on 2026-11-01: B and b), `welfare-signal-unblended` merged, `fork-merge-module-weights` merged, `workspace-feedback` (built), and the two feed fixes merged. The development run's configuration (build order item 5) sets `[vision].pooling = "mean"` (open question 1, ruled b) for the fresh entity.
2. PR 1: heads persist in every arm (`workspace-feedback` task 3.2), the head regressor with the code block, widening and splicing, the null, cross and shifted evaluations, and the ascending error with its pinned definitions, behind `enabled = false`. Includes the golden-trace test.
3. PR 2: `kaine/workspace/content_code.py`: settings, slots, standardisers, encoders, code formation, the pending-code ring with per-processor averaging, the guarded encoder step, attaching the code (on the companion entry, bus option B), audition's published latent, the fingerprint exclusion, the boot checks (privacy rule, encryption, welfare-signal marker, pooling, bus, opt-in).
4. PR 3: identity: the participant seam in `kaine/lifecycle/participants.py` and `ForkManager` (snapshot, restore order, fork, merge from disk, revive, bundle, decommission listing); the checkpoint written with every module-state capture; encoder binding with pooling; `content_code_from` with the head-block override.
5. PR 4: welfare and readout: suspension, breaker with suspended periods excluded, caretaker notice, research-gate field; readout fields on the research log allowlist; `code_sources` in the ignition log; `kaine/research/content_code_readout.py`.
6. PR 5a: the translation shadow off the tick thread, and the probes including cross-modal probes.
7. PR 5b: the new entity-free welfare harness with real audition, sequence and affect on the films, both passes, the engagement condition and the slot-event bound.
8. PR 5c: the long comparison and the forced dropped-modality test on the cached latents.
9. The entity-free welfare check passes and is recorded, the decodability rerun sets `slot_decay_s`, then the operator opts in for the development run (build order item 8).

## Welfare and admissibility

- Experience-changing and welfare-high-risk. Every PR gets the independent second review, and the shadow's review confirms it has no path into live error, intensity or access (decision point 4 of the operator's outcome).
- Ships off, with an opt-in that needs both the config and the operator variable.
- The development run admits components joining as they are built. Each switch-on is a run-control record, and nothing changes inside a run except by that record. `[vision].pooling` is set before the entity boots, not switched mid-life (open question 1).
- The checks of decision 11 run before and during use, and the welfare net runs throughout.

## Implementation estimate

In LLM-agent terms: seven worker PRs of about 300 to 800 changed lines each, tests included. Each takes two to four hours of worker time and one to two hours of lead review, plus the second review on each. PR 2 and PR 3 are the hardest: asynchronous credit assignment, and a new participant seam on identity paths that must not lose an individual. About eight to twelve days elapsed for the code, with the second reviews. The entity-free welfare check is two passes of the vision encoder over about 48,600 clips each, about 75 minutes of encoding per pass at the measured 11 clips a second, plus the module work; eight hours of unattended compute is a safe upper bound, with the vision encoder on the GPU in a window outside entity runs. The long shadow comparison runs on the CPU from cached latents in about an hour. Size L.

## Ruling on the open question

### Open question 1 (review C15): the vision input is CLIP-aligned

The shipped vision latent (`pooling = "attention"`) is InternVideo-Next's attention-pooled global vector, aligned with text in pretraining. The decision rules out any pretrained cross-modal encoder for the content level.

- **Option (a).** Keep attention pooling and disclose it. Cheapest; the code would inherit a vision-language alignment, and W5 grounding would be partly pre-solved by it.
- **Option (b) (recommended).** Switch the vision module to mean pooling of the encoder's patch tokens (`pooling = "mean"`, the same 768 width) for the development run, before the entity boots, and disclose the change. The content code requires it and refuses to build otherwise. The decodability check is rerun with mean-pooled latents before `slot_decay_s` is set. Because the vision encoder's model id does not include the pooling, the content code's binding records it (decision 10); the vision module's own forward-model checkpoint has no such binding today, so the switch is made only for a fresh entity, never for one that has learned under attention pooling.
- **Option (c).** Keep attention pooling for the vision module and feed the content code a second, mean-pooled vector. It keeps the vision module unchanged but doubles the pooled outputs and gives the code a different view of vision from the one the vision forward model and its head predict.

Recommended: **(b)**. Status: **ruled (b) on 2026-11-01** (architecture decisions of 2026-11-01, item 4). Reasoning: the standing rule is no pretrained cross-modal encoder, and the attention-pooled vector is CLIP-aligned; mean pooling of the patch tokens keeps the encoder and the width, for a fresh entity only, with the change disclosed. Decision 13, the boot check and the binding follow (b).

The two open questions of `latent-content-privacy` (the bus and episodes) also bear on this change. They were ruled B and (b) on the same date, and decision 6 follows B.
