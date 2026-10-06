package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"

	"midokoro-map/internal/shiseki/services"
)

// JalanHandler exposes nearby-hotel lookups backed by the Jalan Web Service.
type JalanHandler struct {
	service *services.JalanService
}

// NewJalanHandler creates a JalanHandler. service may be nil when
// JALAN_API_KEY is not configured; NearbyHotels then reports the feature as
// unavailable instead of panicking.
func NewJalanHandler(service *services.JalanService) *JalanHandler {
	return &JalanHandler{service: service}
}

type jalanNearbyResponse struct {
	Hotels []services.JalanNearbyHotel `json:"hotels"`
}

// NearbyHotels handles GET /api/jalan/nearby?lat=..&lng=..&range=.. and
// returns hotels near the given point, each with an affiliate link.
func (h *JalanHandler) NearbyHotels(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if h.service == nil {
		http.Error(w, "Jalan API is not configured", http.StatusServiceUnavailable)
		return
	}

	lat, err := strconv.ParseFloat(r.URL.Query().Get("lat"), 64)
	if err != nil {
		http.Error(w, "lat parameter is required and must be a number", http.StatusBadRequest)
		return
	}
	lng, err := strconv.ParseFloat(r.URL.Query().Get("lng"), 64)
	if err != nil {
		http.Error(w, "lng parameter is required and must be a number", http.StatusBadRequest)
		return
	}
	radiusKm := 3.0
	if raw := r.URL.Query().Get("range"); raw != "" {
		if v, err := strconv.ParseFloat(raw, 64); err == nil {
			radiusKm = v
		}
	}

	hotels, err := h.service.SearchNearby(lat, lng, radiusKm, 10)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(jalanNearbyResponse{Hotels: hotels})
}
