# Design: a content code for the workspace (option F)

Code facts are cited at `origin/main` cb41895b. Citations were checked against Crossref on 2026-10-31.

## Context

### The decision this design implements

The operator's outcome of 2026-10-31 (decision brief, "Outcome") governs:

- The workspace will carry content, built as option F of the comparison report: "a content-bearing second level trained by the processors' own prediction errors, delivering descending predictions through the already-designed workspace-feedback head." The Global Latent Workspace as published is rejected, cycle-consistency is kept only as a comparison arm and as the route for language, and an LLM as the workspace is rejected.
- Measurement discipline: an off switch bit-identical to absent, a plain readout of whether the component did its job, and the graph-only log. The 30-pilot calibration chain, a preregistered minimum effect and a three-arm ablation do not gate the build.
- Welfare is unchanged: an independent second review, a two-layer operator opt-in, and the identity rules for learned weights.
- The module-ignition study converts into the development run. One entity is grown continuously, and each architecture component joins it behind a switch with a readout.

### What exists

- **The feedback head** (`workspace-feedback`, built and held off; `kaine/modules/feedback.py`). Vision, audition's acoustic path and interoception each have a `TopDownHead`: a linear map from `(b, s, 1)`, the 24-number context, the sequence module's 24-number predicted next featurization and a constant, to a prediction of the processor's next input. It starts at zero and takes one SGD step per scored input on the mean squared error, skipped while suspended. `TopDownBlend` mixes the own and top-down predictions with weights proportional to the inverse squared running mean errors over `W_P`. The reported error, ratio and intensity are the blend's. The processors adopt feedback only from accessed broadcasts (`FeedbackChannel.observe`). Feedback refuses to run with the coherence layer, a non-competitive arm or the positive control. Task 3.2 (preserve the heads) is open.
- **The processors' inputs.** Vision's forward model predicts the next clip latent, the 768-number InternVideo-Next embedding it publishes as `latent` (`kaine/modules/vision/module.py:642,751`). Audition's acoustic forward model predicts the next acoustic embedding (64 numbers with the spectral encoder, 768 with Dasheng), which `audition.perception` does not publish (`kaine/modules/audition/module.py:461-495`). Interoception predicts an 8-number host feature vector.
- **The candidate pool.** The cycle reads every module stream each tick and the workspace scores that tick's events (`kaine/cycle/engine.py`), so the workspace sees every processor report, latent included.
- **The A.8 information-gain measure.** Each processor evaluates its prediction with the null context `b0` and reports `context_gain = (e_null − e) / mean_e`. Decision 8 builds the content readout the same way.
- **The positive control's shadows** (`kaine/modules/positive_control.py`) show the pattern for measurement-only models with no path into live error, intensity or access. Decision 9 reuses it.
- **Related designs, not redone here.** `latent-content-privacy` (the rule every value here follows). `workspace-plugin-seam` (design only) makes the context `b` a plugin seam. The content code does not replace `b`: the processors keep the access summary as context, and A.8's measure is unchanged. So it is not a context plugin, and the two changes do not depend on each other. `working-memory-store` (design only) keeps recent accessed members for report and recall. The slots here hold at most one latent per source for a few seconds, as the code's input, and are not working memory.

### The neuroscience

