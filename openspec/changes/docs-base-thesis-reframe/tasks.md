<!-- Documentation-content change. Depends on thesis-test-configuration landing
     first. No code, no config, no behavior change. Every file is public content
     for Erik's review before it ships. -->

## 1. Front-door docs (tier 1 — review the framing here first)

- [ ] 1.1 `docs/README.md` — lead with the base-thesis form; update the modules index
  to mark the active five vs. gated.
- [ ] 1.2 `docs/for-researchers.md` — the offline ablation path + the observed live
  run; observed-not-conversed; reference stimulus corpus.
- [ ] 1.3 `docs/getting-started.md` — install + supervised first boot of the
  base-thesis form (default profile), reference-corpus manifest as the live upgrade.
- [ ] 1.4 `docs/architecture.md` — base-thesis default; perception-as-prediction-error;
  self-initiated voice; output-is-provably-workspace-mediated; richer faculties gated.
- [ ] 1.5 `docs/configuration.md` — the base-thesis toggle set + the new keys
  (`transcription_enabled`, `[volition].policy`, playlist manifest); default profile.
- [ ] 1.6 `docs/reproducing-results.md` — the workspace-mediation ablation as the
  primary falsifier; retire A/B divergence; seeded (offline) vs reference corpus (live).

## 2. Module docs (tier 2)

- [ ] 2.1 Mark each `docs/modules/*.md` as base-thesis-active (soma/chronos/topos/
  audition/lingua) or gated; keep the gated ones' content.
- [ ] 2.2 `docs/modules/audition.md` — STT off by default; audio as prediction error.
- [ ] 2.3 `docs/modules/lingua.md` — output-only voice; self-initiated report, not
  conversational.
- [ ] 2.4 `docs/modules/topos.md` — foveated raw-video perception.

## 3. Consistency pass (tier 2)

- [ ] 3.1 `ARCHITECTURE.md`, `FIRST_BOOT.md`, `SETUP.md` — base-thesis default,
  module framing, boot path.
- [ ] 3.2 Repo-wide: "seeded stimulus" → "reference stimulus corpus" for the LIVE
  tier (keep "seeded" for the offline ablation); drop the A/B divergence description;
  add the output-provably-workspace-mediated property; reconcile module counts.
- [ ] 3.3 `docs/glossary.md`, `docs/deployment-*`, `docs/tech-choices.md` — terminology
  and framing consistency.

## 4. Review

- [ ] 4.1 Front-door tier reviewed by Erik before the breadth pass propagates the
  framing to the remaining files.
- [ ] 4.2 Full docs pass reviewed before publishing (public content).
