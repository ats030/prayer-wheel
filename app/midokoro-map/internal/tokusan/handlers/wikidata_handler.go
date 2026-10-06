package handlers

import (
	"encoding/json"
	"net/http"

	"midokoro-map/internal/tokusan/services"
)

type WikidataImageResponse struct {
	URL        string `json:"url"`
	License    string `json:"license"`
	LicenseURL string `json:"license_url,omitempty"`
	Artist     string `json:"artist,omitempty"`
	Credit     string `json:"credit,omitempty"`
	SourceURL  string `json:"source_url,omitempty"`
}

type WikidataHandler struct{}

func NewWikidataHandler() *WikidataHandler {
	return &WikidataHandler{}
}

func (h *WikidataHandler) GetWikidataImage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	qid := r.URL.Query().Get("qid")
	if qid == "" {
		http.Error(w, "qid parameter is required", http.StatusBadRequest)
		return
	}

	imageURL, license, err := services.FetchWikidataImage(qid)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	attribution, _ := services.FetchCommonsAttribution(r.Context(), imageURL)
	effectiveLicense := attribution.License
	if effectiveLicense == "" {
		effectiveLicense = license
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "private, max-age=3600")
	json.NewEncoder(w).Encode(WikidataImageResponse{
		URL:        imageURL,
		License:    effectiveLicense,
		LicenseURL: attribution.LicenseURL,
		Artist:     attribution.Artist,
		Credit:     attribution.Credit,
		SourceURL:  attribution.SourceURL,
	})
}
