package omatsuri

import (
	"fmt"
	"midokoro-map/internal/omatsuri/handlers"
	"midokoro-map/internal/omatsuri/services"
	"midokoro-map/internal/shared"
	"net/http"
	"path/filepath"
)

// NewHandler keeps domain routes isolated while the outer server owns deployment.
func NewHandler(dataDir string) (http.Handler, error) {
	service, err := services.NewFestivalService(filepath.Join(dataDir, "omatsuri", "festivals.db"))
	if err != nil {
		return nil, fmt.Errorf("load omatsuri: %w", err)
	}

	// Initialize handlers
	festivalHandler := handlers.NewFestivalHandler(service)
	wikidataHandler := handlers.NewWikidataHandler()

	geocodingService := services.NewGeocodingService()
	geocodingHandler := handlers.NewGeocodingHandler(geocodingService)

	hotelAreaService := services.NewHotelAreaServiceWithID(shared.TrackingID("omatsuri"))
	hotelAreaHandler := handlers.NewHotelAreaHandler(hotelAreaService)
	ordinaryHotelHandler := handlers.NewHotelAreaHandler(services.NewHotelAreaServiceWithID(""))

	// Create mux
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/festivals/prefecture/", festivalHandler.GetFestivalsByPrefecture)
	mux.HandleFunc("/api/festivals/descriptions", festivalHandler.GetAllFestivalsWithDescriptions)
	mux.HandleFunc("/api/festivals/", festivalHandler.GetFestivalsOrByQID)
	mux.HandleFunc("/api/festivals", festivalHandler.GetAllFestivals)
	mux.HandleFunc("/api/wiki/image", wikidataHandler.GetWikidataImage)
	mux.HandleFunc("/api/wiki/links", wikidataHandler.GetWikidataLinks)
	mux.HandleFunc("/api/wiki/content", handlers.GetWikipediaContent)
	mux.HandleFunc("/api/commons/image", handlers.GetFindCommonsImage)
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
