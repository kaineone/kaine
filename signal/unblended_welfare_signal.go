// SPDX-FileCopyrightText: 2023 KAINE
// SPDX-License-Identifier: MIT

package signal

// UnblendedWelfareSignal returns the forward‑model errors for each provided Reader without any
// blending or aggregation. Each Reader is expected to expose a ForwardModelError method which
// internally uses the Reader's associated Processor.
//
// Parameters:
//   readers - a slice of Reader instances.
//
// Returns:
//   A slice of float64 values where each entry corresponds to the forward‑model error for the
//   Reader at the same index in the input slice.
func UnblendedWelfareSignal(readers []Reader) []float64 {
	errors := make([]float64, len(readers))
	for i, r := range readers {
		// The Reader implementation is responsible for invoking its own processor's
		// forward‑model error calculation. We simply forward the call.
		errors[i] = r.ForwardModelError()
	}
	return errors
}