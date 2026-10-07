## 1. Encrypted intent log

- [x] 1.1 `kaine/persistence/encrypted_jsonl.py`: `encode_record`, `iter_records`, `has_plaintext_line`, `rewrite_encrypted` (D1). Tests: a round trip under an installed encryptor; a mixed file; a tampered envelope and a wrong key read as unreadable; an envelope read while encryption is disabled reads as unreadable, never as plaintext; a rewrite keeps undecryptable envelopes byte for byte and is atomic.
- [x] 1.2 Lingua writes envelopes and migrates its live log on the first write (D2). Tests: the file starts with envelopes under an encryptor; a sentinel phrase does not appear in the raw bytes; a pre-existing plaintext log is rewritten once.
- [x] 1.3 Readers (D3). Tests: a log holding one undecryptable line makes the voice arm vote diverged, not abstain; the measures report null distinctiveness and count `unreadable_lines`; the pair builder decrypts envelopes and skips unreadable lines.
- [x] 1.4 Hypnos rewrites the being's rotated corpus files at sleep (D4). Test: nothing outside `state/lingua/intent_log/` is rewritten.
- [x] 1.5 `docs/13-security-and-privacy.md`: the sensitivity section and the out-of-scope list describe the current behaviour; the state-encryption spec lists the intent log.
