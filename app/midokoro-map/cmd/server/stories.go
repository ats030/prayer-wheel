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

var storySlugs = []string{"arita-porcelain", "kusatsu-yumomi", "kawagoe-festival"}

func registerStoryRoutes(mux *http.ServeMux, frontendDir string) {
	registerStoryPage(mux, frontendDir, "/stories", "index.html")
	for _, slug := range storySlugs {
		registerStoryPage(mux, frontendDir, "/stories/"+slug, slug+".html")
		registerStoryEvents(mux, slug)
	}
}

func registerStoryPage(mux *http.ServeMux, frontendDir, path, file string) {
	mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		http.ServeFile(w, r, filepath.Join(frontendDir, "stories", file))
	})
	// Accept only canonical page paths (no subtree aliases).
	if path != "/stories" {
		mux.HandleFunc(path+"/", func(w http.ResponseWriter, r *http.Request) {
			http.NotFound(w, r)
		})
	}
}

func registerStoryEvents(mux *http.ServeMux, slug string) {
	prefix := "/api/story-events/" + slug + "/"
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
		log.Printf("story_event story=%s event=%s", slug, event)
		w.WriteHeader(http.StatusNoContent)
	})
}