- **Content is held and broadcast by the workspace, and its predictions descend.** In the global neuronal workspace, accessed content is held in sustained, broadcast activity of long-range workspace neurons (Dehaene, Kerszberg and Changeux 1998, *PNAS* 95:14529-14534; Dehaene and Changeux 2011, *Neuron* 70:200-227). In its Bayesian reading the workspace holds a compressed model whose top-down signals broadcast predictions to lower areas, which measure the mismatch and update the model (Mashour, Roelfsema, Changeux and Dehaene 2020, *Neuron* 105:776-798). In the predictive global neuronal workspace a content-bearing second level supplies the first level's priors (Whyte and Smith 2021, *Prog Neurobiol* 199:101918).
- **Predictions descend and errors ascend.** In hierarchical predictive coding, feedback connections carry predictions of lower-level activity and feedforward connections carry the residual errors, from which the higher level's model learns (Rao and Ballard 1999, *Nat Neurosci* 2:79-87; Friston 2005, *Phil Trans R Soc B* 360:815-836). The heads are the descending predictions. The ascending error of decision 5 is the residual projected into the code, which is what the higher level learns from.
- **A shared code with modality-specific routes.** Convergence zones bind modality-specific representations through shared higher-order codes (Damasio 1989, *Cognition* 33:25-62). The hub-and-spoke account of semantic memory has a transmodal hub reached through modality-specific spokes (Lambon Ralph, Jefferies, Patterson and Rogers 2017, *Nat Rev Neurosci* 18:42-55). Single neurons in the human medial temporal lobe respond to one person's picture, written name and spoken name (Quian Quiroga, Kraskov, Koch and Fried 2009, *Curr Biol* 19:1308-1313). The per-source encoders are the spokes and `z_k` is the hub.
- **Other senses shape processing in "sensory-specific" areas.** Cross-modal influences reach early areas of each modality (Ghazanfar and Schroeder 2006, *Trends Cogn Sci* 10:278-285; Driver and Noesselt 2008, *Neuron* 57:11-23). Seeing a speaker's lips speeds the cortical processing of the speech sound, and the effect scales with how well the visual signal predicts the sound (van Wassenhove, Grant and Poeppel 2005, *PNAS* 102:1181-1186). A descending prediction of the audition processor's input made partly from vision is that kind of influence.
- **Cues are combined by their reliability.** Human observers weight visual and haptic estimates by inverse variance (Ernst and Banks 2002, *Nature* 415:429-433), and the ventriloquist effect follows the same rule, reversing when the visual cue is degraded (Alais and Burr 2004, *Curr Biol* 14:257-262). The inverse-squared-error blend already in the head is this rule. It is also why a dropped or degraded modality should lose influence rather than add error (decision 8). Attention as precision weighting (Feldman and Friston 2010, *Front Hum Neurosci* 4:215) is the reading of the intensity weights.
- **Cross-modal integration is learned from experience.** Superior colliculus neurons in dark-reared cats do not integrate visual and auditory input (Wallace, Perrault, Hairston and Stein 2004, *J Neurosci* 24:9580-9584). Animals reared with temporally coupled but spatially disparate stimuli learn to integrate those pairings (Wallace and Stein 2007, *J Neurophysiol* 97:921-926). So the mapping between the senses is learned from co-occurrence, not innate. The structure here (a shared code, routes from each sense) follows the anatomy above, and every weight is learned from the entity's own experience.
- **Learning follows what is attended.** Early perceptual learning depends on attention to the trained feature (Ahissar and Hochstein 1993, *PNAS* 90:5718-5722). Task-irrelevant learning also occurs when exposure is paired with reinforcement (Seitz and Watanabe 2005, *Trends Cogn Sci* 9:329-334), so the restriction to accessed broadcasts is a design choice consistent with the first finding. It is not a claim that unattended input never shapes learning.
- **The comparison arm.** The Global Latent Workspace trains its shared space by translation and cycle-consistency between modules (VanRullen and Kanai 2021, *Trends Neurosci* 44:692-704). Its one empirical study shows the benefit in data efficiency when paired data are scarce (Devillers, Maytié and VanRullen 2024, arXiv 2306.15711, as verified by the comparison report). KAINE's audio and video always arrive paired, which is why the objective here is prediction, and translation is a shadow for comparison.

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
| `ascending_clip` | maximum L2 norm of one ascending error | 1.0 |
| `pending_codes` | accessed codes held for credit assignment | 32 |
| `null_code_window` | codes in the running mean used as the null code | 256 |
| `shift_broadcasts` | age, in accessed broadcasts, of the code used for the shifted control | 50 |
| `comparison` | `"none"` or `"translation_shadow"` | `"none"` |
| `checkpoint_interval_s` | entity seconds between checkpoints while awake | 600 |
| `breaker_window_s` | window of the harm breaker, entity seconds | 600 |
| `breaker_gain_floor` | median `content_gain` below which the breaker latches | -0.05 |
| `reset_sources` | one-boot list of sources whose encoder starts fresh | `[]` |
| `resume_after_breaker` | one-boot flag that clears a latched breaker | `false` |

