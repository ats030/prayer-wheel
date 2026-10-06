package main

import (
	"encoding/json"
	"fmt"
	"midokoro-map/internal/shared"
	"net/http"
	"os"
	"path/filepath"
)

func registerPublishedSummaries(mux *http.ServeMux, dataDir string) error {
	b, err := os.ReadFile(filepath.Join(dataDir, "published-summaries.json"))
	if err != nil {
		return fmt.Errorf("summary-only startup: %w", err)
	}
	var p shared.PublishedSummaries
	if err := json.Unmarshal(b, &p); err != nil {
		return err
	}
	if err := p.Validate(); err != nil {
		return err
	}
	for kind := range shared.SummarySections {
		mux.HandleFunc("GET /api/"+kind+"/summary/{id}", func(w http.ResponseWriter, r *http.Request) {
			sections, ok := p.Items[kind][r.PathValue("id")]
			if !ok {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Header().Set("Cache-Control", "no-cache")
			json.NewEncoder(w).Encode(map[string]any{"sections": sections, "checked_at": p.CheckedAt})
		})
	}
	return nil
}
