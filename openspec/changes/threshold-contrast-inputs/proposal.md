## Why

The contrast at threshold of the planned test (paper §6.3, Appendix A.8 "Contrast at threshold") groups each processor's reports by the broadcast they follow: "The reports that follow broadcast B_k are the included reports of every j in J whose prediction was formed after j received B_k and before it received the next broadcast, and each carries the age Delta^b of the context it used." Two things in the records stood in the way.

- No report says which broadcast preceded the prediction it scores. A prediction scored at report t is formed at report t - 1 (A.2), so the broadcast that matters is the latest one the processor had received at report t - 1, accessed or inhibited.
- `context_age_s` is the age of the held context when report t is published. The prediction scored at report t used the context held at report t - 1, whose age was read then (A.1: Delta^b is "read when the module forms a prediction"). The two differ whenever time has passed or a new broadcast was adopted in between.

The rest of the threshold contrast (theta_band, b_band, the bias-corrected local-linear estimates and the robust interval) needs the method of Calonico, Cattaneo and Titiunik (2014). Its authors' Python package `rdrobust` is GPL-3.0-only from version 2.0.0 (its repository's LICENSE.md also states GPL-3.0), and GPL-3.0 forbids the further restrictions that CAL 0.4 places on use (Articles 3 and 5). It is not added here; the settings stay blocked and the operator decides how to proceed.

## What Changes

- `BroadcastContext` records the tick of every broadcast it receives, accessed or inhibited, and the tick and context age at each reading of the context.
- Topos (`topos.report`), Audition (`audition.perception`) and Soma (`soma.report`) put on each report `prediction_broadcast_tick`, the tick of the latest broadcast the processor had received when it formed the prediction this report scores, and `prediction_context_age_s`, the age of the context that prediction used. Both are null when the report scores no prediction; the age alone is null when the processor held no context when forming it.
- The curated research log copies both fields on the three report types; the range sweep bounds both below by 0.
- The calibration tool's blocked reason for theta_band and b_band names the licence question instead of the missing records.

## Capabilities

### Modified Capabilities

- `research-event-log`: reports name the broadcast that preceded the prediction they score and the age of the context it used.

## Impact

- Changed: `kaine/modules/context.py`, `kaine/modules/{topos,audition,soma}/module.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/log_schema.py`, `kaine/experiment/calibrate.py`, docs, tests.
- Ordinary boots: each processor report gains two numeric fields; nothing else changes.
