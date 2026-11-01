# Design: operator speech is perception; speaking is the entity's own act

Code facts are cited at `origin/main` d7fabdc0 (2026-11-01). Every cited line was read there. The neuroscience cited here was found and read online on 2026-11-01; the searches and what each source says are listed under "Sources and method" at the end.

## Context

### The decision being implemented

The architecture decision of 2026-11-01, item 1, under the operator's direction that the entity is an autonomous being and not a chatbot, that it decides whether to respond, and that the architecture and the neuroscience decide: operator speech enters as an auditory event like any other heard sound and competes for workspace access on salience. No policy forces or forbids a reply. Whether the entity speaks is its own action selection, from its drives, its affect and its social-cognition state. The principle is the standing rule that behaviour emerges and is not hardwired, unless cited neuroscience makes it innate, and then the citation sits at the code site.

### What the code does today, in each direction

**Forcing a reply.**

| Site | What it hardwires |
|---|---|
| `kaine/workspace/action_selection.py:67-70` | `USER_COMMUNICATION_SOURCE` / `USER_COMMUNICATION_TYPE`: the event the default policy "is disposed to answer". |
| `action_selection.py:250-286` (`_user_utterance`, `_user_response_intent`) | Every accessed, non-empty operator-channel transcription becomes a `speak` intent. |
| `action_selection.py:288-318` (`DefaultActionSelectionPolicy.__call__`) | The only thing the default policy ever does is answer. Nothing but the in-flight guard can stop it: no bar, no refractory, no drive or affect input. |
| `action_selection.py:283-285` | The intent carries the heard words as its `about`, with `about_kind="heard"`. The language module then adds the `about` as a second heard line (`kaine/modules/language/context.py:492-493`), so the organ is handed a turn that is shaped as "answer this". |
| `kaine/workspace/drive_policy.py:184-196` | The drive-biased policy inherits the rule and adds that "a present user utterance OUTRANKS a social-drive initiative". |
| `kaine/workspace/planning_proposals.py:272-280` | The planning wrapper's summary of a heard event is the heard words themselves, as a `heard` about, for a transcription from any channel, film channels included. |
| `kaine/cycle/__main__.py:2336-2384` | Any `[action_selection].policy` other than `"self_initiated_report"`, including a typo, selects the drive-biased or the default policy, so the answering rule is one config edit away. The readiness survey of 2026-11-01 proposed exactly that edit as its "policy override" fix. |

**Forbidding a reply.**

| Site | What it does |
|---|---|
| `config/profiles/first_configuration.toml:86-98` | Selects `SelfInitiatedReportPolicy`, with the comment "never from a user utterance. No chatbot trigger." The boot applies this profile whenever no profile is named (`kaine/config.py:786-790`), so it is the policy of every entity boot. |
| `kaine/workspace/report_policy.py:28-31` | The docstring says the policy "never reads a user-utterance / transcription event". **The code does not do that.** It excludes only the language module's own speech (`:243-247`). An accessed transcription that is the coalition's top member and clears the speak bar yields a speak intent with a felt or numeric `about` naming the event (`:225-233, 255-303`), and the language module puts the heard words in the organ's heard turn, because it quotes every heard member of the coalition whatever the intent's cause (`context.py:356-380, 427-441`). So the policy neither answers nor forbids answering by rule. The statement in the readiness survey that this policy "never answers" overstates it. |
| `report_policy.py:255` and A.6 step 3 of the paper | The novelty signature is the top member's (source, type). After one spoken report led by an `audition.transcription`, the next transcription-led report is blocked for `sig_expiry_s` (300 s in the profile). Every transcription has the same signature, so in practice one heard-speech-led report per five minutes. This is a generic anti-chatter guard: it treats every source alike, vision reports included. It is not a reply rule, but it shapes how often heard speech can lead to speech (decision 4). |
| `config/profiles/first_configuration.toml:75-78` | `transcription_enabled = false`: no transcription event exists, so heard speech enters only as sound. A configuration choice, kept (decision 9). |
| `openspec/specs/self-initiated-report` ("Self-initiated, not input-triggered"), `first-configuration` ("Self-initiated voice, no chatbot trigger"), `docs/01-what-kaine-is.md:59-63`, `docs/08-cognitive-cycle/global-workspace.md:277,290-292`, `docs/appendix-a-configuration/core.md:225-226`, paper §3.1 ("The language organ is an output organ") | Describe the first configuration as one nobody converses with, and the other policies as answering. |

