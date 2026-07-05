# Tasks

## 1. Submission core (`kaine/research/submission.py`)
- [ ] 1.1 `build_research_bundle(*, eval_root, tier="metrics", out_dir) -> Bundle` — metrics-only by default: collect numeric/redacted files from data/evaluation/* (ab_divergence, individuation, welfare, fatigue, prediction_error, coherence, nous_policy); write manifest.json enumerating included files + counts. EXCLUDE intent_expression.jsonl, Mnemos/Qdrant, eidolon self-model, conversation.
- [ ] 1.2 Higher tiers (e.g. "full") require explicit per-field config opt-in AND a recorded bystander-consent + entity-privacy attestation; even then redact. Off by default.
- [ ] 1.3 `preview(bundle) -> str` — field inventory + counts + a sample; printed before any send.
- [ ] 1.4 Encrypt the bundle (reuse state encryptor / gpg-or-age path); reuse `kaine.transfer.email_request` for transport (operator-confirmed, SMTP optional/no-creds, else write bundle + instructions).

## 2. CLI (`kaine/research/__main__.py`)
- [ ] 2.1 `python -m kaine.research.submit`: build → preview → confirm → encrypt → send-or-write. Recipient from `[research_submission].recipient` (suggested kaine.one in config comment), never hardcoded-silent. No automatic/scheduled mode.

## 3. Config
- [ ] 3.1 `[research_submission]` in config/kaine.toml: enabled=false, recipient="", tier="metrics" (+ comments; suggested recipient kaine.one@tuta.com).

## 4. Privacy hardening
- [ ] 4.1 `kaine/modules/topos/encoder.py`: set `os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")` in `load()` before `from_pretrained` (match Mnemos embedder).
- [ ] 4.2 `kaine/modules/hypnos/hot_swap.py`: reject a non-loopback `reload_endpoint_url` unless `KAINE_ALLOW_NONLOCAL_HOT_SWAP=1`.

## 5. Nexus + docs
- [ ] 5.1 Read-only "Research participation" panel in health snapshot + diagnostics.html (status + what's collected + prepare/preview affordance; no auto-send).
- [ ] 5.2 `docs/research-participation.md` (opt-in encouragement, metrics-only scope, privacy guarantees, how to enable, suggested recipient).
- [ ] 5.3 `SECURITY.md` + `docs/security-and-privacy.md`: state the single opt-in operator-initiated exception to all-local; correct intent_expression.jsonl sensitivity (HIGH); document replay_redact_content=false consequence.

## 6. Headers + tests
- [ ] 6.1 Run `scripts/apply_license_headers.py` so new .py carry the SPDX header (the header test added in PR #23 enforces it).
- [ ] 6.2 Tests: bundle metrics-only by default (assert NO speech/monologue/memory paths); preview output; disabled+empty-recipient config; SMTP send mocked + write-fallback; HF telemetry flag set; hot_swap URL validation (loopback ok, non-loopback rejected without the env); shipped `[research_submission].enabled = false` guard.

## 7. Verify
- [ ] 7.1 `.venv/bin/pytest -q -p no:cacheprovider` green (incl. license-header test).
- [ ] 7.2 `python -m kaine.research.submit --preview`-style dry path prints metrics-only inventory; no network without confirm.
- [ ] 7.3 `openspec validate research-submission --strict` passes.
