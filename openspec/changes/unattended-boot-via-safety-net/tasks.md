## 1. Unattended supervision mode: selection and wiring

- [ ] 1.1 Extend supervision-mode resolution in `kaine/cycle/__main__.py` so `KAINE_CYCLE_UNATTENDED=1` selects `"unattended"` and the existing supervision-mode config key accepts `"unattended"` as a third value.
- [ ] 1.2 Implement precedence (unattended env var over research/operator-present selections from config or env) with a warning that names the overridden selection; alter nothing when unattended is not selected.
- [ ] 1.3 Ensure the unattended path initializes only cycle machinery — no experiment registry, no admissibility checks, no research-only modules; condition 3 accepts `[evaluation]` alone.
- [ ] 1.4 Unit tests for mode resolution: env-only selection, config-only selection, both set, precedence + warning, and no-selection default unchanged.
- [ ] 1.5 Integration test that an unattended boot never imports or initializes research-only modules (assert via import hook or module-registry snapshot).

## 2. Safety-net reuse and the Spot liveness probe (condition 6)

- [ ] 2.1 Extract the five-condition net evaluation in `kaine/cycle/research_gate.py` into a form callable from both research and unattended boots, with zero behavior change for research boots (existing research-gate tests pass unmodified).
- [ ] 2.2 Implement `probe_spot_supervisor()` (e.g., `kaine/cycle/spot_probe.py`) returning a structured result for checks S1 enabled / S2 live / S3 armed, using the same config keys and liveness interface the spot-supervisor capability itself uses.
- [ ] 2.3 Wire the probe into the unattended gate as condition 6 ("Spot supervisor live with freeze/recovery armed"); the research gate's evaluation and output must not include condition 6.
- [ ] 2.4 Give condition 6 distinct failure reasons — "not enabled", "not live", "not armed" — surfaced in the refusal text.
- [ ] 2.5 Enforce probe semantics: runs before the entity starts, hard timeout on the liveness check, no caching across boots, read-only (test asserts no supervisor state mutation).
- [ ] 2.6 Unit tests with a fake supervisor: healthy passes; disabled / not-registered / hung-past-timeout / freeze-hook-missing / ladder-unconfigured each fail with the correct reason.

## 3. Exit code and refusal diagnostics

- [ ] 3.1 Confirm exit code 6 is unused across the repo (exit-code constants and the refusal table in `docs/for-researchers.md`), then add `EXIT_UNATTENDED_REFUSED = 6` beside the existing constants in the cycle package.
- [ ] 3.2 Emit the unattended refusal diagnostic: one `N: name` line per failed condition (1–6) on stderr, with the Spot sub-check reason appended for 6, then exit 6.
- [ ] 3.3 Test the refusal matrix: each of conditions 1–6 broken individually → exit 6 with exactly that condition named; all broken → all six named.
- [ ] 3.4 Regression tests: research failure → 5 (conditions 1–5 only, message unchanged); operator-present failure → 2 (message unchanged); no-selection default path unchanged.
- [ ] 3.5 Test that no skip/override env var or config flag bypasses the unattended gate: with a broken net, every candidate override still yields exit 6.

## 4. Documentation

- [ ] 4.1 Add an exit-code-6 row to the refusal table in `docs/for-researchers.md` (unattended boots; conditions 1–6 including the Spot supervisor probe); leave the 2 and 5 rows' meanings and wording unchanged, at most adding a cross-link to the unattended section.
- [ ] 4.2 Add an "Unattended boots" subsection to `docs/for-researchers.md`: selection env var and config key, the six conditions with condition 6's enabled/live/armed detail, the no-override statement, the not-a-research-run note, and that operator-present remains for supervised/first boots.
- [ ] 4.3 Update every other page that enumerates supervision modes or `KAINE_CYCLE_*` environment variables (operator guide, README env table) to include `KAINE_CYCLE_UNATTENDED` and exit code 6.
- [ ] 4.4 Add or extend a docs-consistency test that parses the refusal table and asserts rows 2, 5, and 6 exist, row 6 mentions the Spot supervisor, and the 2/5 row texts match their pre-change snapshots.

## 5. Quadlet `[Install]` change

- [ ] 5.1 In the shipped quadlet (the `.container` unit), set `[Install] WantedBy=multi-user.target` and remove any `default.target`, graphical, or user-session `WantedBy=` value.
- [ ] 5.2 Set `Environment=KAINE_CYCLE_UNATTENDED=1` in the quadlet's `[Container]` section (or its equivalent env mechanism) so the boot-time unit runs the unattended gate.
- [ ] 5.3 Packaging test: parse the quadlet and assert `WantedBy=multi-user.target` and the unattended env var are present; run `systemd-analyze verify` on the unit when systemd is available in the test environment.
- [ ] 5.4 Update the quadlet's accompanying README/comment block: enabling the unit means unattended boot, and the gate is the machine-verified safety net plus Spot probe, not operator presence.

## 6. End-to-end acceptance

- [ ] 6.1 End-to-end test on a tmp install fixture: healthy install + unattended env → net and probe run in preflight, cycle starts, no research modules initialized.
- [ ] 6.2 End-to-end test: unattended with each condition individually broken → exit 6 and the exact condition named on stderr; assert the entity loop never starts.
- [ ] 6.3 End-to-end regression sweep: research boot (healthy and broken → 5), operator-present boot (failure → 2), and no-selection default all behave exactly as before this change.