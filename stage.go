// SPDX-FileCopyrightText: 2024 The KAINE Authors
// SPDX-License-Identifier: MIT

package kaine

import "time"

// Stage represents a stage in the system.
type Stage struct {
	ID       string
	Name     string
	Duration time.Duration
	Active   bool
	// GateColour holds the colour of the gate this stage is currently passing through.
	GateColour GateColour // record the colour of the gate currently passing
}