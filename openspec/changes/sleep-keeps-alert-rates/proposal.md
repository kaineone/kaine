## Why

The third test boot (main c4afcdd2, 2026-10-17) showed an access sawtooth. The sleep reset zeroes the perceptual alert rates `r_f` and `r_s`, so for minutes after every sleep the habituation factor is near 1, and every alert of the familiar stimulus raises arousal as if it were new. The zeroed `r_s` also makes the boredom alert excess large while it rebuilds, so boredom is relieved after every sleep without any change in the scene. KAINE's sleeps last 5 to 32 entity seconds, so this post-sleep novelty is produced by the reset itself, not by any elapsed time.

The habituation literature ties recovery to time, not to a reset:
- Thompson and Spencer (1966, Psychol Rev 73:16-43) and Rankin et al. (2009, Neurobiol Learn Mem 92:135-138), characteristic 2: "If the stimulus is withheld after response decrement, the response recovers at least partially over the observation time." The decay of `r_f` and `r_s` with their time constants already models this spontaneous recovery.
- Rankin et al. (2009), characteristic 10: "Some stimulus repetition protocols may result in properties of the response decrement ... that last hours, days or weeks", which they call long-term habituation. A break does not erase habituation.
- Vankov, Hervé-Minvielle and Sara (1995, Eur J Neurosci 7:1180-1187): locus coeruleus cells that responded on the first visit to each hole of a new board gave "no response to empty holes" in the next session. They responded only to the newly placed object, so the familiarity learned in one session survived the break.

Each running estimate the reset clears, decided from that literature:
- **Alert rates `r_f`, `r_s`: keep.** They are the habituation state itself. Recovery should follow the time away from the stimulus, which their decay already gives, and long-term habituation outlasts breaks.
- **Learning-progress error means: keep.** They are the entity's running expectation of its own forward models' error, and the forward models are not reset by sleep (adaptation is only suspended). Clearing them makes the entity treat a familiar input stream as if it had no history, the same unsupported reset of familiarity as for the alert rates; Vankov et al. show familiarity persisting across sessions. The means are time-weighted: the next report re-weights them by the gap, so a sleep changes them only as any interval of the same length does. Keeping them also lets learning progress register a change in error across the sleep.
- **Intent rate `r_int`: keep.** The cited literature is about responses to repeated stimuli and says nothing about the rate of one's own actions, so it gives no ground for resetting it either. `r_int` updates at every broadcast, and the cycle keeps broadcasting during sleep, so it decays through the sleep by its own rule when no intents occur. Clearing it adds a discontinuity that nothing motivates. The restlessness drive itself is still reset, as the other drives are.
- **Unchanged:** the reset still returns valence, arousal and dominance to baseline, sets every drive to 0 and re-arms its crossing, sets the categorical emotion to neutral, clears the active goals and a speaker's perceived emotion, and keeps the last wellness `w`. Resetting arousal and the drives is what keeps arousal from drifting across a run.

A replay of the third boot's recorded stream (gamma_D 0.2 as on main after #530) shows the sawtooth gone. In the first 180 s after each sleep, the share of time with arousal at or above 0.37 / 0.45 / 0.63 drops from 98% / 98% / 88% (clearing the rates) to 80% / 25% / 9% (keeping them), against 100% / 51% / 9% for the rest of the run. The mean habituation factor of post-sleep alerts drops from 0.544 to 0.081. The 20% below 0.37 is the first half minute after each reset, while the drives rebuild from 0 and the drive-raised target is still near `a_0`.

## What Changes

- Paper A.4 item 4 (PR #47, commit 320b415): the alert rates, error means, `r_int` and `w` carry on through the sleep. Items 1 and section 3.5 drop "or a reset" from the first-presentation wording.
- `Affect.affective_reset()` no longer clears `_alert_fast`, `_alert_slow`, the five error-mean dicts, `_intent_rate` or `_intents_since_broadcast`. Their own decay continues through the sleep.

## Capabilities

### Modified Capabilities

- `affect`: the sleep reset keeps the habituation and learning-progress estimates and the intent rate.

## Impact

- `kaine/modules/affect/module.py`, `docs/09-modules/affect.md`, affect tests.
- Behaviour: no post-sleep burst of arousal or access from the familiar stimulus, and no boredom relief from the reset itself. A sleep followed by a genuinely new scene still arouses through the burst term, and a long quiet still restores the first-presentation response as `r_s` decays.
