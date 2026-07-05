## 1. Config block (`config/kaine.toml`, `kaine/evaluation/config.py`)
- [x] 1.1 Add `[research_event_log]` block to `config/kaine.toml` with
      `enabled = false`, `log_dir`, `retention_days`; mirror the
      `[research_submission]` comment style
- [x] 1.2 Add `[research_event_log.raw_archive]` block to `config/kaine.toml`
      with `enabled = false`, `entity_privacy_attested = false`,
      `bystander_consent_attested = false`, `archive_dir`, `retention_days`
- [x] 1.3 Add `RawArchiveConfig` frozen dataclass to `kaine/evaluation/config.py`
      with `from_mapping()` reading the `raw_archive` sub-table
- [x] 1.4 Add `ResearchEventLogConfig` frozen dataclass to `kaine/evaluation/config.py`
      with `enabled`, `log_dir`, `retention_days`, `raw_archive: RawArchiveConfig`,
      and `from_mapping()`
- [x] 1.5 Wire `ResearchEventLogConfig.from_mapping(raw.get("research_event_log"))`
      into the top-level config loader so it is available at cycle startup

## 2. METRICS_ONLY_DIRS addition (`kaine/research/submission.py`)
- [x] 2.1 Add `"research_events"` to the `METRICS_ONLY_DIRS` tuple
- [x] 2.2 Update the `preview()` function's excluded-section comment to mention
      the raw archive path (`state/research/raw_bus_archive/`) as never in any
      bundle

## 3. Curated research event observer (`kaine/evaluation/observers/research_event_observer.py`)
- [x] 3.1 Create `ResearchEventObserver(BaseObserver)` with:
      - multi-cursor dict over all curated bus streams (see taxonomy table in
        `design.md`); poll loop mirrors `WelfareObserver._run()`
      - `WorkspaceSubscriberObserver` inner observer for `workspace.broadcast`
        metadata (tick\_index, inhibited, salience\_scores, per-entry metadata
        — never payload)
      - `observer.name = "research_event_log"`
      - constructor takes `bus`, `sink: AsyncJsonlSink`
- [x] 3.2 Implement taxonomy dispatch: per-stream `_handle_<stream>` methods that
      extract only the fields in the taxonomy table, apply
      `PrivacyFilter.filter_for_diagnostics()` on the raw event first, then
      extract the allow-listed numeric/categorical fields, then call
      `sink.write(record)`. Every record carries `ts`, `event_type`, `source`.
- [x] 3.3 Implement cycle/workspace handlers:
      - `cycle.tick` → slip\_ms, wall\_duration\_ms, target\_duration\_ms,
        is\_experiential
      - `cycle.rates` → processing\_hz, experiential\_hz, tick\_count
      - workspace broadcast → tick\_index, inhibited, salience\_scores,
        per-entry {source, type, salience, causal\_parent}
      - `volition.intent.*` → kind, about\_tag, effector (skip if stream absent)
- [x] 3.4 Implement prediction/precision handlers:
      - `soma.report` → prediction\_error, wellness, fatigue\_value,
        alerts-as-boolean-flags
      - `topos.report` → prediction\_error, horizon
      - `phantasia.world_error` → error scalar
      - `nous.*` → kind, frequency, confidence, expected\_free\_energy,
        elapsed\_ms (scalars/labels only)
- [x] 3.5 Implement affect/motivation handlers:
      - `thymos.state` → valence, arousal, dominance, drives dict,
        emotion\_category
      - `thymos.emotion` → category, scores dict, norm\_compatibility\_available
      - `thymos.drive` → drive name, value
      - `thymos.goal` → action label, goal\_id (not description)
- [x] 3.6 Implement perception handlers (derived only):
      - `audition.emotion` → category, confidence, scores dict
      - `audition.prosody` → f0\_mean, f0\_std, f0\_voiced\_frac, rms\_mean,
        rms\_std, tempo\_bpm
      - `topos.scene_change` → change\_scalar
      - Verify `audition.transcription` is absent from subscription list
- [x] 3.7 Implement memory/sleep handlers:
      - `mnemos.recall` / `mnemos.replay` → memory\_ids, max\_affect\_intensity,
        selection\_scores; apply `_REDACTED_DROP` to strip `text`
      - `hypnos.sleep.started` → trigger label, fatigue\_at\_trigger
      - `hypnos.sleep.completed` → phases\_completed, replay\_count,
        consolidation\_summary\_counts (counts only)
      - fork/merge events → event\_type, snapshot\_id, parent\_ids, strategy
