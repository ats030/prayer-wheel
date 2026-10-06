package tokusan

import (
	"fmt"
	"midokoro-map/internal/shared"
	"midokoro-map/internal/tokusan/handlers"
	"midokoro-map/internal/tokusan/services"
	"net/http"
	"path/filepath"
)

// NewHandler keeps domain routes isolated while the outer server owns deployment.
func NewHandler(dataDir string) (http.Handler, error) {
	service, err := services.NewTokusanService(filepath.Join(dataDir, "tokusan", "tokusan.db"))
	if err != nil {
		return nil, fmt.Errorf("load tokusan: %w", err)
	}

	tokusanHandler := handlers.NewTokusanHandler(service)
	ordinaryHandler := handlers.NewTokusanHandler(service.WithoutAdvertising())
	selectHandler := func(w http.ResponseWriter, r *http.Request) *handlers.TokusanHandler {
		w.Header().Set("Cache-Control", "private, no-store")
		if shared.RequestAdsEnabled(r) {
			return tokusanHandler
		}
		return ordinaryHandler
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/tokusan/prefecture/", func(w http.ResponseWriter, r *http.Request) { selectHandler(w, r).GetByPrefecture(w, r) })
	mux.HandleFunc("/api/tokusan/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/tokusan/" {
			selectHandler(w, r).GetAll(w, r)
			return
		}
		selectHandler(w, r).GetByQID(w, r)
	})
	mux.HandleFunc("/api/tokusan", func(w http.ResponseWriter, r *http.Request) { selectHandler(w, r).GetAll(w, r) })
	mux.HandleFunc("/api/sections/", tokusanHandler.GetSections)

	wikidataHandler := handlers.NewWikidataHandler()
	mux.HandleFunc("/api/wikiimage", wikidataHandler.GetWikidataImage)

	return mux, nil
}
