// SPDX-FileCopyrightText: 2024 KAINE authors
// SPDX-License-Identifier: MIT

package api

import (
	"net/http"

	"github.com/gorilla/mux"
	"github.com/kaine/kaine/registry"
)

// PathRestart is the HTTP endpoint used to request a restart operation.
const PathRestart = "/restart"

// PathResume is the HTTP endpoint used to request a resume operation.
const PathResume = "/resume"

// RegisterRestartRoutes registers the restart HTTP endpoint.
func RegisterRestartRoutes(reg *registry.Registry, router *mux.Router) {
	router.HandleFunc(PathRestart, restartHandler(reg)).Methods(http.MethodPost)
}

// RegisterResumeRoutes registers the resume HTTP endpoint.
func RegisterResumeRoutes(reg *registry.Registry, router *mux.Router) {
	router.HandleFunc(PathResume, resumeHandler(reg)).Methods(http.MethodPost)
}

// RegisterRestartResumeRoutes registers both restart and resume HTTP endpoints.
func RegisterRestartResumeRoutes(reg *registry.Registry, router *mux.Router) {
	RegisterRestartRoutes(reg, router)
	RegisterResumeRoutes(reg, router)
}

// restartHandler creates a handler that stores a restart flag in the registry.
func restartHandler(reg *registry.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		if id == "" {
			http.Error(w, "missing id", http.StatusBadRequest)
			return
		}
		// Store restart request in the registry.
		// Ignore any return value; the registry implementation may or may not return an error.
		reg.Set("restart:"+id, true)

		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"restarted"}`))
	}
}

// resumeHandler creates a handler that stores a resume flag in the registry.
func resumeHandler(reg *registry.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("id")
		if id == "" {
			http.Error(w, "missing id", http.StatusBadRequest)
			return
		}
		// Store resume request in the registry.
		// Ignore any return value; the registry implementation may or may not return an error.
		reg.Set("resume:"+id, true)

		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"resumed"}`))
	}
}