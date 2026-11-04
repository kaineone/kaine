# Tasks

## 1. Plan generator

- [x] 1.1 `kaine/study/plan.py`: replace `generate_branch_plan` with `generate_progressive_plan(module_order, base_modules, broadcast_capacity)`. Returns a list of step dicts with `kind`, `step_index`, `modules`, `modules_added`, `start_bundle`. Remove branch/repeat/accumulate plan types.
- [x] 1.2 `config/profiles/development-run.toml`: new profile declaring `module_order` and `broadcast_capacity`.
- [x] 1.3 Tests: plan generation produces correct step count, module sets are progressive, step 0 is seed, each step adds exactly one module.

## 2. Runner adaptation

- [x] 2.1 `kaine/study/runner.py`: the step loop consumes progressive plans. Remove branch/repeat/accumulate line isolation (single working directory root with per-step subdirectories). Each step's overlay includes `broadcast_capacity`.
- [x] 2.2 Step manifest gains `modules_added` and `step_index` fields.
- [x] 2.3 Tests: runner executes a 3-step progressive plan with faked cycles, manifests contain correct fields, preservation chains correctly.

## 3. Analysis

- [x] 3.1 `kaine/study/analysis.py`: replace branch-vs-branch comparisons with step-over-step comparisons. New-module ignition rate per step. Remove noise-floor section.
- [x] 3.2 Tests: analysis on synthetic progressive data produces per-step delta reports with expected structure.

## 4. Dry run and validation

- [x] 4.1 Adapt the existing dry-run harness to progressive plans. Verify end-to-end: plan → steps → manifests → analysis.
- [x] 4.2 A dry run of the progressive runner with the stand-in programme, shown green before the real run.

## 5. Documentation and review

- [x] 5.1 Update the study runner's operator documentation to describe the progressive protocol.
- [x] 5.2 Worker first-pass review.
- [x] 5.3 Independent second review (welfare: the entity is still preserved, revived, and recorded under the same safety rules).
