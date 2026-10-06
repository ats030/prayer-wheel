package onsen

import (
	"fmt"
	"midokoro-map/internal/onsen/handlers"
	"midokoro-map/internal/onsen/services"
	"midokoro-map/internal/shared"
	"net/http"
	"path/filepath"
)

// NewHandler keeps domain routes isolated while the outer server owns deployment.
func NewHandler(dataDir string) (http.Handler, error) {
	service, err := services.NewOnsenService(filepath.Join(dataDir, "onsen", "onsen.db"))
	if err != nil {
		return nil, fmt.Errorf("load onsen: %w", err)
	}

	// Initialize handlers
	onsenHandler := handlers.NewOnsenHandler(service)
	wikidataHandler := handlers.NewWikidataHandler()

	geocodingService := services.NewGeocodingService()
	geocodingHandler := handlers.NewGeocodingHandler(geocodingService)

	hotelAreaService := services.NewHotelAreaServiceWithID(shared.TrackingID("onsen"))
	hotelAreaHandler := handlers.NewHotelAreaHandler(hotelAreaService)
	ordinaryHotelHandler := handlers.NewHotelAreaHandler(services.NewHotelAreaServiceWithID(""))
	// Create mux
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/onsen/prefecture/", onsenHandler.GetOnsenByPrefecture)
	mux.HandleFunc("/api/onsen/descriptions", onsenHandler.GetAllOnsenWithDescriptions)
	mux.HandleFunc("/api/onsen/", onsenHandler.GetAllOnsen)
	mux.HandleFunc("/api/onsen", onsenHandler.GetAllOnsen)
	mux.HandleFunc("/api/wiki/image", wikidataHandler.GetWikidataImage)
	mux.HandleFunc("/api/wiki/links", wikidataHandler.GetWikidataLinks)
	mux.HandleFunc("/api/wiki/content", handlers.GetWikipediaContent)
	mux.HandleFunc("/api/geocoding/reverse", geocodingHandler.ReverseGeocode)
	mux.HandleFunc("/api/hotel-area/nearby", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "private, no-store")
		if shared.RequestAdsEnabled(r) {
			hotelAreaHandler.NearbyHotels(w, r)
		} else {
			ordinaryHotelHandler.NearbyHotels(w, r)
		}
	})

	return mux, nil
}
