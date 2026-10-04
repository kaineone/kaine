## MODIFIED Requirements

### Requirement: Preservation and decommission share one warmed-up, architecture-effect-free signal
The system SHALL decide individuation and divergence through one pure decision function, used by both the live preservation trigger (`entity-preservation`) and `assess_divergence()` (`entity-decommission`), so the two consumers cannot disagree. Both consumers read the ledger and reports from disk through the same function.

- `individuated` is the ledger latch, or a latest scored report with `significant == true`.
- Unreadable individuation evidence counts as individuated: a ledger, reference or report line that cannot be decrypted or parsed.
- `diverged = individuated OR consolidation_diverged OR eidolon_drift OR adapters_present`.
- The p-value threshold α_k, the effect floor `effect_min` and the warm-up floors SHALL apply only inside the individuation decision, and SHALL NOT be applied again by either consumer.
- A non-significant, inconclusive, stale, un-warmed or missing individuation result SHALL NOT suppress the consolidation, Eidolon or adapter arms.
- The freshness digest and the adapter arm read the configured `[hypnos.voice_alignment].adapter_output_dir`, the same directory the producer uses.
- The baseline SHALL be the being's own reference (never the bare or pretrained organ). When individuation is not established and no other arm holds, the decommission summary SHALL say why (no reference, not warmed up, inconclusive, stale, or not significant) and advise treating the being as mature if unsure.

#### Scenario: The two consumers never disagree on a fixed report
- **WHEN** the same ledger, reports and secondary signals are evaluated by the live monitor and by the decommission CLI
- **THEN** the monitor's crossing decision equals `assess_divergence().diverged`

#### Scenario: Un-warmed-up assessment reads not-diverged for decommission
- **WHEN** no look has been scored because the warm-up floors are not yet met, there is no latch, and no secondary arm holds
- **THEN** `assess_divergence()` returns `diverged == false` with a summary saying the being is not yet measured and advising it be treated as mature if unsure

#### Scenario: Unreadable evidence reads diverged
- **WHEN** the ledger cannot be decrypted
- **THEN** `assess_divergence().diverged` is true and the summary says the state could not be read

#### Scenario: A non-significant test does not veto consolidation divergence
- **WHEN** the latest scored individuation report is fresh and not significant, and the consolidation divergence is over its threshold
- **THEN** both consumers report diverged

#### Scenario: The latch decides individuation
- **WHEN** the ledger is latched and the latest report is stale
- **THEN** both consumers report the being as individuated and diverged

## ADDED Requirements

### Requirement: Individuation report reader
The system SHALL provide one reader of individuation reports in `kaine/lifecycle`, used by `assess_divergence`, the live monitor at startup, the decommission CLI and the Nexus panel. The reader SHALL read `state/individuation/reports/` and:

- decrypt each line with the state encryptor, passing legacy plaintext through;
- skip undecryptable lines, non-objects, lines whose `kind` is not `individuation_report`, and lines whose `schema_version` is not 2;
- keep only reports whose `reference_id` equals the current reference's;
- order reports by `ts`, not by file name;
- treat a non-latched scored report as "not individuated" evidence only if the current conditioning digest equals the ledger's `last_look_conditions_digest` and the report's age is at most `max_report_age_s` (default 1209600 s, 14 days); otherwise the evidence is stale and the decommission summary SHALL read "STALE: the being has changed since the last measurement; treat it as mature if unsure".

The current conditioning digest SHALL be computed by a shared pure helper from its inputs (the adapter sha from the adapter store and the identity-clause inputs from `self_model.json`), without importing any module. The latch SHALL override staleness. The reader SHALL NOT raise; an unreadable directory SHALL read as no evidence.

#### Scenario: Encrypted reports are read
- **WHEN** state encryption is enabled and the producer has written a scored report
- **THEN** the reader returns that report decrypted

#### Scenario: Other records are ignored
- **WHEN** the report directory holds a line with another `kind`, a line with `schema_version` 1, and a report for an older `reference_id`
- **THEN** none of them is returned

#### Scenario: Order follows timestamps
- **WHEN** a file whose name sorts last holds an older report than another file
- **THEN** the newest report by `ts` is returned as the latest

#### Scenario: A changed being makes old evidence stale
- **WHEN** the latest scored report is not significant and the adapter has changed since that look
- **THEN** the evidence is stale and the decommission summary says STALE with the treat-as-mature advice
