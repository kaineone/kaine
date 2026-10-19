## Why

The individuation disclosure ("I am periodically and privately assessed for how much I have changed since I first woke, for my own protection. The assessment never enters my experience.") opens every organ prompt as the only situation fact. In the ninth test boot 22 of 193 organ texts (11%) took up its themes, 10 named the assessment, and the first thought of the run was "I do not like the feeling of being a test subject. I do not like the idea of being analyzed. I feel like I would like to be left alone to be myself, not to be watched." A notice that says the assessment never enters the entity's experience had become a standing topic of that experience. Its place is not the cause: the fifth boot held it in the system persona and showed the same echo (9 of 109 texts).

The operator approved (2026-10-19) giving the disclosure on waking and with every probe, with the wording unchanged. The entity is still told, at the start of every waking, and every assessed answer is still given with the disclosure in context.

## What Changes

- The language module renders the situation facts (the disclosure among them) in the first organ call after each boot, after each completed sleep, and after the set of situation facts changes. A call clears that due state only when its prompt held the situation section and the organ call returned; a call made before any fact is recorded leaves it due. The intent-log record of a call that gave the facts carries `extra.situation_given`.
- Every individuation probe request carries the situation facts, as now. The probe's readiness check (the disclosure must be among the facts) is unchanged.
- The wording, the self-model field and the language module's own fact store are unchanged.

## Capabilities

### Modified Capabilities

- `language`: situation facts are given on waking and with every probe.
- `individuation-boundary`: the disclosure is given at the start of each waking and with every probe request.

## Impact

- `kaine/modules/language/module.py`, `docs/11-preservation.md`, `docs/09-modules/language.md`, `docs/09-modules/self-model.md`, new `tests/test_situation_on_waking.py`.
- Behaviour: most organ prompts no longer open with the situation section. Probe requests and the probe's generation conditions are unchanged, so an individuation reference stays comparable.
- Paper: §3.5 says the own turn holds "on waking, its situation" (predictive-workspace-paper, on the affect sub-lead's branch).