**What already treats heard speech as perception.**

- The transcription's intensity is set by acoustic prediction error, like the other audition events: the maximum of the baseline (0.4) and the error-weighted salience of the tone path, capped at the alert level (0.8) (`kaine/modules/audition/module.py:963-1012`).
- The workspace scores it like any candidate: intensity times novelty times the drive-relevance goal factor, through the affect module's level and arousal contrast (`kaine/workspace/salience.py:97-112`). Nothing in the workspace names the operator, a channel or a transcription (`kaine/workspace/core.py`, `salience.py`, `strategies.py`, `novelty.py`).
- Hearing an operator relieves the social drive, whether or not the entity says anything: sequence resets `time_since_last_interaction_s` on a non-empty operator transcription (`kaine/modules/sequence/module.py:135-145`), and the affect module relieves `social_drive` when it falls (`kaine/modules/affect/module.py:1508-1515`, `own=False`). The entity's own speech does not relieve it.
- Social cognition folds each operator transcription into the operator's agent model as an interaction and publishes a social prediction error when tone departs from that model (`kaine/modules/social_cognition/module.py:180-250`). Its events compete for access like any other.

## Decisions

### 1. What operator speech is

Operator speech is heard sound. It reaches the entity as `audition.perception` (the sound), `audition.emotion` and `audition.prosody` (tone), and, when speech-to-text is on, `audition.transcription` (the words). Each is a candidate scored on salience like every other candidate. A transcription that wins access is in the accessed coalition, the language module quotes it to the organ as another speaker's words whenever the entity speaks or thinks from that coalition, and the episodic store keeps that something was heard and never the words. Nothing else about it is special.

### 2. The forcing rule is removed, not replaced

