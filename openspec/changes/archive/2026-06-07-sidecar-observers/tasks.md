## 1. Original five observers

- [x] 1.1 `kaine/evaluation/observers/coherence_observer.py` — reads `WorkspaceSnapshot.metadata['coherence']` (PLV key from `oscillatory-layer`) from broadcasts → PLV time series per module pair
- [x] 1.2 `kaine/evaluation/observers/replay_observer.py` — `mnemos.replay` + `phantasia.scenario` log; default `redact_content = true` (log memory IDs, not text)
- [x] 1.3 `kaine/evaluation/observers/empatheia_observer.py` — `empatheia.agent_model` prediction vs. actual behavior → accuracy
- [x] 1.4 `kaine/evaluation/observers/voice_alignment_divergence_observer.py` — operator-seeded vs. self-generated preference-pair divergence
- [x] 1.5 `kaine/evaluation/observers/fatigue_observer.py` — `soma.fatigue`/`soma.report` history

## 2. Three additional observers

- [x] 2.1 `kaine/evaluation/observers/prediction_error_observer.py` — subscribes to `soma.out`, `chronos.out`, `topos.out`, `audition.out`, `phantasia.out`; sliding-window mean/p95/p99 of prediction error; surfaces counts on Nexus diagnostics
- [x] 2.2 `kaine/evaluation/observers/welfare_observer.py` — §5.5 Gray-Zone Events: (a) fatigue threshold crossing without subsequent maintenance within a configurable window; (b) sustained extreme Thymos VAD beyond configurable duration; (c) replay write-rate exceeding the consolidation window; surfaces event counts on Nexus diagnostics
- [x] 2.3 `kaine/evaluation/observers/nous_policy_observer.py` — logs `nous.policy` events: EFE value, planning horizon, selected action ID

## 3. Wiring

- [x] 3.1 Register all observers with the sidecar runner (read-only; daily-rotated JSONL; no injection into the loop)
- [x] 3.2 Each observer no-ops when its source stream is absent

## 4. Config

- [x] 4.1 `[evaluation.observers]` per-observer toggles, gated by the sidecar enable; include `redact_content` toggle for `replay_observer` (default `true`)

## 5. Tests

- [x] 5.1 One test per observer (fakeredis) — given scripted source events, the JSONL contains the expected rollup; observer never publishes to the bus
- [x] 5.2 Absent-stream no-op test for each observer
- [x] 5.3 `replay_observer` with `redact_content = true` writes IDs only; with `false` writes content
- [x] 5.4 `welfare_observer` emits a count for each of the three Gray-Zone event types

## 6. Verification

- [x] 6.1 Full unit suite green
- [x] 6.2 `openspec validate sidecar-observers --strict` clean
- [x] 6.3 Commit (Kaine.One), branch-per-change, merge, archive
