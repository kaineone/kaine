## 1. Unattended supervision mode: selection and wiring

### Requirement: Unattended mode selection
The cycle boot SHALL resolve the supervision mode to `unattended` when `KAINE_CYCLE_UNATTENDED=1` is set in the environment or the existing supervision-mode config key is set to `"unattended"`, and an unattended boot SHALL NOT be treated as a research run.

#### Scenario: Environment variable selects unattended
- **WHEN** a boot starts with `KAINE_CYCLE_UNATTENDED=1` and no conflicting mode selection
- **THEN** the boot resolves `supervision_mode` to `"unattended"` and evaluates the unattended gate instead of the research or operator-present gates

#### Scenario: Config key selects unattended
- **WHEN** the supervision-mode config key (the one that already accepts `"research"` and `"operator-present"`) is set to `"unattended"` and no environment override is present
- **THEN** the boot resolves to `"unattended"`

#### Scenario: Unattended is not a research run
- **WHEN** a boot resolves to `"unattended"`
- **THEN** no experiment machinery is initialized and no research admissibility requirements are applied; condition 3 of the safety net is satisfiable by `[evaluation]` alone

### Requirement: Mode precedence
`KAINE_CYCLE_UNATTENDED=1` SHALL take precedence over any research or operator-present selection from config or environment, with a warning naming the overridden selection, and mode resolution when unattended is NOT selected SHALL remain exactly as today.

#### Scenario: Unattended overrides research selection
- **WHEN** `KAINE_CYCLE_UNATTENDED=1` is set while config selects `"research"`
- **THEN** the boot runs unattended, logs a warning naming the overridden research selection, and the research gate is not consulted

#### Scenario: No selection keeps today's default
- **WHEN** neither unattended nor research is selected
- **THEN** mode resolution and the operator-present gate behave exactly as before this change

- [ ] 1.1 Extend supervision-mode resolution in `kaine/cycle/__main__.py` so `KAINE_CYCLE_UNATTENDED=1` selects `"unattended"` and the existing supervision-mode config key accepts `"unattended"` as a third value.
- [ ] 1.2 Implement precedence (unattended env var over research/operator-present selections from config or env) with a warning that names the overridden selection; alter nothing when unattended is not selected.
- [ ] 1.3 Ensure the unattended path initializes only cycle machinery — no experiment registry, no admissibility checks, no research-only modules; condition 3 accepts `[evaluation]` alone.
- [ ] 1.4 Unit tests for mode resolution: env-only selection, config-only selection, both set, precedence + warning, and no-selection default unchanged.
- [ ] 1.5 Integration test that an unattended boot never imports or initializes research-only modules (assert via import hook or module-registry snapshot).

## 2. Safety-net reuse and the Spot liveness probe (condition 6)

### Requirement: Unattended runs the full safety net
An unattended boot SHALL evaluate the same five safety-net conditions as research mode — (1) `[preservation.divergence_monitor].enabled = true`, (2) `[preservation.welfare_response].enabled = true`, (3) `[evaluation]` or `[research_event_log]` enabled, (4) a real preflight preserve→revive round-trip succeeds on this install, (5) `[security.state_encryption]` enabled when `[preservation].require_encryption = true` — with the same thresholds and no override that skips the net, and SHALL refuse to boot when any condition fails.

#### Scenario: All five conditions hold
- **WHEN** an unattended boot starts on an install where conditions 1–5 all pass
- **THEN** the net passes and boot proceeds to the Spot probe and then the cycle

#### Scenario: A net condition fails
- **WHEN** an unattended boot starts with, e.g., `[preservation.welfare_response].enabled = false`
- **THEN** the boot refuses with exit code 6 and names condition 2 as failed

### Requirement: Spot supervisor probe is the sixth condition
An unattended boot SHALL additionally refuse unless a boot-time probe confirms the Spot supervisor is (a) enabled in configuration, (b) live — responding to its liveness/health check with this entity registered — and (c) armed — the freeze-on-recovery hook is registered and the recovery ladder (snapshot-before-restart, escalation) is configured. Research mode SHALL NOT gain this condition.

#### Scenario: Supervisor disabled
- **WHEN** the Spot supervisor's enabled flag is false and a boot selects unattended
- **THEN** the boot refuses with exit code 6 naming condition 6 with reason "not enabled"

#### Scenario: Supervisor not live
- **WHEN** Spot is enabled in config but the supervisor does not respond to its liveness check, or does not have this entity registered, within the preflight timeout
- **THEN** the boot refuses with exit code 6 naming condition 6 with reason "not live"

#### Scenario: Freeze/recovery not armed
- **WHEN** the supervisor is live but the freeze-on-recovery hook is unregistered or the recovery ladder lacks snapshot-before-restart or escalation
- **THEN** the boot refuses with exit code 6 naming condition 6 with reason "not armed"

