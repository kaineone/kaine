// SPDX-FileCopyrightText: 2024 KAINE
// SPDX-License-Identifier: Apache-2.0

package kaine

import (
	"encoding/json"
)

// Entity represents a core entity within the KAINE system.
type Entity struct {
	// Public fields.
	Name string `json:"name"`

	// Private/internal fields.
	booted    bool `json:"-"`
	BootCount int  `json:"bootCount,omitempty"`
}

// NewEntity constructs a new Entity with the given name.
func NewEntity(name string) *Entity {
	return &Entity{
		Name: name,
	}
}

// Boot performs a full boot of the entity. It is idempotent; subsequent calls
// are no‑ops and do not increment the boot counter.
func (e *Entity) Boot() error {
	if e.booted {
		return nil
	}
	e.booted = true
	e.BootCount++
	// ... other full‑boot initialization logic (unchanged) ...
	return nil
}

// Freeze serialises the entity into a JSON snapshot. The snapshot does not
// include internal bookkeeping fields such as the boot flag.
func (e *Entity) Freeze() ([]byte, error) {
	return json.Marshal(e)
}

// NewEntityFromFrozen creates a new Entity from a frozen snapshot. The entity
// is considered already booted because the snapshot represents a state that
// existed after a successful boot. This prevents a full boot when the entity
// is resumed.
func NewEntityFromFrozen(data []byte) (*Entity, error) {
	var ent Entity
	if err := json.Unmarshal(data, &ent); err != nil {
		return nil, err
	}
	// The entity was booted before it was frozen – preserve that state.
	ent.booted = true
	return &ent, nil
}

// Resume restores a frozen entity without performing a full boot. If the entity
// is already marked as booted (as done by NewEntityFromFrozen), this method
// simply returns without re‑initialising the entity.
func (e *Entity) Resume() error {
	if e.booted {
		// Already booted; nothing more to do.
		return nil
	}
	// If, for some reason, the entity is not marked as booted, fall back to a
	// full boot to bring it to a usable state.
	return e.Boot()
}