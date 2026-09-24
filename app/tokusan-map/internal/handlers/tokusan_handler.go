package handlers

import (
	"encoding/json"
	"net/http"
	"strings"

	"tokusan-map/internal/services"
)

type TokusanHandler struct {
	service *services.TokusanService
}

func NewTokusanHandler(service *services.TokusanService) *TokusanHandler {
	return &TokusanHandler{service: service}
}

func (h *TokusanHandler) GetAll(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(h.service.GetAll())
}

func (h *TokusanHandler) GetByPrefecture(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	prefecture := strings.TrimPrefix(r.URL.Path, "/api/tokusan/prefecture/")
	prefecture = strings.TrimSpace(prefecture)
	if prefecture == "" {
		http.Error(w, "Prefecture parameter is required", http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(h.service.GetByPrefecture(prefecture))
}

func (h *TokusanHandler) GetByQID(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	qid := strings.TrimPrefix(r.URL.Path, "/api/tokusan/")
	qid = strings.TrimSpace(qid)
	if qid == "" {
		http.Error(w, "QID parameter is required", http.StatusBadRequest)
		return
	}
	row := h.service.GetByQID(qid)
	if row == nil {
		http.Error(w, "Tokusan not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(row)
}
