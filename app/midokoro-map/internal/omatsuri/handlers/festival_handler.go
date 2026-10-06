package handlers

import (
	"encoding/json"
	"net/http"
	"strings"

	"midokoro-map/internal/omatsuri/services"
)

type FestivalHandler struct {
	service *services.FestivalService
}

func NewFestivalHandler(service *services.FestivalService) *FestivalHandler {
	return &FestivalHandler{service: service}
}

func (h *FestivalHandler) GetAllFestivals(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	festivals := h.service.GetAll()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(festivals)
}

func (h *FestivalHandler) GetFestivalsByPrefecture(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract prefecture from path: /api/festivals/prefecture/:prefecture
	path := strings.TrimPrefix(r.URL.Path, "/api/festivals/prefecture/")
	prefecture := strings.TrimSpace(path)

	if prefecture == "" {
		http.Error(w, "Prefecture parameter is required", http.StatusBadRequest)
		return
	}

	festivals := h.service.GetByPrefecture(prefecture)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(festivals)
}

// GetFestivalsOrByQID serves the list at /api/festivals/ and one festival at /api/festivals/:qid.
func (h *FestivalHandler) GetFestivalsOrByQID(w http.ResponseWriter, r *http.Request) {
	if strings.TrimSpace(strings.TrimPrefix(r.URL.Path, "/api/festivals/")) == "" {
		h.GetAllFestivals(w, r)
		return
	}
	h.GetFestivalByQID(w, r)
}

func (h *FestivalHandler) GetFestivalByQID(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract qid from path: /api/festivals/:qid
	path := strings.TrimPrefix(r.URL.Path, "/api/festivals/")
	qid := strings.TrimSpace(path)

	if qid == "" {
		http.Error(w, "QID parameter is required", http.StatusBadRequest)
		return
	}

	festival := h.service.GetByQID(qid)
	if festival == nil {
		http.Error(w, "Festival not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(festival)
}

func (h *FestivalHandler) GetAllFestivalsWithDescriptions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	festivals := h.service.GetAllFestivalsWithDescriptions()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(festivals)
}
