package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"midokoro-map/internal/omatsuri/services"
)

// findCommonsImageResponse mirrors a services.CommonsAttribution plus the
// festival name it was matched on, so the client can cache and attribute the
// image exactly like a path-A or path-B result.
type findCommonsImageResponse struct {
	ImageURL            string `json:"image_url"`
	License             string `json:"license,omitempty"`
	LicenseURL          string `json:"license_url,omitempty"`
	Artist              string `json:"artist,omitempty"`
	Credit              string `json:"credit,omitempty"`
	ImageSourceURL      string `json:"image_source_url,omitempty"`
	AttributionRequired bool   `json:"attribution_required"`
}

// GetFindCommonsImage is path C: given a festival's label_ja and prefecture,
// search Commons for a file whose base name is exactly that label and return
// it if and only if it carries usable licence metadata. No licence => 404,
// same contract as path B.
func GetFindCommonsImage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	label := strings.TrimSpace(r.URL.Query().Get("label"))
	prefecture := strings.TrimSpace(r.URL.Query().Get("prefecture"))
	if label == "" {
		http.Error(w, "label parameter is required", http.StatusBadRequest)
		return
	}
	attribution, err := services.FindCommonsImageByName(r.Context(), label, prefecture)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			http.Error(w, "upstream request timed out", http.StatusGatewayTimeout)
			return
		}
		http.Error(w, "no licensed image found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(findCommonsImageResponse{
		ImageURL:            attribution.ImageURL,
		License:             attribution.License,
		LicenseURL:          attribution.LicenseURL,
		Artist:              attribution.Artist,
		Credit:              attribution.Credit,
		ImageSourceURL:      attribution.SourceURL,
		AttributionRequired: attribution.AttributionRequired,
	})
}
