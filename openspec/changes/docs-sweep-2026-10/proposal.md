## Why

The paper (Predictive Workspace) was revised on 2026-10-10 and is the authority
for the design. The code then moved to follow it: no per-source precision
weight, arousal as a global gain, graded intensity, per-member access, the
broadcast context with a null context and a per-report information gain, CAL
0.4, gestation progress that survives restarts, and a six-module first round
of the module-addition study. The book under `docs/` still described the
earlier design in many places and carried factual errors against the code
(module counts, gate condition counts, config defaults, file names that do not
exist), as well as wording that the paper no longer uses.

## What Changes

A full pass over every page of the book outside `docs/records/`:

- Bring each page into line with the revised paper and the merged code, and
  mark what is built and what is not (the matched and pooled arms, the
  positive control and calibration are not built).
- Correct the factual errors found by checking each page against the code,
  including every key of the configuration appendix against `config/kaine.toml`
  and the code's allowlists and defaults.
- Describe KAINE as a cognitive architecture for synthetic minds with
  replaceable modules; remove consciousness claims, safety-by-isolation claims
  and "sovereignty" wording; follow the project's writing rules (no dashes as
  punctuation).
- Regenerate the roadmap appendix.

The dated records under `docs/records/` are historical and are left as written.

## Capabilities

### Modified Capabilities

- `documentation-consistency`: the documentation follows the paper and the
  code of record.

## Impact

- Docs only: `docs/**` (65 pages) and the roadmap appendix.
- No code, no config, no behaviour change.
