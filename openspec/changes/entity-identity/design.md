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
def identity_of_snapshot(snap: ForkSnapshot) -> EntityIdentity | None    # reads snap.metadata["identity"]
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
