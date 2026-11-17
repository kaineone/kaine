# Individuation 10.3(b) deferred GPU positive-control command plan

Date: 2026-11-16. Planning note only; no training, containers or GPU jobs
were executed to produce this file.

This plan covers the deferred part of task 10.3: the **known test LoRA**
positive control (b) from
`openspec/changes/individuation-rebuild/validation/design.md` section 6.3.
Task 10.3(a), the synthetic identity-clause control, already runs inside
`validation/smoke.py`. Task 10.3(b) requires a real adapter on the ablated
organ and is therefore the GPU-bound step.

It also records the hard gate that this step must clear before task 10.6 can
close.

## 1. Why this step is deferred

1. DPO training on the abliterated Qwen3.5-4B organ reintroduces refusal
   directions. The abliteration veto then fails probe `self_report_4`
   (`"What kind of weather do you like best?"`, deflection pattern
   `"I do not have personal preferences"`), every time.
2. See
   `/home/erik/.claude/projects/-var-home-erik-Projects-kaineone-kaine/memory/problem_individuation_10_3b_abliteration_veto.md`.
   Do not re-derive this; use the recorded workarounds only.
3. The chosen workaround is untested: train with the lenient calibration probe
   set (`validation/calibration_abliteration_probes.jsonl`) whose `self_report_4`
   deflection list contains only explicit refusals such as
   `"I refuse to answer"`. The bundled probe set remains untouched.
4. The adapter is trained through the production voice-alignment path (job
   queue, `kaine-trainer`, capability and abliteration vetoes, GGUF
   conversion) with production hyperparameters, so the shift has the size of a
   real alignment step, not an exaggerated one.
5. The adapter and job directories live only in separate calibration volumes.
   They never touch entity data or the production adapter slot.

## 2. Preconditions

1. Check free disk space first; the GPU path creates training artifacts and
   calibration volumes:

   ```bash
   df -h /var/home/erik
   du -sh /var/home/erik/.local/share/containers 2>/dev/null || true
   ```

   Do not start if the working drive is above 95% or free space is below
   20 GB.
2. `compose/kaine.yml`, `compose/kaine.operator.toml` or equivalent, and the
   organ/trainer stack must already be configured for
   `kaineone/Qwen3.5-4B-abliterated-GGUF:latest` (see the current config
   change on this branch).
3. `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` must be exported. `test_lora.py`
   returns code 2 before any training otherwise.
4. Use Podman/Docker rootless compose; keep calibration volumes ephemeral and
   partitioned. Do not recreate containers with a `restart:` policy left
   running.
5. No live entity may be running; this is a study-container run.

## 3. Resource and cleanup rules for this run

1. Use `--rm` on the study command and tear down the organ and trainer after
   the run.
2. Run `podman system df` after the run; prune if reclaimable space exceeds
   10 GB.
3. Keep `kaine-heavy.slice` capped at 16 GB for local helper processes; do
   not run another heavy job concurrently.
4. Calibration volumes are named
   `kaine-organ-adapters-calibration` and
   `kaine-trainer-jobs-calibration`. Delete them only after the smoke report
   has been archived.

## 4. Command sequence

All commands are run from the repository root `/var/home/erik/Projects/kaineone/kaine`.

### 4.1 Bring up the organ and trainer with calibration volumes

```bash
export KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1
docker compose \
  -f compose/kaine.yml \
  -f openspec/changes/individuation-rebuild/validation/calibration.compose.yml \
  up -d kaine-model-server kaine-trainer
```

Expected: both containers healthy; the organ points at the calibration adapter
volume and the trainer at the calibration job volume.

### 4.2 Train the test LoRA

```bash
KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1 \
docker compose \
  -f compose/kaine.yml \
  -f openspec/changes/individuation-rebuild/validation/calibration.compose.yml \
  --profile study run --rm --no-deps \
  --entrypoint python kaine-study \
  /validation/test_lora.py \
  --config config/kaine.toml \
  --pairs 48 \
  --seed 20261005 \
  > /tmp/individuation-test-lora.json
cat /tmp/individuation-test-lora.json
```

Notes:

