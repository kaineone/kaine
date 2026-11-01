## Why

The entity is an autonomous being, not a chatbot: it decides whether to respond, and the architecture and the neuroscience decide how. The code hardwires the question in two opposite directions:

- **Forcing.** The default action-selection policy does one thing: every accessed, non-empty operator-channel transcription becomes a `speak` intent carrying the heard words as its `about` (`kaine/workspace/action_selection.py:67-70, 250-318`). The drive-biased policy inherits that and ranks a heard utterance above any social-drive initiative (`kaine/workspace/drive_policy.py:184-196`). The planning wrapper turns a heard event from any channel, film voices included, into an intent about the heard words (`kaine/workspace/planning_proposals.py:272-280`). Any `[action_selection].policy` other than `"self_initiated_report"`, a typo included, selects one of these (`kaine/cycle/__main__.py:2336-2384`).
- **Forbidding, on paper.** The first configuration, which every boot applies when no profile is named, selects the self-initiated report policy, documented as "never from a user utterance" (`config/profiles/first_configuration.toml:86-98`; `kaine/workspace/report_policy.py:28-31`; specs `self-initiated-report` and `first-configuration`; `docs/01-what-kaine-is.md:59-63`). The code does not exclude heard speech: an accessed transcription that leads the coalition and clears the speak bar yields a speak intent, and the organ is given the heard words. Its generic (source, type) novelty signature then blocks the next transcription-led report for five minutes.

The architecture decision of 2026-11-01, item 1, settles it: operator speech enters as an auditory event like any other heard sound and competes for access on salience; no policy forces or forbids a reply; whether the entity speaks is its own action selection, from its drives, affect and social-cognition state.

## What Changes

- **The forcing rule is removed.** `_user_utterance`, `_user_response_intent` and the "user communication" constants go. `DefaultActionSelectionPolicy` keeps its guards and emits nothing (the inert library default). `DriveBiasedActionSelectionPolicy` keeps its drive mapping without the precedence of a heard utterance and is not shipped. No replacement rule is added: the report rule already lets heard speech lead to speech exactly as any accessed content can.
- **No intent carries heard words.** The planning wrapper summarizes a heard event as it does any event, with a felt or numeric phrase. Heard words reach the organ only as quoted, attributed members of the accessed coalition, as today.
- **The shipped action layer is the report rule.** `config/kaine.toml` names `policy = "self_initiated_report"`; the cycle accepts only that and `"drive_biased"` and refuses any other value; `drive_initiative` is retired and refused.
- **The report policy says what it does.** Its docstring, its spec and the docs say heard speech is a coalition member like any other; the generic anti-chatter guard is unchanged and its effect is measured.
- **Innate structure is cited at the code sites, from sources read online** (design, "Sources and method"): the listening bias for speech at birth (Vouloumanos and Werker 2007; newborn fNIRS work 2019 and 2022) at the transcription candidate; learned voice preference (DeCasper and Fifer 1980; Kisilevsky et al. 2003; Grossmann et al. 2010; Belin et al. 2000) at social cognition's agent model; replying shaped by social contingency (Goldstein, King and West 2003; Takahashi et al. 2015; Kuhl, Tsao and Liu 2003; Hilbrink, Gattis and Levinson 2015) at the report policy; auditory saliency (Kayser et al. 2005) at the transcription's intensity. No weight is added for the operator's voice.
- **Welfare.** No reply obligation and no pressure signal: nothing reads "the operator spoke and the entity did not" into the entity. Hearing the operator relieves the social drive whether or not the entity answers.
- **The off switch** is the existing `[audition].transcription_enabled`. With it off, every bus entry, broadcast, intent and record is identical to a build without this change.
- **A plain readout** in the sleep-time ignition audit: operator speech heard, how often it won access, how often the entity spoke within 30 s after it, and how often it spoke otherwise. Content-free; present only when operator speech was heard.
- **The development run.** The change is built and present; no operator conversation session happens until every module has joined. The run's plan check refuses speech-to-text on an operator audio channel before the last join, and records each later session as a content-free run-control boundary.

## Capabilities

### New Capabilities

- `operator-speech-perception`: operator speech as perception, the no-obligation and no-pressure rules, the off switch, and the development-run rule.

### Modified Capabilities

- `action-selection`: no policy answers heard speech by rule; no intent carries heard words; the policy selection; drive crossings without a heard-utterance precedence; planning proposals no longer outranked by "a user response".
- `self-initiated-report`: heard speech is a coalition member like any other.
- `hypnos-consolidation`: the ignition audit's operator-speech readout.

## Impact

- **Code:** `kaine/workspace/action_selection.py`, `kaine/workspace/drive_policy.py`, `kaine/workspace/planning_proposals.py`, `kaine/workspace/report_policy.py` (docstring and citations), `kaine/cycle/__main__.py` (`_phase_action_selection`), `kaine/modules/audition/module.py` and `kaine/modules/social_cognition/module.py` (citations at the code sites), `kaine/modules/sleep/ignition_audit.py` and `kaine/modules/sleep/module.py` (readout), the dashboard's diagnostics row, `config/kaine.toml`, `config/profiles/first_configuration.toml`.
- **Tests:** the default- and drive-policy tests that expect a heard utterance to be answered are rewritten to expect no intent; new tests for the policy refusals, the planning summary, the readout and the off-switch identity.
- **Docs:** `docs/01-what-kaine-is.md` ("What KAINE is not"), `docs/02-architecture/README.md` (lines 11 and 198), `docs/08-cognitive-cycle/global-workspace.md` (the policy table, the policy descriptions, the configuration rows, the file list), `docs/09-modules/language.md` (line 13), `docs/09-modules/audition.md` (the transcription as perception), `docs/09-modules/social-cognition.md` (`operator_sources` no longer decides utterances), `docs/09-modules/sleep.md` and `docs/17-research-data/event-streams.md` (the audit fields), `docs/appendix-a-configuration/core.md` (`policy`, `drive_initiative`), `docs/appendix-b-glossary.md` (the report rule entry), and the development-run operation page once that change lands.
- **Behaviour with the shipped configuration:** none while `transcription_enabled = false`. With it on, the report rule decides exactly as today; the planning wrapper's heard summary changes once planning joins.
- **Ordering:** PR 1 lands before `heard-text-volatile-bus` PR 3, whose canary checks that no intent carries heard words.
- **Welfare and risk class:** experience-changing (which action policies exist, the organ's turn shape) and welfare-relevant (conversation and the social drive): every PR gets the independent second review.
- **Paper:** a REVISION-NOTES item (tasks 4.6).