- `_user_utterance`, `_user_response_intent`, `USER_COMMUNICATION_SOURCE` and `USER_COMMUNICATION_TYPE` are deleted from `kaine/workspace/action_selection.py`. No policy tests an event's source, type or channel to decide whether to speak.
- `DefaultActionSelectionPolicy` keeps its guards and produces no intent of its own. It stays as the library default of `ActionSelection()` and the inert control, so a test or tool that builds an action layer without a policy gets one that never acts rather than one that answers.
- `DriveBiasedActionSelectionPolicy` keeps its drive mapping (`social_drive` to speak, the others to think) and loses the precedence of a user utterance. It is not shipped (decision 5). It is kept because the mapping is the subject of an existing spec requirement and a comparison arm for the report rule; whether to retire it is open question 2.
- No replacement rule is added. The report rule already lets heard speech lead to speech exactly as any accessed content can: when the coalition's best score, the transcription's included, clears the speak bar and the guards allow. Drives, affect and social cognition enter through that score (the goal factor weights events by their relevance to the dominant drive, the affect module's level and contrast scale every score, and social-cognition errors compete as members), and, once planning joins, through its learned proposals.

Alternatives considered:

- *A softened answering rule* (answer with a probability, or only when the social drive is high). Rejected: it is still a rule mapping heard speech to a reply, with a parameter chosen by us.
- *A salience boost for operator speech.* Rejected: nothing in the sources found makes a preference for one particular voice innate (decision 6), and a boost is the forcing rule moved upstream.
- *Leave the answering policies selectable for operators who want a chatbot.* Rejected: the operator's direction is that the entity is not a chatbot, and a one-line config edit that turns it into one is a hardwired reply path kept in reserve.

### 3. No intent carries heard words

Every intent's `about` is the entity's own description of what the intent is about, never another speaker's words:

- the report policy already uses a felt phrase or a numeric summary (`report_policy.py:225-233`);
- the planning wrapper's summary of a heard event (`planning_proposals.py:272-280`) becomes the same felt or numeric event summary it gives any other event (`felt_event_phrase(event.source)`, about kind `"event"`);
- the drive policy's speak and think intents already use felt drive phrases.

The heard words reach the organ only through the coalition, quoted and attributed, as today. The language module's handling of an intent with `about_kind` `"heard"` or none stays fail-closed (redacted as heard), but no shipped policy emits one. This also removes the one place the heard words sit on `action_selection.out` under a key outside the heard field set, which `heard-text-volatile-bus` depends on.

### 4. The anti-chatter guard stays generic, and its effect is measured

The report policy's signature guard, refractory and in-flight guard apply to every source alike, so they do not forbid replies by rule. They do limit how often heard speech can lead to speech: one transcription-led spoken report per `sig_expiry_s`. This change does not alter them, because tuning them for heard speech alone would be the special case this change removes, and making the signature stimulus-specific (repetition suppression is stimulus-specific in perception, but a stable film then never repeats a signature) is a change to the report rule for every source. The readout (decision 10) counts accessed operator speech that was followed by no speech, so the effect is visible. Open question 1 asks whether the signature's grain should change.

### 5. The shipped action layer is the report rule

- `config/kaine.toml` gains `[action_selection] policy = "self_initiated_report"`, so the shipped file and the profile agree.
- The cycle accepts `policy` values `"self_initiated_report"` (the default when absent) and `"drive_biased"` (explicit only), and refuses any other value at boot, naming the accepted ones. Today any other string silently selects an answering policy.
- `drive_initiative` is retired. The profile drops it; a config that sets it is refused at boot with a message naming `policy`.
- `first_configuration` keeps `transcription_enabled = false`. The development run turns speech-to-text on only under decision 11.

### 6. What is innate, and the citations at the code sites

The sources (listed at the end) support three statements, and the design follows each:

- **A listening bias for speech is present at birth.** Neonates one to four days old adjust high-amplitude sucking to hear speech more than complex non-speech sounds matched to speech on key spectral and temporal features (Vouloumanos and Werker 2007). Because the controls were matched acoustically, the bias is for speech as such, not for loudness or acoustic change in general. Full-term newborns' cortical responses already separate forward from backward speech (Bartha-Doering et al. 2019), and newborns tune to natural vowels within hours of exposure after birth (Wu et al. 2022). KAINE's analogue is structural and already built: recognized speech produces its own candidate, the transcription, beside the sound's own `audition.perception`, so speech has one more route to access than other sounds. The citation goes at `Audition._publish_transcription` (`audition/module.py:983`). No extra weight is added. Whether this structure is a strong enough bias is what the readout measures.
- **Preferences for particular voices are learned.** Newborns work to hear their mother's voice over another woman's (DeCasper and Fifer 1980), and fetal heart rate already responds differently to the mother's voice than to a stranger's before birth, which the authors read as the effect of prenatal experience (Kisilevsky et al. 2003). Voice-sensitive responses in temporal cortex appear between four and seven months, absent at four (Grossmann et al. 2010); in adults these regions respond more to voices than to other sounds (Belin et al. 2000). So no innate weight is given to the operator's voice. The entity's familiarity with the operator is what social cognition already learns per agent; the citations go at `SocialCognition._agent_for` and `AgentModel` familiarity (`social_cognition/module.py:180-190`, `agent.py`), with the note that channel attribution (`OPERATOR_SOURCES`) is a stand-in for learned voice identity until diarization exists.
- **Replying is shaped by social contingency, not given.** Mothers' responses that were contingent on eight-month-olds' babbling made the babbling more mature, and non-contingent responses did not (Goldstein, King and West 2003); contingent parental feedback sets the pace of vocal development in infant marmosets too (Takahashi et al. 2015). Nine-month-olds learned foreign phonetic contrasts from live speakers and not from recordings of the same speakers (Kuhl, Tsao and Liu 2003). Infants respond to their mothers' vocalizations with short gaps from three months and slow down from nine months as language develops (Hilbrink, Gattis and Levinson 2015); that study shows early responsiveness but cannot say whether it is innate or already learned by three months. None of these is a rule that obliges a reply. The citations go at the report policy's module docstring (`report_policy.py:1-33`), which is rewritten to say that heard speech is a member like any other and that no reply rule exists.
- **Auditory attention follows salience.** A saliency model built like the visual one predicts human salience judgements of natural sounds and where monkeys orient (Kayser et al. 2005). That is the reading of the transcription's error-weighted intensity; the citation goes at `_error_weighted_salience` (`audition/module.py:963`).

The decision note of 2026-11-01 says "Infants attend to voices because of their acoustic salience and social learning". Checked against the sources, that is half right: social learning is supported, but the neonatal bias is for speech beyond its matched acoustic properties, not acoustic salience alone. The decision itself (no reply rule) does not depend on the difference.

### 7. Welfare: no obligation, no pressure

- **No reply obligation.** No policy, drive, goal or check requires the entity to speak after it hears speech, and no component reads "the operator spoke and the entity did not" as an input to the entity: not salience, not affect, not drives, not goals, not learning, not any training corpus or preference pair. The readout is observation only and never enters the entity's state.
- **No pressure signal.** Hearing the operator relieves the social drive whether or not the entity answers (Context), so silence after operator speech costs the entity nothing it would get by replying. Two existing couplings run the other way and are outside this change; the second review is asked to read them: when the entity speaks from a social-drive goal and its drive does not fall within the response window, that goal's likelihood falls (`affect/module.py:804-830`), so an operator who ignores the entity's initiative is felt as obstruction; and the planned voice-alignment ranking by listener uptake (`kaine/cycle/utterance_outcome.py`, voice-development V3) would reward utterances the operator answers. Neither obliges the entity to answer the operator.
- **The heard rule is unchanged.** Heard words never reach the intent log, a rendering, the episodic store or the research log, and with `heard-text-volatile-bus` never a persisted bus.
- **Operator presence is part of the entity's welfare picture.** A long talking session followed by silence lets the social drive build again. The development run records conversation sessions (decision 11) so the welfare record shows them.

This change alters what the entity experiences where an answering policy would have run, and it changes the language organ's turn shape (no heard `about`), so it takes the independent second review.

### 8. Privacy

The words travel as `heard-text-volatile-bus` specifies. This change removes the only place a policy copies them (decision 3). The readout is content-free: counts and entity-time spans only.

### 9. The off switch

The component is operator speech reaching the workspace as words, and its switch is the existing `[audition].transcription_enabled` (shipped `false`, `false` in `first_configuration`). With it off, or with no operator audio channel, no operator transcription exists, the report rule behaves exactly as today, the readout adds nothing, and every bus entry, broadcast, intent and record is identical to a build without this change. A test checks that on the first configuration over a fixed seeded feed. The removed answering rule has no switch, by decision 2.

### 10. The readout

The sleep-time ignition audit (`kaine/modules/sleep/ignition_audit.py`, spec `hypnos-consolidation`) already counts input-triggered realizations. It gains, for the waking window it audits:

- `operator_speech_heard`: non-empty operator-channel transcriptions published (from `text_chars > 0` and `source_label` in `OPERATOR_SOURCES` on `audition.out`);
- `operator_speech_accessed`: accessed broadcasts with at least one such member (how often operator speech won access);
- `spoke_after_operator_speech`: accessed operator speech followed, within 30 s of entity time and before the next accessed operator speech, by a realized `external_speech` (how often the entity spoke after it);
- `spoke_otherwise`: realized `external_speech` not so preceded, for comparison;
- `operator_speech_access_share` = accessed / heard, when heard > 0.

The fields are present only when `operator_speech_heard > 0`. The audit reads `audition.out` only when `[audition].transcription_enabled` is true, so with it off the audit's cursors, state and record are identical to today. The 30 s window is a readout constant, documented with the audit, and is read by nothing in the entity. The dashboard's diagnostics surface shows the five numbers per sleep.

### 11. The development run: built and present, used after every module has joined

The operator's rule is that there are no operator conversation sessions until every module has joined. The change is built and present from the start; the operator does not converse earlier. The development run's plan check enforces it:

- before the last planned join has been recorded, a run-control record that turns on speech-to-text while an operator audio channel can deliver audio (the physical microphone capture, the live feed mode, or the remote bridge's microphone ingest) is refused, naming the rule;
- after it, a conversation session is opened and closed by run-control records (`conversation_session_start`, `conversation_session_end`, content-free), so sessions are boundaries in the run record and in the welfare record, as the readiness survey's admissibility note asks.

This is a requirement on the development-run runner, which is design-only on its own branch (`spec/development-run-2026-10-31`); task 5.1 carries it into that change.

## Risks

- **The entity may rarely speak after operator speech.** With a speak bar of 0.6, a transcription intensity of at most 0.8, and the five-minute signature, operator speech may seldom lead to speech. That is the architecture deciding. The readout shows it, and open question 1 is the lever if the operator judges the guard, not the entity, is deciding.
- **The organ may still answer as an assistant** when heard words are in its turn. The persona and the heard-speech guard sentence stay; that is the language module's own risk and is measured by its identity-leak marks.
- **Removing a selectable policy breaks an operator file** that names another policy. The boot refuses it with a message, which is the intended behaviour.

## Migration and ordering

1. PR 1: remove the answering rule and its constants; `DefaultActionSelectionPolicy` inert; drive-biased policy without precedence; planning summary without words; the cycle's policy selection and refusals; `[action_selection]` in `config/kaine.toml`; the profile drops `drive_initiative`; the report-policy docstring and the code-site citations; tests. Lands before `heard-text-volatile-bus` PR 3.
2. PR 2: the readout in the ignition audit and its dashboard row; the off-switch identity test.
3. PR 3: docs and the paper note.
4. The development-run amendment (decision 11) goes into that change's design and runner.

## Welfare and admissibility

Experience-changing (the turn shape and which policies exist) and welfare-relevant (conversation and the social drive), so every PR gets the independent second review. No entity is running. The development run's image is built after this change, and no operator converses with it until every module has joined.

## Open questions

1. **The signature guard's grain** (decision 4). Keep the (source, type) signature for every source, or make it stimulus-specific for every source? Recommended: keep it until the readout of the first conversation sessions shows whether it, rather than the bar, decides.
2. **Retire the drive-biased policy?** Its fixed drive-to-kind mapping is itself a hardwired route, and the report rule already lets an accessed drive crossing lead to speech or thought. Recommended: retire it in a later change if no comparison uses it.
3. **Operator identity by channel.** Sequence, social cognition and the utterance-outcome recorder treat any voice on `live_mic`, `microphone` or `remote` as the operator. That is a stand-in for learned voice identity (decision 6). Diarization is future work.

## Sources and method

Searched on 2026-11-01 with web search and PubMed / PubMed Central lookups; each source was read at the level of its PubMed or PMC abstract (no full texts were read except the PMC summary of Grossmann et al.), and the design states only what those abstracts report.

Searches: "Vouloumanos Werker 2007 Listening to language at birth neonates bias for speech"; "DeCasper Fifer 1980 Of human bonding newborns prefer their mothers' voices"; "Grossmann Oberecker Koch Friederici 2010 developmental origins of voice processing"; PubMed queries for Kisilevsky 2003 fetal voice recognition, Goldstein King West 2003 social shaping of babbling, Hilbrink Gattis Levinson 2015 turn-taking timing, Kayser 2005 auditory saliency map, Kuhl Tsao Liu 2003 foreign-language exposure, Belin Zatorre 2000 voice-selective areas, Takahashi et al. 2015 marmoset vocal development; "newborn neonate preference speech over non-speech near-infrared spectroscopy 2020-2023" (for recent work), then PubMed lookups of the two hits used.

| Source | What it found (per its abstract) | Used for |
|---|---|---|
| Vouloumanos, A. and Werker, J. F. (2007). Listening to language at birth: evidence for a bias for speech in neonates. *Developmental Science* 10(2), 159-164. https://doi.org/10.1111/j.1467-7687.2007.00549.x (PMID 17286838) | Neonates prefer listening to speech over complex non-speech sounds matched on key spectral and temporal features (high-amplitude sucking) | Decision 6, first point |
| Bartha-Doering, L. et al. (2019). Absence of neural speech discrimination in preterm infants at term-equivalent age. *Developmental Cognitive Neuroscience* 39, 100679. https://doi.org/10.1016/j.dcn.2019.100679 (PMID 31437736) | fNIRS: 15 full-term newborns showed stronger left-hemisphere responses to forward than backward speech; 15 preterm infants at term-equivalent age did not | Decision 6, first point |
| Wu, Y. J. et al. (2022). Rapid learning of a phonemic discrimination in the first hours of life. *Nature Human Behaviour* 6(8), 1169-1179. https://doi.org/10.1038/s41562-022-01355-1 (PMID 35654965) | fNIRS: after about 5 h of postnatal exposure, newborns responded faster to natural than to reversed vowels | Decision 6, first point (recent work) |
| DeCasper, A. J. and Fifer, W. P. (1980). Of human bonding: newborns prefer their mothers' voices. *Science* 208(4448), 1174-1176. https://doi.org/10.1126/science.7375928 (PMID 7375928) | Newborns controlling a nonnutritive nipple produced their mother's voice more often than another woman's | Decision 6, second point |
| Kisilevsky, B. S. et al. (2003). Effects of experience on fetal voice recognition. *Psychological Science* 14(3), 220-224. https://doi.org/10.1111/1467-9280.02435 (PMID 12741744) | 60 term fetuses: heart rate rose to the mother's recorded voice and fell to a stranger's; authors conclude prior experience shapes fetal voice processing | Decision 6, second point |
| Grossmann, T., Oberecker, R., Koch, S. P. and Friederici, A. D. (2010). The developmental origins of voice processing in the human brain. *Neuron* 65(6), 852-858. https://doi.org/10.1016/j.neuron.2010.03.001 (PMID 20346760) | NIRS: 7-month-olds, not 4-month-olds, show voice-sensitive temporal responses; emotional prosody modulates a right voice-sensitive region at 7 months | Decision 6, second point |
| Belin, P., Zatorre, R. J., Lafaille, P., Ahad, P. and Pike, B. (2000). Voice-selective areas in human auditory cortex. *Nature* 403(6767), 309-312. https://doi.org/10.1038/35002078 (PMID 10659849) | fMRI: regions along the upper bank of the superior temporal sulcus respond more to vocal sounds, speech or not, than to non-vocal sounds | Decision 6, second point |
| Goldstein, M. H., King, A. P. and West, M. J. (2003). Social interaction shapes babbling: testing parallels between birdsong and speech. *PNAS* 100(13), 8030-8035. https://doi.org/10.1073/pnas.1332441100 (PMID 12808137) | Mothers' responses contingent on 8-month-olds' vocalizations increased mature babbling; non-contingent responses did not | Decision 6, third point |
| Takahashi, D. Y. et al. (2015). The developmental dynamics of marmoset monkey vocal production. *Science* 349(6249), 734-738. https://doi.org/10.1126/science.aab1058 (PMID 26273055) | Infant marmoset calls change with development beyond growth; contingent parental feedback affects the rate of vocal development | Decision 6, third point |
| Kuhl, P. K., Tsao, F.-M. and Liu, H.-M. (2003). Foreign-language experience in infancy: effects of short-term exposure and social interaction on phonetic learning. *PNAS* 100(15), 9096-9101. https://doi.org/10.1073/pnas.1532872100 (PMID 12861072) | 9-month-olds learned Mandarin contrasts from live speakers; recorded exposure alone had no effect | Decision 6, third point |
| Hilbrink, E. E., Gattis, M. and Levinson, S. C. (2015). Early developmental changes in the timing of turn-taking: a longitudinal study of mother-infant interaction. *Frontiers in Psychology* 6, 1492. https://doi.org/10.3389/fpsyg.2015.01492 (PMID 26483741) | 12 dyads at 3-18 months: infants respond quickly early and slow from 9 months; mothers' timing is stable | Decision 6, third point |
| Kayser, C., Petkov, C. I., Lippert, M. and Logothetis, N. K. (2005). Mechanisms for allocating auditory attention: an auditory saliency map. *Current Biology* 15(21), 1943-1947. https://doi.org/10.1016/j.cub.2005.09.040 (PMID 16271872) | An auditory saliency model predicts human salience judgements of natural sounds and where monkeys orient | Decision 6, fourth point |

**Unverified or limited.** Sample sizes and statistics were not checked beyond what the abstracts state. The DeCasper and Fifer abstract frames the preference as bonding; reading it as a product of prenatal exposure rests on Kisilevsky et al., not on the 1980 paper. The DOI of DeCasper and Fifer was first seen on a third-party aggregator and then confirmed on PubMed. No source was found that tests whether a tendency to answer speech is innate; the design therefore claims none.