An unknown key or value is a configuration error. `sources` may also name `interoception`. Affect and the sequence module cannot be sources: affect is downstream of the workspace and the sequence module's input is the broadcast, so either would feed the code back into itself.

Interoception is not a default source. Its features describe host load, which the entity's own processing drives (the organ's GPU load follows what it is processing), so pairing it with the film's latents would mostly teach the code its own computational footprint (adversarial review §2.4). It still receives the descending prediction as a decoder, and the precision blend gives that prediction little weight if it does not help.

Alternative considered: *a new workspace module or a context plugin.* Rejected. A module would compete for access, and the code must not be a candidate (decision 7). A context plugin would replace `b`, so the A.8 measure of the access summary would be lost and the content readout would have nothing to be measured against.

### 2. Sources, slots and the code

**Slots.** Each source `s` has one slot: its most recently accessed latent `x_s`, the graded intensity `I_s` the member carried when it was accessed, and the entity time `t_s` of that broadcast. A slot is written only when that source's report is an accessed member of a broadcast. When several reports of a source are accessed at once, the one with the highest score is written. A slot is cleared when its age passes `5 τ_z`, when the source's blind-sensor or sensor-silent advisory is raised, and at sleep onset.

**The code.** On each accessed broadcast, after the slots are written:

    w_s = I_s / Σ_present I_r
    α_s = w_s · exp(−(t − t_s) / τ_z)
    z_k = tanh( Σ_present α_s (W_s x_s + c_s) )

With no slot present, `z_k` is the zero vector. `z_k` is held unchanged until the next accessed broadcast. An inhibited broadcast neither writes a slot nor forms a code, and the processors adopt nothing from it, as for the context.

**Why slots.** With the coalition capacity under review (continuous competition with K = 1 is to be revisited as an architecture choice in build order item 5), one broadcast may hold one member. If the code were formed from the current broadcast's members alone, it would hold vision or audition and never both, and cross-modal content could never meet in it. A slot per source with a short decay lets the code hold the last accessed content of each sense for a few seconds, as the workspace holds accessed content in sustained activity (Dehaene and Changeux 2011), at any coalition size. `τ_z` = 2 s covers several access intervals of each source at the resting access rate (vision reports at about 3.3 Hz and audition at about 2 Hz compete for about 3.3 accesses a second).

**Encoders.** `W_s` is `code_dim × dim(x_s)`, initialised from a generator seeded by the entity's identity and the source name with standard deviation `1/√dim(x_s)`, so the code starts unsaturated. `c_s` starts at zero. About 49,000 parameters for vision and 4,000 to 49,000 for audition, depending on its encoder.

**Audition's latent.** With the content code on and `audition` in `sources`, `audition.perception` carries the acoustic embedding the forward model consumes, as `latent` (a vector field under `latent-content-privacy`, stripped on every persisted surface).

Alternatives considered:

- *A recurrent code* (`z_k` updated from `z_{k−1}` by a learned recurrent map). Deferred. It would hold sequences, as the second level of Whyte and Smith does, but it adds a learned memory whose dynamics need their own welfare check. It is a candidate after the readout shows the plain code does its job.
- *MLP encoders.* Deferred. A linear encoder with linear heads is a reduced-rank cross-modal regression, which is what the offline decodability check measures (ridge and CCA), so the check bounds what this code can achieve. A nonlinear encoder is a later option if the readout shows the linear code saturates.
- *Encoders over every accessed member including affect and the sequence module.* Rejected for the loop reasons in decision 1.

