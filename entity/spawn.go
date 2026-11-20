// SPDX-FileCopyrightText: 2024 KAINE
// SPDX-License-Identifier: MIT

package entity

import (
	"context"
	"log"

	"github.com/spf13/viper"
)

// Repository defines the persistence operations required for an Entity.
type Repository interface {
	Create(ctx context.Context, e *Entity) error
}

// Service provides the public API for managing Entities.
type Service struct {
	repo Repository
}

// Entity represents a domain entity.  Fields are defined elsewhere.
type Entity struct {
	// ...
}

// Spawn creates a new Entity, persists it, and triggers custody‑related
// actions when the custody feature is enabled.
func (s *Service) Spawn(ctx context.Context, data map[string]interface{}) (*Entity, error) {
	// Construct the entity from the incoming data.
	e := &Entity{
		// Populate fields based on data...
	}

	// Persist the entity.
	if err := s.repo.Create(ctx, e); err != nil {
		return nil, err
	}

	// If custody handling is enabled, escrow the DEK and publish to GitHub.
	if viper.GetBool("custody.enabled") {
		if err := escrow_dek(e); err != nil {
			log.Printf("escrow_dek failed for entity %v: %v", e, err)
		}
		if err := publish_to_github(e); err != nil {
			log.Printf("publish_to_github failed for entity %v: %v", e, err)
		}
	}

	return e, nil
}