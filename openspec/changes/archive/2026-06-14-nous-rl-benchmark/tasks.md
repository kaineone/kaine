## 1. Reusable Nous factory

- [x] 1.1 Extract Nous's pymdp generative-model construction into a reusable
      factory callable by both the live module and the benchmark, with the live
      module's behavior and tests unchanged.

## 2. Environments

- [x] 2.1 Define the discrete-POMDP interface (`reset`/`step`, `A`/`B`, scalar
      reward + preference `C`).
- [x] 2.2 Implement the epistemic task (hidden state revealed by a costed probe).
- [x] 2.3 Implement the exploitation task (fully observed, fixed optimal mapping).
- [x] 2.4 Parameterize noise/horizon/info-cost for sensitivity runs.

## 3. Agents

- [x] 3.1 AIF agent adapter driving the Nous factory on an env (infer → select
      EFE-minimizing policy → act), no bus/intents.
- [x] 3.2 Tabular Q-learning (ε-greedy, decaying schedule) baseline; per-task
      hyperparameter grid on held-out seeds, chosen values recorded.

## 4. Metrics + verdict

- [x] 4.1 Decision quality, sample efficiency (steps-to-competence, regret),
      value of epistemic action (probe rate/timing, epistemic vs exploitation gap).
- [x] 4.2 Verdict classifier: per-task WIN/NULL/NEGATIVE via a permutation /
      Mann–Whitney test across seeds with a minimum effect size; aggregate verdict.

## 5. Runner + output

- [x] 5.1 `runner.py` + `__main__.py` CLI: run tasks × seeds, write seeded JSONL
      (task, seed, agent, hyperparameters, raw returns, metrics, verdict).
- [x] 5.2 CLI summary table; null/negative stated plainly.

## 6. Docs + tests

- [x] 6.1 `docs/` page: how to run; how to read a null/negative result.
- [x] 6.2 Deterministic seeded run; epistemic task where a correct EFE agent
      out-info-seeks a no-exploration baseline; verdict boundary unit tests;
      offline/no-boot assertion (no bus, no entity).

## 7. Verify

- [x] 7.1 `openspec validate nous-rl-benchmark --strict`.
- [x] 7.2 Full suite green; Nous live tests unchanged; benchmark runs offline.
