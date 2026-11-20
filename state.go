// SPDX-FileCopyrightText: 2023 KAINE
// SPDX-License-Identifier: MIT

package api

// Request represents an incoming request.
type Request struct {
	// Example fields – actual fields may vary.
	ID   string
	Data string
}

// State holds the internal state of the service.
type State struct {
	// Other state fields omitted for brevity.

	// Requests is a log of all processed requests.
	Requests []Request
}

// Request records a request and returns success without changing other state.
// It appends the incoming request to the Requests log and returns nil to indicate success.
func (s *State) Request(req Request) error {
	// Record the request.
	s.Requests = append(s.Requests, req)

	// Return success without modifying other state.
	return nil
}