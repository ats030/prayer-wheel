package main

import (
	"log"
	"net/http"
	"path/filepath"
	"strings"
)

// Fixed event names allow aggregates in existing request/service logs. No event
// body, identifier, referrer, query or location is read or stored by the app.
var storyEvents = map[string]bool{
	"view": true, "entry-home": true, "entry-shared": true,
	"explore": true, "follow": true, "share-open": true,
	"share-returned": true, "copy-success": true,
}

func registerStoryRoutes(mux *http.ServeMux, frontendDir string) {
	const path = "/stories/arita-porcelain"
	mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		http.ServeFile(w, r, filepath.Join(frontendDir, "stories", "arita-porcelain.html"))
	})
	// Accept only the single canonical page path (no subtree aliases).
	mux.HandleFunc(path+"/", func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	})
	const prefix = "/api/story-events/arita-porcelain/"
	mux.HandleFunc(prefix, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		if r.Method != http.MethodPost {
			w.Header().Set("Allow", "POST")
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		event := strings.TrimPrefix(r.URL.Path, prefix)
		if !storyEvents[event] || r.URL.RawQuery != "" {
			http.NotFound(w, r)
			return
		}
		if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" {
			http.Error(w, "same origin required", http.StatusForbidden)
			return
		}
		if r.ContentLength != 0 {
			http.Error(w, "empty body required", http.StatusBadRequest)
			return
		}
		log.Printf("story_event story=arita-porcelain event=%s", event)
		w.WriteHeader(http.StatusNoContent)
	})
}