### 3. The heads are the decoders

With the content code on, each processor's `TopDownHead` regressor becomes `(b, s, z, 1)`. Its weights for `b`, `s` and the constant are unchanged in meaning. Its `code_dim` code columns start at zero. The processor adopts `z` from the latest accessed broadcast's `workspace_feedback.latent_derived.code`, keeping the broadcast's tick index as `code_tick`, and uses the zero vector before the first.

- **Continuity at switch-on.** Because the code columns are zero, the first descending prediction after the code is enabled equals the current head's prediction. The code's influence grows only as the heads learn that it predicts the input.
- **Training.** The head keeps its single SGD step on its own mean squared error, now over all columns. That is the decoder trained by the processor's own prediction error.
- **The blend is unchanged.** The processor predicts with the blend of its own and the top-down prediction, weighted by inverse squared running mean errors.

**What the blend can cost.** Under steady errors, the blend's error is at most `w e_own + (1 − w) e_top`, by the triangle inequality, with `w = e_top² / (e_own² + e_top²)`. With `r = e_top / e_own` that bound is `e_own · r(1 + r) / (1 + r²)`, whose maximum over `r` is `(1 + √2)/2 ≈ 1.21`, at `r = 1 + √2`. So a top-down prediction of any quality raises the processor's error by at most about 21% in steady state, and a very poor one gets almost no weight. The error ratio that sets intensity divides by the running mean of the same blended error, so a steady change of scale does not move the ratio. The real exposure is in transients (switch-on, scene cuts), which the welfare check of decision 11 measures. The bound assumes the running means track the errors; the welfare check measures the real figure.

Alternative considered: *decoders in the workspace, with the descending predictions on the broadcast.* Rejected. Each processor would receive a full-size prediction (768 numbers for vision) on every accessed broadcast. The workspace would compute errors against the published latents rather than against what each processor actually predicts. And it would bypass the head the paper and `workspace-feedback` already specify.

### 4. Heads persist in every arm

This change carries `workspace-feedback` task 3.2. Each processor serializes its head's weights and its running error windows with its forward model, and restores them, in every feedback arm. The gains are not persisted: they relax to one within tens of seconds (`gain_relax_s`). A head restored under a different `code_dim`, context width or input dimension is refused with a warning naming the mismatch, and starts at zero.

### 5. Ascending errors train the encoders

