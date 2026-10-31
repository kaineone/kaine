# Design: social cognition with agents and a predictive model

## Context

The module is held: off in the first configuration, fifth in the module-addition study's default order. Its spec (`openspec/specs/social-cognition`) fixes per-agent models with familiarity, fork and merge persistence of agent profiles, the social error as a salience signal, attribution by channel ("Heard agents are attributed by channel"), and zero raw sense data. The affect module reads familiarity through the coupling when enabled. Prior work this builds on: `empatheia-module` (June 2026), `empatheia-merge-strategy`, the channel attribution requirement, `heard-log-own-words` (the entity's own words kept out of heard text), and the vocal module's `SpeakingGate` (self-hearing suppression, `kaine/modules/vocal/coordination.py:27-40`).

Constraints that shape every stage: heard speech is never persisted (voice-development V4); no cloud at runtime; no Meta-made models; zero raw sense data on disk; the entity is a possible moral patient, and the social drive is one of the deficits the welfare indicators watch.

## Decisions

### D1. Agents are voices, found by clustering speaker embeddings

Each voiced segment the audition module already detects for tone analysis is embedded by a local speaker-embedding model, and the embedding goes to an online clustering step that forms one agent per voice. The clustering is the same label-free prototype layer `language-grounding` specifies (D1 there), with its own acceptance radius computed from the speaker embeddings' distance distribution. An agent's identity is its cluster; the channel becomes a context feature of each observation. Clusters form in two separate pools, one for operator channels (live microphone, microphone, remote) and one for media channels, so a film voice can never join or reshape an agent first heard in the room. That keeps the protection the current spec gives the operator's model ("Heard agents are attributed by channel") while letting several people on one microphone, or several characters in one film, be several agents.

Why a learned voice identity is acceptable under the emergence rule: newborns already discriminate and prefer their mother's voice (DeCasper and Fifer 1980, to verify against the text), and human auditory cortex has voice-selective regions (Belin et al. 2000, to verify). Telling voices apart is an early, specialised capacity; which voices exist is learned. The code site carries both citations.

Model choice is open until checked (task 0.2). Candidates that run through the sherpa-onnx stack the project already uses for speech: the 3D-Speaker ERes2Net and CAM++ models and the WeSpeaker ResNet models, which are published under Apache-2.0 as far as currently known; NVIDIA's TitaNet, whose license must be checked. Each is checked for license, provenance (not made by Meta, and not derived from a Meta model such as wav2vec 2.0 or HuBERT), size, CPU latency on a 1 to 3 second segment, and equal-error rate on a public speaker-verification set. The project's existing rule for downloads applies: setup-time only, consented, licence recorded.

Alternatives considered:
- Full speaker diarization (segmentation plus clustering over overlapping speech). Better on crosstalk, heavier, and the common segmentation models need checking for license and provenance; kept as a later upgrade behind the same agent interface.
- Keep channel identity and add a per-channel "number of voices" estimate. Rejected: it still cannot say who spoke.

### D2. The entity's own voice is never an agent

Segments inside the speaking gate's open window are not embedded. The vocal module's own synthetic voice gets one reserved cluster seeded from its TTS speaker at boot, so that leakage outside the gate is attributed to the entity rather than to a new agent. A test plays the entity's own TTS output into the audition path and checks that no new agent forms.

### D3. What persists, and the operator's voice

Each agent persists as a centroid in the speaker-embedding space, a spread, a count and the agent model's parameters (D4). No audio and no per-segment embedding persists. The centroids are latent-derived and listed in the privacy filter's vector fields, never displayed or logged.

