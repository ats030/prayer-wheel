package handlers

import (
	"encoding/json"
	"net/http"

	"midokoro-map/internal/shiseki/services"
)

// wikiSectionPayload is the per-section JSON shape for the four panel
// sections. Summary is the LLM-generated one-paragraph digest (empty when the
// article has no relevant text, a model is unavailable, or summarization is
// disabled). Blocks is the raw fallback content when the article has a
// matching section heading, except for summaryOnlyDesignations: those sites
// never carry the raw text, and RawOmitted marks a section whose text exists
// but has no summary yet. SourceURL is the canonical ja.wikipedia.org page the
// content was drawn from.
type wikiSectionPayload struct {
	Summary    string                        `json:"summary,omitempty"`
	Blocks     []services.WikipediaTextBlock `json:"blocks,omitempty"`
	RawOmitted bool                          `json:"raw_omitted,omitempty"`
	SourceURL  string                        `json:"source_url,omitempty"`
}

// summaryOnlyDesignations are the designations cmd/summary-warm covers first
// (special + national + local). Their panels show the summary only; the other
// designations keep the raw text until their summaries are warmed too.
var summaryOnlyDesignations = map[string]bool{"special": true, "national": true, "local": true}

// WikipediaContentHandler serves /api/wiki/content. designation looks up a
// site's designation by QID so the raw-text policy is decided server-side.
type WikipediaContentHandler struct {
	designation func(qid string) string
	profile     *services.SectionProfile
}

func NewWikipediaContentHandler(service *services.ShisekiService) *WikipediaContentHandler {
	return &WikipediaContentHandler{designation: func(qid string) string {
		if site := service.GetByQID(qid); site != nil {
			return site.Designation
		}
		return ""
	}, profile: services.ShisekiProfile}
}

// NewGeoWikipediaContentHandler serves the geo tab's natural monuments.
func NewGeoWikipediaContentHandler() *WikipediaContentHandler {
	return &WikipediaContentHandler{designation: func(string) string { return "" }, profile: services.GeoProfile}
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

	History    wikiSectionPayload `json:"history,omitempty"`
	Remains    wikiSectionPayload `json:"remains,omitempty"`
	Access     wikiSectionPayload `json:"access,omitempty"`
	Highlights wikiSectionPayload `json:"highlights,omitempty"`

	// SectionsUnavailable reports that the section lookup itself failed (for
	// example a Wikipedia rate limit) rather than that the article has no such
	// section. Without this the client cannot tell the two apart and caches the
	// empty result forever, so a single transient failure hides all four
	// sections for the rest of the browsing session.
	SectionsUnavailable bool `json:"sections_unavailable,omitempty"`
}

func (h *WikipediaContentHandler) GetWikipediaContent(w http.ResponseWriter, r *http.Request) {
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
	history, remains, access, highlights, transient, _ := h.profile.FetchPanelSections(r.Context(), title)
	if transient {
		// The lookup itself failed (rate limit, 5xx, network). Do not render
		// the four empty sections as "the article has no such content"; flag it
		// so the client keeps the panel visible and retries on the next open.
		response.SectionsUnavailable = true
	} else {
		summaryOnly := h.profile.SummaryOnly() || summaryOnlyDesignations[h.designation(qid)]
		response.History = toPayload(history, summaryOnly)
		response.Remains = toPayload(remains, summaryOnly)
		response.Access = toPayload(access, summaryOnly)
		response.Highlights = toPayload(highlights, summaryOnly)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func toPayload(section services.PanelSection, summaryOnly bool) wikiSectionPayload {
	payload := wikiSectionPayload{
		Summary:   section.Summary,
		Blocks:    section.Blocks,
		SourceURL: section.SourceURL,
	}
	if summaryOnly {
		payload.RawOmitted = payload.Summary == "" && len(payload.Blocks) > 0
		payload.Blocks = nil
	}
	return payload
}