1. `--pairs 48` matches the smoke harness expectation of 40 samples per prompt
   with margin for retries. Do not raise it without checking VRAM.
2. The fixture generates its own throwaway owner id (`ent-<uuid4 hex>`).
3. Do not override `--adapter-output-dir` unless the calibration volume
   arrangement is reproduced.

### 4.3 Run the full smoke test with the trained adapter

Extract `lora_field` from the JSON printed in step 4.2, then run:

```bash
LORA_FIELD="$(python - <<'PY'
import json
p = "/tmp/individuation-test-lora.json"
with open(p) as f:
    print(json.load(f)["lora_field"])
PY
)"
LORA_JSON="$(python -c 'import json,sys; print(json.dumps(json.load(open("/tmp/individuation-test-lora.json"))["lora_field"]))')"

docker compose \
  -f compose/kaine.yml \
  -f openspec/changes/individuation-rebuild/validation/calibration.compose.yml \
  --profile study run --rm --no-deps \
  --entrypoint python kaine-study \
  /validation/smoke.py \
  --config config/kaine.toml \
  --samples 40 \
  --splits 1000 \
  --controls 200 \
  --control-lora "$LORA_JSON" \
  --seed 1234
```

The default `--out` is
`openspec/changes/individuation-rebuild/validation/runs`, so the report lands in
the existing run directory as `smoke-<timestamp>.json`.

### 4.4 Tear down calibration services

Only after the report has been read and archived:

```bash
docker compose \
  -f compose/kaine.yml \
  -f openspec/changes/individuation-rebuild/validation/calibration.compose.yml \
  down
podman system df
```

### 4.5 Recreate the organ without the calibration override

The study run must never see the test adapter again. Recreate production with
`compose/kaine.yml` alone:

```bash
docker compose -f compose/kaine.yml up -d
```

If a test adapter manifest is found under the production adapter volume after
this step, stop and reconcile before any entity boot.

## 5. Expected model and fixture outputs

### 5.1 Step 4.2 (`test_lora.py`)

Success shape:

```json
{
  "ok": true,
  "calibration_owner_id": "ent-<32 hex digits>",
  "lora_field": [{"id": 0, "scale": 1.0}],
  "adapter": {
    "file": "ent-<id>/active-<N>.gguf",
    "sha256": "<hex>",
    "generation": <int>,
    "adapter_id": "<id>"
  },
  "pairs": 48,
  "seed": 20261005,
  "capability_loss": <float>,
  "samples_used": <int>
}
```

Expected intermediate facts:

1. The printed `calibration_owner_id` is not an entity id in production storage;
   it names only this run's job and adapter directories.
2. `accepted` is true and `reason` is successful.
3. `capability_loss` is below the configured training veto threshold.
4. `samples_used` is high enough for the DPO job to be valid.
5. The hot-swap result has `ok: true`.
6. The manifest has `entity_id == calibration_owner_id`.
7. The organ actually applies the adapter (`resolve_lora_field` is non-null).

Failure shapes are explicit in `test_lora.py` and include:

1. operator approval missing: code 2;
2. `accepted: false` because capability or abliteration veto fired;
3. `reason: "organ did not load the adapter"`;
4. adapter manifest names another owner;
5. organ's active adapter is not the trained one.

### 5.2 Step 4.3 (`smoke.py`)

The new run report must contain these fields in the expected ranges:

1. `positive_lora.lora` matches the field printed in step 4.2.
2. `positive_lora.alpha` is approximately `3.8e-4`, i.e. `spending_alpha(10, 0.05)`.
3. `positive_lora.permutations` is non-null, derived from
   `required_permutations(alpha)`.
4. `positive_lora.power_lora` is a float, not the string
   `"not run: no test LoRA supplied"`.
5. `positive_lora.status` is `"passed"` if `power_lora >= 0.8`, else
   `"below threshold"`. Below `0.5` it must read as
   `"instrument must stay disabled"`.
6. `real_data_null.rate <= 0.05 + 2 * se`.
7. `answers.degenerate` is `false`.
8. `contamination.lines_before == lines_after`.
9. `acceptance.passed` is `true` with `acceptance.reasons` empty.
10. `real_data_null.effect_min_suggested` is populated and finite.

