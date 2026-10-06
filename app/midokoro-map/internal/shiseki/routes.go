package shiseki

import (
	"fmt"
	"midokoro-map/internal/shared"
	"midokoro-map/internal/shiseki/handlers"
	"midokoro-map/internal/shiseki/services"
	"net/http"
	"path/filepath"
)

// NewHandler keeps domain routes isolated while the outer server owns deployment.
func NewHandler(dataDir string) (http.Handler, error) {
	service, err := services.NewShisekiService(filepath.Join(dataDir, "shiseki", "shiseki.db"))
	if err != nil {
		return nil, fmt.Errorf("load shiseki: %w", err)
	}

	// Initialize handlers
	shisekiHandler := handlers.NewShisekiHandler(service)
	wikidataHandler := handlers.NewWikidataHandler()

	geocodingService := services.NewGeocodingService()
	geocodingHandler := handlers.NewGeocodingHandler(geocodingService)

	jalanService := services.NewJalanService() // nil when JALAN_API_KEY is unset
	jalanHandler := handlers.NewJalanHandler(jalanService)

	hotelAreaService := services.NewHotelAreaServiceWithID(shared.TrackingID("shiseki"))
	hotelAreaHandler := handlers.NewHotelAreaHandler(hotelAreaService)
	ordinaryHotelHandler := handlers.NewHotelAreaHandler(services.NewHotelAreaServiceWithID(""))
	// Create mux
	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/shiseki/prefecture/", shisekiHandler.GetShisekiByPrefecture)
	mux.HandleFunc("/api/shiseki/descriptions", shisekiHandler.GetAllShisekiWithDescriptions)
	mux.HandleFunc("/api/shiseki/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/shiseki/" {
			shisekiHandler.GetAllShiseki(w, r)
			return
		}
		shisekiHandler.GetShisekiByQID(w, r)
	})
	mux.HandleFunc("/api/shiseki", shisekiHandler.GetAllShiseki)
	mux.HandleFunc("/api/wiki/image", wikidataHandler.GetWikidataImage)
	mux.HandleFunc("/api/wiki/links", wikidataHandler.GetWikidataLinks)
	mux.HandleFunc("/api/wiki/content", handlers.NewWikipediaContentHandler(service).GetWikipediaContent)
	mux.HandleFunc("/api/geocoding/reverse", geocodingHandler.ReverseGeocode)
	mux.HandleFunc("/api/jalan/nearby", jalanHandler.NearbyHotels)
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