#### Scenario: Research gate unchanged
- **WHEN** a research-mode boot runs the safety net on an install with Spot disabled
- **THEN** the research gate evaluates conditions 1–5 only and exits 5 (not 6) on failure

### Requirement: Probe is preflight, per-boot, and read-only
The Spot probe SHALL run on every unattended boot during preflight before the entity starts, SHALL NOT accept cached or stale liveness results, and SHALL NOT mutate supervisor or entity state (no freeze, no restart, no writes).

#### Scenario: Probe runs every boot
- **WHEN** two unattended boots run in sequence and the supervisor is stopped before the second
- **THEN** the second boot refuses with exit 6; no cached liveness result is reused

#### Scenario: Probe has no side effects
- **WHEN** the probe runs against a healthy supervisor
- **THEN** supervisor state (registrations, incident log, restart counters) is unchanged by the probe

- [ ] 2.1 Extract the five-condition net evaluation in `kaine/cycle/research_gate.py` into a form callable from both research and unattended boots, with zero behavior change for research boots (existing research-gate tests pass unmodified).
- [ ] 2.2 Implement `probe_spot_supervisor()` (e.g., `kaine/cycle/spot_probe.py`) returning a structured result for checks S1 enabled / S2 live / S3 armed, using the same config keys and liveness interface the spot-supervisor capability itself uses.
- [ ] 2.3 Wire the probe into the unattended gate as condition 6 ("Spot supervisor live with freeze/recovery armed"); the research gate's evaluation and output must not include condition 6.
- [ ] 2.4 Give condition 6 distinct failure reasons — "not enabled", "not live", "not armed" — surfaced in the refusal text.
- [ ] 2.5 Enforce probe semantics: runs before the entity starts, hard timeout on the liveness check, no caching across boots, read-only (test asserts no supervisor state mutation).
- [ ] 2.6 Unit tests with a fake supervisor: healthy passes; disabled / not-registered / hung-past-timeout / freeze-hook-missing / ladder-unconfigured each fail with the correct reason.

## 3. Exit code and refusal diagnostics

### Requirement: Distinct exit code for unattended refusal
An unattended boot that fails the safety net or the Spot probe SHALL exit with code 6, a code not used by any other KAINE cycle outcome, defined once beside the existing exit-code constants.

#### Scenario: Unattended net failure exits 6
- **WHEN** an unattended boot fails any of conditions 1–6
- **THEN** the process exits with code 6

#### Scenario: No collision with existing codes
- **WHEN** the cycle exit-code constants are enumerated
- **THEN** 6 is distinct from every existing code, including 0, 1, 2, and 5

### Requirement: Refusal names the failed conditions
The unattended refusal SHALL print every failed condition to stderr as `N: name` (conditions 1–6, using the established names: preservation enabled, welfare response wired, logging active, dry self-check passed, encryption satisfied, Spot supervisor live and armed), including the failing Spot sub-check, before exiting 6.

#### Scenario: Single failure named
- **WHEN** only condition 4 (dry self-check) fails on an unattended boot
- **THEN** stderr names exactly condition 4 and the process exits 6

#### Scenario: Multiple failures all named
- **WHEN** conditions 1, 3, and 6 all fail on an unattended boot
- **THEN** stderr lists all three, each with its name and, for 6, the Spot sub-check reason

### Requirement: Existing refusals keep their meanings
Exit code 2 SHALL continue to mean operator-present gate failure for boots that selected neither research nor unattended, and exit code 5 SHALL continue to mean research safety-net failure, with unchanged messages and conditions 1–5.

#### Scenario: Operator-present unchanged
- **WHEN** a boot selects neither research nor unattended and the operator-present check fails
- **THEN** the process exits 2 with today's message

#### Scenario: Research unchanged
- **WHEN** a research boot fails the safety net
- **THEN** the process exits 5 with today's message, evaluating conditions 1–5 only

#### Scenario: No bypass of the unattended gate
- **WHEN** any skip/override-style variable (e.g., `KAINE_CYCLE_SKIP_SAFETY_NET=1`) is set on an unattended boot with a broken net
- **THEN** the boot still refuses with exit 6 — there is no override that skips the net

- [ ] 3.1 Confirm exit code 6 is unused across the repo (exit-code constants and the refusal table in `docs/for-researchers.md`), then add `EXIT_UNATTENDED_REFUSED = 6` beside the existing constants in the cycle package.
- [ ] 3.2 Emit the unattended refusal diagnostic: one `N: name` line per failed condition (1–6) on stderr, with the Spot sub-check reason appended for 6, then exit 6.
- [ ] 3.3 Test the refusal matrix: each of conditions 1–6 broken individually → exit 6 with exactly that condition named; all broken → all six named.
- [ ] 3.4 Regression tests: research failure → 5 (conditions 1–5 only, message unchanged); operator-present failure → 2 (message unchanged); no-selection default path unchanged.
- [ ] 3.5 Test that no skip/override env var or config flag bypasses the unattended gate: with a broken net, every candidate override still yields exit 6.