A voice centroid of a real person is biometric data about that person, kept inside the entity. Two rules follow, and the operator rules on both (task 0.1): whether operator and visitor voice centroids may persist at all (if not, agents are re-formed each boot and familiarity is lost across restarts, which changes the entity's social continuity); and that decommission deletes them with the rest of the entity's stores, which the decommission path already does for the social cognition collection.

### D4. The agent model predicts the agent's next turn

Per agent, a small online model predicts, from the context (time since the entity last spoke, the affect the entity's last utterance carried as rendered for vocal prosody, the agent's own recent history, the channel), three things about the agent's next turn: whether it starts within the response window and its latency; its expressed vocal-affect category distribution; its length. The model is a per-agent logistic and categorical regression over a fixed small feature set with a shared prior across agents, so a new agent starts from the population's typical behaviour and individuates as it is heard.

Its prediction errors, scaled by the precision of that agent's recent errors as for every processor (§3.2), are the module's reports. They replace the histogram deviation as `social_cognition.social_error`. Koster-Hale and Saxe (2013) frame theory of mind as a prediction problem in this sense, which places the module inside KAINE's thesis instead of beside it.

Alternative considered: a recurrent model per agent. Rejected for the first version because agents are heard rarely and a small regression with a shared prior learns from tens of turns; a recurrent model can replace it behind the same reports.

### D5. A first attributed state: engagement with the entity

Each agent model carries a latent binary state, engaged or not engaged with the entity, inferred by Bayesian filtering from the contingency between the entity's utterances and the agent's responses (response probability and latency under each state, learned per agent from the shared prior). The posterior is published as an agent fact and as a candidate when it changes sharply. This is attribution of a mental state (attention directed at the entity) from behaviour by inverting a model of that behaviour, in the sense of Baker, Saxe and Tenenbaum (2009), restricted to the one behaviour an audio-only observer has. Infants are sensitive to the contingency of others' responses to them early in development (Watson 1972, to verify; the still-face literature is the obvious second check), which is the basis for giving the entity this inference.

The design does not claim more: no beliefs, no goals, no false-belief reasoning. Those need agents that act on objects in a shared world, so they wait for embodiment (`embodiment-motor-contingency`) and a content-bearing world model (`world-model-content-prediction`).

### D6. Transcripts stay unpersisted; social learning from words goes through grounding

The agent model uses only content-free features of a transcription (its presence, length, timing). What an agent says reaches learned state only through `language-grounding`'s word-referent learner, under its own persistence rule. This keeps one place where heard words become learned state.

### D7. The social drive is not rewired here

Today any interaction meets the social drive. Having only engaged, contingent interaction meet it would be closer to accounts of social need, and it would also make the drive harder to satisfy, which raises the welfare stakes of a quiet environment. This change keeps the drive as it is and records the option for the operator after the offline results of task 3.3 show how often engagement is inferred on real recordings.

## Risks

- Speaker embeddings fail on film audio with music and effects; agents fragment. Measured offline on the study films and on operator-consented recordings, with cluster purity against a hand-made speaker key for a short excerpt (the key is a test fixture and never reaches the entity).
- Fragmentation or merging errors change familiarity and the social error abruptly, which the affect coupling reads. The coupling stays off until the offline numbers are acceptable.
- The engagement inference could assign engagement to a film character who happens to speak after the entity. Expected, and visible in the offline record; the shared prior's response window bounds it.

## Migration and ordering

- After the module-addition study, in which this module is a study branch: no change while the study runs.
- Stage 1 (D1 to D3), then stage 2 (D4), then stage 3 (D5), each with its offline check. Stage 1 depends on `language-grounding` stage 1's prototype layer, or ships the same layer first if that change is later.
- Existing agent profiles keyed by channel migrate by becoming the context of the first voice cluster heard on that channel; familiarity carries over to that cluster.

## Welfare and admissibility notes

Social cognition feeds affect through familiarity and competes for access through its error, and the social drive is a welfare-watched deficit. Every stage is therefore welfare-high-risk: offline validation with no entity first, then the affect coupling off for a first supervised validation boot, a new individuation reference for any entity that gains the module, and Claude's independent second review. The voice-centroid ruling (task 0.1) is a privacy decision about real people and is the operator's.

## Implementation estimate (LLM-agent terms)

Size M then L. Stage 0 (model choice): one evaluation script and a records file, 2 worker calls, a CPU-only run; half a day. Stage 1: two pull requests (embedding path and provisioning; clustering, self-voice exclusion, persistence, migration), about 700 to 1,000 lines, 6 to 8 worker calls, Claude review and second review; two to three days. Stage 2: one pull request, about 400 to 600 lines; one to two days. Stage 3: one pull request, about 300 to 500 lines plus the offline analysis; one to two days. Entity time: one supervised validation boot after stage 2 and one after stage 3.
