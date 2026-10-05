## API

```python
@dataclass(frozen=True)
class EntityIdentity:
    entity_id: str                 # "ent-<32 hex>" (minted, uuid4) or "legacy-<32 hex>" (sha256 prefix)
    lineage: tuple[str, ...] = ()  # ancestor entity_ids, oldest first; () for a root being
    origin: str = "minted"         # "minted" | "legacy"
    minted_at: float = 0.0         # wall time the identity was created or derived
    legacy_source: str | None = None  # e.g. "bundle:<preservation_id>" or "forks:<digest>"

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
def read_identity_sidecar(container_dir: Path) -> EntityIdentity | None             # no decryption; IdentityError when unreadable
def resolve_spawn_identity(state_root, *, prior_lived: bool) -> EntityIdentity
    # file present -> it; absent + not prior_lived -> mint + save;
    # absent + prior_lived -> legacy_identity("forks:<digest of this tree's snapshot ids>") + save
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

### D4. Live legacy trees

A tree that has lived without an identity file gets a legacy ID derived from the sorted IDs of the snapshots under its own `state/forks`. That ID is persisted at once. It is deterministic for that tree at that moment, and stable afterwards because it is persisted.

### D5. The history query reads metadata only

The query reads snapshot metadata and bundle manifests, and never decrypts entity content.
- A record without an identity belongs to no known being, so it does not count for a minted being.
- A being whose own identity cannot be determined counts as lived, so it is never regressed into a womb.

### D6. Merges

A merged snapshot keeps the target being's identity, the parent in `merge(parent_id, fork_id)`. The merged-in fork's ID is appended to its lineage record as `merged_from` in the metadata, not as an ancestor.

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
- **The sources:** `bundle:<preservation_id>` and `forks:<sha256 of the newline-joined sorted snapshot ids>`.

A change to either needs a migration change of its own.

### D9. What this change touches in the lifecycle code

- `ForkManager.snapshot`, `ForkManager.fork` and `ForkManager.merge` gain identity metadata and the sidecar.
- `preserve_live` and `revive` gain identity metadata and restore it.
- `capture_backup` adds the identity to its manifest.
- `fork_being` job payloads add the identity.

Artifact copying in `fork()` is unchanged. Re-encrypting a fork's artifacts under the child's key belongs to `entity-key-custody`.

Custody keeps its own metadata in its own files, keyed by `entity_id`. `entity.json` never holds custody fields.
