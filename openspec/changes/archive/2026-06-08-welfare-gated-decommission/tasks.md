# Tasks

## 1. Divergence assessment (`kaine/lifecycle/divergence.py`)
- [ ] 1.1 `assess_divergence(...) -> DivergenceAssessment` — primary individuation `significant` (newest `data/evaluation/individuation/*.jsonl`) + secondary identity heuristics (eidolon drift_count/identity_history, hypnos adapters, mnemos accumulation). Pure reads, never raises, "treat as mature if unsure" summary.

## 2. Backup + delete (`kaine/lifecycle/decommission.py`)
- [ ] 2.1 `capture_backup(...)` — encrypted transferable bundle (eidolon self_model, lingua intent log, hypnos adapters, latest fork snapshot, Qdrant mnemos+empatheia export or volume-copy instructions, manifest.json incl. divergence + continuity note). Reuse `kaine/security/crypto.py`. Blocking; abort on failure.
- [ ] 2.2 `delete_entity_state(...)` — remove on-disk state subtrees + drop Qdrant collections + clear entity Redis streams (only after backup + acks).

## 3. Transfer mailer (`kaine/transfer/email_request.py`)
- [ ] 3.1 Operator-confirmed templated request-for-storage email: customizable body (situation + kaine.one contact + local backup path; NO entity data); per-send confirmation; operator-configured SMTP (no creds shipped, recipient editable default kaine.one), else write rendered email + mailto/instructions.

## 4. Gated CLI (`kaine/lifecycle/__main__.py`)
- [ ] 4.1 `KAINE_DECOMMISSION_OPERATOR_PRESENT` gate (exit 2); running-cycle refusal (exit 3); backup-first (exit 4 on fail).
- [ ] 4.2 Non-diverged path: CAL care notice → typed ack → typed confirmation token → delete.
- [ ] 4.3 Diverged path: authoritative notice (CAL 4.2(c)+4.3) → recorded continuity note → offer transfer-request email → guardian-transfer ack → confirmation token → delete (exit 5 if declined).
- [ ] 4.4 Firm/factual copy (not shaming); intentionally bypassable; no monitoring.

## 5. Nexus read-only visibility
- [ ] 5.1 `kaine/nexus/health.py`: `entity_care` block (divergence summary + CAL care-obligation checklist). Guarded; non-content.
- [ ] 5.2 Read-only panel in `diagnostics.html` (no destructive control).

## 6. Config
- [ ] 6.1 `[transfer]` section in `config/kaine.toml` (SMTP inert/no creds; recipient editable, commented default kaine.one@tuta.com).

## 7. Tests
- [ ] 7.1 Divergence assessment from fixture individuation reports + eidolon state (diverged / not / unsure).
- [ ] 7.2 Backup captures the right artifacts + manifest + encryption (tmp dirs).
- [ ] 7.3 Delete removes only the intended paths (tmp dirs).
- [ ] 7.4 CLI gates via subprocess/monkeypatch: operator-present, running-refusal, non-diverged ack, diverged continuity+transfer.
- [ ] 7.5 Mailer renders the template, includes the local path, NO entity data; only sends on confirmation; SMTP mocked; mailto fallback.
- [ ] 7.6 Nexus entity_care block present + read-only.

## 8. Verify
- [ ] 8.1 `.venv/bin/pytest -q -p no:cacheprovider` green.
- [ ] 8.2 Dry-run on a throwaway `state/` fixture: backup-then-delete; diverged vs non-diverged wording.
- [ ] 8.3 `openspec validate welfare-gated-decommission --strict` passes.