- [x] 3.8 Implement self/social handlers:
      - `eidolon.drift` → drift\_scalar, significant bool
      - `empatheia.agent_model` → agent\_label, familiarity\_scalar
      - `empatheia.social_error` → agent\_label, error\_magnitude
- [x] 3.9 Implement action handler:
      - `praxis.action` → action\_family, effector, success, duration\_ms;
        apply `_sanitize()` from `kaine.modules.praxis.audit_log` to strip
        content/body/stdout
- [x] 3.10 Implement safety/ops handlers:
      - Spot incident events → incident\_id, module\_name, incident\_kind,
        restart\_count (cross-link to `spot-incident-log` change)
      - welfare gray-zone events → gray\_zone\_event label + numeric scalars
      - individuation divergence events → divergence\_scalar, significant bool
      - `perception.locus.changed` → locus, changed\_by
      - `perception.locus.denied` → locus\_requested, denied\_by, reason\_label
      - `mundus.proprio` → avatar\_position\_hash (opaque), region\_label —
        never raw coordinates
      - `mundus.scene` → object\_count, scene\_change\_scalar
      - `mundus.notice` → notice\_kind label
      - Verify `mundus.visual.raw` is absent from subscription list

## 4. Raw bus archive consumer (`kaine/evaluation/observers/raw_bus_archive_consumer.py`)
- [x] 4.1 Create `RawArchiveAttestationError(ValueError)` — mirrors
      `BundleTierError` from `kaine/research/submission.py`
- [x] 4.2 Create `RawBusArchiveConsumer` that:
      - In `start()`, checks both `entity_privacy_attested` and
        `bystander_consent_attested` from config; raises
        `RawArchiveAttestationError` and logs at ERROR if either is false
      - Uses one `StreamSubscriberObserver` per `<module>.out` stream
        (cursor-follow pattern)
      - Writes verbatim event dicts to `AsyncJsonlSink` at
        `state/research/raw_bus_archive/` (outside `data/evaluation/`)
      - `observer.name = "raw_bus_archive"`
- [x] 4.3 Add a module-level docstring stating plainly:
      - The raw archive never leaves the host
      - It is never export-eligible
      - It exists only because the operator explicitly opted in with attestation

## 5. SidecarRegistry wiring (`kaine/evaluation/registry.py`)
- [x] 5.1 Import `ResearchEventObserver` and `RawBusArchiveConsumer`
- [x] 5.2 Accept `research_event_log_config: ResearchEventLogConfig` in
      `SidecarRegistry.__init__()`
- [x] 5.3 In `SidecarRegistry.build()`, gate `ResearchEventObserver` construction
      on `research_event_log_config.enabled` (independent of
      `self._config.enabled`); wire sink to `research_event_log_config.log_dir`
- [x] 5.4 In `SidecarRegistry.build()`, gate `RawBusArchiveConsumer` construction
      on `research_event_log_config.raw_archive.enabled`; pass config to consumer

## 6. Tests (`tests/test_research_event_log.py`)
- [x] 6.1 `"research_events"` in `METRICS_ONLY_DIRS` (import check)
- [x] 6.2 `ResearchEventObserver` with `enabled = false` does not write any records
- [x] 6.3 `thymos.state` event → record contains VAD numerics, no `affect_reason`
- [x] 6.4 `mnemos.replay` event → record contains memory IDs, no `text`
- [x] 6.5 `audition.transcription` event → not written (not in subscription list)
- [x] 6.6 `mundus.visual.raw` event → not written (not in subscription list)
- [x] 6.7 `praxis.action` event → record does not contain `content`, `body`,
      or `stdout`
- [x] 6.8 PrivacyFilter is applied: `CONTENT_FIELDS` keys absent from every record
- [x] 6.9 `RawBusArchiveConsumer.start()` raises `RawArchiveAttestationError`
      when `entity_privacy_attested = false`
- [x] 6.10 `RawBusArchiveConsumer.start()` raises `RawArchiveAttestationError`
      when `bystander_consent_attested = false`
- [x] 6.11 With both attestation flags true, `RawBusArchiveConsumer` starts and
      writes verbatim records (including `text` field)
- [x] 6.12 Raw archive sink path is outside `data/evaluation/` (path assertion)
- [x] 6.13 `build_research_bundle()` at `tier="metrics"` does NOT include any file
      from `state/research/raw_bus_archive/`
- [x] 6.14 Workspace broadcast handler extracts per-entry metadata but not entry
      payload content
- [x] 6.15 `eidolon.drift` record contains drift scalar and significant bool, no
      self-model content