## 4. Documentation

### Requirement: Refusal exit-code table documents code 6
`docs/for-researchers.md` SHALL list exit code 6 in its refusal exit-code table — scoped to unattended boots and naming the six conditions including the Spot supervisor probe — while the rows for 2 and 5 keep their current meanings and text.

#### Scenario: Table shows all three refusal codes
- **WHEN** a reader consults the refusal exit-code table in `docs/for-researchers.md`
- **THEN** it contains rows for 2 (operator-present, unchanged), 5 (research safety net, unchanged), and 6 (unattended safety net including the Spot supervisor probe)

#### Scenario: Unattended mode is documented
- **WHEN** a reader looks up how to select unattended mode
- **THEN** the docs describe `KAINE_CYCLE_UNATTENDED=1`, the `"unattended"` config value, the six conditions with condition 6's enabled/live/armed detail, the absence of any override, and that unattended is not a research run

- [ ] 4.1 Add an exit-code-6 row to the refusal table in `docs/for-researchers.md` (unattended boots; conditions 1–6 including the Spot supervisor probe); leave the 2 and 5 rows' meanings and wording unchanged, at most adding a cross-link to the unattended section.
- [ ] 4.2 Add an "Unattended boots" subsection to `docs/for-researchers.md`: selection env var and config key, the six conditions with condition 6's enabled/live/armed detail, the no-override statement, the not-a-research-run note, and that operator-present remains for supervised/first boots.
- [ ] 4.3 Update every other page that enumerates supervision modes or `KAINE_CYCLE_*` environment variables (operator guide, README env table) to include `KAINE_CYCLE_UNATTENDED` and exit code 6.
- [ ] 4.4 Add or extend a docs-consistency test that parses the refusal table and asserts rows 2, 5, and 6 exist, row 6 mentions the Spot supervisor, and the 2/5 row texts match their pre-change snapshots.

## 5. Quadlet `[Install]` change

### Requirement: Quadlet installs for headless unattended boot
The shipped KAINE quadlet SHALL be installed under `multi-user.target` (`[Install] WantedBy=multi-user.target`, replacing any user-session or graphical target) and SHALL select unattended mode via its environment, so an enabled unit starts at system boot with no operator session, gated by the verified safety net rather than by a human claim.

#### Scenario: Unit starts at headless boot
- **WHEN** the quadlet is enabled on a machine that boots to `multi-user.target` with no user session
- **THEN** the KAINE unit is started by `multi-user.target`

#### Scenario: Quadlet boots unattended, not operator-present
- **WHEN** the KAINE unit starts from the quadlet at boot
- **THEN** its environment selects unattended mode (`KAINE_CYCLE_UNATTENDED=1`), so a healthy install boots and a broken net exits 6 rather than exiting 2 with nobody present

- [ ] 5.1 In the shipped quadlet (the `.container` unit), set `[Install] WantedBy=multi-user.target` and remove any `default.target`, graphical, or user-session `WantedBy=` value.
- [ ] 5.2 Set `Environment=KAINE_CYCLE_UNATTENDED=1` in the quadlet's `[Container]` section (or its equivalent env mechanism) so the boot-time unit runs the unattended gate.
- [ ] 5.3 Packaging test: parse the quadlet and assert `WantedBy=multi-user.target` and the unattended env var are present; run `systemd-analyze verify` on the unit when systemd is available in the test environment.
- [ ] 5.4 Update the quadlet's accompanying README/comment block: enabling the unit means unattended boot, and the gate is the machine-verified safety net plus Spot probe, not operator presence.

## 6. End-to-end acceptance

### Requirement: Unattended boot behaves end to end
On a healthy install, an unattended boot SHALL start the cycle without research machinery; on an install failing any gate condition it SHALL refuse with exit 6 naming the failures; research and operator-present boots SHALL be unaffected.

#### Scenario: Healthy unattended boot
- **WHEN** `KAINE_CYCLE_UNATTENDED=1` is set on an install where all six conditions pass
- **THEN** preflight completes (including the preserve→revive self-check and the Spot probe) and the cycle starts with no experiment or admissibility modules initialized

#### Scenario: Broken install refuses before the entity starts
- **WHEN** `KAINE_CYCLE_UNATTENDED=1` is set on an install with the Spot supervisor disabled
- **THEN** the boot refuses with exit 6 naming condition 6 ("not enabled") before the entity loop starts, and the failed boot triggers no supervisor restarts

- [ ] 6.1 End-to-end test on a tmp install fixture: healthy install + unattended env → net and probe run in preflight, cycle starts, no research modules initialized.
- [ ] 6.2 End-to-end test: unattended with each condition individually broken → exit 6 and the exact condition named on stderr; assert the entity loop never starts.
- [ ] 6.3 End-to-end regression sweep: research boot (healthy and broken → 5), operator-present boot (failure → 2), and no-selection default all behave exactly as before this change.