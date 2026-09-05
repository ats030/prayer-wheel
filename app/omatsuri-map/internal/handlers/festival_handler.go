package handlers

import (
	"encoding/json"
	"net/http"

	"omatsuri-map/internal/services"
)

// FestivalHandler handles festival-related HTTP requests
type FestivalHandler struct {
	service *services.FestivalService
}

// NewFestivalHandler creates a new festival handler
func NewFestivalHandler(service *services.FestivalService) *FestivalHandler {
	return &FestivalHandler{service: service}
}

// FestivalResponse represents the API response structure
type FestivalResponse struct {
	QID        string  `json:"qid"`
	LabelJA    string  `json:"label_ja"`
	LabelEN    *string `json:"label_en,omitempty"`
	Prefecture string  `json:"prefecture"`
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
}

// FestivalsResponse represents a list of festivals
type FestivalsResponse struct {
	Festivals []FestivalResponse `json:"festivals"`
	Count     int                `json:"count"`
}

// FestivalsByPrefectureResponse represents festivals grouped by prefecture
type FestivalsByPrefectureResponse struct {
	Prefecture string             `json:"prefecture"`
	Festivals  []FestivalResponse `json:"festivals"`
}

// HandleFestivals handles GET /api/festivals requests
func (h *FestivalHandler) HandleFestivals(w http.ResponseWriter, r *http.Request) {
	festivals := h.service.GetAll()
	
	response := FestivalsResponse{
		Festivals: convertToFestivalResponses(festivals),
		Count:     len(festivals),
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// HandleFestivalsByPrefecture handles GET /api/festivals/prefecture/:prefecture requests
func (h *FestivalHandler) HandleFestivalsByPrefecture(w http.ResponseWriter, r *http.Request) {
	prefecture := r.PathValue("prefecture")
	festivals := h.service.GetByPrefecture(prefecture)
	
	response := FestivalsByPrefectureResponse{
		Prefecture: prefecture,
		Festivals:  convertToFestivalResponses(festivals),
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// HandleFestivalByID handles GET /api/festivals/:qid requests
func (h *FestivalHandler) HandleFestivalByID(w http.ResponseWriter, r *http.Request) {
	qid := r.PathValue("qid")
	festival, err := h.service.GetByID(qid)
	
	if err != nil {
		http.Error(w, "Failed to retrieve festival", http.StatusInternalServerError)
		return
	}
	
	if festival == nil {
		http.Error(w, "Festival not found", http.StatusNotFound)
		return
	}
	
	response := convertToFestivalResponse(festival)
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// Helper functions
func convertToFestivalResponses(festivals []services.Festival) []FestivalResponse {
	responses := make([]FestivalResponse, len(festivals))
	for i, f := range festivals {
		responses[i] = convertToFestivalResponse(&f)
	}
	return responses
}

func convertToFestivalResponse(f *services.Festival) FestivalResponse {
	return FestivalResponse{
		QID:        f.QID,
		LabelJA:    f.LabelJA,
		LabelEN:    f.LabelEN,
		Prefecture: f.Prefecture,
		Latitude:   f.Latitude,
		Longitude:  f.Longitude,
	}
}
