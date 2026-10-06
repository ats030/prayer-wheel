package handlers

import (
	"encoding/json"
	"net/http"

	"midokoro-map/internal/onsen/services"
)

// wikiSectionPayload is the per-section JSON shape for the five panel
// sections. Summary is the LLM-generated lead sentence (empty when the article
// has no relevant text, a model is unavailable, or summarization is disabled
// in a deployment without a warmed cache). Items is the structured list of
// labelled rows. The raw article text is not sent (decided 2026-10-01): a
// section without a summary is empty and the client hides it. SourceURL is the
// canonical ja.wikipedia.org page the content was drawn from. SourceTitle is
// set only when the content came from the municipality article fallback.
type wikiSectionPayload struct {
	Summary     string                 `json:"summary,omitempty"`
	Items       []services.SectionItem `json:"items,omitempty"`
	SourceURL   string                 `json:"source_url,omitempty"`
	SourceTitle string                 `json:"source_title,omitempty"`
}

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

	History  wikiSectionPayload `json:"history,omitempty"`
	Food     wikiSectionPayload `json:"food,omitempty"`
	Efficacy wikiSectionPayload `json:"efficacy,omitempty"`
	Access   wikiSectionPayload `json:"access,omitempty"`
	Tourism  wikiSectionPayload `json:"tourism,omitempty"`

	// SectionsUnavailable reports that the section lookup itself failed (for
	// example a Wikipedia rate limit) rather than that the article has no such
	// section. Without this the client cannot tell the two apart and caches the
	// empty result forever, so a single transient failure hides all five
	// sections for the rest of the browsing session.
	SectionsUnavailable bool `json:"sections_unavailable,omitempty"`
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

	// Best-effort: a missing section must not fail the request. A transient
	// lookup failure (rate limiting, a 5xx, a network error) is flagged so the
	// client does not cache the empty result as if the article genuinely had no
	// sections. A permanent failure (article does not resolve, no matching
	// heading) is treated like any other empty result and cached normally.
	history, food, efficacy, access, tourism, transient, _ := services.FetchPanelSections(r.Context(), title, qid)
	if transient {
		// The lookup itself failed (rate limit, 5xx, network). Do not render
		// the five empty sections as "the article has no such content"; flag it
		// so the client keeps the panel visible and retries on the next open.
		response.SectionsUnavailable = true
	} else {
		response.History = toPayload(history)
		response.Food = toPayload(food)
		response.Efficacy = toPayload(efficacy)
		response.Access = toPayload(access)
		response.Tourism = toPayload(tourism)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func toPayload(section services.PanelSection) wikiSectionPayload {
	return wikiSectionPayload{
		Summary:     section.Summary,
		Items:       section.Items,
		SourceURL:   section.SourceURL,
		SourceTitle: section.SourceTitle,
	}
}
