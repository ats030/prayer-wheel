package handlers

import (
	"encoding/json"
	"net/http"

	"omatsuri-map/internal/services"
)

type WikipediaContentResponse struct {
	Description       string `json:"description"`
	SourceURL         string `json:"source_url"`
	ImageURL          string `json:"image_url,omitempty"`
	License           string `json:"license,omitempty"`
	LicenseURL        string `json:"license_url,omitempty"`
	Artist            string `json:"artist,omitempty"`
	Credit            string `json:"credit,omitempty"`
	ImageSource       string `json:"image_source_url,omitempty"`
	ContentLicenseURL string `json:"content_license_url"`
}

func GetWikipediaContent(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	title := r.URL.Query().Get("title")
	qid := r.URL.Query().Get("qid")
	if title == "" || qid == "" {
		http.Error(w, "title and qid parameters are required", http.StatusBadRequest)
		return
	}
	content, err := services.FetchWikipediaContent(title, qid)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	response := WikipediaContentResponse{
		Description:       content.Description,
		SourceURL:         content.SourceURL,
		ImageURL:          content.ImageURL,
		License:           content.Attribution.License,
		LicenseURL:        content.Attribution.LicenseURL,
		Artist:            content.Attribution.Artist,
		Credit:            content.Attribution.Credit,
		ImageSource:       content.Attribution.SourceURL,
		ContentLicenseURL: "https://creativecommons.org/licenses/by-sa/4.0/",
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}
