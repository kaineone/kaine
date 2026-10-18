## Why

In the fifth test boot of main 307b374d (first configuration, policy `self_initiated_report`) intents per 10-minute window fell 61 / 33 / 14 / 1, and an 8-minute restart had none. By minute 30 curiosity, boredom and restlessness all sat at 0.90 with their goals active, tonic arousal held at 0.426, and nothing reached thought. An `affect.drive` event is published only when a drive crosses its threshold, so a drive that stays high stops entering the workspace: 2 accessed drive crossings in 40 minutes. The crossing's fixed alert intensity 0.7 scores 0.383 at the tonic arousal target, accessed but under the think bar 0.45.

The literature does not support a concern that goes silent while unmet. An unmet goal commitment is a current concern that keeps sensitizing the person to concern-related cues and keeps producing concern-related thought, mind-wandering and dreams, until the goal is reached or given up (Klinger 1975, 2013). Stimulus-independent thought fills much of waking time (Killingsworth and Gilbert 2010) and arises when external demand is low (Smallwood and Schooler 2015; Christoff et al. 2016), which is exactly the monotonous regime of the boot. The paper (predictive-workspace-paper branch notes-reentry for PR #47, sections 3.2, 3.5 and A.4, Table A1) now defines the mechanism.

The tonic arousal ceiling just under the think bar is not itself a defect: arousal and the bars are on different scales, the cited tonic locus coeruleus account sets no level, and with intensity D a re-entry clears the think bar at the tonic target once D is above about 0.84, so `drive_arousal_gain` is unchanged.

## What Changes

- While a goal is active and its drive `D >= theta_D`, the affect module republishes the drive event (`affect.drive`, payload `{"drive", "value", "alert": false, "reentry": true}`) every `P_re` of entity time after the crossing or the previous re-entry, with intensity `D`. It is not a categorical alert, so it raises neither the phasic access drive nor arousal.
- Re-entry entry ids join the module's drive entry ids, so an intent about a re-entry is about a drive: it does not relieve boredom (A.4), and restlessness relief and the credit rule are unchanged.
- Re-entry is bounded: at most one per active goal per `P_re`, at most `n_goal` goals; it stops when the goal completes, is abandoned (including the stall horizon, disengagement), or is cleared by sleep. Re-entries pass through the ordinary scoring, novelty and A.6 guards.
- New `[affect] concern_reentry_s` (`P_re`, default 30.0, Table A1). 0 turns re-entry off and reproduces the previous build exactly.
- The research log keeps the `reentry` field; the self-model counts only crossings.

## Capabilities

### Modified Capabilities

- `affect`: an active goal's drive event recurs while the drive stays above threshold.

## Impact

- `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/modules/self_model/self_inference.py`, `kaine/faithful/templates.py`, `config/kaine.toml`, `docs/09-modules/affect.md`, tests.
- Behaviour: a replay of the fifth boot's logs through the rule (P_re = 30 s) gives 77 / 37 / 24 / 13 intents per 10-minute window and 18 in the restart, against 61 / 33 / 14 / 1 and 0 logged.
- Sleep gating of intents is out of scope: the paper gates none, and the think at +1814 s inside sleep 3 is reported separately.