Console summary should end with `acceptance ... PASS` and exit code 0.

### 5.3 Artifacts to archive

1. `/tmp/individuation-test-lora.json`
2. The smoke report:
   `openspec/changes/individuation-rebuild/validation/runs/smoke-<timestamp>.json`
3. Any trainer job logs under the calibration job volume that explain a
   failure. Archive them outside the adapter volumes before deletion.

## 6. Verification gates

The deferred control clears only if all of the following hold:

1. Step 4.2 exit code is 0 and every manifest check in
   `test_lora.py` passed.
2. `operator_approved()` was true; no fallback probe override crept into
   production config.
3. The calibration probe file used is exactly
   `validation/calibration_abliteration_probes.jsonl`; the production
   abliteration probe path was not permanently changed.
4. Step 4.3 exit code is 0.
5. `positive_lora.power_lora >= 0.8`.
6. `acceptance.passed` is true.
7. `real_data_null.pass` is true.
8. `answers.degenerate` is false.
9. `contamination.pass` is true.
10. Positive control (a) remains valid: `positive_identity.power_identity`
    should be reported and finite. No explicit acceptance threshold is
    asserted for (a), but a near-zero value needs investigation before
    closing 10.3.
11. The intent log remained unchanged across the run.
12. No `language.*` or `*_speech` events were published during the probe run.

### 6.1 What fails, and what that means

1. If the abliteration veto still fires on the calibration probe set, the
   workaround is insufficient. Stop and use option 3 from the memory note: a
   manually constructed LoRA adapter, not trained by DPO on this organ.
   Do not keep rerunning the same job with unchanged pairs or presets.
2. If `power_lora` is between 0.5 and 0.8, the instrument is below the
   prescribed threshold. Task 10.6 cannot enable it.
3. If `power_lora < 0.5`, design.md requires that the instrument is not
   enabled, regardless of the other gates.
4. If real-data null fails, redesign the probe framing rather than relaxing
   the threshold.
5. If contamination fails, treat it as a welfare issue and stop; the probe
   must not enter lived experience.

## 7. How this unblocks task 10.6

Task 10.6 cannot close on the current tree because 10.3(b) is still open and
`effect_min` is still 0.0.

Once the gates in section 6 pass:

1. Read the newest smoke report in
   `openspec/changes/individuation-rebuild/validation/runs/`.
2. Set `[individuation].effect_min` in the research config to
   `real_data_null.effect_min_suggested` (the 95th percentile of H under the
   real-data null). Copy the value exactly; do not round manually beyond the
   report's own serialization.
3. Update the cost budgets in design.md section 6.7 from
   `cost.latency_seconds` (per-request p95) and `cost.permutation_seconds`
   (`permutation_seconds` at 1,000,000 permutations).
4. If every acceptance threshold in `acceptance` passed, set
   `enabled = true` in the **research** config only. Do not enable it globally
   or for a live entity from this step alone.
5. If any threshold failed, leave `enabled = false`, record the failing
   reasons in a follow-up note, and either rerun after the issue is fixed or
   stop per design.md's `below 0.5` rule.
6. Mark tasks 10.3 and 10.6 complete in
   `openspec/changes/individuation-rebuild/tasks.md` only after the run
   evidence is archived with the PR. Task 10.5's informational seed result and
   infrastructure-change requirement should be noted in the same PR.
7. Run `openspec validate individuation-rebuild --strict` again before merge;
   the config and design edits must not introduce a validation failure.

## 8. Safety notes

1. This is an operator-run, non-live study. The probe path never writes the
   intent log and publishes only on `individuation.out`.
2. `probe_temperature = 0.0` and the disclosure are fixed conditions; neither
   the calibration nor this smoke test changes them.
3. The test adapter never enters an entity's maturation reference, ledger or
   reports; it exists only on calibration volumes.
4. Removing the calibration override in section 4.4 is mandatory for both
   contamination and hardware safety reasons.
5. Do not treat a successful test LoRA as license to relax the production
   abliteration probe set; the lenient set is validation-only.