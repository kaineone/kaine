## API

```python
@dataclass(frozen=True)
class EntityIdentity:
    entity_id: str                 # "ent-<32 hex>" (minted, uuid4) or "legacy-<32 hex>" (sha256 prefix)
    lineage: tuple[str, ...] = ()  # ancestor entity_ids, oldest first; () for a root being
    origin: str = "minted"         # "minted" | "legacy"
    minted_at: float = 0.0         # wall time the identity was created or derived
    legacy_source: str | None = None  # e.g. "bundle:<preservation_id>" or "tree:<digest>"

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EntityIdentity": ...   # raises IdentityError on malformed input

IDENTITY_PATH = Path("state/identity/entity.json")

class IdentityError(RuntimeError): ...

def load_identity(path: Path = IDENTITY_PATH) -> EntityIdentity | None   # None when absent; IdentityError when unreadable
def save_identity(identity: EntityIdentity, path: Path = IDENTITY_PATH) -> None  # atomic, 0600; refuses to overwrite a different entity_id
def mint_identity() -> EntityIdentity                                   # new root identity; pure
def fork_identity(parent: EntityIdentity) -> EntityIdentity              # new id, lineage = parent.lineage + (parent.entity_id,)
def legacy_identity(source: str) -> EntityIdentity                       # deterministic: same source -> same entity_id
def identity_of_snapshot(snap: ForkSnapshot) -> EntityIdentity | None    # reads snap.metadata["identity"] (after decryption)
def write_identity_sidecar(container_dir: Path, identity: EntityIdentity) -> None  # plaintext identity.json beside an encrypted container
def read_identity_sidecar(container_dir: Path) -> tuple[str, tuple[str, ...]] | None  # (entity_id, lineage); no decryption; IdentityError when unreadable
def own_lived_artifacts(state_root) -> list[Path]     # this tree's own lived artifacts (D4); never forks/ or preservation/
def resolve_spawn_identity(state_root) -> EntityIdentity
    # file present -> it; absent + no own artifacts -> mint + save;
    # absent + own artifacts -> legacy_identity("tree:<digest of those artifacts>") + save
def has_prior_lived_history_in_lineage(identity: EntityIdentity | None, state_root) -> bool
    # None -> True (unknown lineage counts as lived); else True iff a fork snapshot or
    # preservation record carries this entity_id or one in its lineage
```

## Decisions

### D1. The ID format

`ent-` plus 32 hex characters from `uuid4`. It is opaque and carries no time, host or name, so it reveals nothing about the operator.

### D2. Where the identity lives

`state/identity/entity.json`, inside the being's state tree, so it moves with the being.
- It is not encrypted. The ID is not cognitive content, and key custody needs to read it before any key is unsealed.
- It is owner-only, like the rest of `state/`.

### D3. Never mint on revival

Revival restores the bundle's identity. A bundle without one gets `legacy_identity("bundle:<preservation_id>")`, which is deterministic. If a different identity file already exists in the target tree, revival refuses rather than silently overwriting it.

### D4. Live legacy trees: this tree's own artifacts only

`state/forks` and `state/preservation` hold other beings as well as this one (preserved beings, older forks), so they are never evidence that *this* tree has lived.
- **Legacy evidence is this tree's own lived artifacts:** the developmental stage file, the Phantasia world-model checkpoint, the Hypnos consolidation-divergence record and the perception desired-state.
- A tree with no identity file and none of those artifacts is a fresh spawn and is minted an ID, however many foreign fork snapshots or bundles sit under `state/`.
- A tree with no identity file and at least one of them gets a legacy ID with source `tree:<digest>`. The digest is the SHA-256 hex of the sorted lines `<path relative to the state root>\0<sha256 of the file>`, one per present artifact. The ID is persisted at once. It is deterministic at that moment and stable afterwards, because it is persisted and never re-derived.
- `resolve_spawn_identity` computes this evidence itself; it is never fed the old global `has_prior_lived_history`.

### D5. The history query reads metadata only

The query reads snapshot metadata and bundle manifests, and never decrypts entity content.
- A record without an identity belongs to no known being, so it does not count for a minted being.
- A being whose own identity cannot be determined counts as lived, so it is never regressed into a womb.

### D6. Merges

A merged snapshot keeps the target being's identity, the parent in `merge(parent_id, fork_id)`. The merged-in being's `entity_id` is recorded as `merged_from_entity` in the metadata (the existing `merged_from` key keeps holding the two snapshot IDs), not as an ancestor.

