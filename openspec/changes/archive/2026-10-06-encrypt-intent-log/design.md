## Context

- `StateEncryptor.encrypt_text` returns one base64 line per call, framed with a magic header.
- `maybe_decrypt` passes non-envelope input through unchanged.
- `decrypt_text` takes a fast path when encryption is disabled: it returns the text as is, even when that text is an envelope.
- The JSONL sink already writes one envelope per line.

## Decisions

### D1. One shared line reader
`kaine/persistence/encrypted_jsonl.py` provides the following. It depends only on the standard library and `kaine.security.crypto`, so the boundary-neutral contract holds.
- **`encode_record(record) -> str`:** `json.dumps(record, sort_keys=True)`, passed through `encrypt_text`.
- **`iter_records(path) -> Iterator[Line]`:** yields one `Line(record: dict | None, unreadable: bool)` per non-blank line.
  - An envelope is decrypted with the active encryptor, whether or not encryption is currently enabled. This avoids `decrypt_text`'s disabled fast path, which would hand back ciphertext.
  - A non-envelope line is parsed as plaintext JSON.
  - A line that fails authentication, has no key, or does not parse into a dict yields `unreadable=True`.
  - A missing file yields nothing. Any other I/O error propagates to the caller, which already treats it protectively.
- **`has_plaintext_line(path) -> bool`.**
- **`rewrite_encrypted(path) -> bool`:**
  - Rewrites every plaintext line as an envelope. Envelope lines are copied byte for byte, including ones it cannot decrypt, so nothing is ever dropped.
  - Writes to a temp file in the same directory, then fsync, `os.replace`, and an fsync of the directory.
  - Returns whether it rewrote.
  - Refuses (returns False) when encryption is disabled.

### D2. Writers
- `IntentExpressionLog._write` writes `encode_record(record)`.
- Before the first write of a process under enabled encryption, it calls `rewrite_encrypted(path)` once if `has_plaintext_line(path)`.

### D3. Readers fail closed
- **`_has_spoken`:** the first unreadable line returns True (spoken). Before this change, a line that failed to parse was skipped, so a log of nothing but unreadable lines read as "never spoken" and the voice arm abstained.
- **`compute_sleep_measures`:**
  - Counts unreadable lines as `unreadable_lines` in the measures record.
  - When the count is above 0, `distinctiveness` and `self_consistency` are null, and the cumulative profile is not updated from that file.
  - Null distinctiveness for a being that has spoken is a diverged vote.
- **The pair builder:** skips unreadable lines, counts them, and logs the count. They are not training data, and the template arm's rate is unaffected because they are not counted as scanned.

### D4. Migration scope
- **Rewritten:** only the running being's own live log, by Lingua on its first write, and its rotated `sleep-*.jsonl` files, by Hypnos at sleep after rotation.
- **Never rewritten:** anything under backups, `state/forks` or a preservation bundle.
- **Decommission:** copies the live log's bytes into the bundle unchanged, so the bundle holds envelopes under the same key as the rest of the bundle.

## Risks

- **A wrong or missing key.**
  - Every line reads as unreadable, so the arm votes diverged and the measures are null. Preservation stays protective.
  - Lingua keeps appending envelopes under the new key and never rewrites envelope lines it cannot read. Those lines are therefore never lost.
