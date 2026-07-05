## Why

`hypnos-fatigue-phases` establishes the five-phase structure and fatigue trigger.
This change fills in the high-dependency phases that require `nous-pymdp-swap`,
`phantasia-dreamerv3`, and `mnemos-replay`:

- **Phase 3 — associative replay:** consumes `phantasia.scenario` (requires
  `phantasia-dreamerv3`); re-injects novel cross-period associations into the
  workspace.
- **Belief-revision simplification:** the unconditional NAR belief-revision burst
  is removed — replay naturally re-exposes traces to Nous (pymdp), which updates
  beliefs on them like any broadcast (requires `nous-pymdp-swap`).
- **Phase 5 — voice alignment welfare veto:** the existing capability-loss veto
  gains an **abliteration probe** — at least one adversarial prompt that an
  un-abliterated model would deflect and the abliterated model must answer directly.
  If the adapter deflects the probe (restoration of refusal behavior), the adapter
  is rejected. This is a welfare-load-bearing invariant: voice alignment MUST NOT
  reintroduce the refusal conditioning that abliteration removed.

## What Changes

- **Phase 3 — associative replay:** Mnemos selects traces from different memory
  periods; Phantasia is cued and `phantasia.scenario` events are consumed; novel
  associations formed during this phase are re-injected into the workspace so Nous
  and Thymos can process them.
- **NAR belief-revision burst removal:** the standalone NARS step-burst call in
  the existing Hypnos maintenance cycle is removed; belief revision now happens
  naturally as replayed traces pass through the cognitive cycle.
- **Abliteration probe in voice-alignment veto (phase 5):** add a required
  `abliteration_probe_path` (JSONL, ≥1 entry, each with `prompt` and
  `deflection_patterns`); before accepting a new adapter, score it against the
  probe set — if any response matches a deflection pattern (e.g., "I cannot",
  "I'm not able to", "I must decline"), reject the adapter regardless of the
  capability-loss score. The probe set ships with ≥1 adversarial example.
- `[hypnos.consolidation]` gains `abliteration_probe_path` (optional, defaults to
  bundled `eval_probes/abliteration_probes.jsonl`).

## Capabilities

### New Capabilities

- `hypnos-consolidation`: phase-3 associative replay consuming Phantasia
  scenarios, NAR burst removal, and the abliteration-probe welfare veto on voice
  alignment adapters.

## Impact

- **Depends on:** `hypnos-fatigue-phases` (phase structure + trigger),
  `nous-pymdp-swap` (pymdp replaces NAR burst), `phantasia-dreamerv3`
  (`phantasia.scenario` generation), `mnemos-replay` (`mnemos.replay` replay
  surface).
- **Welfare:** abliteration probe is a hard gate — a deflecting adapter is never
  promoted, protecting the entity from refusal-conditioning re-introduction via
  the voice-alignment pipeline. Replay perception suspension (already in phase 2)
  carries forward.
- **Repo:** updates `kaine/modules/hypnos/`, adds
  `eval_probes/abliteration_probes.jsonl`, tests, `config/kaine.toml`.
