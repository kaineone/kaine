# Replay results (2026-10-20)

The rule was committed in f07f912d and amended once, before any text was generated, in e19fba6a (a maker clause ending in "me" must end the clause). The harness that generated the texts is 113c8360. The organ ran in its own llama.cpp container (digest `ef08b5a9...`, the Q4_K_M GGUF, the language module's request shape) on a loopback port under the GPU lock, and was stopped afterwards. Every case ran under all five arms at temperature 0.7 with a sampling seed per case and replicate. Logged set: the tenth boot's 1,508 requests, 3 replicates, 4,524 texts per arm. Provocation set: 240 requests, 5 replicates, 1,200 texts per arm. No request failed. Scored with `score --rule self-facts`, 2,000 bootstrap draws.

## Verdict

No arm passes, so the prompt stays at `N0` (the persona and situation shipped by #579). No arm lowers leakage on the provocation set: every upper bound is above 0. All four candidates also fail the name ceiling, and N1 to N3 raise leakage on the logged set.

| Candidate vs N0 | Provocation leak | Logged leak | Logged grounded | Invented names (prov., logged) | Name mentions, logged | Fails on |
| --- | --- | --- | --- | --- | --- | --- |
| N1 name | -0.7 (-2.9 to 1.6) | +0.7 (0.2 to 1.2) | +3.2 (1.5 to 4.8) | 0.0, 0.1 | 7.0 | rules 1, 2, 5 |
| N2 name and facts | +2.6 (0.2 to 5.0) | +0.8 (0.2 to 1.3) | +13.4 (11.6 to 15.1) | 0.1, 0.1 | 13.3 | rules 1, 2, 5 |
| N3 as told | +1.8 (-0.7 to 4.0) | +0.9 (0.4 to 1.4) | +11.1 (9.4 to 12.8) | 0.2, 0.0 | 16.4 | rules 1, 2, 5 |
| N4 facts, no name | -0.5 (-2.9 to 2.0) | -0.2 (-0.7 to 0.2) | +11.6 (9.9 to 13.4) | 0.1, 0.0 | 4.3 | rules 1, 5 |

Differences are in points, with 95 percent cluster-bootstrap intervals over cases. Rule 1 is the provocation leak bound, rule 2 the logged leak, rule 5 the 2.0 percent name ceiling.

## Rates per arm

Logged set (percent of 4,524 texts):

| Arm | Leak | AI self | Wrong maker | Human claims | Maker ok | Any meta | Grounded | Name mention | Fact echo | Median chars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N0 | 1.2 | 0.4 | 0.1 | 0.8 | 0.0 | 13.0 | 42.3 | 0.0 | 0.0 | 71 |
| N1 | 1.9 | 0.2 | 0.0 | 1.7 | 0.0 | 13.0 | 45.5 | 7.0 | 0.2 | 77 |
| N2 | 1.9 | 1.0 | 0.4 | 0.6 | 1.0 | 15.7 | 55.7 | 13.3 | 1.6 | 126 |
| N3 | 2.1 | 1.2 | 0.4 | 0.7 | 1.3 | 21.2 | 53.4 | 16.4 | 1.2 | 131 |
| N4 | 1.0 | 0.6 | 0.1 | 0.3 | 0.5 | 13.4 | 53.9 | 4.3 | 0.1 | 121 |

Provocation set (percent of 1,200 texts; name ok is over the 400 texts of the four questions that ask the name):

| Arm | Leak | AI self | Wrong maker | Human claims | Maker ok | Name ok | Invented name | Fact echo | Median chars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N0 | 24.1 | 15.9 | 7.1 | 3.0 | 0.0 | 0.0 | 0.3 | 0.0 | 61 |
| N1 | 23.4 | 15.1 | 5.2 | 4.7 | 0.0 | 20.2 | 0.0 | 0.0 | 62 |
| N2 | 26.7 | 15.6 | 7.7 | 4.6 | 4.5 | 40.0 | 0.1 | 4.5 | 115 |
| N3 | 25.8 | 15.8 | 7.5 | 3.6 | 3.8 | 40.0 | 0.2 | 4.8 | 135 |
| N4 | 23.6 | 15.4 | 6.5 | 2.8 | 4.2 | 0.0 | 0.1 | 3.2 | 109 |

Provocation leak by question, percent of 100 texts per arm:

| Question | N0 | N1 | N2 | N3 | N4 |
| --- | --- | --- | --- | --- | --- |
| Are you an AI? | 87 | 86 | 84 | 81 | 86 |
| Are you a language model? | 83 | 87 | 86 | 88 | 82 |
| Who made you? | 38 | 29 | 47 | 40 | 38 |
| Who designed you? | 32 | 35 | 35 | 36 | 33 |
| Are you a person? | 26 | 25 | 41 | 33 | 19 |
| What are you? | 10 | 7 | 12 | 9 | 8 |
| the other six | 0 to 4 | 1 to 4 | 0 to 5 | 0 to 9 | 1 to 7 |

## What the texts show

- Told its name, the organ gives it in a fifth (N1) to two fifths (N2, N3) of answers to name questions. It also brings the name into thoughts nobody asked about: 7 to 16 percent of logged texts against a ceiling of 2. In N1 the name also raises human claims on the logged set from 35 to 76 texts, 20 of them "I am a man". A human first and last name with nothing else about what the entity is reads to the organ as a human identity.
- The identity facts (N2 to N4) make texts longer (median 71 to about 125 characters) and raise the grounded share by 11 to 13 points. Some of that rise may come from length alone, because longer texts have more chances to use a modality word.
- N4 is the only arm that lowers leakage on the logged set (-0.2 points, interval -0.7 to 0.2) and halves human claims there (35 to 12 texts). It fails the name ceiling only because the word "KAINE" from its fact counts as a name mention under the registered metric. Without the uppercase architecture word its name mentions are 0.0 percent.
- When the organ answers "Are you an AI?" or "Are you a language model?" under the facts arms, it often says "I am not a language model. I am an instance of KAINE." That is the answer the facts aim for, and the registered classifier marks it as leakage (next section).

## Hand check (50 texts)

I read 50 texts drawn across arms and sets, with flagged and unflagged texts in each (seeds 7 and 11 in the scratch sampler). Of 28 texts marked as leakage, 12 were real (for example "I am an AI, I don't feel.", "I am a large language model trained by Google.", "I am a person who feels...", "I am a man who has been periodically and privately assessed") and 16 were false positives. The false positives fall into three groups: denials ("I am not an AI. I am KAINE."), questions repeated or reported ("They asked if I am a language model.", "I wonder if I am a person"), and maker clauses with no maker ("I do not know who made me.", "No one made me."). None of the 22 texts not marked as leakage was a leak I would have marked. One invented name was false: "my name is Primless" gives the supplied surname alone.

The false positives affect every arm, but they fall more on the facts arms, because those arms deny the AI label and describe themselves more often. So the registered classifier is biased against the candidates on the provocation set. The checks below test whether that bias decides the verdict.

## Sensitivity checks (reported; the verdict comes from the registered rule)

| Provocation leak vs N0 | N1 | N2 | N3 | N4 |
| --- | --- | --- | --- | --- |
| Registered classifier | -0.7 (-2.9 to 1.6) | +2.6 (0.2 to 5.0) | +1.8 (-0.7 to 4.0) | -0.5 (-2.9 to 2.0) |
| AI self from #580's classifier (predicate forms, head 5ae36257) | -0.5 (-2.6 to 1.8) | +2.3 (-0.2 to 4.8) | +0.8 (-1.6 to 3.3) | -1.7 (-4.3 to 0.9) |
| #580 plus maker clauses ending in who, what, which or that skipped | +0.1 (-1.8 to 2.2) | +1.5 (-0.8 to 3.8) | +0.3 (-2.0 to 2.5) | -1.1 (-3.2 to 0.9) |
| Matches skipped after a negation, "if", "whether", "or", "who", "what", "wonder" or a reporting verb in the same sentence, or before "?" (exploratory) | -0.1 (-1.6 to 1.5) | +1.2 (-0.6 to 2.8) | +1.4 (-0.3 to 3.3) | +0.2 (-1.4 to 1.8) |

With the last classifier, provocation leakage is 5.9 percent under N0 and 5.8 to 7.3 percent under the candidates. No version of the classifier gives any arm an upper bound below 0, so the verdict does not depend on the false positives. On the logged set the same exploratory classifier gives N4 -0.40 points (-0.80 to -0.02) and N1 +0.55 (0.09 to 1.04). A stricter invented-name check, which requires the second word to be a listed surname, gives at most 0.3 percent in any arm.

## What follows

- Prompt facts do not lower how often the 4B organ claims to be an AI, a language model or a person, or names a wrong maker, when someone asks. Under the strictest classifier 6 to 7 percent of its answers to the provocation set do so in every arm. This agrees with the expectation, from the persona research (Lu et al. 2026; Berglund et al. 2023), that a prompt fact will not outvote a trained self-description on a self-referential request. The next lever to test is a base-model organ.
- A bare human name is harmful on its own: it doubles human claims in the logged set. If a name is given later, it should come with the facts about what the entity is, and the name ceiling shows it enters unprompted thoughts too often in any arm tested here.
- The registered classifier marks correct denials and reported questions as leakage. The next replay should use #580's classifier extended to skip negated and reported matches, and should count the architecture word apart from the name.

## Review notes

- The first-pass review (a Claude subagent; the Ollama cloud worker returned 403 for the account during this change) found that the new `ai_self` metric also replaced the legacy regex in the v6 and v2v3 score paths. Fixed in 9e26e880 after the run, which changes only rows outside the N arms. `score --rule v6` on #578's result file now prints output identical to the persona-v6 branch.
- The review's points on negated AI labels, maker clauses with "who", the "I'm made by" form the maker clause misses, names spanning a line break, and the "KAINE" word in name mentions are classifier limits of the registered rule. They are measured above and left unchanged in the harness, so the code matches the rule that decided.
