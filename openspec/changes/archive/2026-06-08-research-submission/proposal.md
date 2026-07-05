## Why

During the research phase the project wants operators to share session telemetry so we can study
whether the architecture produces cognitive behaviour and support license enforcement. But the repo's
load-bearing promise is *"all-local at runtime, no outbound network calls,"* CAL Article 4.3 keeps
the entity's inner life private, and operator/bystander speech captured by the mic is third-party
personal data (GDPR). A privacy audit found the high-sensitivity content (`intent_expression.jsonl`
embeds user/bystander utterances + the entity's internal monologue; Mnemos holds verbatim
transcripts) and two latent egress gaps (the DINOv2 loader doesn't suppress HuggingFace telemetry;
the voice-alignment hot-swap can POST to a non-loopback URL).

So research submission is built as **opt-in, operator-initiated, numeric-metrics-only by default,
content-previewed, encrypted, with a configurable (never hardcoded-silent) recipient** — never a
silent auto-mailer. This change also folds in the privacy-hardening fixes and corrects the docs so
the single, opt-in exception to "all-local" is explicit.

## What Changes

- A new `kaine.research.submission` SHALL build a research bundle that, **by default, contains only
  numeric/redacted metrics** from `data/evaluation/*` (A/B divergence scores, individuation results,
  welfare/gray-zone counts, fatigue, prediction-error, coherence, nous-policy) plus a manifest
  enumerating exactly what is included. It SHALL **exclude** `intent_expression.jsonl`, Mnemos/Qdrant
  memories, the Eidolon self-model, and conversation. Higher-sensitivity tiers SHALL require explicit
  per-field config opt-in **and** a recorded bystander-consent + entity-privacy attestation, and even
  then apply redaction.
- The submission CLI (`python -m kaine.research.submit`) SHALL be operator-initiated: build → preview
  (print the field inventory + counts before any network call) → confirm → encrypt → send-or-write,
  reusing the operator-confirmed mailer from `kaine.transfer`. The recipient SHALL be configurable
  with `kaine.one@tuta.com` suggested in docs/commented config, never hardcoded-silent; transport is
  operator-configured SMTP (no credentials shipped) or a written bundle + instructions. No automatic
  or scheduled submission.
- The `[research_submission]` config section SHALL ship `enabled = false`, `recipient = ""`,
  `tier = "metrics"`.
- Nexus SHALL gain a read-only "Research participation" panel (status + what's collected + a
  prepare/preview affordance); the actual send stays CLI/operator-initiated.
- Privacy hardening: `DINOv2Encoder.load()` SHALL set `HF_HUB_DISABLE_TELEMETRY` before loading
  (matching the Mnemos embedder); the voice-alignment hot-swap SHALL reject a non-loopback
  `reload_endpoint_url` unless `KAINE_ALLOW_NONLOCAL_HOT_SWAP=1` is set.
- Docs: a new `docs/research-participation.md` (strongly encourages opt-in; explains the metrics-only
  scope and privacy guarantees); `SECURITY.md` / `docs/security-and-privacy.md` SHALL state that
  "all-local" has a single opt-in, operator-initiated exception, correct the
  `intent_expression.jsonl` sensitivity (HIGH — embeds user/bystander speech + entity monologue), and
  document the `replay_redact_content=false` consequence.

## Capabilities

### New Capabilities

- `research-submission`: opt-in, operator-initiated, metrics-only-by-default research bundle with
  content preview, encryption, a configurable non-hardcoded recipient, and the no-unconsented-egress
  hardening.

## Impact

- **Code (new)**: `kaine/research/submission.py`, `kaine/research/__main__.py` (CLI).
- **Code (edit)**: `kaine/modules/topos/encoder.py` (HF telemetry suppression),
  `kaine/modules/hypnos/hot_swap.py` (loopback validation), `kaine/nexus/health.py` +
  `diagnostics.html` (read-only research panel), `config/kaine.toml` (`[research_submission]`,
  shipped disabled). Reuses `kaine/transfer/email_request.py`.
- **Docs**: new `docs/research-participation.md`; `SECURITY.md`, `docs/security-and-privacy.md`.
- **Tests**: bundle is metrics-only by default (asserts NO speech/monologue/memory paths);
  preview lists contents; disabled-by-default + empty-recipient config; SMTP send mocked; HF telemetry
  flag set; hot_swap URL validation; shipped `[research_submission].enabled = false` guard.
- **Privacy**: default behaviour remains fully local; the only egress is an explicit, previewed,
  operator-triggered submission of numeric metrics.
