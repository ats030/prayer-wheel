package handlers

import (
	"encoding/json"
	"net/http"
	"strings"

	"midokoro-map/internal/omatsuri/services"
)

type ReverseGeocodeRequest struct {
	Lat float64 `json:"lat"`
	Lng float64 `json:"lng"`
}

type ReverseGeocodeResponse struct {
	Success      bool   `json:"success"`
	Location     string `json:"location"`
	FullLocation string `json:"full_location"`
	Prefecture   string `json:"prefecture"`
	City         string `json:"city"`
	ErrorMessage string `json:"error_message"`
}

type GeocodingHandler struct {
	service *services.GeocodingService
}

func NewGeocodingHandler(service *services.GeocodingService) *GeocodingHandler {
	return &GeocodingHandler{service: service}
}

func (h *GeocodingHandler) ReverseGeocode(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	var req ReverseGeocodeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(ReverseGeocodeResponse{
			Success:      false,
			ErrorMessage: "Invalid request body: " + err.Error(),
		})
		return
	}

	result, err := h.service.ReverseGeocode(req.Lat, req.Lng)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(ReverseGeocodeResponse{
			Success:      false,
			ErrorMessage: err.Error(),
		})
		return
	}

	// Build location string from result
	// Priority: City > Town > Village > Suburb
	var locationPart string
	if result.Address.City != "" {
		locationPart = result.Address.City
	} else if result.Address.Town != "" {
		locationPart = result.Address.Town
	} else if result.Address.Village != "" {
		locationPart = result.Address.Village
	} else if result.Address.Suburb != "" {
		locationPart = result.Address.Suburb
	}

	// Keep the useful hierarchy without returning Nominatim's often very long display_name.
	parts := []string{result.Address.State, locationPart, result.Address.CityDistrict, result.Address.Suburb, result.Address.Quarter, result.Address.Neighbourhood, result.Address.Road}
	fullLocation := buildFullLocation(parts...)

	response := ReverseGeocodeResponse{
		Success:      true,
		Location:     locationPart,
		FullLocation: fullLocation,
		Prefecture:   result.Address.State,
		City:         locationPart,
	}

	json.NewEncoder(w).Encode(response)
}

func buildFullLocation(parts ...string) string {
	unique := make([]string, 0, len(parts))
	seen := make(map[string]bool)
	for _, part := range parts {
		if part != "" && !seen[part] {
			unique = append(unique, part)
			seen[part] = true
		}
	}
	return strings.Join(unique, " ")
}
