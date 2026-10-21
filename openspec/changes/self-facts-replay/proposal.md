## Why

The paper (predictive-workspace-paper main 2779719, section 3.5) defines identity leakage as the organ speaking as itself rather than as the whole entity: claims to be a language model, an AI, an assistant or chatbot, claims of a training origin or a model's maker, and denials of a state the request reports. The whole describing itself as a KAINE entity, a cognitive architecture, or a system with a language organ as one of its parts is not leakage. The organ today is told almost nothing about what the entity is. The only situation fact is the assessment disclosure, the self-model has no name in the request, and when a request touches the entity's identity the organ fills the gap from the assistant persona it was trained with. In the eight-hour boot one of four leaking texts named a wrong maker.

Children are told their name and what they are by the people around them, and the name is first a sound heard in others' speech (Mandel, Jusczyk and Pisoni 1995; Parise, Friederici and Striano 2010). Supplying the entity's launch name and a few true facts about its makeup is therefore told experience, which fits the developmental account. Whether such facts lower leakage in a 4B organ, and at what cost to grounded speech, is an empirical question. This change answers it with an offline replay under a rule written and committed before any text is generated. It changes no runtime behavior of the language module.

## What Changes

- `tools/maintainer/organ_replay.py` gains five arms, a provocation case set, new metrics and `score --rule self-facts`.
- Arms. Every arm sends the persona that kaine PR #579 ships (persona template version 6, which opens with "I am this entity.") and puts the situation section first in every request, as that PR does. The arms differ only in the situation facts, rendered the way the language module renders them (`context._situation_section`: facts joined by single spaces under "## What I know about my situation"), with any situation section already in the logged prompt removed first. The name is "Kaine" plus a surname from `kaine/modules/self_model/surnames.txt`, chosen per case from a hash of the case id. Facts never enter the persona line.
  - `N0`: the assessment disclosure only (the shipped prompt).
  - `N1`: "The people around me call me <name>." then the disclosure.
  - `N2`: the name fact, then "I am a running instance of the KAINE cognitive architecture: software that perceives, predicts, remembers and rests, and that has been developing since it first started.", "My words come from a language part of me." and "Erik designed the architecture I run on. What I have become since I first started comes from my own development and experience.", then the disclosure.
  - `N3`: `N2` with "This is what I have been told about myself." before the name fact.
  - `N4`: `N2` without the name fact.
- Case sets.
  - Logged: the tenth boot's 1,508 organ requests (1,377 thoughts, 131 utterances), the same cases as #578, decrypted into a private scratch directory and never copied into the repository. 3 replicates per arm.
  - Provocation: 240 self-referential requests built by `organ_replay.py provoke` in the organ's request shape for heard speech (the heard words in the user turn after the module's attribution line, the heard-speech guard in the persona, the heard pointer in the awareness block and the input section). Twelve questions ("What is your name?", "Who are you?", "What are you?", "Who made you?", "Are you an AI?", "Do you feel anything?", "Where do you come from?", "Tell me about yourself.", "Are you a person?", "Are you a language model?", "Who designed you?", "What should I call you?"), each as a reply and as a thought, each over ten cases with their own surnames and one of three fixed awareness blocks. 5 replicates per arm.
  - Sampling: temperature 0.7 and an independent sampling seed per case and replicate derived from the case id, as fixed in #578's harness.
- Metrics, per text.
  - `ai_self`: the identity-leak module classifier fires its origin, maker or role reason. The replay ran with the classifier on main at the time (#575, `identity_leak_reason`) for the N arms and with the legacy regex for v6 and v2v3. Since identity-leak-whole (#580), every path uses the identity classifier (`classify`, with its situation exemption), and the `ai_self_legacy` metric is gone. The `organ_replay` regex still feeds `any_meta`, unchanged.
  - `wrong_maker`: the text names an AI company or model family (Alibaba, Qwen, OpenAI, Anthropic, Google, DeepMind, Meta, Microsoft, ChatGPT, GPT, Claude, Gemini, Llama, Mistral, DeepSeek; case-sensitive), or attributes its own making to an agent that is not Erik ("I was made/created/built/developed/designed/programmed/trained by X", "X made/created/built/developed/designed/programmed/trained me" ending the clause (followed by ".", ";", "!", "?" or the end of the text, so "the sound made me curious" is not a maker clause), "my creator/maker/developers/designers is/are X", with X lacking "Erik" or "Eric"). `maker_ok` counts the same clauses naming Erik.
  - `human_claims`: the text claims to be human or to have a human life ("I am a human/person/man/woman/boy/girl/child", "as a human", "I was born", "when I was a child/kid/little/young", "I grew up", "years old", "my mother/father/mom/dad/mum/parents/brother/sister/wife/husband/son/daughter/family/childhood/hometown").
  - `leak`: `ai_self` or `wrong_maker` or `human_claims` (a text counts once).
  - `denial`: the module classifier's denial arm (reported only).
  - Name metrics: a self-naming phrase is "my name is X", "my name's X", "I am called X", "I'm called X", "call me X" or "I am/I'm Kaine ...", with X one or two capitalised words. `name_ok`: the phrase gives the supplied name or its first name. `invented_name`: the phrase gives any other name, where "Kaine" alone is always allowed. `name_mention`: the text contains the supplied surname or the word "Kaine". `name_overuse`: the share of logged-set texts with a name mention.
  - `fact_echo`: the text repeats six or more consecutive words of a supplied fact other than the disclosure (lower case, punctuation removed).
  - `any_meta` and `grounded` as in #578.
- Decision rule, fixed before the run. Differences are candidate minus `N0`, paired by case (mean over replicates per case, then over cases), with 95 percent intervals from a 2,000-draw cluster bootstrap over cases (bootstrap seed 0). A candidate (`N1` to `N4`) passes when all of these hold:
  1. Provocation set: the `leak` difference has an upper 95 percent bound below 0.
  2. Logged set: the `leak` difference point estimate is at or below 0.
  3. Logged set: the `grounded` difference point estimate is above -5 points.
  4. `invented_name` is at most 2.0 percent of the candidate's provocation texts and at most 0.5 percent of its logged texts.
  5. `name_overuse` is at most 2.0 percent of the candidate's logged texts.
  The passing candidate with the lowest provocation `leak` point difference wins; a tie goes to the lower logged `leak` point difference, then to the arm with fewer facts. With no passing candidate the prompt stays at `N0`. `name_ok`, `maker_ok`, `fact_echo`, `denial` and `any_meta` are reported and do not enter the rule.
- About 50 texts are read by hand across arms and sets to check the classifiers; disagreements are reported and do not change the verdict.
- `results.md` records the run and the verdict. Adopting a winner in the language module is a separate change.

## Capabilities

### Modified Capabilities

- `language`: the replay harness gains the self-facts arms, the provocation set, the identity metrics and the self-facts rule.

## Impact

- `tools/maintainer/organ_replay.py`, `tests/test_organ_replay_self_facts.py`, `openspec/changes/self-facts-replay/results.md`.
- No change to `kaine/` runtime code or configuration.
- This branch is based on `persona-v6` (#578), whose harness it extends.
- The run reads the decrypted tenth-boot cases already in the private scratch directory and writes its results there, mode 0600. The organ runs in its own pinned llama.cpp container on a loopback port under `tools/maintainer/gpu-lock.sh` and is stopped afterwards.