### D7. Plaintext sidecars beside every encrypted container (agreed with key custody)

Key custody must learn which being's key opens a container *before* decrypting it, so the identity inside an encrypted snapshot cannot be the only copy. Every encrypted container gets a plaintext sidecar holding `entity_id` and `lineage` only:
- fork snapshots: `state/forks/<snapshot_id>/identity.json`;
- preservation bundles: the plaintext `manifest.json` gains an `identity` object;
- decommission backups: their plaintext `manifest.json` gains the same object;
- forked-being batch jobs: the job payload carries the fork's identity next to `fork_snapshot_id`.

The metadata inside the snapshot still records the identity. On load, the two must agree; a mismatch is an `IdentityError`. Custody additionally binds `entity_id` as AEAD associated data, so a swapped sidecar fails closed.

### D8. Frozen formats

The string format (`ent-`/`legacy-` plus 32 lowercase hex) and the legacy derivation are frozen, because custody uses the ID in ciphertext bindings and key-file names.
- **The derivation:** `"legacy-" + sha256(source.encode("utf-8")).hexdigest()[:32]`.
- **The sources:** `bundle:<preservation_id>` and `tree:<digest>`, as defined in D4.

A change to either needs a migration change of its own. Carrying an existing ID is not a derivation: a legacy ID read from a bundle manifest keeps its value, and its `legacy_source` records where it was read from (`manifest:<preservation_id>`).

### D9. What this change touches in the lifecycle code

- `ForkManager.snapshot`, `ForkManager.fork` and `ForkManager.merge` gain identity metadata and the sidecar.
- `preserve_live` and `revive` gain identity metadata and restore it.
- `capture_backup` adds the identity to its manifest.
- `fork_being` job payloads add the identity.

Artifact copying in `fork()` is unchanged. Re-encrypting a fork's artifacts under the child's key belongs to `entity-key-custody`.

Custody keeps its own metadata in its own files, keyed by `entity_id`. `entity.json` never holds custody fields.

### D10. Ordering and failure (agreed with key custody)

- **Ordering.** `resolve_spawn_identity` runs in the cycle start path before any module is constructed, before the oscillator layer, Spot or any snapshot writer starts. A legacy ID is therefore persisted before anything in the same boot can write a new artifact that would shift the derivation.
- **Failure.** Every `IdentityError` is raised before any state is modified:
  - an unreadable `entity.json`;
  - a sidecar that disagrees with the in-snapshot identity;
  - a revive target that holds a different ID.

  Revival validates the bundle's identity against the target tree before it restores any module state, and never writes to the bundle. Key custody maps an `IdentityError` to its cannot-resume path (keep all state, raise a welfare incident, never mint).
- **Revive persistence.** Revival checks the target tree's identity before anything starts, but writes the bundle's identity to the tree only after the revive has landed. A revive that is refused or fails therefore leaves no identity behind, so the next ordinary spawn on that tree cannot reuse the bundle's ID. If the write fails after landing, the boot stops with exit code 11 and the modules are shut down.
- **Preservation never fails over identity.** Snapshots and preservations read the identity through a guard. An unreadable identity is logged as an error, the snapshot metadata records `identity_unreadable` with the reason, the plaintext manifest records only `identity_unreadable: true`, and the being is preserved without an identity. Welfare-protective preservation outranks attribution.
- **Sidecar failure keeps the snapshot.** The identity is already inside the snapshot, and a missing sidecar is accepted on load, so a sidecar that cannot be written is logged and the snapshot is kept.

### D11. How identity reaches the lifecycle code

- `ForkManager` takes an optional `identity_source: Callable[[], EntityIdentity | None]`, which defaults to none.
  - The cycle passes the running tree's loader.
  - A manager without a source writes no identity, which is today's behaviour for tools and tests, so a test can never pick up the host's real identity.
- `fork()` always overwrites the inherited `identity` key with the child's forked identity. A fork of a snapshot that has no identity gets `fork_identity(legacy_identity("snapshot:<parent id>"))`, so its lineage reaches back to the legacy parent the way a revived legacy bundle does, and it records the parent snapshot ID as `forked_from_unidentified`.
- Preservation bundles live under the configured preservation `out_root` (default `backups/`), so the history query takes the bundle roots to scan.