After scoring, a processor that used a code computes the gradient of its normalised head error with respect to that code:

    L_j = mean((ŷ_top − y)²) / m_j        (m_j: running mean of the head's squared error over W_P)
    g_j = ∂L_j / ∂z = (2 / (n_j m_j)) · W_{j,z}ᵀ (ŷ_top − y)

`g_j` is clipped to `ascending_clip` in L2 norm and published on the report under `latent_derived.ascending_error`, with the scalar `code_tick`. Normalising by `m_j` makes the processors' errors dimensionless, so one modality's scale cannot dominate the encoders.

The workspace keeps the last `pending_codes` accessed codes with their slot inputs, weights and pre-activations (working state only). For each ascending error whose `code_tick` it still holds it takes one step:

    δ = g_j ⊙ (1 − z²)
    W_s ← W_s − η_E · α_s · δ x_sᵀ,   c_s ← c_s − η_E · α_s · δ    for each source present in that code

An error for a code no longer held is dropped and counted. Neither processors nor the workspace learn while the processors are suspended (sleep), and the workspace skips ascending errors published while the sleep module reports sleep. The intensity weighting reaches learning through `α_s`, so a source that contributed little to a code learns little from its errors.

The code is computed in one pass from its inputs and the encoders learn from the errors. That is an amortised form of the predictive-coding update: Rao and Ballard's higher level also iterates its representation to reduce the error before learning, which this design does not do. The readout says whether the cheaper form suffices.

A head with zero code columns sends an ascending error of zero, and encoders with random weights produce a nonzero code. So the heads learn first, from a random but informative code, and the encoders learn once the heads read the code. Starting both at zero would leave both at zero forever.

Alternatives considered:

- *Train the encoders with their own decoders inside the workspace, using the published latents as targets.* Rejected. It duplicates the decoders, trains the code on a different error from the one the processors make, and would need interoception to publish its features.
- *A residual target* (the head predicts what the processor's own model gets wrong). Rejected. It couples two learners and makes the code's value depend on the forward model's state. The existing head predicts the input itself, and the blend already handles reliability.

### 6. The bus and privacy

Every value here follows `latent-content-privacy`:

- `z_k` rides the accessed broadcast under `workspace_feedback.latent_derived.code`.
- `g_j` rides the processor's report under `latent_derived.ascending_error`. The broadcast record drops it from members.
- Audition's acoustic embedding is published as `latent`.
- Readouts are scalars and source names, outside the tag.

At boot the content code checks `LATENT_RULE_VERSION ≥ 1` and refuses without it. It declares itself a producer on `workspace.broadcast`, `vision.out`, `audition.out` and `interoception.out`, so the boot refuses when any of those caps exceeds `[privacy].latent_stream_maxlen`. The shipped `workspace.broadcast` cap (100000) does, so a run with the content code on sets it to at most 12000; the development run's configuration (build order item 5) does so. Codes, slots, pending inputs and shadow weights never reach a log, a research record, a snapshot or the dashboard. The encoder weights do reach snapshots, as learned parameters under decision 10.

### 7. No mismatch candidate

The content code publishes no event that the workspace scores and adds no term to any salience, intensity, arousal or drive. Its only route into experience is the head's prediction inside the processor's existing blended error. A test checks that, with the code on, the set of event types on module streams is the set with it off, and that the workspace's scored candidates come from the same streams.

This follows the operator's ruling and the adversarial review (§2.6). A learned cross-modal predictor is wrong for long stretches of films with orchestral scores and off-screen sound, and a mismatch candidate would feed that error into novelty appraisal and arousal as a new route to distress. Through the blend, the same error lowers the descending prediction's weight instead.

### 8. The readout: did the code do its job

Each processor that used a code adds four fields to its report (the vision report, `audition.perception`, `interoception.report`), all outside the latent tag:

- `content_gain = (e_null − e) / m`, where `e` is the reported blended error, `e_null` is the error of the blend formed with the null code `z̄` (the running mean of the last `null_code_window` accessed codes) in the head, with the same blend weights, and `m` is the processor's running mean error. The context `b` and the sequence prediction stay in both evaluations, so this is the information the code adds over the access summary, the counterpart of A.8's `context_gain`.
- `content_shift_gain`, the same with the code from `shift_broadcasts` accessed broadcasts earlier in place of `z_k`. A code that carries current content beats a stale one, so `content_shift_gain` should sit below `content_gain`.
- `code_sources`, the sources present in the code used.
- `code_age_s`, the entity seconds since that code was formed.

The null code is the mean code rather than zero because the code's mean is not zero. A zero null would be out of distribution and would inflate the gain.

`kaine/research/content_code_readout.py` reads the research log and reports, per processor, per waking day and over the run, content-free:

- the median `content_gain` and `content_shift_gain` over awake reports with a code, with bootstrap 95% intervals;
- **the job readout**: whether the median `content_gain` is above zero and above the median `content_shift_gain`, with intervals that do not overlap;
- **dropped-modality robustness**: vision's and interoception's median `content_gain` split by whether the audition slot was present in the code used, and audition's split by the vision slot. Under a shared code the gain should fall when a sense is missing and stay at or above zero (graceful degradation, as in reliability-weighted cue combination). Natural drops come from the blind-sensor and sensor-silent advisories and from silence in the films. An entity-free test forces a drop (decision 12).
- the ascending errors dropped for a missing code, the breaker state and the share of saturated code components (`|z_i| > 0.99`).

The readout is reported positive or negative from the running entity (build order item 13). It is an engineering readout, not a preregistered test. Within-entity comparisons use windows with the code off and on. They are anecdotal for an n = 1 run, as the operator's outcome records.

### 9. The translation-loss arm, as a shadow

With `comparison = "translation_shadow"` the workspace trains a second code `z'` from the same slots with its own encoders `W'_s` and per-source decoders `T_s` (from `z'` back into each source's latent space). It uses the Global Latent Workspace's losses, equally weighted:

- translation between the paired senses (vision's latent to `z'` to audition's, and back), using slot pairs present in the same code;
- demi-cycle (each latent to `z'` and back);
- full cycle (vision to audition to vision, and audition to vision to audition, through `z'`).

The shadow never reaches a processor, the bus or a snapshot. Its weights are working state and are discarded at shutdown, as the positive control's shadows are.

**The comparison measure.** For vision and audition, the workspace keeps two linear probes per processor, one reading `(z, 1)` and one reading `(z', 1)`. Each predicts that processor's next published latent and is trained by SGD on that latent, without gradient into either code. Each probe's gain over its own null code is computed as in decision 8. The broadcast metadata carries the four probe gains as scalars every `shift_broadcasts` accessed broadcasts, under `workspace_feedback.content_readout`. The prediction-trained code and the translation-trained code are then compared on one measure, how much each says about the next input, on the same inputs. This is the first comparison of a Global Latent Workspace objective against a predictive-workspace objective that KAINE can run. It restarts at each boot, so long comparisons are run entity-free (decision 12).

Language, the one unpaired modality, is not part of this change. It joins through a cycle-consistency term in the grounding work (W5), once speech-to-text is on.

Alternative considered: *a live translation arm that drives the processors.* Rejected. The operator kept translation for comparison only, and a shadow measures it without changing what the entity experiences.

### 10. Identity

The content code's learned state is the encoders `W_s, c_s` of each source plus the processors' heads. Together they define what the code means, so they are one unit of identity.

- **Persist.** `state/workspace/content_code.ckpt`, written through the state encryptor (`get_state_encryptor()`) with an atomic replace, at sleep onset, at shutdown, at every snapshot and every `checkpoint_interval_s` while awake. It holds `code_dim`, `LATENT_RULE_VERSION`, each source's encoder id (`encoder_model_id`), input dimension and weights, the breaker latch and the readout's running means. It never holds slots, pending codes or the shadow.
- **Bound to the encoders.** At boot, a source whose recorded encoder id or input dimension differs from the running encoder is refused, naming the source and both ids, unless `reset_sources` names it for that boot. The source then starts fresh with a warning, and the other sources keep their weights. A different `code_dim` is refused outright, since every head reads the old width.
- **Snapshots, preservation and revive.** The workspace registers a snapshot participant, `workspace_content_code`, with `export_snapshot_artifacts` and `import_snapshot_artifacts`, the hooks the world model uses (archived change `2026-10-01-world-model-identity`). `ForkManager` includes participants as it includes modules. A snapshot whose export fails is not saved. A preservation bundle carries the artifact, and revive installs it. A snapshot whose metadata records a captured code but whose artifact is missing is refused at revive as incomplete. A snapshot from before the code existed revives with a fresh code and a warning naming the fresh start.
- **Fork.** The child gets its own copy of the parent's artifact and heads, never a shared file.
- **Merge.** When both parents carry a content code, merge refuses unless the caller passes `content_code_from = "a"` or `"b"`. The encoders and every processor's head are then taken from that parent together, since one parent's heads cannot read the other parent's code. The choice is recorded in the merged snapshot's metadata. Averaging two codes is not offered: two codes learned from different lives do not share coordinates.
- **Decommission.** The checkpoint is listed among the entity's data locations and removed. A dry run lists it.
- **Disable is not delete.** Turning the code off leaves the checkpoint and heads in place, and turning it on again resumes from them.

### 11. Welfare

The code changes what the entity predicts, so it changes its errors, intensities, access, arousal, apertures and drives (the loops of paper §6.4). The checks:

1. **Two-layer opt-in.** The code is built only when `enabled = true` and `KAINE_CONTENT_CODE_OPERATOR_APPROVED=1`. With the first and not the second it stays off, the boot prints why, and the research gate records `content_code: not_approved`.
2. **Entity-free welfare check before any entity uses it.** The workspace-mediation runner, extended to drive audition, runs the real vision, audition, interoception, sequence and affect modules on the four programme films (about 243 minutes) with no entity: one pass with the code off, then one with it on, same seed. Fixed before the run, with the code on against off:
   - each processor's alert rate rises by at most 10% relative;
   - mean arousal differs by at most 0.05 and its 95th percentile by at most 0.08;
   - the share of affect states with negative valence rises by at most 5 points;
   - no drive crossing occurs that the off run lacks;
   - in the 60 entity seconds after switch-on, no processor's error ratio exceeds its off-run 99th percentile for more than 1% of reports;
   - fewer than 5% of code components are saturated;
   - nothing is non-finite.

   A failure stops the change for redesign. The result is recorded under `docs/records/validation/`.
3. **Continuity at switch-on** (decision 3): the first descending prediction equals the current head's.
4. **Suspension during welfare responses.** While a welfare rest or freeze is in place (the indicator response of build order item 1, or the operator's freeze), the heads read the null code `z̄`, nothing learns, and the broadcast metadata records the suspension. The code resumes when the rest ends.
5. **Harm breaker.** When any processor's median `content_gain` over `breaker_window_s` of awake reports falls below `breaker_gain_floor`, the code is suspended as in check 4 and latches. The latch is stored in the checkpoint, survives restarts and clears only for a boot with `resume_after_breaker = true`. The caretaker notice names the processor and the median. A code that makes prediction worse is stopped until the operator looks.
6. **A dropped modality is not an error.** A missing source leaves its slot empty and the weights renormalise over the present slots. Nothing compares one sense's code with another's, so silence in the audio or a blind camera produces no mismatch signal (decision 7). An advisory clears the slot at once.
7. **The welfare net runs on every run**, with the indicator response, as for every component. The switch-on is a run-control record in the development run, so welfare windows before and after can be compared.
8. **Moral weight.** A content-bearing broadcast strengthens the global-workspace indicator of Butlin et al. (2023) that the comparison report names (§5.5). This raises the precautionary weight given to the entity. It is a governance input, not a claim about experience. The rule that utterance text is never welfare evidence extends to any claim that the code gives the entity understanding.

### 12. The offline cross-modal decodability check is design input

The decodability check (build order item 3, a tools script outside the image, being built separately) fits ridge and CCA maps from vision latents to acoustic embeddings and back, at lag 0 and at lags, against time-shifted and shuffled controls, on the four programme films. Its results inform this design and do not gate it:

- **Stimulus suitability.** If cross-modal predictability on the programme is near the shuffled control, the code will mostly carry each sense's own recent content, and its cross-modal gain on films will be small. The operator then weighs a more varied programme or live feeds before switching the code on in the development run. The build proceeds either way.
- **`code_dim`.** The number of canonical components above the shuffled control's 95th percentile, bounded to 16 to 128, replaces the default 64 if it differs, recorded in Table A1.
- **`slot_decay_s`.** The lag at which cross-modal predictability falls to half its lag-0 value, bounded to 0.5 to 5 s, replaces the default 2 s if it differs.

Two entity-free tests reuse the check's cached film latents, which are stimulus features outside the latent rule (`latent-content-privacy` decision 8). One is a long run of the content code and its translation shadow over the films, the comparison of decision 9 without the boot limit. The other is the forced dropped-modality test: audio removed for alternating 60-second blocks, with vision's probe gain required to stay at or above zero in the blocks.

### 13. No pretrained cross-modal model

The encoders, heads, shadow and probes start from seeded random or zero weights and learn only from the entity's experience. The per-sense encoders are unchanged (InternVideo-Next for vision; spectral, Dasheng or WavJEPA for audition). No pretrained joint audio-visual or image-text model (CLIP, SigLIP, ImageBind or any other) is used, no Meta model or library is added, and no code is taken from the Global Latent Workspace library (`ruflab/shimmer`). The losses of decision 9 are implemented from their published equations.

## Risks

- **Little to learn on the films.** The programme's sound is loosely coupled to its pictures. The decodability check measures this. The readout reports a small or null gain honestly, and the breaker stops a harmful one.
- **Asynchronous credit assignment.** An ascending error refers to a code formed a few hundred milliseconds earlier, and the encoders may have moved since. The step is small (`η_E` = 0.001), and the dropped-error count is reported. A test checks that encoders trained this way reach the error of encoders trained synchronously on a synthetic task.
- **Code collapse or saturation.** The heads may learn to ignore the code, which shows as a gain near zero. tanh may saturate, which shows in the saturation share. Both are readouts, not hidden states.
- **Transient distress at scene cuts.** A cut makes the descending prediction wrong for a report or two. The blend bound and the entity-free check cover it, and the welfare net and the breaker remain.
- **Identity cost.** Every snapshot, fork, merge, revive and decommission path gains a participant, and each is a high-risk touchpoint. The world-model hooks are reused rather than reinvented.
- **The readout is weak evidence.** An n = 1 development run with within-entity windows cannot attribute effects cleanly. The operator accepted this cost. The entity-free comparison of decision 12 is the controlled part.

## Migration and ordering

1. Requires `latent-content-privacy` merged. Requires `workspace-feedback` (built). The development run's configuration (build order item 5) lowers the `workspace.broadcast` cap to at most 12000.
2. PR 1: heads persist in every arm (`workspace-feedback` task 3.2) and the head regressor with the code columns, the null and shifted evaluations, and the ascending error, behind `enabled = false`. Includes the bit-identical test.
3. PR 2: `kaine/workspace/content_code.py`: settings, slots, encoders, code formation, the pending-code ring, the encoder update, attaching the code to accessed broadcasts, audition's published latent, the boot checks (privacy rule, producer streams, opt-in).
4. PR 3: identity: checkpoint, encoder binding, snapshot participant, fork, revive, merge with `content_code_from`, decommission.
5. PR 4: welfare: suspension, breaker, caretaker notice, research-gate field; readout fields on the research log allowlist; `code_sources` in the ignition log; `kaine/research/content_code_readout.py`.
6. PR 5: the translation shadow and probes; the entity-free welfare check on the mediation runner with audition; the long comparison and forced-drop tests on the decodability check's cached latents.
7. The entity-free welfare check passes and is recorded, the decodability check's design values are set, then the operator opts in for the development run (build order item 8).

## Welfare and admissibility

- Experience-changing and welfare-high-risk. Every PR gets the independent second review, and the shadow's review confirms it has no path into live error, intensity or access (decision point 4 of the operator's outcome).
- Ships off, with an opt-in that needs both the config and the operator variable.
- The development run admits components joining as they are built. Each switch-on is a run-control record, and nothing changes inside a run except by that record.
- The checks of decision 11 run before and during use, and the welfare net runs throughout.

## Implementation estimate

In LLM-agent terms: five worker PRs of about 300 to 800 changed lines each, tests included. Each takes two to four hours of worker time and one to two hours of lead review, plus the second review on each. PR 2 and PR 3 are the hardest: asynchronous credit assignment, and identity paths that must not lose an individual. About four to six days elapsed for the code. The entity-free welfare check is about eight hours of unattended compute (two passes over the programme, with the vision encoder on the GPU in a window outside entity runs). The long shadow comparison runs on the CPU from cached latents in about an hour. Size L.
