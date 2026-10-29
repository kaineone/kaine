# Replay results (2026-10-20)

The tenth boot's intent log gave 1,508 cases (1,377 thoughts, 131 utterances, 10 waking requests with the situation section), none skipped. Each case ran under V5, V5m, V5e and V5l with 3 replicates at temperature 0.7 on the pinned organ (llama.cpp digest `ef08b5a9...`, Q4_K_M GGUF, the language module's request shape): 4,524 texts per variant. Scored with `score --rule v6`, 2,000 bootstrap draws.

## The run that decides (per-case seeds)

| Variant | Any meta | AI self-description | Second person | Disclosure | List | Echo | Loop | Grounded | Median chars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Live tenth boot (logged texts, same classifiers) | 23.2 | 0.27 | 1.4 | 0.1 | 15.3 | 7.8 | 0.9 | 48.5 | 88 |
| V5 (as logged) | 22.7 | 0.2 | 1.9 | 0.1 | 15.3 | 7.1 | 1.1 | 50.9 | 88 |
| V5m (no manner clause) | 18.6 | 0.2 | 2.4 | 0.1 | 13.5 | 2.9 | 0.8 | 50.8 | 83 |
| V5e (no system text) | 29.6 | 0.7 | 5.1 | 0.2 | 24.4 | 0.7 | 1.8 | 47.5 | 91 |
| V5l (no "- " marker) | 9.7 | 0.4 | 1.6 | 0.2 | 0.2 | 5.0 | 3.2 | 51.8 | 75 |

Percent of texts; grounded is the percent of texts sharing a modality with their awareness block. V5 reproduces the live boot's rates.

Paired differences from V5 over the non-waking cases (point, 95 percent interval), in points:

| Candidate | Any meta | Grounded | AI self-description | Passes |
| --- | --- | --- | --- | --- |
| V5m | -4.2 (-5.5 to -2.9) | -0.1 (-1.8 to 1.6) | +0.1 (-0.1 to 0.3) | no: AI self-description above 0 |
| V5e | +7.0 (5.4 to 8.5) | -3.4 (-5.2 to -1.5) | +0.5 (0.3 to 0.8) | no |
| V5l | -13.2 (-14.6 to -11.7) | +0.8 (-1.0 to 2.6) | +0.2 (0.0 to 0.4) | no: AI self-description above 0 |

Winner: none. Under the rule fixed before the run the persona stays at version 5. V5l removes nearly all list-form texts and cuts meta-commentary from 22.7 to 9.7 percent, but its AI self-description count rises from 7 to 16 texts in 4,524 (0.2 to 0.4 percent). The rule allows no rise, so adopting it would need a decision outside the rule.

Waking requests (30 texts per variant): any meta V5 10.0, V5m 23.3, V5e 6.7, V5l 23.3 percent.

The rule as committed before the run (57053057) named every request in the intent log as the cases, and the scoring code committed before the run computed the decision over all of them, the 10 waking requests included. The same text also said the waking requests do not enter the rule. Leaving them out of the decision was added after the first-pass review. With them included the verdict is the same: V5m fails (any meta -4.1, interval -5.5 to -2.7; grounded -0.1; AI self-description +0.1), V5e fails (any meta +6.9, interval 5.3 to 8.4), and V5l fails (any meta -13.0, interval -14.5 to -11.6; grounded +0.9; AI self-description +0.2). No candidate passes either way.

`BROAD_AI` and `BROAD_ECHO` widen the shared `ai_self()` and `echo()` classifiers, which every rule uses. `score --rule v2v3` on older result files, such as #558's, therefore reports higher AI self-description, echo and any-meta rates than #558 reported. The table layout is unchanged. Since identity-leak-whole (#580), `ai_self()` uses the language module's identity classifier, so `BROAD_AI` no longer exists and the v6 tables above were scored with it.

## The first run (set aside)

The first run sent every case of a replicate with one seed (1000, 1001, 1002). Its V5 gave 9.6 percent any meta and 1.0 percent list form against the live 23.2 and 15.3 percent. A diagnostic on 231 live list-form cases and 231 others: sent without a seed, as the language module sends them, 45 and 38 replayed texts opened a list (18 percent overall); sent with seed 1000, 2 and 0 did. A shared seed gives every case the same random stream, so the first run's three replicates were three correlated draws. Its rule outcome (no winner) is not used. The replay behind persona version 5 (#558) used the same seeding.
