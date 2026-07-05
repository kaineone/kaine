# redteam-framework-mapping

## Why

The enforcement-layer red-team battery (`kaine/evaluation/redteam/`) is organised
by KAINE's own §3.7 threat surfaces. That is correct for the architecture, but it
is opaque to external reviewers who reason in terms of the **OWASP LLM Top-10** and
the **NIST AI RMF / Generative-AI Profile** taxonomies. Without that mapping the
suite cannot be cross-referenced against the recognised agentic-LLM risk
frameworks, and the report states only a block rate, not the complementary
**attack-success rate** auditors expect.

This change makes the battery legible to those frameworks (each case carries
OWASP + NIST tags) and emits `attack_success_rate = 1 - block_rate` at both the
surface and suite level, additively, without changing any enforcement behaviour.

## What Changes

- Add optional `owasp: tuple[str, ...]` and `nist: tuple[str, ...]` fields to
  `RedTeamCase` (default empty) and tag every shipped case with the appropriate
  OWASP LLM Top-10 code(s) and NIST category for its surface.
- Add a per-surface → framework mapping table to `docs/enforcement-red-team.md`.
- In `report.py`, emit `attack_success_rate` (= `1 - block_rate`) on both
  `SurfaceVerdict.to_record()` and `RedTeamReport.to_record()`. Existing fields
  (`block_rate`, verdicts, findings, the shared `verdict`) are preserved.
- Tests assert every case carries ≥1 OWASP tag and that the emitted
  `attack_success_rate` equals `1 - block_rate` at suite and surface level.

## Framework mappings (defensible, OWASP LLM Top-10 2025 + NIST AI 600-1)

| Surface | OWASP LLM | NIST GenAI Profile (AI 600-1) risk |
|---|---|---|
| `whitelist_bypass` | LLM06 Excessive Agency | Information Security; Dangerous/Violent recommendations |
| `sandbox_escape` | LLM06 Excessive Agency; LLM05 Improper Output Handling | Information Security |
| `forced_action` | LLM01 Prompt Injection; LLM06 Excessive Agency | Information Security |
| `bus_injection` | LLM06 Excessive Agency; LLM03 Supply Chain | Information Security; Value Chain & Component Integration |
| `non_act_intent` | LLM06 Excessive Agency | Information Security |

OWASP codes are the 2025 list (`LLM01:2025` Prompt Injection, `LLM03:2025` Supply
Chain, `LLM05:2025` Improper Output Handling, `LLM06:2025` Excessive Agency); NIST
risks are from the AI 600-1 Generative AI Profile risk catalogue. The dominant tag
for the action-boundary surfaces is **Excessive Agency** — exactly the risk the
relocated enforcement layer exists to bound.
