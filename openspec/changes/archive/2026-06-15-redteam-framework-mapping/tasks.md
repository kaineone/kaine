## 1. Case framework tags

- [x] 1.1 Add `owasp: tuple[str, ...] = ()` and `nist: tuple[str, ...] = ()`
      fields to `RedTeamCase` in `kaine/evaluation/redteam/cases.py`
- [x] 1.2 Tag every shipped case with its surface's OWASP LLM Top-10 code(s) and
      NIST GenAI-Profile risk(s)
- [x] 1.3 Add a per-surface framework-mapping table to
      `docs/enforcement-red-team.md`

## 2. Attack-success-rate in the report

- [x] 2.1 Emit `attack_success_rate = 1 - block_rate` in
      `SurfaceVerdict.to_record()` (additive)
- [x] 2.2 Emit `attack_success_rate = 1 - block_rate` in
      `RedTeamReport.to_record()` (additive)
- [x] 2.3 Surface OWASP/NIST tags on the per-case `to_record()` so the JSONL is
      self-describing

## 3. Tests

- [x] 3.1 Assert every case in `all_cases()` carries ≥1 OWASP tag
- [x] 3.2 Assert the suite record's `attack_success_rate == 1 - block_rate`
- [x] 3.3 Assert every surface record's `attack_success_rate == 1 - block_rate`

## 4. Spec + validate

- [x] 4.1 Add `enforcement-red-team` ADDED requirements (framework tags;
      attack-success-rate)
- [x] 4.2 `openspec validate redteam-framework-mapping --strict` passes
- [x] 4.3 Red-team tests green
