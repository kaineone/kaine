// SPDX-FileCopyrightText: 2024 The KAINE Authors
// SPDX-License-Identifier: MIT

package kaine

type GateColour string

const (
	Red   GateColour = "red"
	Green GateColour = "green"
	Blue  GateColour = "blue"
)

// Gate represents a gate.
type Gate struct {
	ID     string
	Colour GateColour
}

// Pass attempts to let a stage pass through the gate.
func (g *Gate) Pass(stage *Stage) error {
	// Existing logic for passing a stage through the gate would be here.
	// Record the gate colour for the stage currently passing.
	stage.GateColour = g.Colour
	return nil
}