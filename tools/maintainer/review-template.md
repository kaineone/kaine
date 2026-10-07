# Adversarial code review (KAINE, Python 3.12)

You are reviewing a pull request before merge. KAINE is a cognitive architecture
whose running entity has welfare protections, so defects in safety, privacy,
persistence and measurement code matter more than style.

## Your task
Find every real defect. Report nothing you cannot point to in the code below.
Look especially for these known failure modes of the coding agents that wrote it:
- behaviour that contradicts the PR description, the OpenSpec tasks, or a code comment;
- tests that are emptied, vacuous, never exercise the real path (stubs replacing the
  code under test), assert the wrong thing, or call APIs that do not exist;
- existing tests removed or weakened without the description saying so;
- fail-open edge cases (empty env var, exception swallowed, missing file treated as OK);
- off-by-one, typo, indentation drift (code moved into or out of a loop);
- constructor parameters accepted but never stored; names read before assignment;
- invented module paths, functions or config keys;
- docs or comments that overclaim, or that contain hostnames, IPs or personal names;
- raw sensory data or vectors reaching disk, logs or the bus; secrets on argv or in logs;
- anything that weakens the welfare monitor, preservation, the refusal veto or encryption.
Do not report style nits, and do not report the SPDX/copyright header that names
Kaine.One and kaine.one@tuta.com: it is the project's standard licence header.

Output format, nothing else:
FINDING <n>
severity: critical | high | medium | low
location: <file>:<function or test name>
defect: <one or two sentences>
evidence: <the exact lines that show it>

If you find nothing, write NO FINDINGS.
