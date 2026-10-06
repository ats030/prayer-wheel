package handlers

import (
	"encoding/json"
	"net/http"
	"strings"

	"midokoro-map/internal/onsen/services"
)

type OnsenHandler struct {
	service *services.OnsenService
}

func NewOnsenHandler(service *services.OnsenService) *OnsenHandler {
	return &OnsenHandler{service: service}
}

func (h *OnsenHandler) GetAllOnsen(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	onsens := h.service.GetAll()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(onsens)
}

func (h *OnsenHandler) GetOnsenByPrefecture(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract prefecture from path: /api/onsen/prefecture/:prefecture
	path := strings.TrimPrefix(r.URL.Path, "/api/onsen/prefecture/")
	prefecture := strings.TrimSpace(path)

	if prefecture == "" {
		http.Error(w, "Prefecture parameter is required", http.StatusBadRequest)
		return
	}

	onsens := h.service.GetByPrefecture(prefecture)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(onsens)
}

func (h *OnsenHandler) GetOnsenByQID(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract qid from path: /api/onsen/:qid
	path := strings.TrimPrefix(r.URL.Path, "/api/onsen/")
	qid := strings.TrimSpace(path)

	if qid == "" {
		http.Error(w, "QID parameter is required", http.StatusBadRequest)
		return
	}

	onsen := h.service.GetByQID(qid)
	if onsen == nil {
		http.Error(w, "Onsen not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(onsen)
}

func (h *OnsenHandler) GetAllOnsenWithDescriptions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	onsens := h.service.GetAllOnsenWithDescriptions()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(onsens)
}
