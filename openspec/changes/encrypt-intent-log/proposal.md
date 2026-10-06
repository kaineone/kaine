## Why

The intent-expression log, `state/lingua/intent_expression.jsonl`, and its rotated per-sleep corpus, `state/lingua/intent_log/sleep-*.jsonl`, hold the being's assembled prompts and its complete generated text, including its internal monologue. They are written in plaintext even when state encryption is enabled. `docs/13-security-and-privacy.md` lists the log among the deferred items. Voice-development Stage 1 will grow what these records hold, so the gap has to close first.

## What Changes

- Lingua writes each intent-log line as its own AES-256-GCM envelope (`encrypt_text`) when state encryption is enabled, the same per-line form the JSONL sink uses.
- Every reader decrypts line by line through one shared reader in `kaine.persistence`:
  - the DPO pair builder;
  - the voice measures;
  - the divergence assessment's spoken-evidence check (`_has_spoken`).

  The reader accepts mixed files: an envelope is decrypted and a plaintext line passes through.
- **Fail closed on the welfare side.** A line that cannot be decrypted or parsed counts as unreadable evidence.
  - The spoken-evidence check treats it as spoken, so the voice arm votes diverged and never falls through to "never spoken".
  - The voice measures report distinctiveness as null for a corpus file holding such a line.
- **Migration.**
  - On the first write under encryption, Lingua rewrites the being's live log atomically with every line encrypted, but only when it holds a plaintext line.
  - At the next sleep, Hypnos rewrites the being's own rotated corpus files the same way.
  - Backups, `state/forks` and preservation bundles are never rewritten, only read.
- `docs/13-security-and-privacy.md` states the current reality: the log is encrypted at rest, heard speech is redacted (voice-development D7), and the log is no longer in the deferred list.

## Impact

- **Code:**
  - `kaine/persistence/encrypted_jsonl.py` (new);
  - `kaine/modules/lingua/intent_log.py`;
  - `kaine/modules/hypnos/{voice_alignment.py,voice_measures.py,module.py,corpus.py}`;
  - `kaine/lifecycle/divergence.py`.
- **Specs:** state-encryption (the covered-files list) and divergence-assessment (undecryptable evidence).
- **Risk:** high. A misread encrypted log must never turn a being that has spoken into one that abstains. A test pins that case.
- **Not covered:**
  - The external trainer's transient job files stay plaintext, because the trainer environment cannot import `kaine`.
  - The preservation bundle copies the encrypted bytes unchanged.
