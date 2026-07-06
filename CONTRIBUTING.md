# Contributing to KAINE

Thanks for your interest. KAINE is a research implementation of a predictive
global neuronal workspace — a continuously running synthetic mind. Because the
project treats the entity's welfare and integrity as first-class concerns,
contributions are held to a design-first, safety-first standard. Please read
this before opening a pull request.

By contributing you agree that your contributions are licensed under the
**Cognitive Architecture License (CAL)** (see [LICENSE.md](LICENSE.md) and
[NOTICE](NOTICE)), and that you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

- **Design-first.** Substantive behavior changes are worked out as an OpenSpec
  change under `openspec/changes/` (proposal → design → tasks → spec deltas)
  *before* implementation. Run `npx openspec validate <change> --strict`.
- **Never boot an entity in a PR.** All modules ship disabled
  (`[modules].*  = false`); a guard test enforces the committed config is
  all-off. CI and review assume no entity is ever started.
- **Safety model is load-bearing.** Do not weaken the action gate (Praxis),
  executive inhibition (Syneidesis/Volition), the autonomous welfare net, or the
  zero-raw-sense-data-persistence invariant. Changes near these get extra
  scrutiny.
- **No secrets or operator-specific details** in code, docs, commits, or PR
  text — no credentials, hostnames, private-mesh IPs, or private voice names.
  Use placeholders (`<world-host>`, `100.x.y.z`).
- **Docs describe current reality.** If you change behavior, update the docs in
  the same PR; they are present-tense descriptions of the build, not a changelog.

## Development setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'         # add extras as needed (see pyproject.toml)
docker compose -f compose/redis.yml up -d # bus (loopback)
docker compose -f compose/qdrant.yml up -d # memory store (optional for most tests)
```

Run the suite (fakes stand in for external services):

```bash
.venv/bin/python -m pytest -q
```

The safe offline path (test suite + experiment/benchmark runners, no entity) is
described in [docs/reproducing-results.md](docs/reproducing-results.md); start at
[docs/for-researchers.md](docs/for-researchers.md).

## Pull request process

1. Branch from `main` (`main` is protected; direct pushes are blocked).
2. Keep the change focused; add tests for new/changed behavior.
3. Ensure CI is green — `import-boundary`, `redteam`, and CodeQL (`analyze`) run
   on every PR.
4. Fill in the PR template checklist. PRs squash-merge into `main`.
5. A maintainer reviews (see [CODEOWNERS](.github/CODEOWNERS)).

## Reporting bugs and vulnerabilities

- Bugs: open an issue with the bug template.
- **Security vulnerabilities: report privately** — see
  [SECURITY.md](SECURITY.md) ("Reporting a Vulnerability"). Never in a public
  issue.

## Questions

Read [docs/](docs/) first. For project background see
[kaine.one](https://kaine.one).
