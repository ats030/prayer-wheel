package handlers

import (
	"encoding/json"
	"log"
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

// sectionsResponse is the /api/sections/{qid} payload. SectionsUnavailable
// marks a transient Wikipedia failure so the client does not treat the empty
// panel as final. SectionsRetry marks sections served without their summary
// (LLM failed or disabled) so the client does not cache the response.
type sectionsResponse struct {
	Sections            map[string]services.PanelSection `json:"sections"`
	SectionsUnavailable bool                             `json:"sections_unavailable,omitempty"`
	SectionsRetry       bool                             `json:"sections_retry,omitempty"`
}

// officialPanelSection assembles the panel section for one official-source
// section. A stored LLM summary (data/official_summaries.json) takes
// precedence; otherwise the raw text is split into blocks as the reading
// fallback. An empty sourceText and no stored summary yield an empty section,
// which the client hides. A stored SummaryNone (no relevant content) is
// treated the same as having no summary.
func officialPanelSectionHasContent(section services.PanelSection) bool {
	return section.Summary != "" || len(section.Items) > 0 || len(section.Blocks) > 0
}

func officialPanelSection(qid, section, sourceURL, rawText string) services.PanelSection {
	out := services.PanelSection{SourceURL: sourceURL}
	if content, ok := services.GetOfficialSummary(qid, section); ok &&
		!(content.Summary == services.SummaryNone && len(content.Items) == 0) {
		out.Summary = content.Summary
		out.Items = content.Items
		return out
	}
	if rawText != "" {
		var blocks []services.WikipediaTextBlock
		for _, paragraph := range strings.Split(rawText, "\n") {
			if paragraph = strings.TrimSpace(paragraph); paragraph != "" {
				blocks = append(blocks, services.WikipediaTextBlock{Text: paragraph})
			}
		}
		out.Blocks = blocks
	}
	return out
}

// GetSections returns the LLM-structured Wikipedia sections for one item.
func (h *TokusanHandler) GetSections(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	qid := strings.TrimSpace(strings.TrimPrefix(r.URL.Path, "/api/sections/"))
	row := h.service.GetByQID(qid)
	if row == nil {
		http.Error(w, "Tokusan not found", http.StatusNotFound)
		return
	}
	resp := sectionsResponse{Sections: map[string]services.PanelSection{}}
	if row.Description != "" {
		resp.Sections["about"] = services.PanelSection{
			Blocks:    []services.WikipediaTextBlock{{Text: row.Description}},
			SourceURL: row.SourceURL,
		}
		if section := officialPanelSection(qid, "history", row.SourceURL, h.service.GetHistory(qid)); officialPanelSectionHasContent(section) {
			resp.Sections["history"] = section
		}
		if section := officialPanelSection(qid, "production", row.SourceURL, h.service.GetProduction(qid)); officialPanelSectionHasContent(section) {
			resp.Sections["production"] = section
		} else if row.ProductionArea != "" {
			// 製造方法テキストが無い品目は、品目定義の製造地区をそのまま表示する。
			resp.Sections["production"] = services.PanelSection{
				Blocks:    []services.WikipediaTextBlock{{Text: row.ProductionArea}},
				SourceURL: row.SourceURL,
			}
		}
	} else if title := row.WikipediaTitle(); title != "" {
		sections, transient, err := services.FetchPanelSections(r.Context(), title)
		if err != nil {
			log.Printf("tokusan-map: sections for %s (%s): %v", qid, title, err)
			resp.SectionsUnavailable = transient
		} else {
			resp.Sections = sections
			for _, s := range sections {
				if s.SectionRetry() {
					resp.SectionsRetry = true
				}
			}
		}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}
