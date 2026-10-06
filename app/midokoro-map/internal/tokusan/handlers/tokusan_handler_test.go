package handlers

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"midokoro-map/internal/tokusan/services"
)

func TestOfficialItemSections(t *testing.T) {
	t.Setenv("TOKUSAN_AMAZON_URL", "https://www.amazon.co.jp/s?k={query}&tag=test-22")
	service, err := services.NewTokusanService("../../../data/tokusan/tokusan.db")
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	handler := NewTokusanHandler(service)
	var official *services.Tokusan
	for _, row := range service.GetAll() {
		if row.Description != "" {
			copy := row
			official = &copy
			break
		}
	}
	if official == nil {
		t.Fatal("catalog has no official-source items")
	}
	if official.WikipediaTitle() != "" {
		t.Fatal("official source mistaken for Wikipedia")
	}
	if official.AffiliateURL == "" {
		t.Fatal("official item has no configured search link")
	}
	request := httptest.NewRequest("GET", "/api/sections/"+official.QID, nil)
	response := httptest.NewRecorder()
	handler.GetSections(response, request)
	if response.Code != 200 {
		t.Fatalf("sections status %d", response.Code)
	}
	var body sectionsResponse
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	about := body.Sections["about"]
	if len(about.Blocks) != 1 || about.Blocks[0].Text != official.Description || about.SourceURL != official.SourceURL {
		t.Fatalf("official explanation or attribution lost: %+v", about)
	}
	if about.Summary != "" || body.SectionsUnavailable || body.SectionsRetry {
		t.Fatal("official explanation must not require LLM or Wikipedia availability")
	}
	if _, ok := body.Sections["history"]; ok {
		t.Fatal("history must not be shown without an LLM summary")
	}
	var withHistory *services.Tokusan
	for _, row := range service.GetAll() {
		if row.Description != "" && service.GetHistory(row.QID) != "" {
			copy := row
			withHistory = &copy
			break
		}
	}
	if withHistory == nil {
		t.Fatal("catalog has no official history text")
	}
	sections := func(qid string) sectionsResponse {
		response := httptest.NewRecorder()
		handler.GetSections(response, httptest.NewRequest("GET", "/api/sections/"+qid, nil))
		var out sectionsResponse
		if err := json.Unmarshal(response.Body.Bytes(), &out); err != nil {
			t.Fatal(err)
		}
		return out
	}
	if _, ok := sections(withHistory.QID).Sections["history"]; ok {
		t.Fatal("raw history text must not be shown without an LLM summary")
	}
	original := officialSummary
	defer func() { officialSummary = original }()
	officialSummary = func(qid, section string) (services.SectionContent, bool) {
		if qid == withHistory.QID && section == "history" {
			return services.SectionContent{Summary: "要約"}, true
		}
		return services.SectionContent{Summary: services.SummaryNone}, qid == official.QID
	}
	if _, ok := sections(official.QID).Sections["history"]; ok {
		t.Fatal("a SummaryNone history must stay hidden")
	}
	history := sections(withHistory.QID).Sections["history"]
	if history.Summary != "要約" || history.SourceURL != withHistory.SourceURL {
		t.Fatalf("history summary or attribution lost: %+v", history)
	}
	if len(history.Blocks) != 0 {
		t.Fatal("history must show only the summary, not the original text")
	}
	var withProduction *services.Tokusan
	for _, row := range service.GetAll() {
		if row.Description != "" && service.GetProduction(row.QID) != "" {
			copy := row
			withProduction = &copy
			break
		}
	}
	if withProduction == nil {
		t.Fatal("catalog has no official production text")
	}
	response = httptest.NewRecorder()
	handler.GetSections(response, httptest.NewRequest("GET", "/api/sections/"+withProduction.QID, nil))
	body = sectionsResponse{}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	production := body.Sections["production"]
	if len(production.Blocks) == 0 || production.SourceURL != withProduction.SourceURL || production.Summary != "" {
		t.Fatalf("official production or attribution lost: %+v", production)
	}
	listed, _ := json.Marshal(service.GetAll()[:1])
	if strings.Contains(string(listed), "history") {
		t.Fatal("history text must stay out of the list payload")
	}
	response = httptest.NewRecorder()
	handler.GetByQID(response, httptest.NewRequest("GET", "/api/tokusan/"+official.QID, nil))
	if response.Code != 200 {
		t.Fatalf("stable local ID lookup status %d", response.Code)
	}
	response = httptest.NewRecorder()
	handler.GetSections(response, httptest.NewRequest("GET", "/api/sections/local-missing", nil))
	if response.Code != 404 {
		t.Fatalf("missing item status %d", response.Code)
	}
}
