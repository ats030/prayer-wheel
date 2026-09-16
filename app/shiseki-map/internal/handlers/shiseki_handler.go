package handlers

import (
	"encoding/json"
	"net/http"
	"strings"

	"shiseki-map/internal/services"
)

type ShisekiHandler struct {
	service *services.ShisekiService
}

func NewShisekiHandler(service *services.ShisekiService) *ShisekiHandler {
	return &ShisekiHandler{service: service}
}

func (h *ShisekiHandler) GetAllShiseki(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	shisekis := h.service.GetAll()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(shisekis)
}

func (h *ShisekiHandler) GetShisekiByPrefecture(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract prefecture from path: /api/shiseki/prefecture/:prefecture
	path := strings.TrimPrefix(r.URL.Path, "/api/shiseki/prefecture/")
	prefecture := strings.TrimSpace(path)

	if prefecture == "" {
		http.Error(w, "Prefecture parameter is required", http.StatusBadRequest)
		return
	}

	shisekis := h.service.GetByPrefecture(prefecture)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(shisekis)
}

func (h *ShisekiHandler) GetShisekiByQID(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract qid from path: /api/shiseki/:qid
	path := strings.TrimPrefix(r.URL.Path, "/api/shiseki/")
	qid := strings.TrimSpace(path)

	if qid == "" {
		http.Error(w, "QID parameter is required", http.StatusBadRequest)
		return
	}

	shiseki := h.service.GetByQID(qid)
	if shiseki == nil {
		http.Error(w, "Shiseki not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(shiseki)
}

func (h *ShisekiHandler) GetAllShisekiWithDescriptions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	shisekis := h.service.GetAllShisekiWithDescriptions()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(shisekis)
}
