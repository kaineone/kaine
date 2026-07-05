## 1. Package

- [x] 1.1 Add `kaine.lifecycle` to setuptools packages
- [x] 1.2 Create `kaine/lifecycle/__init__.py`

## 2. Snapshot

- [x] 2.1 Implement `kaine/lifecycle/snapshot.py` with `ForkSnapshot` dataclass + JSON load/save (atomic write-then-rename)

## 3. Merge strategies

- [x] 3.1 Implement `kaine/lifecycle/strategies.py` with `MergeStrategy` protocol + `UnionMergeStrategy` default + specialized strategies for mnemos / nous / eidolon / thymos
- [x] 3.2 Tests covering each strategy's documented semantics

## 4. ForkManager

- [x] 4.1 Implement `kaine/lifecycle/manager.py` with `ForkManager` (snapshot, restore, fork, merge), `AdapterMerger` protocol, `FakeAdapterMerger` default
- [x] 4.2 Tests: snapshot roundtrip, fork-with-shed, merge invokes strategies, restore-into-registry

## 5. Config

- [x] 5.1 Add `[lifecycle]` block to `config/kaine.toml`

## 6. Verification

- [x] 6.1 Full suite passes
- [x] 6.2 `openspec validate fork-merge --strict` clean
- [ ] 6.3 Commit, merge, archive
