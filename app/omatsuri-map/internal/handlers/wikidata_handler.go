package handlers

import (
	"encoding/json"
	"net/http"

	"omatsuri-map/internal/services"
)

type WikidataResponse struct {
	URL        string `json:"url"`
	License    string `json:"license"`
	LicenseURL string `json:"license_url,omitempty"`
	Artist     string `json:"artist,omitempty"`
	Credit     string `json:"credit,omitempty"`
	SourceURL  string `json:"source_url,omitempty"`
}

type WikidataHandler struct {
}

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

	url, license, err := services.FetchWikidataImage(qid)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	attribution, err := services.FetchCommonsAttribution(url)
	effectiveLicense := attribution.License
	if effectiveLicense == "" {
		effectiveLicense = license
	}
	if err != nil || effectiveLicense == "" || (attribution.AttributionRequired && attribution.Artist == "" && attribution.Credit == "") {
		http.Error(w, "image attribution metadata is incomplete", http.StatusNotFound)
		return
	}

	response := WikidataResponse{
		URL:        url,
		License:    effectiveLicense,
		LicenseURL: attribution.LicenseURL,
		Artist:     attribution.Artist,
		Credit:     attribution.Credit,
		SourceURL:  attribution.SourceURL,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}
